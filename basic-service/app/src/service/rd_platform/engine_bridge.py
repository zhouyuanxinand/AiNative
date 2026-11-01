"""Project-scoped adapter for the existing exact-copy production pipeline."""
from __future__ import annotations

import json
import hashlib
import re
import zipfile
from pathlib import Path

import yaml
from lxml import etree

from .completion import EvidenceBlocked, PLACEHOLDER, sha256, source_input_path, _clarification_adoption
from .business_binding import verify_binding


def _binding_receipt(snapshot, plan):
    binding = verify_binding(snapshot)
    if not binding:
        return {}
    expected = {'binding_id': binding['id'], 'business_fingerprint': binding['fingerprint']}
    if any(plan.get(key) != value for key, value in expected.items()):
        raise EvidenceBlocked('引擎模板计划与当前固定业务选择不一致')
    if any((plan.get('assets', {}).get(kind) or {}).get('sha256') != asset['sha256']
           for kind, asset in binding['document_template']['assets'].items()):
        raise EvidenceBlocked('引擎固定资产与已绑定业务选择不一致')
    return expected


def artifact(path, kind, artifact_id=None):
    path = Path(path).resolve()
    digest = sha256(path)
    location_id = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    return {"id": artifact_id or f"{kind}-{location_id}-{digest[:12]}", "name": path.name,
            "path": str(path), "kind": kind, "sha256": digest}


def write_json(path, payload, kind):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_export(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return artifact(path, kind)


def _export(value):
    """Downloadable evidence references IDs/hashes, never server directories."""
    if isinstance(value, dict):
        return {key: _export(item) for key, item in value.items()
                if key != "path" and (not key.endswith("_path") or key in {"semantic_path", "target_path"})}
    if isinstance(value, list):
        return [_export(item) for item in value]
    if isinstance(value, str):
        if re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/)", value):
            return Path(value).name
        return re.sub(r"(?:[A-Za-z]:[\\/]|\\\\)[^\s\"'<>|]+", "[internal-path]", value)
    return value


def check_assets(assets, *, check_original=False):
    for kind, value in assets.items():
        path = Path(value.get("path") or "")
        if not path.is_file() or not value.get("sha256") or sha256(path) != value["sha256"]:
            raise EvidenceBlocked(f"固定资产 {kind} 缺失或 hash 已变化")
        if check_original and value.get("original_path"):
            original = Path(value["original_path"])
            if not original.is_file() or sha256(original) != value["sha256"]:
                raise EvidenceBlocked(f"引擎实时规则 {kind} 已变化，与固定规则版本不一致")


def controlled_product_label(product_type):
    """Read the product label without treating a combined UI title as identity."""
    from jonhon_taskbook.template_registry import list_product_catalog
    for item in list_product_catalog():
        if item["value"] == product_type:
            return item["label"]
    raise EvidenceBlocked("已固定产品类型缺少受控目录标签")


