# -*- coding: utf-8 -*-
"""
pipeline_cli.py — 研制任务书自动填充流水线统一入口

用法（CLI，cwd = basic-service/app）：
    python -m src.pipeline_cli --tech 技术要求.docx --spec 产品规范.docx --tpl 模板.docx
    python -m src.pipeline_cli --tech ... --out 输出.docx

也可作为模块调用：
    from src.pipeline_cli import run_pipeline
    result = run_pipeline(tech, spec, tpl, out, use_llm=True, cb=print)

业务规则（config/*.yaml）与提示词（prompts/*.md）位于 src/service/，
与 jonhon_taskbook 包同级；ROOT 指向该目录。
"""
from __future__ import annotations
import argparse, json, sys, time
# Windows + Conda can fail to load ``_ssl.pyd`` after some document/image
# native extensions have already altered the DLL search state.  The semantic
# clients are imported lazily much later, so preload the stdlib SSL binding at
# the process entry point.  This applies equally to CLI, FastAPI and acceptance
# matrix calls and does not change any business rule or model configuration.
import ssl as _stdlib_ssl  # noqa: F401
from pathlib import Path
from typing import Callable

# ROOT 指向 src/service/，即 config/、prompts/ 与 jonhon_taskbook 包的同级根。
# 必须在导入 jonhon_taskbook 之前把 service/ 加入 sys.path，以便包的绝对导入
# 在 ``python -m src.pipeline_cli``（cwd=basic-service/app）下也能解析。
ROOT = Path(__file__).resolve().parent / "service"
sys.path.insert(0, str(ROOT))

from jonhon_taskbook.build_fingerprint import build_fingerprint
from jonhon_taskbook.development_process_policy import normalize_development_process
from jonhon_taskbook.template_variant_policy import normalize_organization_scope


def _console_print(message: object) -> None:
    """Write progress without crashing on legacy Windows console encodings."""
    text = str(message)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(encoding, errors="replace").decode(encoding))


