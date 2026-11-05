"""Controlled target-template derivation; structural reuse is never approval.

Paths and approved rules are resolved by the authenticated application boundary.
This module performs byte, applicability, mapping and evidence checks again.
No engineering text is generated: professional values are exact source quotes.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
import shutil
import uuid

import yaml

from .template_onboarding import prepare_template_candidate, validate_candidate_mapping
from .template_outline_editor import apply_template_edit_plan


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def candidate_file(candidate, filename):
    if not isinstance(filename, str) or not filename or Path(filename).is_absolute():
        raise ValueError("候选资产引用必须为包内相对路径")
    root = Path(candidate).resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("候选资产引用越界或缺失")
    return path


def full_manifest(candidate):
    """Hash every byte reviewed, including Profile/rules/sources/regression."""
    root = Path(candidate).resolve()
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.relative_to(root).as_posix() not in {"lifecycle.json", "asset_manifest.json"}:
            if not path.resolve().is_relative_to(root):
                raise ValueError("候选包不能包含越界链接")
            files[path.relative_to(root).as_posix()] = file_hash(path)
    return {"schema_version": "1.0", "files": files, "digest": digest(files)}


def core_asset_digest(candidate):
    root = Path(candidate)
    report = json.loads((root / "onboarding_report.json").read_text(encoding="utf-8"))
    files = dict(report.get("files") or {})
    for index, name in enumerate(report.get("derivation_assets", [])):
        files["derivation_" + str(index)] = name
    return digest({key: {"file": name, "sha256": file_hash(candidate_file(root, name))}
                   for key, name in sorted(files.items())})


def _write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _public(value):
    if isinstance(value, dict):
        return {k: _public(v) for k, v in value.items() if k != "path" and not k.endswith("_path")}
    if isinstance(value, list):
        return [_public(v) for v in value]
    return value


def _citation(citation, sources, blocks):
    if not isinstance(citation, dict):
        raise ValueError("目标专业依据必须为固定来源引用对象")
    matched = [block for block in blocks if all(citation.get(key) == block.get(key) for key in
               ("source_id", "version", "sha256", "location")) and citation.get("quote")
               and citation["quote"] == block["quote"]]
    if not matched or not any(source["id"] == citation["source_id"] for source in sources):
        raise ValueError("目标专业依据的来源版本、摘要、定位或原文无效")
    return deepcopy(citation)


def validate_target_asset_shapes(profile, mapping):
    if not isinstance(profile, dict) or not isinstance(mapping, dict):
        raise ValueError("目标Profile和mapping必须为对象")
    for key in ("semantic_routing", "indicator_map", "delivery_gate", "qa_profile"):
        if not isinstance(profile.get(key), dict):
            raise ValueError("目标Profile字段必须为对象：" + key)
    if profile.get("indicator_sources") != {"workbook": False, "reference_families": []}:
        raise ValueError("目标Profile必须关闭未固定、未验证目标适用性的全局指标参考来源")
    contracts = profile.get("professional_evidence_contract")
    if not isinstance(contracts, dict) or set(contracts) != {"indicators", "methods", "criteria"}:
        raise ValueError("目标Profile缺少批准的指标/方法/判据来源语义映射合同")
    for contract in contracts.values():
        if not isinstance(contract, dict) or set(contract) - {"labels", "headings"}:
            raise ValueError("专业来源映射仅支持精确标签和语义标题")
        values = []
        for key in ("labels", "headings"):
            entries = contract.get(key, [])
            if not isinstance(entries, list) or any(not isinstance(v, str) or not v.strip() for v in entries):
                raise ValueError("专业来源精确标签及标题必须为文本列表")
            values.extend(entries)
        if not values:
            raise ValueError("每类专业依据必须固定至少一个批准来源语义定位")
    from .indicator_profile_validator import validate_indicator_profile
    validate_indicator_profile(profile, source="目标Profile")
    for key in ("delivery_gate", "qa_profile"):
        headings = profile[key].get("required_headings")
        if not isinstance(headings, list) or any(not isinstance(h, str) or not h.strip() for h in headings):
            raise ValueError("目标Profile必需章节必须为文本列表")
    for rows in profile["indicator_map"].values():
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get("name"), str) for r in rows):
            raise ValueError("目标指标映射必须为含名称的对象列表")
    for group in ("semantic_roles", "categories"):
        rules = mapping.get(group, {})
        if not isinstance(rules, dict):
            raise ValueError("目标mapping类别组必须为对象")
        for rule in rules.values():
            if not isinstance(rule, dict):
                raise ValueError("目标mapping类别必须为对象")
            headings = rule.get("target_heading_keywords", [])
            if not isinstance(headings, (list, str)) or (isinstance(headings, list) and any(not isinstance(h, str) for h in headings)):
                raise ValueError("目标mapping标题必须为文本或文本列表")
            level = rule.get("target_heading_level", 0)
            if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 9:
                raise ValueError("目标mapping标题层级无效")


def validate_difference_package(baseline, target, package, sources, approved_rules, blocks,
                                target_profile_path=None, target_mapping_path=None):
    problems = []
    required = {"product_type", "domain", "product_label", "domain_label", "version"}
    if not isinstance(target, dict) or not required.issubset(target) or any(not isinstance(target[k], str) or not target[k].strip() for k in required):
        raise ValueError("派生目标身份不完整")
    if not package.get("applicability") or package["applicability"].get("product_type") != target["product_type"] or package["applicability"].get("domain") != target["domain"]:
        problems.append("目标适用范围未明确绑定产品和领域")
    if not baseline.get("template") or not baseline.get("sha256") or file_hash(baseline["template"]) != baseline["sha256"]:
        raise ValueError("派生基线已变化或未固定摘要")
    for kind in ("profile", "mapping"):
        if baseline.get(kind + "_path") and file_hash(baseline[kind + "_path"]) != baseline.get(kind + "_sha256"):
            raise ValueError("派生基线专业资产已变化")
    rules = {r.get("id"): r for r in approved_rules}
    selected = []
    for ref in package.get("rule_refs", []):
        rule = rules.get(ref.get("id"))
        if (not rule or rule.get("version") != ref.get("version") or rule.get("digest") != ref.get("digest")
                or not rule.get("approval", {}).get("actor") or rule.get("status") != "published"
                or not rule.get("publication", {}).get("actor")
                or rule.get("applicability", {}).get("product_type") != target["product_type"]
                or rule.get("applicability", {}).get("domain") != target["domain"]
                or rule.get("digest") != digest({k: v for k, v in rule.items() if k != "digest"})):
            problems.append("差异规则未获批准、摘要变化或不适用于目标")
        else:
            selected.append(rule)
    if not selected:
        problems.append("缺少目标适用的批准差异规则")
    profile = None
    if target_profile_path and target_mapping_path and Path(target_profile_path).is_file() and Path(target_mapping_path).is_file():
        try:
            validate_target_asset_shapes(yaml.safe_load(Path(target_profile_path).read_text(encoding="utf-8")),
                                         yaml.safe_load(Path(target_mapping_path).read_text(encoding="utf-8")))
        except yaml.YAMLError as exc:
            raise ValueError("目标资产YAML无法读取") from exc
    for key, path in (("profile_sha256", target_profile_path), ("mapping_sha256", target_mapping_path)):
        if not path or not Path(path).is_file():
            problems.append("缺少完整目标资产：" + key)
        elif not any(rule.get("asset_bindings", {}).get(key) == file_hash(path) for rule in selected):
            problems.append("目标资产未绑定已发布的批准差异规则：" + key)
    if target_profile_path and Path(target_profile_path).is_file():
        profile = yaml.safe_load(Path(target_profile_path).read_text(encoding="utf-8"))
        if not isinstance(profile, dict):
            problems.append("目标Profile必须是对象")
            profile = None
        elif (not profile.get("indicator_map") or not profile.get("delivery_gate", {}).get("required_headings")
              or not profile.get("qa_profile", {}).get("required_headings")
              or profile.get("semantic_routing", {}).get("copy_source_text_only") is not True
              or profile.get("product_type") not in {target["product_type"], target["product_label"]}):
            problems.append("目标Profile缺少专业指标、适用产品、原文写入合同或交付/QA义务")
    professional = {}
    if not isinstance(package.get("professional_evidence", {}), dict):
        raise ValueError("目标专业依据必须为对象")
    for kind in ("indicators", "methods", "criteria"):
        values = package.get("professional_evidence", {}).get(kind, [])
        if not isinstance(values, list):
            raise ValueError("目标专业依据类别必须为引用列表")
        if not values:
            problems.append("目标专业依据缺失：" + kind)
        professional[kind] = []
        for value in values:
            try:
                citation = _citation(value, sources, blocks)
                contract = (profile or {}).get("professional_evidence_contract", {}).get(kind, {})
                source_block = next(block for block in blocks if all(citation.get(k) == block.get(k) for k in
                                    ("source_id", "version", "sha256", "location", "quote")))
                if not (source_block.get("heading") in contract.get("headings", []) or
                        any(re.match(r"^" + re.escape(label) + r"\s*[:：]\s*\S", source_block["quote"])
                            for label in contract.get("labels", []))):
                    raise ValueError("专业依据未匹配批准的来源语义映射：" + kind)
                source = next(s for s in sources if s["id"] == citation["source_id"])
                if source.get("role") == "reference" or source.get("applicability", {}).get("product_type") != target["product_type"] or source.get("applicability", {}).get("domain") != target["domain"]:
                    raise ValueError("专业来源未明确适用目标产品和领域")
                professional[kind].append(citation)
            except ValueError as exc:
                problems.append(str(exc))
    operations = (package.get("edit_plan") or {}).get("operations", [])
    if not operations:
        problems.append("缺少受控目标结构差异计划")
    if operations and all(op.get("operation") == "rename" for op in operations):
        problems.append("仅修改名称不构成目标专业模板派生")
    # Every operation is approved verbatim; a UI/model proposal is not authority.
    allowed = [op for rule in selected for op in rule.get("operations", [])]
    if any(op not in allowed for op in operations):
        problems.append("章节差异操作未绑定批准规则")
    if profile:
        quotes = [c["quote"] for c in professional["indicators"]]
        for rows in profile.get("indicator_map", {}).values():
            if not isinstance(rows, list):
                problems.append("目标指标映射必须为列表")
                continue
            for row in rows:
                if not isinstance(row, dict) or not row.get("name") or not any(row["name"] in quote for quote in quotes):
                    problems.append("目标指标映射缺少对应的专业原文依据")
    return {"passed": not problems, "blockers": problems, "rules": selected, "professional_evidence": professional}


def prepare_derivation_candidate(*, baseline, target, difference_package, sources,
                                 approved_rules, output_dir, taxonomy_path=None,
                                 chat_json_fn=None, fixture=False, target_profile_path=None,
                                 target_mapping_path=None):
    """Build a full candidate, or a truthful blocked receipt without publication.

    Sources must be authenticated server-resolved fixed uploads. ``fixture`` is
    for clearly labeled test assets only; production lifecycle rejects them.
    """
    from rd_platform.completion import validate_sources, evidence_blocks
    output = Path(output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("派生候选目录必须为空")
    output.mkdir(parents=True, exist_ok=True)
    validate_sources({"sources": sources, "project_id": sources[0].get("project_id") if sources else None,
                      "case_id": sources[0].get("case_id") if sources else None})
    blocks = evidence_blocks(sources, output.parent / ("." + output.name + "_normalization"))
    validation = validate_difference_package(baseline, target, difference_package, sources, approved_rules, blocks,
                                             target_profile_path, target_mapping_path)
    if any(block.get("normalization", {}).get("requires_review") for block in blocks):
        validation["passed"] = False
        validation["blockers"].append("目标专业资料经过格式转换，尚缺转换保真复核；不能作为已批准专业依据")
    receipt = {"schema_version": "1.0", "kind": "template_derivation", "target": deepcopy(target),
               "baseline": {k: v for k, v in baseline.items() if k not in {"template", "profile_path", "mapping_path"}},
               "status": "validated" if validation["passed"] else "blocked", "fixture": bool(fixture),
               "validation": validation, "publish_ready": False}
    if not validation["passed"]:
        _write(output / "derivation_report.json", receipt)
        return receipt
    # Reuse the established signed outline operation validator and DOCX editor.
    intermediate = output.parent / ("." + output.name + "_derived.docx")
    try:
        apply_template_edit_plan(baseline["template"], str(intermediate), difference_package["edit_plan"], confirmed=True)
        if chat_json_fn is None:
            # The published target mapping is already a deterministic approved
            # semantic plan; reuse onboarding without an unnecessary model call.
            approved_mapping = yaml.safe_load(Path(target_mapping_path).read_text(encoding="utf-8")) or {}
            def chat_json_fn(_, payload):
                slots = json.loads(payload)["slots"]
                decisions = []
                for key, rule in {**approved_mapping.get("semantic_roles", {}), **approved_mapping.get("categories", {})}.items():
                    headings = rule.get("target_heading_keywords", [])
                    headings = [headings] if isinstance(headings, str) else headings
                    matches = [slot for slot in slots if slot["title"] in headings and
                               (not rule.get("target_heading_level") or slot["level"] == rule["target_heading_level"])]
                    if len(matches) != 1:
                        raise ValueError("已批准目标mapping未唯一定位实际派生章节")
                    decisions.append({"category": key, "target_slot": matches[0]["id"], "confidence": 1,
                                      "reason": "已发布批准规则固定的目标语义映射"})
                return {"mappings": decisions}
        kwargs = {key: target[key] for key in ("product_type", "product_label", "domain", "domain_label", "version")}
        if taxonomy_path:
            kwargs["taxonomy_path"] = taxonomy_path
        report = prepare_template_candidate(str(intermediate), str(output), chat_json_fn=chat_json_fn, **kwargs)
    finally:
        intermediate.unlink(missing_ok=True)
    # Bind the target evidence to the original engine's controlled Profile.
    profile_path = output / report["files"]["profile"]
    profile = yaml.safe_load(Path(target_profile_path).read_text(encoding="utf-8"))
    mapping_path = output / report["files"]["mapping"]
    shutil.copy2(target_mapping_path, mapping_path)
    mapping_options = {"taxonomy_path": taxonomy_path} if taxonomy_path else {}
    mapping_validation = validate_candidate_mapping(str(output / report["files"]["template"]), str(mapping_path), **mapping_options)
    if not mapping_validation["passed"]:
        receipt.update(status="blocked", validation={**validation, "passed": False,
                       "blockers": mapping_validation["problems"]})
        report["machine_validation_passed"] = False
        _write(output / "onboarding_report.json", report)
        _write(output / "derivation_report.json", receipt)
        return receipt
    report["mapping_validation"] = mapping_validation
    from .template_scanner import scan_template_tree
    titles = {slot["title"] for slot in scan_template_tree(str(output / report["files"]["template"]))}
    required_titles = set(profile.get("delivery_gate", {}).get("required_headings", [])) | set(profile.get("qa_profile", {}).get("required_headings", []))
    if required_titles - titles:
        receipt.update(status="blocked", validation={**validation, "passed": False,
                       "blockers": ["目标Profile必需章节缺失：" + title for title in sorted(required_titles - titles)]})
        report["machine_validation_passed"] = False
        _write(output / "onboarding_report.json", report)
        _write(output / "derivation_report.json", receipt)
        return receipt
    profile.setdefault("semantic_routing", {})["category_mapping"] = report["files"]["mapping"]
    profile["target_applicability"] = deepcopy(difference_package["applicability"])
    profile["professional_evidence"] = deepcopy(validation["professional_evidence"])
    profile["approved_difference_rules"] = difference_package["rule_refs"]
    profile_path.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
    _write(output / "approved_rules.json", validation["rules"])
    baseline_assets = []
    for kind, source_key, expected_key, suffix in (("template", "template", "sha256", ".docx"),
                 ("profile", "profile_path", "profile_sha256", ".yaml"), ("mapping", "mapping_path", "mapping_sha256", ".yaml")):
        if baseline.get(source_key):
            name = "baseline_" + kind + suffix
            shutil.copy2(baseline[source_key], output / name)
            if file_hash(output / name) != baseline.get(expected_key):
                raise ValueError("派生过程中受控基线资产变化")
            baseline_assets.append(name)
    shutil.copy2(target_profile_path, output / "target_profile_source.yaml")
    shutil.copy2(target_mapping_path, output / "target_mapping_source.yaml")
    _write(output / "difference_package.json", difference_package)
    source_manifest = []
    for source in sources:
        name = "sources/" + digest({"id": source["id"], "sha256": source["sha256"]}) + Path(source.get("name") or source["path"]).suffix
        destination = output / name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(source["path"], destination)
        if file_hash(destination) != source["sha256"]:
            raise ValueError("派生过程中来源摘要变化")
        source_manifest.append({**{k: v for k, v in source.items() if k != "path"}, "file": name})
    _write(output / "source_manifest.json", {"sources": source_manifest})
    validate_sources({"sources": sources, "project_id": sources[0].get("project_id") if sources else None,
                      "case_id": sources[0].get("case_id") if sources else None})
    _write(output / "derivation_report.json", receipt)
    report["derivation_assets"] = ["approved_rules.json", "difference_package.json", "source_manifest.json", "derivation_report.json",
                                   "target_profile_source.yaml", "target_mapping_source.yaml", *baseline_assets, *[s["file"] for s in source_manifest]]
    report["derivation"] = {"target": target, "fixture": bool(fixture), "professional_validation_passed": True}
    _write(output / "onboarding_report.json", report)
    receipt["asset_digest"] = core_asset_digest(output)
    receipt["asset_manifest"] = full_manifest(output)
    return receipt


def record_regression_evidence(candidate_dir, *, runner, cases, fixture=False):
    """Run the trusted original-engine adapter; store artifact-backed evidence.

    ``runner`` is application code, not a client callback. It returns engine,
    checks and output file references. No Boolean upload can replace this call.
    """
    candidate = Path(candidate_dir).resolve()
    report = json.loads((candidate / "onboarding_report.json").read_text(encoding="utf-8"))
    fixed_asset_digest = core_asset_digest(candidate)
    results = []
    if not cases:
        raise ValueError("回归至少需要一个固定来源样例")
    for case in cases:
        result = runner(candidate, deepcopy(case))
        if core_asset_digest(candidate) != fixed_asset_digest:
            raise ValueError("回归过程中候选核心资产变化，未形成批准证据")
        if result.get("engine") != "src.pipeline_cli.run_pipeline" or not result.get("checks") or not all(c.get("passed") is True for c in result["checks"]):
            raise ValueError("原引擎回归检查未通过")
        outputs = [{"file": r["file"], "sha256": file_hash(candidate_file(candidate, r["file"]))} for r in result.get("outputs", [])]
        if not outputs:
            raise ValueError("回归缺少真实引擎产物")
        results.append({"case": _public(case), "engine": result["engine"], "checks": result["checks"], "outputs": outputs})
    evidence = {"schema_version": "1.0", "asset_digest": fixed_asset_digest,
                "target": {"product_type": report["product_type"], "domain": report["domain"]},
                "fixture": bool(fixture), "runs": results}
    _write(candidate / "regression_evidence.json", evidence)
    return {"file": "regression_evidence.json", "sha256": file_hash(candidate / "regression_evidence.json")}


class OriginalPipelineRegressionRunner:
    """Trusted adapter for target assets; invokes the existing production engine.

    Case paths must be server-resolved, fixed uploaded inputs. The persisted
    evidence strips those paths and binds hashes, all six parameters and model.
    """
    def __init__(self, *, actor_id, model_selection, progress=lambda _: None, cancelled=lambda: False):
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("真实回归需要登录用户")
        self.actor_id, self.model = actor_id, {k: model_selection.get(k, "") for k in ("provider", "name", "id")}
        self.progress, self.cancelled = progress, cancelled

    def __call__(self, candidate, case):
        from rd_platform.completion import validate_sources, source_input_path, FIELDS
        from . import llm_client
        from .usage_context import model_user_scope
        from src.pipeline_cli import run_pipeline
        candidate = Path(candidate).resolve()
        report = json.loads((candidate / "onboarding_report.json").read_text(encoding="utf-8"))
        fixed_asset_digest = core_asset_digest(candidate)
        sources, context = case.get("sources", []), case.get("context", {})
        validate_sources(case)
        if any(not context.get(field) for field in FIELDS):
            raise ValueError("目标回归缺少六参数")
        if context["product_type"] != report["product_type"] or context["product_domain"] != report["domain"]:
            raise ValueError("回归样例不适用目标产品及领域")
        inputs = {}
        for role in ("tech", "spec"):
            found = [s for s in sources if s.get("role") == role]
            if len(found) != 1:
                raise ValueError("原引擎回归需要唯一技术要求及产品规范")
            inputs[role] = found[0]
        model = self.model
        if not llm_client.get_model_status(model.get("provider", ""), model.get("name", ""), model.get("id", "")).get("configured"):
            raise ValueError("原引擎回归所选模型未配置，未调用或伪造运行")
        target = candidate / "regression" / digest({"context": context, "sources": [{k: s.get(k) for k in ("id", "version", "sha256")} for s in sources]})[:20] / uuid.uuid4().hex
        target.mkdir(parents=True, exist_ok=False)
        output = target / "taskbook.docx"
        def progress(message):
            if self.cancelled():
                raise ValueError("目标模板回归已取消")
            self.progress(str(message))
        if self.cancelled():
            raise ValueError("目标模板回归已取消")
        files = report["files"]
        try:
            with model_user_scope("" if self.actor_id.startswith("local:") else self.actor_id), llm_client.model_scope(model.get("provider", ""), model.get("name", ""), model.get("id", "")):
                result = run_pipeline(
                    tech_path=str(source_input_path(inputs["tech"], target)), spec_path=str(source_input_path(inputs["spec"], target)),
                    tpl_path=str(candidate_file(candidate, files["template"])), profile_path=str(candidate_file(candidate, files["profile"])),
                    category_mapping_path=str(candidate_file(candidate, files["mapping"])), out_path=str(output),
                    use_llm=True, preserve_unfilled_template=True, formal_output=True,
                    selected_product_type=context["product_type"], selected_product_type_label=report["product_label"],
                    selected_product_domain=context["product_domain"], development_process=context["development_process"],
                    product_series=context["product_series"], organization_scope=context["organization_scope"],
                    cover_phase=context["cover_phase"], cb=progress)
            validate_sources(case)
            if core_asset_digest(candidate) != fixed_asset_digest:
                raise ValueError("回归过程中候选资产变化")
            if self.cancelled():
                raise ValueError("目标模板回归已取消")
        except Exception as exc:
            _write(target / "regression_receipt.json", {"engine": "src.pipeline_cli.run_pipeline", "context": context,
                "ok": False, "error_type": type(exc).__name__, "asset_digest": fixed_asset_digest})
            raise ValueError("真实原引擎回归失败；失败尝试已留存，未形成批准证据") from exc
        receipt = {"engine": "src.pipeline_cli.run_pipeline", "context": context, "model": model,
                   "sources": [{k: s.get(k) for k in ("id", "version", "sha256", "role")} for s in sources],
                   "ok": result.get("ok") is True, "delivery_status": result.get("delivery_status"),
                   "asset_digest": fixed_asset_digest}
        _write(target / "regression_receipt.json", receipt)
        return {"engine": receipt["engine"], "checks": [
                    {"id": "original_engine_delivery_gate", "passed": result.get("ok") is True},
                    {"id": "taskbook_output", "passed": output.is_file()},
                    {"id": "fixed_sources_revalidated", "passed": True}],
                "outputs": [{"file": p.relative_to(candidate).as_posix()} for p in sorted(target.rglob("*")) if p.is_file()]}