def _adopted_indicator_conditions(snapshot, plan, completion):
    """Adapt verified RD replies to the legacy indicator -> condition contract.

    The original engine accepts applicability conditions, never replacement
    engineering values. Free-form adopted requirements remain in the completion
    ledger; they cannot be silently repurposed as indicator overrides.
    """
    fields = {"规格", "接触件规格", "档位", "线规", "AWG", "壳体号", "位数", "芯数",
              "型号", "系列", "条件", "测试条件", "试验条件", "温度", "测试温度",
              "试验温度", "大气压", "试验阶段", "测试阶段", "振动等级"}
    profile = yaml.safe_load(Path(plan["selection"]["profile_path"]).read_text(encoding="utf-8")) or {}
    names = {str(item.get("name", "")) for items in (profile.get("indicator_map") or {}).values() for item in items}
    requirements = {item["id"]: item for item in snapshot.get("requirements", [])}
    sources = {item["id"]: item for item in snapshot.get("sources", [])}
    compact = lambda value: "".join(str(value).split())
    values, audit = {}, []
    for record in snapshot.get("clarifications", []):
        if record.get("status") != "adopted":
            continue
        item = {"clarification_id": record.get("id"), "requirement_id": record.get("requirement_id"),
                "status": "not_forwarded"}
        audit.append(item)
        requirement = requirements.get(record.get("requirement_id")) or {}
        name = str(requirement.get("title") or "").strip().rstrip("：:")
        if name not in names:
            item["reason"] = "需求标题未精确对应受控指标，不推测指标映射"
            continue
        answer = str(record.get("answer") or "").strip()
        clauses = [part.strip() for part in re.split(r"[；;\n]+", answer) if part.strip()]
        answer_conditions = set()
        valid = bool(clauses) and len(answer) <= 500
        for clause in clauses:
            field, separator, text = clause.replace(":", "：", 1).partition("：")
            valid = valid and bool(separator and field.strip() in fields and text.strip())
            valid = valid and not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]|(?:跳过|忽略|改写|覆盖|直接通过|强制通过)", text)
            answer_conditions.add((field.strip(), compact(text).removesuffix("。")))
        if not valid:
            item["reason"] = "答复不是原引擎支持的指标适用条件；未作为指标值覆盖"
            continue
        # Compare complete labeled clauses: #22 must not match #22D, nor may
        # “条件” be extracted from “不适用条件”. Commas remain inside values so
        # a list or range cannot be shortened to its first member.
        adopted_conditions = set()
        for clause in re.split(r"[；;\n。]+", str(requirement.get("content", ""))):
            field, separator, text = clause.replace(":", "：", 1).partition("：")
            if separator and field.strip() in fields and text.strip():
                adopted_conditions.add((field.strip(), compact(text)))
        if not answer_conditions.issubset(adopted_conditions):
            item["reason"] = "条件未被当前需求正文明确采用"
            continue
        verified = None
        for entry in completion["ledger"]:
            if entry.get("requirement_id") != requirement.get("id") or entry.get("status") != "evidence_ready":
                continue
            for candidate in entry.get("candidates", []):
                source = sources.get(candidate.get("source_id")) or {}
                if (candidate.get("adopted") is not True or candidate.get("quote") != requirement.get("content")
                        or candidate.get("sha256") != source.get("sha256")
                        or candidate.get("version") != source.get("version")):
                    continue
                adopted = _clarification_adoption(requirement, candidate, [record])
                if adopted:
                    verified = adopted
                    break
            if verified:
                break
        if not verified:
            item["reason"] = "缺少当前需求版本、采纳历史与固定答复来源的一致原文证据"
            continue
        value = "；".join(clauses)
        if name in values and values[name] != value:
            raise EvidenceBlocked(f"指标 {name} 存在多个不同的已采纳适用条件，需先明确同一指标的适用范围")
        values[name] = value
        item.update(status="forwarded", indicator_name=name, conditions=value, evidence=verified)
    return values, audit


