"""Historical evidence scope is physical, not an LLM destination category."""
import base64
import json
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from jonhon_taskbook.coverage_ledger import exclude_review_reference_sources, parse_docx_to_ledger
from jonhon_taskbook.html_reporter import generate_report
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks
from jonhon_taskbook.source_scope import review_reference_source_ids


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5Wk3kAAAAASUVORK5CYII="
)


def _fixture(tmp_path):
    document = Document()
    document.add_heading("测试设备及测试结果", 1)
    for index in range(33):
        document.add_paragraph(f"第{index + 1}批压力测试结果：")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text, table.cell(0, 1).text = "样品编号", "实测压力/kPa"
        table.cell(1, 0).text, table.cell(1, 1).text = f"YLZJ-{index + 1}", str(199 + index / 10)
        document.add_picture(BytesIO(_PNG))
    history_end = len(document.element.body) - 1

    # Formal requirements within a mixed results chapter must remain body input.
    document.add_paragraph("测试内容：58psi氮气，保压30min，泄漏值＜3%。")
    document.add_paragraph("测试内容：0.2MPa（不超过29psi）氮气，保压30min，泄漏值＜2%。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "出厂试验项目", "判定标准"
    table.cell(1, 0).text, table.cell(1, 1).text = "盐雾", "试验时间≥48h，接触电阻应≤20mΩ"
    document.add_paragraph("测试要求如下：")
    requirement_image_index = len(document.element.body) - 1
    document.add_picture(BytesIO(_PNG))

    # These are ordinary paragraphs in converted DOCs; old heading metadata
    # keeps assigning them to the last test-results section.
    appendix_one_index = len(document.element.body) - 1
    document.add_paragraph("附录一：UQD04-Z03XXXXX流体连接器规格书")
    document.add_picture(BytesIO(_PNG))
    document.add_paragraph("工作压力0.3MPa；泄漏值≤5×10-6Pa.m³/s。")
    appendix_four_index = len(document.element.body) - 1
    document.add_paragraph("附录四：漏液检测线拉拔力测试结果")
    document.add_picture(BytesIO(_PNG))
    appendix_six_index = len(document.element.body) - 1
    document.add_paragraph("附录六：压缩空气管控标准")
    document.add_paragraph("压缩空气按照GB/T 13277管控，固体粒子满足4级、压力露点满足3级、总油量满足5级。")
    document.add_picture(BytesIO(_PNG))
    path = tmp_path / "historical-and-formal.docx"
    document.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    classification = {
        "source_blocks": blocks,
        "classifications": [{"source_id": block["id"],
                             "category": ("performance_indicator", "other", "testability")[index % 3]}
                            for index, block in enumerate(blocks)],
    }
    return path, classification, history_end, requirement_image_index, appendix_one_index, appendix_four_index, appendix_six_index


def test_99_historical_blocks_are_review_only_across_categories_and_stop_at_appendices(tmp_path):
    _, classification, history_end, required_image, appendix_one, appendix_four, appendix_six = _fixture(tmp_path)
    review_ids = review_reference_source_ids(classification)
    historical = [block for block in classification["source_blocks"] if block["body_index"] < history_end]
    assert len(historical) == 99
    assert {block["id"] for block in historical}.issubset(review_ids)
    for block in classification["source_blocks"]:
        if history_end <= block["body_index"] < appendix_four or block["body_index"] >= appendix_six:
            assert block["id"] not in review_ids, block
        elif appendix_four <= block["body_index"] < appendix_six:
            assert block["id"] in review_ids, block
    assert next(block["id"] for block in classification["source_blocks"]
                if block["body_index"] == required_image) not in review_ids
    assert len(review_ids) == 101


def test_review_report_retains_source_coordinates_and_keeps_formal_limits(tmp_path):
    source, classification, *_ = _fixture(tmp_path)
    ledger = parse_docx_to_ledger(str(source))
    references = exclude_review_reference_sources(ledger, classification)
    assert len(references) == 101
    assert all(reference["semantic_source_ids"] and reference["source_body_index"] >= 0 for reference in references)
    assert all(reference["source_file"] == str(source.resolve()) for reference in references)
    kept = "\n".join(block.raw_text for block in ledger.blocks)
    for evidence in ("58psi", "泄漏值＜2%", "试验时间≥48h", "连接器规格书", "GB/T 13277", "压力露点满足3级"):
        assert evidence in kept
    output = tmp_path / "taskbook.docx"
    Document().save(output)
    ledger.save(output.with_suffix(".coverage_ledger.json"))
    report = Path(generate_report(str(output))).read_text(encoding="utf-8")
    assert "仅供审阅" in report and "不计入正文覆盖率" in report
    for reference in references:
        assert reference["semantic_source_ids"][0] in report


def _plan_fixture(tmp_path):
    source, classification, *_ = _fixture(tmp_path)
    output = tmp_path / "output.docx"
    target = Document()
    target.add_heading("其他要求", 1)
    target.save(output)
    from jonhon_taskbook.semantic_orchestrator import extract_template_slots
    slots = extract_template_slots(str(output))
    plan = {"schema_version": "1.0", "policy": {"llm_may_generate_text": False,
            "allowed_operations": ["copy_exact"], "delete_requires_explicit_rule": True},
            "roles": {}, "scope": {}, "section_mappings": [], "route_audit": {},
            "slots": slots, "source_blocks": classification["source_blocks"],
            "decisions": [{"target_slot": slots[0]["id"],
                           "source_ids": [block["id"] for block in classification["source_blocks"]],
                           "operation": "copy_exact", "edit_action": "append", "confidence": 0.99,
                           "reason": "old route includes raw historical artifacts"}]}
    return source, classification, output, plan


def test_backfill_does_not_turn_historical_other_or_testability_into_body(tmp_path):
    import yaml
    from jonhon_taskbook.semantic_orchestrator import _backfill_classified_routes
    _, classification, _, plan = _plan_fixture(tmp_path)
    mapping = tmp_path / "categories.yaml"
    mapping.write_text(yaml.safe_dump({"categories": {
        category: {"target_heading_keywords": ["其他要求"]}
        for category in ("performance_indicator", "other", "testability")
    }}, allow_unicode=True), encoding="utf-8")

    decisions, _ = _backfill_classified_routes([], plan["slots"], plan["source_blocks"], classification, str(mapping))

    routed = {source_id for decision in decisions for source_id in decision["source_ids"]}
    assert routed.isdisjoint(review_reference_source_ids(classification))
    assert routed


def test_executor_rechecks_saved_plan_and_never_copies_review_only_sources(tmp_path):
    from jonhon_taskbook.semantic_orchestrator import apply_semantic_plan
    _, classification, output, plan = _plan_fixture(tmp_path)

    evidence = apply_semantic_plan(str(output), plan)

    assert evidence["passed"]
    assert {item["source_id"] for item in evidence["inserted"]}.isdisjoint(review_reference_source_ids(classification))
    result = Document(output)
    texts = "\n".join(paragraph.text for paragraph in result.paragraphs)
    assert "第1批压力测试结果" not in texts
    assert "58psi" in texts and "GB/T 13277" in texts
    assert len(result.tables) == 1  # Only the formal acceptance table remains.
    assert len(evidence["review_only_sources"]) == 101


def test_cached_plan_is_rechecked_without_calling_the_model(tmp_path):
    from jonhon_taskbook.semantic_orchestrator import _plan_cache_key, build_semantic_plan
    source, classification, template, old_plan = _plan_fixture(tmp_path)
    spec = tmp_path / "spec.docx"
    Document().save(spec)
    plan_path = tmp_path / "plan.json"
    key = _plan_cache_key(str(source), str(spec), str(template), requirement_classification=classification)
    (tmp_path / f".{key}.semantic_cache.json").write_text(
        json.dumps({"cache_key": key, "plan": old_plan}, ensure_ascii=False), encoding="utf-8")

    def unexpected_model_call(*_args, **_kwargs):
        raise AssertionError("cached deterministic scope correction must not call a model")

    plan = build_semantic_plan(str(source), str(spec), str(template), str(plan_path),
                              chat_json_fn=unexpected_model_call, requirement_classification=classification)

    routed = {source_id for decision in plan["decisions"] for source_id in decision["source_ids"]}
    assert routed.isdisjoint(review_reference_source_ids(classification))
    assert len(plan["route_audit"]["review_only_sources"]) == 101
    assert json.loads(plan_path.read_text(encoding="utf-8"))["decisions"] == plan["decisions"]


@pytest.mark.parametrize("boundary", ["next_appendix", "same_level", "higher_level", "same_title", "same_title_subheading"])
def test_formal_appendix_keeps_subheadings_until_a_real_scope_boundary(tmp_path, boundary):
    source = Document()
    level = 2 if boundary == "higher_level" else 1
    if level == 2:
        source.add_heading("产品资料", 1)
    source.add_heading("测试设备及测试结果", level)
    old_image = len(source.element.body) - 1
    source.add_picture(BytesIO(_PNG))
    source.add_paragraph("附录一：连接器规格书")
    source.add_heading("外形尺寸", level + 1)
    formal_image = len(source.element.body) - 1
    source.add_picture(BytesIO(_PNG))
    source.add_heading("安装尺寸", level + 1)
    second_formal_image = len(source.element.body) - 1
    source.add_picture(BytesIO(_PNG))
    if boundary == "next_appendix":
        source.add_paragraph("附录二：连接器振动测试结果")
    else:
        title = "测试设备及测试结果" if boundary.startswith("same_title") else "后续测试结果"
        source.add_heading(title, level - 1 if boundary == "higher_level" else level)
        if boundary == "same_title_subheading":
            source.add_heading("振动测试结果", level + 1)
    new_history_image = len(source.element.body) - 1
    source.add_picture(BytesIO(_PNG))
    path = tmp_path / "appendix-with-subheadings.docx"
    source.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    classification = {"source_blocks": blocks, "classifications": [
        {"source_id": block["id"], "category": "other"} for block in blocks
    ]}

    review_ids = review_reference_source_ids(classification)
    review_positions = {block["body_index"] for block in blocks if block["id"] in review_ids}

    assert formal_image not in review_positions
    assert second_formal_image not in review_positions
    assert old_image in review_positions
    assert new_history_image in review_positions
