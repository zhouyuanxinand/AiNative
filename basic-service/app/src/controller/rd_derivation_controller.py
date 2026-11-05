"""Authenticated governance boundary for controlled target-template derivation."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
import yaml

from src.controller.rd_controller import (RdRoute, _actor, _store, _key, _governance_permissions, _require_governance)
from src.service.rd_platform.store import RdError
from jonhon_taskbook.asset_lifecycle import ControlledAssetLifecycle, _catalog_lock, _atomic_text
from jonhon_taskbook.derivation_rules import DerivationRuleRegistry
from jonhon_taskbook.template_derivation import (
    OriginalPipelineRegressionRunner, candidate_file, core_asset_digest, digest, file_hash,
    full_manifest, prepare_derivation_candidate, record_regression_evidence,
    validate_target_asset_shapes,
)
from jonhon_taskbook.template_outline_editor import get_template_outline, _validate_operations, _plan_hash
from jonhon_taskbook.template_registry import resolve_template_selection


router = APIRouter(prefix="/api/rd", tags=["template-governance"], route_class=RdRoute)


def _lifecycle(request):
    if getattr(request.app.state, "rd_template_lifecycle", None):
        return request.app.state.rd_template_lifecycle
    if getattr(request.app.state.config, "template_candidate_dir", None):
        from src.controller.taskbook_controller import _STATE
        if _STATE.asset_lifecycle is None:
            raise HTTPException(503, "受控模板治理尚未初始化")
        result = _STATE.asset_lifecycle
    else:
        # Isolated application/test instances own an isolated catalog too.
        root = _store(request).asset_root / "controlled_templates"
        root.mkdir(parents=True, exist_ok=True)
        catalog = root / "catalog.yaml"
        if not catalog.exists():
            catalog.write_text("product_types: {}\n", encoding="utf-8")
        result = ControlledAssetLifecycle(candidate_root=root / "candidates", catalog_path=catalog,
            template_root=root / "templates", mapping_root=root / "mappings", profile_root=root / "profiles", audit_root=root / "audit")
    request.app.state.rd_template_lifecycle = result
    return result


def _rules(request):
    return DerivationRuleRegistry(_lifecycle(request).candidate_root.parent / "derivation_rules")


def _read_permission(request):
    if not any(_governance_permissions(request).get(k) for k in
               ("can_prepare_templates", "can_review_templates", "can_publish_templates")):
        raise HTTPException(403, "当前主体没有模板治理读取权限")


def _error(exc):
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(404, "治理对象或固定资产不存在") from None
    if isinstance(exc, ValueError):
        raise HTTPException(409 if "冲突" in str(exc) or "变化" in str(exc) else 422, str(exc)[:300]) from None
    raise exc


async def _payload(request, allowed):
    try:
        if int(request.headers.get("content-length", "0")) > 2_000_000:
            raise HTTPException(413, "治理请求过大")
        value = await request.json()
        if not isinstance(value, dict) or set(value) != set(allowed):
            raise ValueError("治理参数包含未支持字段；主体、路径和批准状态由服务器确定")
        if "reason" in value and (not isinstance(value["reason"], str) or not 1 <= len(value["reason"].strip()) <= 2000):
            raise ValueError("治理意见必须为1至2000字符的文本")
        return value
    except ValueError as exc:
        _error(exc)


async def _upload(file, limit=2_000_000):
    payload = await file.read(limit + 1)
    if not payload or len(payload) > limit:
        raise HTTPException(413, "上传文件为空或超过治理文件限制")
    return payload


async def _mutate(request, payload, operation):
    """Persist receipts around a serialized lifecycle write, including retries."""
    key, actor = _key(request), _actor(request)
    root = _lifecycle(request).candidate_root.parent
    root.mkdir(parents=True, exist_ok=True)
    fingerprint = digest({"route": request.url.path, "actor": actor, "payload": payload})
    receipt_key = digest({"actor": actor, "key": key})
    def run():
        try:
            with _catalog_lock(root / "governance-operations"):
                path = root / "receipts" / (receipt_key + ".json")
                if path.is_file():
                    receipt = json.loads(path.read_text(encoding="utf-8"))
                    if receipt["fingerprint"] != fingerprint:
                        raise ValueError("治理幂等键冲突")
                    if receipt.get("status", "completed") == "completed":
                        return receipt["response"]
                    if receipt.get("status") == "started":
                        raise HTTPException(409, "前次治理操作结果未知，需核对已有候选或发布事实后处理；禁止盲目重发")
                else:
                    receipt = {}
                path.parent.mkdir(parents=True, exist_ok=True)
                started = {"fingerprint": fingerprint, "status": "started", "attempt": receipt.get("attempt", 0) + 1}
                _atomic_text(path, json.dumps(started, ensure_ascii=False))
                try:
                    result = operation()
                except (ValueError, FileNotFoundError, HTTPException) as exc:
                    _atomic_text(path, json.dumps({**started, "status": "failed", "error_type": type(exc).__name__}, ensure_ascii=False))
                    raise
                _atomic_text(path, json.dumps({**started, "status": "completed", "response": result}, ensure_ascii=False))
                return result
        except (ValueError, FileNotFoundError) as exc:
            _error(exc)
    return await asyncio.to_thread(run)


def _sources(request, pid, cid, source_ids=None, target=None, expected_input_revision=None):
    actor, store = _actor(request), _store(request)
    project = store.get_project(actor, pid)
    case = next((case for case in project["cases"] if case["id"] == cid), None)
    if case is None:
        raise HTTPException(404, "案例不存在")
    if expected_input_revision is not None and case["input_revision"] != expected_input_revision:
        raise HTTPException(409, "资料输入版本已变化")
    context = case.get("context", {})
    if target and (context.get("product_type") != target["product_type"] or context.get("product_domain") != target["domain"]):
        raise HTTPException(422, "案例固定产品/领域不适用派生目标")
    active = store._active_sources(case)
    ids = source_ids if source_ids is not None else [s["id"] for s in active]
    if not isinstance(ids, list) or not ids or any(not isinstance(s, str) for s in ids) or len(ids) > 100 or len(ids) != len(set(ids)):
        raise HTTPException(422, "必须指定本案例去重后的固定来源")
    sources = []
    for sid in ids:
        source = next((s for s in active if s["id"] == sid), None)
        if source is None:
            raise HTTPException(404, "指定资料不属于本案例当前固定输入")
        sources.append({**deepcopy(source), "path": str(store.source_path(actor, pid, cid, sid)),
                        "project_id": pid, "case_id": cid,
                        "applicability": {"product_type": context.get("product_type"), "domain": context.get("product_domain")}})
    return case, sources


def _candidate(request, candidate_id):
    try:
        candidate = _lifecycle(request)._candidate(candidate_id)
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)
    binding_path = candidate / "project_binding.json"
    if binding_path.exists():
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        _store(request).get_project(_actor(request), binding["project_id"])
    return candidate


def _validate_live_sources(request, candidate):
    binding_path = candidate / "project_binding.json"
    if not binding_path.exists():
        return
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    report = json.loads(candidate_file(candidate, "onboarding_report.json").read_text(encoding="utf-8"))
    _, sources = _sources(request, binding["project_id"], binding["case_id"], binding["source_ids"],
                          {"product_type": report["product_type"], "domain": report["domain"]}, binding["input_revision"])
    manifest = json.loads(candidate_file(candidate, "source_manifest.json").read_text(encoding="utf-8"))
    expected = [{k: s.get(k) for k in ("id", "version", "sha256")} for s in manifest["sources"]]
    actual = [{k: s.get(k) for k in ("id", "version", "sha256")} for s in sources]
    if actual != expected:
        raise HTTPException(409, "候选固定来源版本已失效")


def _detail(request, candidate_id):
    lifecycle = _lifecycle(request)
    candidate = _candidate(request, candidate_id)
    if not (candidate / "onboarding_report.json").exists():
        result = json.loads(candidate_file(candidate, "derivation_report.json").read_text(encoding="utf-8"))
        result.update(candidate_id=candidate_id, id=candidate_id, asset_manifest=full_manifest(candidate))
        return result
    result = lifecycle.describe(candidate_id)
    result["id"] = candidate_id
    for filename, key in (("derivation_report.json", "derivation_report"), ("regression_evidence.json", "regression"), ("visual_evidence.json", "visual_review"), ("project_binding.json", "project_binding")):
        if (candidate / filename).exists():
            result[key] = json.loads((candidate / filename).read_text(encoding="utf-8"))
    result["target"] = (result.get("derivation") or {}).get("target") or {"product_type": result.get("product_type"), "domain": result.get("domain")}
    result["validation"] = result.get("derivation_report", {}).get("validation")
    result["project_binding"] = result.get("project_binding")
    result["kind"] = "template_derivation" if result.get("derivation_report") else "template_onboarding"
    attempts = sorted((candidate / "regression").rglob("regression_receipt.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    result["regression_attempts"] = [json.loads(path.read_text(encoding="utf-8")) for path in attempts[:20]]
    return result


@router.get("/template-rules")
async def list_rules(request: Request, page: int = Query(1, ge=1), page_size: int = Query(5, ge=1, le=50)):
    _read_permission(request)
    items = _rules(request).list()
    return {"items": items[(page-1)*page_size:page*page_size], "total": len(items), "page": page, "page_size": page_size}


@router.post("/template-rules")
async def create_rule(request: Request, payload: str = Form(...), target_profile: UploadFile = File(...), target_mapping: UploadFile = File(...)):
    actor = _require_governance(request, "can_prepare_templates")
    if len(payload) > 100_000:
        raise HTTPException(413, "规则参数过大")
    try:
        body = json.loads(payload)
        if not isinstance(body, dict) or set(body) != {"target", "operations", "reason"}:
            raise ValueError("规则仅接受目标、操作及依据；批准由服务器治理")
        profile, mapping = await _upload(target_profile), await _upload(target_mapping)
        if not isinstance(yaml.safe_load(profile), dict) or not isinstance(yaml.safe_load(mapping), dict):
            raise ValueError("目标Profile和mapping必须为YAML对象")
        validate_target_asset_shapes(yaml.safe_load(profile), yaml.safe_load(mapping))
        bindings = {"profile_sha256": __import__("hashlib").sha256(profile).hexdigest(), "mapping_sha256": __import__("hashlib").sha256(mapping).hexdigest()}
        def operation():
            rule = _rules(request).create(actor=actor, target=body["target"], operations=body["operations"],
                asset_bindings=bindings, reason=body["reason"], idempotency_key=digest({"actor": actor, "key": _key(request)}))
            directory = _rules(request).root / "assets" / rule["id"]
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "target_profile.yaml").write_bytes(profile)
            (directory / "target_mapping.yaml").write_bytes(mapping)
            return rule
        return await _mutate(request, {**body, "asset_bindings": bindings}, operation)
    except (ValueError, FileNotFoundError, yaml.YAMLError) as exc:
        _error(ValueError("规则YAML无效") if isinstance(exc, yaml.YAMLError) else exc)


@router.post("/template-rules/{rule_id}/review")
async def review_rule(request: Request, rule_id: str):
    actor = _require_governance(request, "can_review_templates")
    body = await _payload(request, {"approved", "reason", "expected_digest"})
    return await _mutate(request, body, lambda: _rules(request).review(rule_id, actor=actor,
        approved=body.get("approved"), reason=body.get("reason"), expected_digest=body.get("expected_digest"),
        idempotency_key=digest({"actor": actor, "key": _key(request)})))


@router.post("/template-rules/{rule_id}/publish")
async def publish_rule(request: Request, rule_id: str):
    actor = _require_governance(request, "can_publish_templates")
    body = await _payload(request, {"expected_digest"})
    return await _mutate(request, body, lambda: _rules(request).publish(rule_id, actor=actor,
        expected_digest=body.get("expected_digest"), idempotency_key=digest({"actor": actor, "key": _key(request)})))


@router.get("/template-derivations")
async def list_derivations(request: Request, page: int = Query(1, ge=1), page_size: int = Query(5, ge=1, le=50)):
    _read_permission(request)
    root = _lifecycle(request).candidate_root
    ids = sorted([p.name for p in root.iterdir() if p.is_dir() and p.name.isalnum() and
                  ((p / "derivation_report.json").exists() or (p / "onboarding_report.json").exists())]) if root.exists() else []
    visible = []
    for candidate_id in ids:
        try:
            _candidate(request, candidate_id)
            visible.append(candidate_id)
        except RdError as exc:
            if exc.status not in {403, 404}:
                raise
    ids = visible
    return {"items": [_detail(request, id) for id in ids[(page-1)*page_size:page*page_size]], "total": len(ids), "page": page, "page_size": page_size}


@router.get("/template-derivations/{candidate_id}")
async def get_derivation(request: Request, candidate_id: str):
    _read_permission(request)
    try:
        return _detail(request, candidate_id)
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)


@router.get("/template-derivations/{candidate_id}/assets/{filename:path}")
async def candidate_asset(request: Request, candidate_id: str, filename: str):
    _read_permission(request)
    try:
        path = candidate_file(_candidate(request, candidate_id), filename)
        return FileResponse(path, filename=path.name)
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)


@router.post("/template-derivations")
async def derive(request: Request):
    _require_governance(request, "can_prepare_templates")
    body = await _payload(request, {"baseline_product_type", "baseline_domain", "target", "project_id", "case_id", "source_ids", "rule_id", "professional_evidence"})
    try:
        target = body.get("target", {})
        if not isinstance(target, dict) or set(target) != {"product_type", "product_label", "domain", "domain_label", "version"} or any(not isinstance(v, str) or not v.strip() for v in target.values()):
            raise ValueError("派生目标字段不完整")
        rule = _rules(request).get(body.get("rule_id"))
        case, sources = _sources(request, body.get("project_id"), body.get("case_id"), body.get("source_ids"), target)
        baseline = resolve_template_selection(body.get("baseline_product_type"), body.get("baseline_domain"))
        outline = get_template_outline(str(baseline.template_path))
        operations = _validate_operations(outline, rule["operations"])
        fingerprint = file_hash(baseline.template_path)
        edit_plan = {"template_fingerprint": fingerprint, "operations": operations, "plan_hash": _plan_hash(fingerprint, operations)}
        package = {"applicability": {"product_type": target["product_type"], "domain": target["domain"]},
                   "rule_refs": [{k: rule[k] for k in ("id", "version", "digest")}],
                   "edit_plan": edit_plan, "professional_evidence": body.get("professional_evidence", {})}
        root = _rules(request).root / "assets" / rule["id"]
        def operation():
            candidate_id = uuid.uuid4().hex
            candidate = _lifecycle(request).candidate_root / candidate_id
            prepare_derivation_candidate(baseline={"id": body["baseline_product_type"], "domain": body["baseline_domain"],
                "template": str(baseline.template_path), "sha256": fingerprint,
                **({"profile_path": str(baseline.profile_path), "profile_sha256": file_hash(baseline.profile_path),
                    "mapping_path": str(baseline.category_mapping_path), "mapping_sha256": file_hash(baseline.category_mapping_path)}
                   if getattr(baseline, "profile_path", None) and getattr(baseline, "category_mapping_path", None) else {})}, target=target,
                difference_package=package, sources=sources, approved_rules=[rule], output_dir=candidate,
                target_profile_path=root / "target_profile.yaml", target_mapping_path=root / "target_mapping.yaml")
            # Bind project authorization and input revision without leaking paths.
            (candidate / "project_binding.json").write_text(json.dumps({"project_id": body["project_id"], "case_id": body["case_id"],
                "input_revision": case["input_revision"], "source_ids": body["source_ids"]}, ensure_ascii=False), encoding="utf-8")
            return _detail(request, candidate_id)
        return await _mutate(request, body, operation)
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)


@router.post("/template-derivations/{candidate_id}/regression")
async def regression(request: Request, candidate_id: str):
    actor = _require_governance(request, "can_prepare_templates")
    body = await _payload(request, {"project_id", "case_id", "expected_input_revision"})
    candidate = _candidate(request, candidate_id)
    try:
        binding = json.loads(candidate_file(candidate, "project_binding.json").read_text(encoding="utf-8"))
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)
    if any(body.get(k) != binding.get(k) for k in ("project_id", "case_id")) or body.get("expected_input_revision") != binding["input_revision"]:
        raise HTTPException(409, "回归必须使用候选固定项目和资料版本")
    detail = _detail(request, candidate_id)
    case, sources = _sources(request, body["project_id"], body["case_id"], binding["source_ids"], detail["target"], body["expected_input_revision"])
    runner = OriginalPipelineRegressionRunner(actor_id=actor, model_selection=case["model_selection"])
    def operation():
        _validate_live_sources(request, candidate)
        evidence = record_regression_evidence(candidate, runner=runner, cases=[{"project_id": body["project_id"], "case_id": body["case_id"],
            "context": case["context"], "sources": sources, "input_revision": case["input_revision"]}])
        _validate_live_sources(request, candidate)
        _require_governance(request, "can_prepare_templates")
        return {"candidate_id": candidate_id, "regression": evidence}
    return await _mutate(request, body, operation)


@router.post("/template-derivations/{candidate_id}/bind-project")
async def bind_legacy_candidate(request: Request, candidate_id: str):
    _require_governance(request, "can_prepare_templates")
    body = await _payload(request, {"project_id", "case_id", "source_ids", "expected_input_revision", "expected_manifest_digest"})
    candidate = _candidate(request, candidate_id)
    detail = _detail(request, candidate_id)
    case, sources = _sources(request, body.get("project_id"), body.get("case_id"), body.get("source_ids"),
                            detail["target"], body.get("expected_input_revision"))
    if not isinstance(body.get("expected_input_revision"), int):
        raise HTTPException(422, "绑定必须固定资料输入版本")
    def operation():
        if detail.get("project_binding") or detail["status"] in {"approved", "published", "rolled_back"}:
            raise HTTPException(409, "已固定项目或已审核的候选不能改绑来源；请创建新候选")
        if body["expected_manifest_digest"] != full_manifest(candidate)["digest"]:
            raise ValueError("候选资产变化，绑定版本冲突")
        report_path = candidate_file(candidate, "onboarding_report.json")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        manifest_sources = []
        for source in sources:
            suffix = Path(source.get("name") or source["path"]).suffix
            name = "sources/" + digest({"id": source["id"], "sha256": source["sha256"]}) + suffix
            target = candidate / name
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(source["path"], target)
            if file_hash(target) != source["sha256"]:
                raise ValueError("绑定期间来源变化")
            manifest_sources.append({**{k: v for k, v in source.items() if k != "path"}, "file": name})
        _atomic_text(candidate / "source_manifest.json", json.dumps({"sources": manifest_sources}, ensure_ascii=False))
        report["derivation_assets"] = [*report.get("derivation_assets", []), "source_manifest.json", *[s["file"] for s in manifest_sources]]
        _atomic_text(report_path, json.dumps(report, ensure_ascii=False))
        _atomic_text(candidate / "project_binding.json", json.dumps({"project_id": body["project_id"], "case_id": body["case_id"],
            "input_revision": case["input_revision"], "source_ids": [s["id"] for s in sources]}, ensure_ascii=False))
        return _detail(request, candidate_id)
    return await _mutate(request, body, operation)


@router.post("/template-derivations/{candidate_id}/visual-review")
async def visual_review(request: Request, candidate_id: str, pages: list[UploadFile] = File(...),
                        expected_asset_digest: str = Form(...), conclusion: str = Form(...), reason: str = Form(...)):
    actor = _require_governance(request, "can_review_templates")
    candidate = _candidate(request, candidate_id)
    if not 1 <= len(pages) <= 200 or conclusion != "passed" or not reason.strip():
        raise HTTPException(422, "需要完整页面、复核结论和意见")
    if expected_asset_digest != core_asset_digest(candidate):
        raise HTTPException(409, "待视觉复核资产已变化")
    try:
        regression_path = candidate_file(candidate, "regression_evidence.json")
    except (ValueError, FileNotFoundError) as exc:
        _error(exc)
    uploads = []
    for upload in pages:
        payload = await _upload(upload, 5_000_000)
        try:
            with Image.open(io.BytesIO(payload)) as image:
                image.verify()
                if image.format not in {"PNG", "JPEG"}:
                    raise ValueError("仅接受实际PNG/JPEG页面")
        except Exception:
            raise HTTPException(422, "视觉证据必须为可解码页面图片") from None
        uploads.append(payload)
        if sum(len(payload) for payload in uploads) > 50_000_000:
            raise HTTPException(413, "视觉证据总大小超过50MB运行限制")
    def operation():
        output = candidate / "visual_pages"
        output.mkdir(exist_ok=True)
        references = []
        for index, payload in enumerate(uploads):
            path = output / (str(index + 1) + ".image")
            path.write_bytes(payload)
            references.append({"file": path.relative_to(candidate).as_posix(), "sha256": file_hash(path)})
        evidence = {"asset_digest": expected_asset_digest, "reviewer": actor, "conclusion": conclusion, "reason": reason,
                    "regression_sha256": file_hash(regression_path), "pages": references}
        path = candidate / "visual_evidence.json"
        path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
        return {"candidate_id": candidate_id, "visual_review": {"file": path.name, "sha256": file_hash(path)}}
    return await _mutate(request, {"expected_asset_digest": expected_asset_digest, "conclusion": conclusion, "reason": reason,
        "pages": [__import__("hashlib").sha256(b).hexdigest() for b in uploads]}, operation)


@router.post("/template-derivations/{candidate_id}/review")
async def review_candidate(request: Request, candidate_id: str):
    actor = _require_governance(request, "can_review_templates")
    body = await _payload(request, {"approved", "reason", "expected_manifest_digest"})
    if not isinstance(body.get("approved"), bool):
        raise HTTPException(422, "审核决定必须为布尔值")
    candidate = _candidate(request, candidate_id)
    evidence = None
    if body["approved"]:
        _validate_live_sources(request, candidate)
        try:
            evidence = {key: {"file": filename, "sha256": file_hash(candidate_file(candidate, filename))}
                        for key, filename in (("regression", "regression_evidence.json"), ("visual", "visual_evidence.json"))}
        except (ValueError, FileNotFoundError) as exc:
            _error(exc)
    return await _mutate(request, body, lambda: _lifecycle(request).review(candidate_id, approved=body["approved"], reviewer=actor,
        reason=body.get("reason", ""), regression_passed=bool(evidence), visual_review_passed=bool(evidence),
        evidence_manifest=evidence, expected_manifest_digest=body.get("expected_manifest_digest")))


@router.post("/template-derivations/{candidate_id}/publish")
async def publish_candidate(request: Request, candidate_id: str):
    actor = _require_governance(request, "can_publish_templates")
    body = await _payload(request, {"expected_target_digest"})
    _validate_live_sources(request, _candidate(request, candidate_id))
    return await _mutate(request, body, lambda: _lifecycle(request).publish(candidate_id, publisher=actor, expected_target_digest=body.get("expected_target_digest")))


@router.post("/template-derivations/{candidate_id}/rollback")
async def rollback_candidate(request: Request, candidate_id: str):
    actor = _require_governance(request, "can_publish_templates")
    body = await _payload(request, {"reason"})
    _candidate(request, candidate_id)
    return await _mutate(request, body, lambda: _lifecycle(request).rollback(candidate_id, actor=actor, reason=body.get("reason", "")))
