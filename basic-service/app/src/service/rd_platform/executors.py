"""Synchronous local-real actions for the RD worker.

Only this module's ``execute`` is the public executor entry point. The original
taskbook engine keeps responsibility for semantic routing and exact source copy.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil

import yaml

from . import completion, engine_bridge
from .completion import EvidenceBlocked
from .business_binding import verify_binding
from .product_series import filename_series_candidates


ACTION_IDS = {"resolve_context", "template_plan", "content_completion", "generate", "verify", "consistency"}


def _result(status="completed", result=None, artifacts=None, obligations=None, reasons=None):
    return {"status": status, "result": result or {}, "artifacts": artifacts or [],
            "obligations": obligations or [], "blocked_reasons": reasons or []}


def _previous(previous, action):
    value = previous.get(action) or {}
    return value.get("result", value) if isinstance(value, dict) else {}


def _context(snapshot, previous):
    return _previous(previous, "resolve_context").get("context") or completion.context_of(snapshot)


def _pin(source, directory, kind):
    source = Path(source)
    destination = Path(directory) / (kind + source.suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return engine_bridge.artifact(destination, kind)


def _rules(directory):
    from jonhon_taskbook.template_registry import PROJECT_ROOT
    assets = {}
    for source in sorted((PROJECT_ROOT / "config").glob("*.yaml")):
        kind = "rule_" + source.stem
        assets[kind] = {**_pin(source, directory, kind), "original_path": str(source.resolve())}
    return assets


def _candidate_bundle(snapshot, context, blocks, directory, cause):
    """Produce reviewable seed assets without declaring a new product enabled.

    A document declaration cannot establish the professional applicability of a
    different product's profile. All missing target assets remain blockers.
    """
    from jonhon_taskbook.template_registry import resolve_template_selection
    directory = Path(directory) / "candidate"
    applicable = []
    for block in completion.labeled_values(blocks, ("模板基线",)):
        source_blocks = [item for item in blocks if item["source_id"] == block["source_id"]]
        labels = {}
        for key in ("模板适用产品", "模板适用领域", "模板适配依据"):
            values = completion.labeled_values(source_blocks, (key,))
            if len(values) == 1:
                labels[key] = values[0]["value"]
        if (block["role"] != "reference" and labels.get("模板适用产品") == context["product_type"]
                and labels.get("模板适用领域") == context["product_domain"] and labels.get("模板适配依据")):
            applicable.append((block, labels))
    requirements = ["目标产品完整受控Profile（含专业指标与技术要求模式）", "目标产品语义分类mapping",
                    "目标产品/领域适用规则及专业义务", "模板结构与真实资料回归及QA依据"]
    base = {"context": context, "product_route": deepcopy(snapshot.get("product_route")),
            "composition_route": deepcopy(snapshot.get("composition_route")),
            "candidate_asset_requirements": requirements, "cause": engine_bridge._export(str(cause)), "publish_ready": False}
    artifacts = []
    if len(applicable) == 1 and (snapshot.get("composition_route") or {}).get("value") in {"adapt", "new"}:
        evidence, labels = applicable[0]
        try:
            product_type, domain = evidence["value"].split("/", 1)
            seed = resolve_template_selection(product_type, domain)
            for kind, path in (("template", seed.template_path), ("profile", seed.profile_path), ("mapping", seed.category_mapping_path)):
                artifacts.append(_pin(path, directory, "candidate_seed_" + kind))
            applicability = {"target_product_type": context["product_type"], "target_domain": context["product_domain"],
                             "baseline": evidence["value"], "source_id": evidence["source_id"],
                             "source_sha256": evidence["sha256"], "location": evidence["location"],
                             "rationale": labels["模板适配依据"], "status": "unvalidated_declaration",
                             "engineering_applicability_validated": False}
            base["applicability"] = applicability
            artifacts.append(engine_bridge.write_json(directory / "applicability.json", applicability, "applicability"))
            base["candidate_assets"] = {item["kind"]: item for item in artifacts}
        except (ValueError, FileNotFoundError) as exc:
            base["candidate_error"] = engine_bridge._export(str(exc))
    artifacts.append(engine_bridge.write_json(directory / "candidate_manifest.json", base, "candidate_manifest"))
    return _result("blocked", base, artifacts,
                   [{"id": f"candidate:{i}", "status": "blocked", "reason": value} for i, value in enumerate(requirements)],
                   ["缺少目标产品完整受控资产；基线候选包与资料声明不能替代专业适用校验", engine_bridge._export(str(cause))])


def _template_plan(snapshot, previous, blocks, directory):
    from jonhon_taskbook.template_registry import resolve_template_selection
    context = _context(snapshot, previous)
    missing = [field for field, value in context.items() if not value]
    if missing:
        raise EvidenceBlocked("模板适用性判断缺少参数：" + "、".join(missing))
    for axis in ("product_route", "composition_route"):
        if not (snapshot.get(axis) or {}).get("value"):
            raise EvidenceBlocked("缺少真实业务决定：" + axis)
    binding = verify_binding(snapshot)
    if binding:
        locked = binding['document_template']
        assets = {kind: _pin(item['path'], directory, kind) for kind, item in locked['assets'].items()}
        assets.update(_rules(directory))
        selection = {'product_type': context['product_type'], 'product_domain': context['product_domain'],
                     'product_type_label': engine_bridge.controlled_product_label(context['product_type']),
                     'template_path': assets['template']['path'],
                     'profile_path': assets['profile']['path'], 'category_mapping_path': assets['mapping']['path']}
        result = {'context': context, 'selection': selection, 'assets': assets,
                  'binding_id': binding['id'], 'business_fingerprint': binding['fingerprint'],
                  'product_route': deepcopy(binding['product_route']),
                  'composition_route': deepcopy(binding['composition_route']),
                  'business_context': deepcopy(binding.get('business_context', {})),
                  'workflow': deepcopy(binding['workflow']), 'publish_ready': True,
                  'applicability': {'kind': 'adopted_controlled_business_binding'},
                  'composition_operations': [{'operation': 'use_bound_controlled_assets'}]}
        if snapshot['composition_route']['value'] != 'direct':
            raise EvidenceBlocked('已锁定资产仅支持直接选用；结构适配仍缺少受控差异验证')
        artifact = engine_bridge.write_json(Path(directory) / 'template_plan.json', result, 'template_plan')
        return _result(result=result, artifacts=[*assets.values(), artifact])
    try:
        selected = resolve_template_selection(context["product_type"], context["product_domain"])
    except (ValueError, FileNotFoundError) as exc:
        return _candidate_bundle(snapshot, context, blocks, directory, exc)
    # The catalog has historical aliases. They must not change a submitted
    # product identity silently; aliases require explicit prior normalization.
    if selected.product_type != context["product_type"] or selected.product_domain != context["product_domain"]:
        raise EvidenceBlocked("目录别名将改变已提交产品身份；请先明确真实产品分类")
    assets = {}
    for kind, path in (("template", selected.template_path), ("profile", selected.profile_path), ("mapping", selected.category_mapping_path)):
        assets[kind] = _pin(path, directory, kind)
    assets.update(_rules(directory))
    selection = selected.to_dict()
    selection.update(template_path=assets["template"]["path"], profile_path=assets["profile"]["path"],
                     category_mapping_path=assets["mapping"]["path"])
    result = {"context": context, "selection": selection, "assets": assets,
              "product_route": deepcopy(snapshot.get("product_route")),
              "composition_route": deepcopy(snapshot.get("composition_route")),
              "applicability": {"kind": "published_controlled_catalog", "product_type": context["product_type"],
                                "product_domain": context["product_domain"]},
              "composition_operations": [], "publish_ready": True}
    route = snapshot["composition_route"]["value"]
    if route in {"adapt", "new"}:
        result["publish_ready"] = False
        result["composition_operations"].append({"operation": "pin_candidate_baseline",
                                                  "rationale": "保存已有受控基线；不将复用基线声明为结构适配或新模板已完成"})
        asset = engine_bridge.write_json(Path(directory) / "template_plan.json", result, "template_plan")
        reason = "编制路线要求结构适配或新模板，但尚缺有来源的受控章节差异计划及目标资产验证"
        return _result("blocked", result, [*assets.values(), asset],
                       [{"id": "composition:structural_plan", "status": "blocked", "reason": reason}], [reason])
    result["composition_operations"].append({"operation": "use_controlled_assets",
                                              "rationale": "所选产品/领域已有完整受控模板、Profile和mapping，按直接选用编制路线使用"})
    artifact = engine_bridge.write_json(Path(directory) / "template_plan.json", result, "template_plan")
    return _result(result=result, artifacts=[*assets.values(), artifact])


def _consistency(snapshot, previous, blocks):
    context = _context(snapshot, previous)
    checks, reasons = [], []
    if not snapshot.get("sources"):
        reasons.append("本案例尚无真实来源资料，不能完成资料身份和版本检查")
    for field in ("product_series", "product_type", "product_domain"):
        candidates = (filename_series_candidates(snapshot) if field == "product_series"
                      else completion.labeled_values(blocks, (*completion.FIELD_LABELS[field], field)))
        for value in candidates:
            if value["role"] == "reference":
                continue
            actual = completion.canonical_value(field, value["value"])
            check = {"field": field, "expected": context[field], "actual": actual,
                     "source_id": value["source_id"], "location": value["location"]}
            if field == "product_series":
                check.update({key: value[key] for key in ("kind", "quote", "version", "sha256", "name_sha256")})
            checks.append(check)
            if context[field] and actual != context[field]:
                source_label = f"{value['source_id']}（{value['quote']}）" if field == "product_series" else value['source_id']
                reasons.append(f"来源 {source_label} 的 {field}={actual} 与项目参数 {context[field]} 不一致")
    # Multiple uploads of one role are not automatically interpreted as revisions
    # of the same document. Require one explicit engine input per role.
    for role in ("tech", "spec"):
        sources = [source for source in snapshot.get("sources", []) if source["role"] == role]
        if len(sources) > 1:
            reasons.append(f"存在多份 {role} 来源，版本/适用范围未唯一决定")
    for source in snapshot.get("sources", []):
        checks.append({"source_id": source["id"], "version": source["version"], "sha256": source["sha256"], "bytes_verified": True})
    return _result("blocked" if reasons else "completed", {"checks": checks, "consistent": not reasons}, reasons=reasons)


def execute(action_id, snapshot, previous_results, work_dir, progress, cancelled):
    """Execute one fixed action; all outputs are scoped to ``work_dir``.

    Missing evidence is a blocked result, not a synthetic successful remote call.
    Results containing paths are internal worker state and must be scrubbed by
    the Store's public projection; artifact paths are download resolver inputs.
    """
    if action_id not in ACTION_IDS:
        return _result("failed", reasons=[f"未知动作：{action_id}"])
    try:
        if cancelled():
            raise EvidenceBlocked("工作包已取消")
        if snapshot.get("execution_mode") != "local_real":
            raise EvidenceBlocked("执行器只接受local_real，示例契约不能成为生产成功证据")
        completion.validate_sources(snapshot)
        verify_binding(snapshot)
        for resource in snapshot.get("resources", []):
            if resource.get("enabled") is False or resource.get("binding_mode", "local_real") != "local_real":
                raise EvidenceBlocked(f"资源 {resource.get('id')} 已停用或不是本地真实能力")
        directory = Path(work_dir).resolve() / action_id
        directory.mkdir(parents=True, exist_ok=True)
        progress(f"执行{action_id}：检索本案例固定版本本地证据")
        # Generate/verify consume fixed receipts instead of reparsing all sources;
        # byte identity is checked above regardless of action.
        blocks = completion.evidence_blocks(snapshot.get("sources", []), directory) if action_id not in {"generate", "verify"} else []
        if cancelled():
            raise EvidenceBlocked("工作包已取消")
        if action_id == "resolve_context":
            context, provenance, candidates, obligations, reasons = completion.resolve_context(snapshot, blocks)
            result = {"context": context, "context_provenance": provenance, "candidates": candidates,
                      "lookup": {"mode": "local_real", "source_count": len(snapshot.get("sources", [])),
                                 "external_ontology": "contract_example_only", "kbox": "contract_example_only"}}
            return _result("blocked" if obligations or reasons else "completed", result, obligations=obligations,
                           reasons=reasons + (["六参数仍缺少唯一有来源依据"] if obligations else []))
        if action_id == "template_plan":
            return _template_plan(snapshot, previous_results, blocks, directory)
        if action_id == "consistency":
            return _consistency(snapshot, previous_results, blocks)
        plan = _previous(previous_results, "template_plan")
        if action_id == "content_completion":
            from .completion_loop import run_completion
            if not plan.get("selection") or not plan.get("assets", {}).get("template"):
                raise EvidenceBlocked("缺少有效受控模板计划")
            engine_bridge.check_assets(plan["assets"])
            profile_path = plan["selection"].get("profile_path")
            profile = yaml.safe_load(Path(profile_path).read_text(encoding="utf-8")) if profile_path else {}
            ledger = completion.build_completion_ledger(
                plan["selection"]["template_path"], plan.get("context") or _context(snapshot, previous_results), blocks,
                profile=profile, requirements=snapshot.get("requirements", []),
                clarifications=snapshot.get("clarifications", []),
            )
            ledger, session = run_completion(snapshot, ledger, blocks, progress, cancelled,
                                             resume=snapshot.get("completion_resume"),
                                             asset_refs={key: {"sha256": value.get("sha256")} for key, value in plan["assets"].items()})
            obligations = [item for item in ledger if item["status"] == "blocked"]
            conversions = {block["source_id"]: block["normalization"] for block in blocks
                           if block.get("normalization", {}).get("requires_review")}
            # The original engine can produce a review copy with unresolved
            # business inputs. Such a copy is never a formally approved output.
            generation_ready = (plan.get("publish_ready") is True
                                and session["stop_reason"] not in {"cancelled", "permission_revoked", "source_invalid", "deadline_exceeded", "budget_exhausted"}
                                and all(sum(source["role"] == role for source in snapshot.get("sources", [])) == 1
                                        for role in ("tech", "spec")))
            result = {"ledger": ledger, "ready": not obligations and not conversions and session["stop_reason"] == "converged",
                      "generation_ready": generation_ready, "conversion_review": conversions,
                      "completion_session": session,
                      "coverage_scope": "all_retained_template_sections_and_gaps",
                      "policy": "exact local source evidence; original engine copies text; no invented engineering facts"}
            asset = engine_bridge.write_json(directory / "completion_ledger.json", result, "completion_ledger")
            return _result("completed" if generation_ready or result["ready"] else "blocked", result, [asset], obligations,
                           [f"适用内容缺口 {len(obligations)} 项缺少明确本次资料依据"]
                           if obligations and not generation_ready else [])
        done = _previous(previous_results, "content_completion")
        if action_id == "generate":
            result, artifacts, passed = engine_bridge.generate(snapshot, plan, done, directory, progress, cancelled)
            return _result("completed" if passed else "blocked", result, artifacts,
                           reasons=[] if passed else [result.get("error") or "真实引擎未通过生成及交付门禁"])
        if action_id == "verify":
            report = engine_bridge.verify(snapshot, _previous(previous_results, "generate"), plan, done)
            asset = engine_bridge.write_json(directory / "verification.json", report, "verification")
            return _result("completed" if report["delivery_approved"] else "blocked", report, [asset], reasons=report["blockers"])
    except EvidenceBlocked as exc:
        return _result("blocked", {"delivery_approved": False} if action_id == "verify" else {}, reasons=[str(exc)])
    except Exception as exc:
        # Do not expose arbitrary exception strings: model/provider exceptions
        # and filesystem exceptions may contain credentials or private paths.
        return _result("failed", {"error_type": type(exc).__name__}, reasons=[f"动作{action_id}执行失败（{type(exc).__name__}）；未声明完成"])