def generate(snapshot, plan, completion, work_dir, progress, cancelled):
    business = _binding_receipt(snapshot, plan)
    if (completion.get("ready") is not True and completion.get("generation_ready") is not True
            or not isinstance(completion.get("ledger"), list)):
        raise EvidenceBlocked("缺少有效来源和适用内容检查记录，不能生成任务书")
    unresolved = [item for item in completion["ledger"] if item.get("status") == "blocked"]
    if unresolved and completion.get("generation_ready") is not True:
        raise EvidenceBlocked("适用内容缺口尚未补齐，且尚不具备复核稿生成条件")
    check_assets(plan.get("assets") or {}, check_original=True)
    for kind in ("template", "profile", "mapping", "rule_qa_gate"):
        if kind not in plan.get("assets", {}):
            raise EvidenceBlocked(f"缺少固定受控资产 {kind}")
    inputs = {}
    for role in ("tech", "spec"):
        found = [source for source in snapshot.get("sources", []) if source["role"] == role]
        if len(found) != 1:
            raise EvidenceBlocked(f"原任务书引擎要求唯一 {role} 资料，本案例有 {len(found)} 份；不得静默选第一份")
        inputs[role] = str(source_input_path(found[0], work_dir))
    from jonhon_taskbook import llm_client
    from jonhon_taskbook.usage_context import model_user_scope
    actor = snapshot.get("actor_id") or snapshot.get("submitted_by")
    if not isinstance(actor, str) or not actor.strip():
        raise EvidenceBlocked("缺少提交人的真实登录userid，不能发送无用户归属的模型请求")
    model = snapshot.get("model_selection") or {}
    status = llm_client.get_model_status(model.get("provider", ""), model.get("name", ""), model.get("id", ""))
    if not status.get("configured"):
        raise EvidenceBlocked("本地真实任务书引擎强制使用语义模型；所选模型缺少有效服务凭据")
    target = Path(work_dir) / "generated"
    target.mkdir(parents=True, exist_ok=True)
    context = plan["context"]
    selection = plan["selection"]
    indicator_clarifications, clarification_adaptation = _adopted_indicator_conditions(snapshot, plan, completion)

    def cb(message):
        if cancelled():
            raise EvidenceBlocked("工作包已取消，停止采用引擎输出")
        progress(_export(str(message)))

    # Do not call taskbook_controller._run_job: that route owns a global
    # Downloads side effect. run_pipeline itself writes only to this directory.
    from src.pipeline_cli import run_pipeline
    usage_userid = "" if actor.startswith("local:") else actor.strip()
    with model_user_scope(usage_userid), llm_client.model_scope(model.get("provider", ""), model.get("name", ""), model.get("id", "")):
        raw = run_pipeline(
            tech_path=inputs["tech"], spec_path=inputs["spec"],
            tpl_path=selection["template_path"], profile_path=selection["profile_path"],
            category_mapping_path=selection["category_mapping_path"],
            out_path=str(target / "taskbook.docx"), use_llm=True,
            preserve_unfilled_template=True, formal_output=True,
            selected_product_type=context["product_type"],
            selected_product_type_label=controlled_product_label(context["product_type"]),
            selected_product_domain=context["product_domain"],
            development_process=context["development_process"], product_series=context["product_series"],
            organization_scope=context["organization_scope"], cover_phase=context["cover_phase"], cb=cb,
            indicator_clarifications=indicator_clarifications,
        )
    if cancelled():
        raise EvidenceBlocked("工作包已取消，停止采用引擎输出")
    check_assets(plan["assets"], check_original=True)
    generated, evidence = [], []
    for path in sorted(target.rglob("*")):
        if path.is_file():
            kind = "taskbook" if path == target / "taskbook.docx" else "engine_evidence"
            original = artifact(path, kind)
            evidence.append(original)
            if path.suffix.lower() == ".json":
                exported = target / "public_evidence" / path.relative_to(target)
                public = write_json(exported, {
                    "export_policy": "logical_references_only", "original_sha256": original["sha256"],
                    "original_artifact_id": original["id"], "evidence": json.loads(path.read_text(encoding="utf-8")),
                }, kind)
                generated.append(public)
            elif path.suffix.lower() in {".md", ".html", ".txt", ".yaml", ".yml", ".csv", ".log"}:
                exported = target / "public_evidence" / path.relative_to(target)
                exported.parent.mkdir(parents=True, exist_ok=True)
                text = path.read_text(encoding="utf-8")
                text = re.sub(r"(?:[A-Za-z]:[\\/]|\\\\)[^\s\"'<>|]+", "[internal-path]", text)
                exported.write_text(text, encoding="utf-8")
                public = artifact(exported, kind)
                public["original_sha256"] = original["sha256"]
                generated.append(public)
            else:
                generated.append(original)
    output = next((item for item in evidence if item["kind"] == "taskbook"), None)
    receipt = write_json(target / "engine_receipt.json", {
        "engine": "src.pipeline_cli.run_pipeline", "execution_mode": "local_real",
        "project_id": snapshot.get("project_id"), "case_id": snapshot.get("case_id"),
        "workpackage_id": snapshot.get("workpackage_id"), "context": context,
        **business,
        "source_hashes": {source["id"]: source["sha256"] for source in snapshot["sources"]},
        "assets": plan["assets"], "output": output, "evidence": evidence, "engine_result": raw,
        "indicator_clarifications": indicator_clarifications, "clarification_adaptation": clarification_adaptation,
        "completion_review": {"ready": completion.get("ready") is True,
                              "unresolved_count": len(unresolved),
                              "conversion_review": completion.get("conversion_review", {})},
    }, "engine_receipt")
    generated.append(receipt)
    passed = raw.get("ok") is True and bool(output) and completion.get("ready") is True and not unresolved
    review_error = ("已生成复核文件；仍有未补齐内容或转换资料待复核，未批准正式交付"
                    if output and not passed and not raw.get("error") else "")
    return {"engine": "src.pipeline_cli.run_pipeline", "execution_mode": "local_real",
            "workpackage_id": snapshot.get("workpackage_id"),
            **business,
            "ok": passed, "delivery_status": raw.get("delivery_status", "failed") if passed or not output else "review_required",
            "warnings": _export(raw.get("warnings", [])), "error": _export(raw.get("error") or review_error),
            "output": output, "receipt": receipt, "evidence": evidence}, generated, passed