def _configure_console_output() -> None:
    """Keep direct prints in downstream modules safe on legacy consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")
            except (OSError, ValueError):
                pass


def _deep_merge_dict(base: dict, override: dict) -> dict:
    """Recursively merge controlled policy dictionaries without mutating inputs."""
    merged = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_configured_qa_policy(
    profile_data: dict,
    *,
    preserve_template_guidance: bool,
    selected_product_domain: str = "",
) -> tuple[dict, dict, str]:
    """Load the repository QA policy and apply only explicit profile overrides.

    ``config/qa_gate.yaml`` is the common quality contract. Product profiles may
    override it through a ``qa_gate`` mapping, while ``qa_profile`` only supplies
    product/domain flags. This keeps QA behavior observable and prevents the
    configuration file from becoming dead documentation.
    """
    import yaml

    config_path = ROOT / "config" / "qa_gate.yaml"
    configured = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    rules = _deep_merge_dict(configured, profile_data.get("qa_gate") or {})
    qa_profile = profile_data.get("qa_profile") or {}
    normalized_domain = str(selected_product_domain or "").strip().lower()

    if preserve_template_guidance:
        block = rules.setdefault("block_if", {})
        block["red_text_count_gt"] = 10**9
        block["highlight_count_gt"] = 10**9
        block["change_record_data_rows_gt"] = 10**9
        block["template_phrases_exist"] = []

    flags = {
        "is_as9100": bool(
            normalized_domain == "as9100"
            or qa_profile.get("is_as9100", False)
        ),
        "is_civil_aircraft": bool(
            normalized_domain in {"airworthiness", "civil_aviation"}
            or qa_profile.get("is_civil_aircraft", False)
        ),
        "allow_landscape": bool(qa_profile.get("allow_landscape", False)),
        "standard_sort_order": profile_data.get("std_sort_order", []),
        "standards_heading_keywords": qa_profile.get(
            "standards_heading_keywords",
            ["适用的法律法规要求", "适用法律法规", "引用标准"],
        ),
    }
    return rules, flags, str(config_path)


def _run_configured_qa_gate(
    out_path: str,
    profile_data: dict,
    *,
    preserve_template_guidance: bool,
    selected_product_domain: str = "",
) -> dict:
    """Execute the common configured QA gate and persist machine evidence."""
    import zipfile
    from lxml import etree
    from jonhon_taskbook.qa_gate import QAGate

    rules, flags, config_path = _load_configured_qa_policy(
        profile_data,
        preserve_template_guidance=preserve_template_guidance,
        selected_product_domain=selected_product_domain,
    )
    with zipfile.ZipFile(out_path) as package:
        root = etree.fromstring(package.read("word/document.xml"))
    checked = QAGate(rules, flags).check(root)
    checked["passed"] = not bool(checked.get("blocked"))
    checked["config_path"] = config_path
    checked["profile_override_applied"] = bool(profile_data.get("qa_gate"))
    sidecar = Path(out_path).with_suffix(".configured_qa_gate.json")
    sidecar.write_text(
        json.dumps(checked, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checked["sidecar"] = str(sidecar)
    return checked


def _run_final_placeholder_sweep(
    out_path: str,
    result: dict,
    step: Callable[[str], None],
) -> int:
    """Remove unresolved value placeholders and persist cleanup evidence."""
    from jonhon_taskbook.placeholder_cleanup import final_placeholder_sweep_docx

    changed = final_placeholder_sweep_docx(out_path)
    stats = result.setdefault("meta", {}).setdefault("stats", {})
    stats["final_placeholder_sweep"] = changed
    if changed:
        step(f"  最终占位符清扫: {changed}")
    return changed


def _indicator_evidence_count(out_path: str) -> int:
    audit_path = Path(out_path).with_suffix(".indicator_audit.json")
    if not audit_path.is_file():
        return 0
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return 0
    for key in ("output_canonical_names", "output_indicator_names"):
        values = audit.get(key)
        if isinstance(values, list):
            return len({str(value) for value in values if str(value).strip()})
    return 0


def _category_evidence_count(classification: dict | None, category: str) -> int:
    if not isinstance(classification, dict):
        return 0
    rows = classification.get("classifications") or []
    return len({
        str(row.get("source_id"))
        for row in rows
        if isinstance(row, dict)
        and row.get("category") == category
        and row.get("source_id")
    })


def _run_delivery_gate_stage(
    out_path: str,
    result: dict,
    profile_data: dict,
    requirement_classification: dict | None,
    business_value_audit: dict | None = None,
) -> dict:
    """Run the real delivery gate and persist its complete decision."""
    from jonhon_taskbook.delivery_gate import run_delivery_gate

    delivery_policy = dict(
        profile_data.get("delivery_gate")
        or profile_data.get("delivery_policy")
        or {}
    )
    process_audit_path = Path(out_path).with_suffix(".process_rule_audit.json")
    deleted_semantic_headings: list[str] = []
    if process_audit_path.is_file():
        try:
            process_audit = json.loads(process_audit_path.read_text(encoding="utf-8"))
            deleted_semantic_headings = [
                str(value).strip()
                for value in process_audit.get("deleted_semantic_headings", [])
                if str(value).strip()
            ]
        except (OSError, json.JSONDecodeError, TypeError):
            deleted_semantic_headings = []
    if deleted_semantic_headings:
        delivery_policy["excluded_required_headings"] = deleted_semantic_headings

    pipeline_report = {
        "meta": result.get("meta", {}),
        "delivery_gate": delivery_policy,
        "indicator_table": _indicator_evidence_count(out_path),
        "interface_definition": _category_evidence_count(
            requirement_classification, "interface_definition"
        ),
        "semantic_labels": {
            "indicator_table": "技术指标",
            "interface_definition": "接口尺寸要求",
        },
    }
    value_gate = business_value_audit or {
        "passed": False,
        "blockers": [{
            "code": "BUSINESS_VALUE_AUDIT_MISSING",
            "message": "缺少最终Word与受控指标账本一致性审查",
        }],
    }
    gate = run_delivery_gate(
        out_path,
        pipeline_report,
        {
            "passed": bool(value_gate.get("passed")),
            "blockers": list(value_gate.get("blockers") or []),
        },
    )
    sidecar = Path(out_path).with_suffix(".delivery_gate.json")
    sidecar.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    gate["sidecar"] = str(sidecar)
    gate["pipeline_report"] = pipeline_report
    return gate


# ══════════════════════════════════════════════════════════════════
# 核心流水线
# ══════════════════════════════════════════════════════════════════

def run_pipeline(
    tech_path: str,
    spec_path: str,
    tpl_path:  str,
    out_path:  str,
    profile_path: str | None = None,
    use_llm:   bool = True,
    baseline_docx: str | None = None,
    baseline_json: str | None = None,
    fail_on_regression: bool = False,
    category_mapping_path: str | None = None,
    preserve_unfilled_template: bool = False,
    formal_output: bool = True,
    selected_product_type: str | None = None,
    selected_product_type_label: str | None = None,
    selected_product_domain: str = "",
    development_process: str = "全新",
    product_series: str = "",
    organization_scope: str = "non_central_research",
    cover_phase: str = "",
    cb: Callable[[str], None] = print,
) -> dict:
    """
    执行完整流水线。
    步骤顺序：LLM多节点语义分类与规划 → 原文精确复制 →
    图片注入 → 后处理 → QA门禁 → HTML报告。
    LLM 只输出 source_id 路由决策，不生成或改写正式正文。
    图片注入必须在后处理之前，确保注入的图片段落也能被居中处理。
    cb: 进度回调，每一步完成时调用，传入一行进度文字。
    返回 {'ok': bool, 'out': str, 'report': str, 'warnings': list, 'error': str}
    """
    try:
        from jonhon_taskbook.cover_fields import normalize_cover_phase

        development_process = normalize_development_process(development_process)
        organization_scope = normalize_organization_scope(organization_scope)
        cover_phase = normalize_cover_phase(cover_phase)
    except ValueError as exc:
        return {
            "ok": False,
            "delivery_status": "failed",
            "out": out_path,
            "report": "",
            "sidecars": {},
            "warnings": [],
            "error": str(exc),
            "meta": {},
        }

    result = {
        "ok": False,
        "delivery_status": "failed",
        "out": out_path,
        "report": "",
        "sidecars": {},
        "warnings": [],
        "error": "",
        "meta": {
            "product_type": "",
            "profile": "",
            "profile_label": "",
            "use_llm": bool(use_llm),
            "auto_inferred": False,
            "qa_ok": None,
            "regression_passed": None,
            "requirement_classification_passed": None,
            "output_name": Path(out_path).name,
            "development_process": development_process,
            "product_series": product_series,
            "organization_scope": organization_scope,
            "cover_phase": cover_phase,
            "selected_product_domain": selected_product_domain,
            "preserve_unfilled_template": bool(preserve_unfilled_template),
            "formal_output": bool(formal_output),
            "template_path": str(tpl_path),
            "stats": {},
            "build_fingerprint": build_fingerprint(include_process=True),
        },
    }
    t0 = time.time()

    def step(msg): cb(f"[{time.time()-t0:5.1f}s] {msg}")

    # ── 0. 参数校验 ────────────────────────────────────────────
    for label, p in [("技术要求", tech_path), ("产品规范", spec_path),
                     ("模板", tpl_path)]:
        if not Path(p).exists():
            result["error"] = f"{label} 文件不存在: {p}"
            cb(f"❌ {result['error']}")
            return result

    if not use_llm:
        result["error"] = (
            "LLM 语义分类和标题树路由是生产必需步骤；"
            "已禁止关闭后退回关键词、章节号或章节顺序猜测"
        )
        cb(f"❌ {result['error']}")
        return result

    if not profile_path or profile_path == "__AUTO_INFER__":
        result["error"] = (
            "现行受控流程必须由产品目录或命令行显式提供产品 Profile；"
            "已禁止自动猜测产品类型并套用默认连接器配置"
        )
        cb(f"❌ {result['error']}")
        return result
    if not category_mapping_path:
        result["error"] = (
            "现行受控流程必须显式提供语义分类映射；"
            "已禁止按章节号、章节顺序或旧版数字槽位写入"
        )
        cb(f"❌ {result['error']}")
        return result

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    # ── 0.4 需求原文块全量语义分类（LLM只返回ID与类别）────────
    classification_ok = True
    requirement_classification = None
    if category_mapping_path:
        step("🗂 需求原文块语义分类…")
        classification_path = str(
            Path(out_path).with_suffix(".requirement_classification.json")
        )
        try:
            from jonhon_taskbook.requirement_classifier import (
                build_requirement_classification,
            )

            requirement_classification = build_requirement_classification(
                tech_path,
                category_mapping_path,
                output_path=classification_path,
                use_llm=use_llm,
            )
            classification_ok = bool(requirement_classification.get("passed"))
            summary = requirement_classification.get("summary", {})
            result["meta"].update(
                {
                    "requirement_classification": classification_path,
                    "requirement_classification_passed": classification_ok,
                    "requirement_source_count": summary.get("source_count", 0),
                    "requirement_category_counts": summary.get("category_counts", {}),
                }
            )
            step(
                f"   全量分类: {summary.get('classified_count', 0)}/"
                f"{summary.get('source_count', 0)}，其他="
                f"{summary.get('category_counts', {}).get('other', 0)}"
            )
        except Exception as exc:
            classification_ok = False
            result["meta"]["requirement_classification_passed"] = False
            message = f"需求语义分类失败: {exc}"
            result["warnings"].append(message)
            if category_mapping_path:
                result["error"] = (
                    f"{message}。为避免按章节号、章节顺序或旧配置猜测位置，"
                    "受控语义流程已停止；请配置可用的 LLM 后重试。"
                )
                cb(f"❌ {result['error']}")
                return result

    # ── 0.5 多节点语义规划（必需；只产生ID映射）───────────────
    semantic_plan = None
    semantic_plan_path = str(Path(out_path).with_suffix(".semantic_plan.json"))
    if use_llm:
        step("🧭 LLM 多节点语义规划（不生成正文）…")
        try:
            from jonhon_taskbook.semantic_orchestrator import build_semantic_plan
            semantic_plan = build_semantic_plan(
                tech_path,
                spec_path,
                tpl_path,
                plan_path=semantic_plan_path,
                requirement_classification=requirement_classification,
                category_mapping_path=category_mapping_path,
            )
            result["meta"]["semantic_plan"] = semantic_plan_path
            result["meta"]["semantic_decision_count"] = len(
                semantic_plan.get("decisions", [])
            )
            step(
                f"   语义决策: {result['meta']['semantic_decision_count']} 条，"
                "全部限定为 copy_exact"
            )
        except Exception as e:
            result["error"] = (
                f"LLM语义规划失败: {e}。为避免退回数字槽位或章节顺序猜测，"
                "本次生成已停止。"
            )
            result["warnings"].append(result["error"])
            cb(f"❌ {result['error']}")
            return result

    # ── 1. 受控配置：产品类型/领域已在入口选择 ──────────────────
    step("🔍 读取受控产品配置…")
    product_type = ""
    profile_label = ""
    try:
        from jonhon_taskbook.product_router import load_profile
        profile_data, profile_label, detected_label = load_profile(
            tech_path=tech_path,
            profiles_dir=str(ROOT / "jonhon_taskbook"),
            explicit_profile=profile_path,
        )
        product_type = (
            selected_product_type_label
            or selected_product_type
            or str(profile_data.get("product_type", detected_label))
        )
    except Exception as exc:
        result["error"] = f"受控产品 Profile 加载失败: {exc}"
        cb(f"❌ {result['error']}")
        return result
    result["meta"]["product_type"] = product_type
    result["meta"]["profile"] = Path(profile_path).name
    result["meta"]["profile_label"] = profile_label
    result["meta"]["auto_inferred"] = False
    # Delivery thresholds are product policy, not chapter identity. Keep them
    # in the selected profile so different products can declare different
    # minimum evidence counts without changing the routing implementation.
    _delivery_policy = profile_data.get("delivery_gate") or profile_data.get("delivery_policy") or {}
    if isinstance(_delivery_policy, dict):
        result["meta"]["delivery_gate"] = dict(_delivery_policy)
    step(f"   配置文件: {Path(profile_path).name}")
    if selected_product_type:
        step(f"   受控产品类型: {product_type}（用户选择）")
    elif product_type:
        step(f"   产品识别: {product_type}")

    # ── 2. 规则填充（yaml 配置驱动）────────────────────────────
    step("📝 规则填充…")
    try:
        from jonhon_taskbook.fill import fill
        _patch_print(cb)
        fill(
            tech_path,
            spec_path,
            tpl_path,
            out_path,
            profile_path,
            finalize=False,
            requirement_classification=requirement_classification,
            category_mapping_path=category_mapping_path,
            preserve_unfilled_template=preserve_unfilled_template,
            controlled_product_label=(selected_product_type_label or selected_product_type or ""),
            controlled_product_domain=selected_product_domain,
            development_process=development_process,
            product_series=product_series,
            organization_scope=organization_scope,
            cover_phase=cover_phase,
        )
        _restore_print()
    except Exception as e:
        _restore_print()
        result["error"] = f"规则填充失败: {e}"
        cb(f"❌ {result['error']}")
        return result
    process_audit_path = Path(out_path).with_suffix(".process_rule_audit.json")
    if process_audit_path.is_file():
        result["sidecars"]["process_rule_audit"] = str(process_audit_path)
    template_variant_audit_path = Path(out_path).with_suffix(
        ".template_variant_audit.json"
    )
    if template_variant_audit_path.is_file():
        result["sidecars"]["template_variant_audit"] = str(
            template_variant_audit_path
        )
    step("   规则填充完成")
    image_warning_file = Path(out_path).with_suffix(Path(out_path).suffix + ".image_warnings.json")
    if image_warning_file.exists():
        try:
            image_warnings = json.loads(image_warning_file.read_text(encoding="utf-8"))
            if isinstance(image_warnings, list):
                # 只上报真正异常（已过滤/低置信），超出 max_images 的溢出提示不作为警告
                real_warns = [w for w in image_warnings if "未自动采用" not in str(w)]
                result["warnings"].extend(str(w) for w in real_warns)
                result["meta"]["image_warning_count"] = len(image_warnings)
                result["meta"]["image_overflow_count"] = len(image_warnings) - len(real_warns)
        except Exception as e:
            result["warnings"].append(f"图片决策告警读取失败: {e}")

    # ── 3. 执行 LLM 路由（确定性原文复制）─────────────────────
    if use_llm and semantic_plan:
        step("📎 按 source_id 精确复制原文…")
        try:
            from jonhon_taskbook.semantic_orchestrator import (
                apply_semantic_plan,
                review_semantic_decisions,
            )
            evidence_path = str(Path(out_path).with_suffix(".semantic_evidence.json"))
            evidence = apply_semantic_plan(
                out_path,
                semantic_plan,
                evidence_path=evidence_path,
                only_empty=True,
            )
            result["meta"]["semantic_evidence"] = evidence_path
            result["meta"]["semantic_inserted_count"] = len(evidence["inserted"])
            result["meta"]["semantic_skipped_count"] = len(evidence["skipped"])
            result["meta"]["semantic_execution_passed"] = bool(evidence.get("passed"))
            step(
                f"   原文复制: {len(evidence['inserted'])} 块；"
                f"安全跳过: {len(evidence['skipped'])} 块"
            )
            if not evidence.get("passed"):
                reasons = sorted({
                    str(item.get("reason", "unknown"))
                    for item in evidence.get("blocking_skipped", [])
                })
                result["error"] = (
                    "语义决策执行门禁失败：存在未执行的非安全决策"
                    f"（{', '.join(reasons) or 'unknown'}）。"
                    "本次结果不得继续交付。"
                )
                cb(f"❌ {result['error']}")
                return result

            review = review_semantic_decisions(semantic_plan, evidence)
            review_path = Path(out_path).with_suffix(".semantic_review.json")
            review_path.write_text(
                json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            result["meta"]["semantic_review"] = str(review_path)
            blockers = [x for x in review.get("issues", []) if x.get("severity") == "block"]
            if blockers:
                result["error"] = (
                    f"LLM语义复核发现 {len(blockers)} 个阻断问题；"
                    "本次结果不得继续交付，请检查 semantic_review.json"
                )
                cb(f"❌ {result['error']}")
                return result
            if review.get("issues"):
                result["warnings"].append(
                    f"语义复核记录 {len(review['issues'])} 条建议（不作为阻断项）；"
                    f"详见 {review_path.name}"
                )
                step(f"   语义复核：记录 {len(review['issues'])} 条建议，继续进入确定性 QA")
        except Exception as e:
            result["error"] = f"语义决策执行失败（未写入生成文字）: {e}"
            result["warnings"].append(result["error"])
            cb(f"❌ {result['error']}")
            return result

    # ── 4. 图片媒体注入（fill() 内部已做 XML 注入 + inject_media，此处仅补漏）────
    step("🖼  图片媒体注入…")
    try:
        from jonhon_taskbook.media_injector import inject_media
        n = inject_media(tech_path, out_path)
        if n:
            step(f"   注入 {n} 个媒体文件")
        else:
            step(f"   媒体文件已在 fill 阶段注入，无需补注")
    except Exception as e:
        result["warnings"].append(f"图片注入警告: {e}")

    # ── 5. 后处理：清红字 / 图片居中 / 表格缩放 / 清横版 ────────
    step("🎨 后处理…")
    try:
        from jonhon_taskbook.postprocess import postprocess
        ps = postprocess(
            out_path,
            preserve_template_guidance=(
                preserve_unfilled_template and not formal_output
            ),
            selected_product_domain=selected_product_domain,
        )
        result["meta"]["stats"].update({
            "red_cleared": ps.get("red_cleared", 0),
            "hl_cleared": ps.get("hl_cleared", 0),
            "date_cleared": ps.get("date_cleared", 0),
            "para_deleted": ps.get("para_deleted", 0),
            "indicator_instruction_deleted": ps.get("indicator_instruction_deleted", 0),
            "figure_captions_renumbered": ps.get("figure_captions_renumbered", 0),
            "figure_references_renumbered": ps.get("figure_references_renumbered", 0),
            "phase_placeholder_cleared": ps.get("phase_placeholder_cleared", 0),
            "domain_artifact_deleted": ps.get("domain_artifact_deleted", 0),
            "img_centered": ps.get("img_centered", 0),
            "table_rescaled": ps.get("table_rescaled", 0),
            "budget_tables_width_normalized": ps.get(
                "budget_tables_width_normalized", 0
            ),
            "header_identity_paragraphs_normalized": ps.get(
                "header_identity_paragraphs_normalized", 0
            ),
            "landscape_cleared": ps.get("landscape_cleared", 0),
            "orphan_media_removed": ps.get("orphan_media_removed", 0),
            "metadata_fields_cleared": ps.get("metadata_fields_cleared", 0),
            "rsid_attributes_removed": ps.get("rsid_attributes_removed", 0),
        })
        msg = (f"   红字→黑: {ps['red_cleared']}  高亮清除: {ps['hl_cleared']}"
               f"  日期清除: {ps['date_cleared']}  整段删除: {ps['para_deleted']}")
        if ps.get("img_centered"):    msg += f"  图片居中: {ps['img_centered']}"
        if ps.get("table_rescaled"):  msg += f"  表格缩放: {ps['table_rescaled']}"
        if ps.get("budget_tables_width_normalized"):
            msg += f"  经济性表格等宽: {ps['budget_tables_width_normalized']}"
        if ps.get("landscape_cleared"): msg += f"  横版清除: {ps['landscape_cleared']}"
        if ps.get("indicator_instruction_deleted"):
            msg += f"  \u6307\u6807\u8868\u63d0\u793a\u6e05\u9664: {ps['indicator_instruction_deleted']}"
        if ps.get("figure_captions_renumbered"):
            msg += f"  \u56fe\u9898\u91cd\u6392: {ps['figure_captions_renumbered']}"
        if ps.get("figure_references_renumbered"):
            msg += f"  \u56fe\u53f7\u5f15\u7528\u540c\u6b65: {ps['figure_references_renumbered']}"
        if ps.get("orphan_media_removed"):
            msg += f"  孤立媒体清理: {ps['orphan_media_removed']}"
        if ps.get("metadata_fields_cleared"):
            msg += f"  隐私元数据清理: {ps['metadata_fields_cleared']}"
        step(msg)

    except Exception as e:
        result["warnings"].append(f"后处理警告: {e}")

    # Keep the final governed sweep outside the formatting exception boundary:
    # a post-processing failure must not allow unresolved values to reach QA.
    try:
        _run_final_placeholder_sweep(out_path, result, step)
    except Exception as e:
        result["warnings"].append(f"最终占位符清扫警告: {e}")

    # ── 6. QA 门禁 ────────────────────────────────────────────
    step("🔍 QA 门禁检查…")
    qa_ok = False
    try:
        from jonhon_taskbook.fill import run_coverage_and_qa
        _qa_cfg = None
        try:
            import yaml as _yaml
            _qa_cfg = _yaml.safe_load(Path(profile_path).read_text(encoding="utf-8"))
        except Exception:
            _qa_cfg = None
        qa_ok = run_coverage_and_qa(
            tech_path,
            out_path,
            _qa_cfg,
            preserve_template_guidance=(
                preserve_unfilled_template and not formal_output
            ),
            template_path=tpl_path,
        )
        result["meta"]["qa_ok"] = bool(qa_ok)
        _gate_rpt = Path(out_path).with_suffix(".qa_gate_report.md")
        if _gate_rpt.exists():
            try:
                from jonhon_taskbook.html_reporter import _load_qa_gate_report
                _gate = _load_qa_gate_report(out_path)
                result["meta"]["gate_result"] = _gate
                if not qa_ok:
                    for v in _gate.get("categories", {}).values():
                        for issue in v:
                            step(f"   ❌ {issue}")
                    for w in _gate.get("warnings", []):
                        step(f"   ⚠️ {w}")
            except Exception:
                pass
        if not qa_ok:
            result["warnings"].append("QA门禁有阻断项，请检查输出文件")
    except Exception as e:
        result["warnings"].append(f"QA检查警告: {e}")
        result["meta"]["qa_ok"] = False

    # ── 6.1 统一配置 QA 门禁 ─────────────────────────────────
    # fill.run_coverage_and_qa 负责覆盖率与业务账本；这里另外执行
    # config/qa_gate.yaml，保证 CLI、Web 和测试使用同一份版式/污染规则。
    configured_qa_ok = False
    try:
        configured_qa = _run_configured_qa_gate(
            out_path,
            profile_data,
            preserve_template_guidance=(
                preserve_unfilled_template and not formal_output
            ),
            selected_product_domain=selected_product_domain,
        )
        configured_qa_ok = bool(configured_qa.get("passed"))
        result["meta"]["configured_qa_ok"] = configured_qa_ok
        result["meta"]["configured_qa_config"] = configured_qa.get("config_path", "")
        result["meta"]["configured_qa_gate"] = {
            "blocked": bool(configured_qa.get("blocked")),
            "block_reasons": configured_qa.get("block_reasons", []),
            "warnings": configured_qa.get("warnings", []),
        }
        result["sidecars"]["configured_qa_gate"] = configured_qa.get("sidecar", "")
        if not configured_qa_ok:
            for issue in configured_qa.get("block_reasons", []):
                step(f"   ❌ 配置门禁: {issue}")
            result["warnings"].append("统一配置 QA 门禁有阻断项")
    except Exception as e:
        result["meta"]["configured_qa_ok"] = False
        result["warnings"].append(f"统一配置 QA 门禁执行失败: {e}")
    qa_ok = bool(qa_ok and configured_qa_ok)
    result["meta"]["qa_ok"] = qa_ok

    # ── 6.1.1 语义目标完整性门禁 ───────────────────────────────
    # 全文覆盖率不能证明内容写在了正确章节。这里用 source_id、分类结果和
    # 实时无编号标题树核对目标位置；需精确核对的类别由分类 YAML 外置配置。
    semantic_integrity_ok = False
    try:
        from jonhon_taskbook.semantic_integrity_gate import (
            run_semantic_integrity_gate,
        )

        semantic_integrity = run_semantic_integrity_gate(
            out_path,
            semantic_plan,
            requirement_classification,
            category_mapping_path,
        )
        semantic_integrity_ok = bool(semantic_integrity.get("passed"))
        result["meta"]["semantic_integrity_ok"] = semantic_integrity_ok
        result["meta"]["semantic_integrity_gate"] = {
            "checked": len(semantic_integrity.get("checked", [])),
            "violations": semantic_integrity.get("violations", []),
        }
        result["sidecars"]["semantic_integrity_gate"] = semantic_integrity.get(
            "sidecar", ""
        )
        if not semantic_integrity_ok:
            for issue in semantic_integrity.get("violations", []):
                step(
                    "   ❌ 语义位置门禁: "
                    f"{issue.get('code', 'UNKNOWN')} "
                    f"{issue.get('source_id', '')} → {issue.get('target_path', '')}"
                )
            result["warnings"].append("语义目标完整性门禁存在阻断项")
    except Exception as e:
        result["meta"]["semantic_integrity_ok"] = False
        result["warnings"].append(f"语义目标完整性门禁执行失败: {e}")

    qa_ok = bool(qa_ok and semantic_integrity_ok)
    result["meta"]["qa_ok"] = qa_ok

    # 最终Word必须与本次受控指标裁决账本逐字段一致。该检查发生在全部
    # 后处理之后，防止正文生成正确、但表格装配/清理阶段又把值丢失。
    business_value_audit: dict = {"passed": False, "blockers": []}
    try:
        from jonhon_taskbook.business_value_gate import audit_indicator_values

        business_value_audit = audit_indicator_values(out_path)
        result["meta"]["business_value_audit"] = {
            "passed": bool(business_value_audit.get("passed")),
            "checked_decisions": int(
                business_value_audit.get("checked_decisions", 0) or 0
            ),
            "blocker_count": len(business_value_audit.get("blockers") or []),
        }
        result["sidecars"]["business_value_audit"] = business_value_audit.get(
            "sidecar", ""
        )
        if not business_value_audit.get("passed"):
            for blocker in business_value_audit.get("blockers", [])[:10]:
                step(f"   ❌ 指标值门禁: {blocker.get('message', blocker)}")
            result["warnings"].append("最终Word与受控指标账本不一致")
    except Exception as e:
        business_value_audit = {
            "passed": False,
            "blockers": [{
                "code": "BUSINESS_VALUE_AUDIT_ERROR",
                "message": f"指标值门禁执行失败: {e}",
            }],
        }
        result["meta"]["business_value_audit"] = {
            "passed": False,
            "checked_decisions": 0,
            "blocker_count": 1,
        }
        result["warnings"].append(f"指标值门禁执行失败: {e}")

    # ── 6.2 正式交付门禁 ─────────────────────────────────────
    # 不能只把 Profile 的 delivery_gate 写进 meta；必须实际调用
    # run_delivery_gate，让门禁结论参与最终 ok/blocked 状态。
    delivery_gate_ok = False
    try:
        delivery_gate = _run_delivery_gate_stage(
            out_path,
            result,
            profile_data,
            requirement_classification,
            business_value_audit,
        )
        delivery_gate_ok = bool(delivery_gate.get("passed"))
        result["meta"]["delivery_gate_result"] = {
            "passed": delivery_gate_ok,
            "deliverable": bool(delivery_gate.get("deliverable", delivery_gate_ok)),
            "blockers": delivery_gate.get("blockers", []),
            "warnings": delivery_gate.get("warnings", []),
        }
        result["sidecars"]["delivery_gate"] = delivery_gate.get("sidecar", "")
        for warning in delivery_gate.get("warnings", []):
            step(f"   ⚠ {warning}")
            result["warnings"].append(str(warning))
        if not delivery_gate_ok:
            for blocker in delivery_gate.get("blockers", []):
                step(f"   ❌ 交付门禁: {blocker}")
            result["warnings"].append("正式交付门禁有阻断项")
    except Exception as e:
        result["meta"]["delivery_gate_result"] = {
            "passed": False,
            "deliverable": False,
            "blockers": [f"交付门禁执行失败: {e}"],
            "warnings": [],
        }
        result["warnings"].append(f"正式交付门禁执行失败: {e}")

    # ── 7. HTML 报告 ───────────────────────────────────────────
    try:
        import zipfile, re
        with zipfile.ZipFile(out_path) as z:
            _xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
            _media = [n for n in z.namelist() if n.startswith("word/media/")]
        result["meta"]["stats"].update({
            "drawing_count": _xml.count("<w:drawing"),
            "media_count": len(_media),
        })
    except Exception:
        pass

    # ── 7. HTML 报告 ───────────────────────────────────────────
    step("📊 生成 HTML 报告…")
    try:
        from jonhon_taskbook.html_reporter import generate_report
        rpt = generate_report(out_path)
        result["report"] = rpt
        step(f"   报告: {Path(rpt).name}")
    except Exception as e:
        result["warnings"].append(f"HTML报告警告: {e}")

    # ── 8. 可选基线回归比较 ────────────────────────────────────
    # 默认只生成差异报告，不阻断交付；只有显式指定
    # fail_on_regression=True 时，差异才会改变最终结果。
    regression_ok = True
    if baseline_docx:
        step("🔁 比较 OOXML/结构化账本基线…")
        regression_path = Path(out_path).with_suffix(".regression.json")
        try:
            if not Path(baseline_docx).exists():
                raise FileNotFoundError(f"基线 DOCX 不存在: {baseline_docx}")

            actual_json = None
            if baseline_json:
                semantic_evidence = result["meta"].get("semantic_evidence")
                if semantic_evidence and Path(semantic_evidence).exists():
                    actual_json = semantic_evidence
                else:
                    raise FileNotFoundError(
                        "指定了 --baseline-json，但本次未生成 semantic_evidence.json；"
                        "请同时启用 --llm，或不要指定 JSON 基线"
                    )

            from jonhon_taskbook.regression_compare import build_regression_report

            regression = build_regression_report(
                baseline_docx,
                out_path,
                expected_json=baseline_json,
                actual_json=actual_json,
            )
            regression_path.write_text(
                json.dumps(regression, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            regression_ok = bool(regression["passed"])
            result["meta"]["regression_report"] = str(regression_path)
            result["meta"]["regression_passed"] = regression_ok
            if regression_ok:
                step(f"   基线一致: {regression_path.name}")
            else:
                changed_parts = len(regression.get("docx_differences", {}))
                json_changed = bool(regression.get("json_differences"))
                step(
                    f"   检出差异: {changed_parts} 个 OOXML/媒体部分，"
                    f"JSON差异={'有' if json_changed else '无'}"
                )
                result["warnings"].append(
                    f"基线回归存在差异，详见 {regression_path.name}"
                )
        except Exception as e:
            regression_ok = False
            result["meta"]["regression_passed"] = False
            result["warnings"].append(f"基线回归比较失败: {e}")

    elapsed = time.time() - t0
    result["ok"] = (
        bool(qa_ok)
        and delivery_gate_ok
        and classification_ok
        and (regression_ok or not fail_on_regression)
    )
    result["delivery_status"] = "approved" if result["ok"] else "blocked"
    result["meta"]["delivery_status"] = result["delivery_status"]
    if result["ok"]:
        step(f"\n✅ 完成并通过门禁！耗时 {elapsed:.1f}s  →  {out_path}")
    else:
        if not result.get("error"):
            result["error"] = "文件已生成，但未通过受控交付门禁；可下载复核件和查看质量报告"
        step(f"\n⛔ 已生成但未通过交付门禁！耗时 {elapsed:.1f}s  →  {out_path}")
    if result["warnings"]:
        for w in result["warnings"]:
            step(f"   ⚠ {w}")
    return result


# ══════════════════════════════════════════════════════════════════
# 辅助：自动选配置文件
# ══════════════════════════════════════════════════════════════════

def _auto_profile(tech_path: str) -> str:
    """历史调用名：现行流程故意禁止自动猜 Profile。"""
    raise ValueError(
        "自动 Profile 路由已禁用；请从受控产品目录选择产品类型和领域"
    )


# ══════════════════════════════════════════════════════════════════
# 辅助：临时重定向 print，让 fill.py 的日志也走 cb
# ══════════════════════════════════════════════════════════════════

_original_print = print   # 模块加载时保存，永远不会被替换

def _patch_print(cb):
    import builtins
    _real = _original_print
    def _safe_print(*a, **kw):
        msg = " ".join(str(x) for x in a)
        try:
            cb(msg)
        except Exception:
            _real(msg)
    builtins.print = _safe_print

def _restore_print():
    import builtins
    builtins.print = _original_print


# ══════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════

def main():
    _configure_console_output()
    ap = argparse.ArgumentParser(description="研制任务书自动填充流水线")
    ap.add_argument("--tech", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--tpl", required=True)
    ap.add_argument("--out",     default=None)
    ap.add_argument("--profile", required=True,
                    help="受控产品 Profile YAML")
    ap.add_argument("--llm", action="store_true", default=True,
                    help="兼容参数；生产流程始终启用 LLM 语义路由")
    ap.add_argument("--baseline", default=None,
                    help="可选：用于 OOXML 回归比较的基线 DOCX")
    ap.add_argument("--baseline-json", default=None,
                    help="可选：用于比较 semantic_evidence.json 的基线 JSON（需同时启用 --llm）")
    ap.add_argument("--fail-on-regression", action="store_true",
                    help="基线存在差异时令流水线失败；默认仅生成报告")
    ap.add_argument("--category-mapping", required=True,
                    help="需求语义分类到模板标题语义的受控映射 YAML")
    ap.add_argument("--preserve-unfilled-template", action="store_true",
                    help="没有来源内容的章节完整保留受控模板原文和格式")
    ap.add_argument(
        "--review-copy",
        action="store_true",
        help="生成内部复核件并允许保留模板编制说明；正式交付默认关闭",
    )
    ap.add_argument("--product-type", default=None,
                    help="受控产品类型 ID；不从文件名猜测")
    ap.add_argument("--product-label", default=None,
                    help="产品类型显示名称，仅用于报告与日志")
    ap.add_argument("--product-domain", default="",
                    help="受控产品领域 ID；用于裁剪领域专属模板章节")
    ap.add_argument("--development-process", default="全新",
                    help="研制流程，例如：全新、改型I、改型II、改型III")
    ap.add_argument("--product-series", default="",
                    help="产品系列；用于受控故障模式库匹配")
    ap.add_argument(
        "--organization-scope",
        default="non_central_research",
        help="产品归属范围：non_central_research 或 central_research",
    )
    ap.add_argument(
        "--cover-phase",
        default="",
        help="封面研制阶段，只能为 F、C、S、D；不得从研制流程分类推断",
    )
    args = ap.parse_args()

    out = args.out
    if out is None:
        stem = Path(args.tech).stem.replace("技术要求", "").replace("（JONHON受控）", "").strip()
        # 输出落到运行时根（basic-service/app）的 正式输出/ 目录。
        out_dir = ROOT.parent.parent / "正式输出"
        out_dir.mkdir(exist_ok=True)
        out = str(out_dir / f"研制任务书_{stem}.docx")

    result = run_pipeline(
        tech_path=args.tech,
        spec_path=args.spec,
        tpl_path=args.tpl,
        out_path=out,
        profile_path=args.profile,
        use_llm=args.llm,
        baseline_docx=args.baseline,
        baseline_json=args.baseline_json,
        fail_on_regression=args.fail_on_regression,
        category_mapping_path=args.category_mapping,
        preserve_unfilled_template=args.preserve_unfilled_template,
        formal_output=not args.review_copy,
        selected_product_type=args.product_type,
        selected_product_type_label=args.product_label,
        selected_product_domain=args.product_domain,
        development_process=args.development_process,
        product_series=args.product_series,
        organization_scope=args.organization_scope,
        cover_phase=args.cover_phase,
        cb=_console_print,
    )
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