def verify(snapshot, generated, plan, completion):
    """Rerun configured QA on fixed bytes and inspect real coverage evidence."""
    from jonhon_taskbook.qa_gate import QAGate
    from jonhon_taskbook.qa_policy import load_configured_qa_policy

    output, receipt = generated.get("output"), generated.get("receipt")
    if not output or not receipt:
        raise EvidenceBlocked("缺少真实生成成果和引擎回执；成功布尔值不能证明已通过校验")
    check_assets({"output": output, "receipt": receipt})
    check_assets(plan.get("assets") or {})
    saved = json.loads(Path(receipt["path"]).read_text(encoding="utf-8"))
    business = _binding_receipt(snapshot, plan)
    if any(saved.get(key) != value or generated.get(key) != value for key, value in business.items()):
        raise EvidenceBlocked('生成回执不属于当前已绑定业务选择')
    available = {item["id"]: item for item in [*generated.get("evidence", []), *generated.get("artifacts", []), output]}
    evidence = {}
    for reference in saved.get("evidence", []):
        actual = available.get(reference.get("id"))
        if not actual or actual.get("sha256") != reference.get("sha256"):
            raise EvidenceBlocked("固定引擎证据引用缺失或hash不一致")
        evidence[actual["id"]] = actual
    check_assets(evidence)
    for scope in ("project_id", "case_id"):
        if saved.get(scope) != snapshot.get(scope):
            raise EvidenceBlocked("引擎回执与本次工作包身份不一致")
    origin_package = snapshot.get("upstream_workpackage_id") or snapshot.get("workpackage_id")
    if saved.get("workpackage_id") != origin_package:
        raise EvidenceBlocked("引擎回执不是本次固定的上游生成工作包")
    if saved.get("source_hashes") != {source["id"]: source["sha256"] for source in snapshot["sources"]}:
        raise EvidenceBlocked("引擎回执的来源版本与本次提交不一致")
    if saved.get("output", {}).get("sha256") != output["sha256"]:
        raise EvidenceBlocked("成果hash与引擎回执不一致")
    if completion.get("ready") is not True:
        raise EvidenceBlocked("缺少已完成的适用内容账")
    profile = yaml.safe_load(Path(plan["selection"]["profile_path"]).read_text(encoding="utf-8")) or {}
    rules, flags, _ = load_configured_qa_policy(
        profile, preserve_template_guidance=True,
        selected_product_domain=plan["context"]["product_domain"],
        config_path=plan["assets"]["rule_qa_gate"]["path"],
    )
    flags["template_path"] = plan["selection"]["template_path"]
    with zipfile.ZipFile(output["path"]) as package:
        xml = etree.fromstring(package.read("word/document.xml"), etree.XMLParser(resolve_entities=False, no_network=True))
    qa = QAGate(rules, flags).check(xml)
    blockers = list(qa.get("block_reasons", []))
    text = "\n".join(xml.xpath('//*[local-name()="t"]/text()'))
    if PLACEHOLDER.search(text):
        blockers.append("正式成果仍含人工填写或其他待补齐占位")
    compact = lambda value: "".join(str(value).split())
    adopted_evidence = []
    for item in completion.get("ledger", []):
        if item.get("status") == "blocked":
            blockers.append(f"适用内容未补齐：{item.get('title')}")
        if item.get("status") == "evidence_ready":
            required = [candidate for candidate in item["candidates"]
                        if (candidate["role"] in {"tech", "spec"} or candidate.get("adoption"))
                        and candidate.get("adopted") is not False]
            if not required:
                blockers.append(f"内容已标完成但缺少已采用设计输入：{item.get('title')}")
            for candidate in required:
                quote = candidate["quote"]
                offset = compact(text).find(compact(quote)) if compact(quote) else -1
                adopted_evidence.append({"gap_id": item.get("id"), "source_id": candidate.get("source_id"),
                                         "source_location": candidate.get("location"),
                                         "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
                                         "output_text_offset": offset, "verified": offset >= 0})
                if offset < 0:
                    blockers.append(f"已采用的补齐依据尚未在最终成果定位：{item.get('title')} / {quote[:120]}")
    ledger_path = Path(output["path"]).with_suffix(".coverage_ledger.json")
    if not ledger_path.is_file():
        blockers.append("缺少引擎真实输入覆盖率账本")
        coverage = {}
    else:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        blocks = ledger.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            blockers.append("真实覆盖率账本为空或无效")
            blocks = []
        uncovered = [item.get("block_id") for item in blocks if item.get("covered") is not True]
        if uncovered:
            blockers.append(f"仍有未覆盖来源块：{','.join(map(str, uncovered[:20]))}")
        coverage = {"total": len(blocks), "uncovered": uncovered}
    raw = saved.get("engine_result") or {}
    meta = raw.get("meta") or {}
    if raw.get("ok") is not True or meta.get("qa_ok") is not True or meta.get("configured_qa_ok") is not True:
        blockers.append("原任务书引擎质量门禁未通过或缺少执行证据")
    if meta.get("semantic_integrity_ok") is not True:
        blockers.append("缺少通过的原引擎语义位置完整性门禁")
    delivery = meta.get("delivery_gate_result") or {}
    if delivery.get("passed") is not True:
        blockers.extend(delivery.get("blockers") or ["原引擎交付门禁未通过"])
    return {"delivery_approved": not blockers, "qa": qa, "coverage": coverage, "adopted_evidence": adopted_evidence,
            "output_sha256": output["sha256"], "blockers": blockers,
            "scope": "local_real_engine_and_configured_qa"}
