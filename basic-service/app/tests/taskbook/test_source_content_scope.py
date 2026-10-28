from tests.support.paths import APP_ROOT
import json
import base64
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from jonhon_taskbook.coverage_ledger import parse_docx_to_ledger, mark_covered_from_output
from jonhon_taskbook.semantic_orchestrator import extract_source_blocks
from jonhon_taskbook.semantic_orchestrator import _is_heading, _is_style_heading
from jonhon_taskbook.template_scanner import scan_template_tree
from jonhon_taskbook.coverage_ledger import exclude_semantic_structure_headings


def _save(tmp_path, paragraphs, name="requirements.docx"):
    document = Document()
    document.add_heading("射频连接器技术协议", 1)
    for text, level in paragraphs:
        if level:
            document.add_heading(text, level)
        else:
            document.add_paragraph(text)
    path = tmp_path / name
    document.save(path)
    return path


def _overzealous_headings(_system, payload):
    data = json.loads(payload)
    return {"headings": [{"body_index": item["body_index"], "level": 3, "confidence": 0.99}
                         for item in data["paragraphs"]]}


def test_inline_requirements_survive_incorrect_model_heading_hints(tmp_path):
    requirements = [
        "2.1 应用领域：主要应用于无线通信设备、测试测量仪器及车载射频系统。",
        "2.2 工作环境：支持室内、户外使用，适配设备整机集成。",
        "2.3 功能定位：实现同轴线缆与设备之间的可靠连接。",
        "3.2 结构形式：直式/弯式可选，公头/母头适配，螺纹锁紧/卡扣式固定。",
        "3.3 适配线缆：匹配50Ω/75Ω射频同轴电缆，适配RG174、RG58、RG213。",
        "5.1 整体尺寸：外形符合对应型号国标尺寸，孔位匹配行业通用规格。",
        "5.4 安装要求：安装便捷，锁紧后无晃动。",
    ]
    path = _save(tmp_path, [("2. 应用背景与使用场景", 2)] + [(text, 0) for text in requirements])
    audit = tmp_path / "structure.json"
    blocks = extract_source_blocks(str(path), "tech", chat_json_fn=_overzealous_headings, structure_audit_path=audit)
    ledger = parse_docx_to_ledger(str(path))
    assert {b["text"] for b in blocks} == set(requirements)
    assert {b.raw_text for b in ledger.blocks} == set(requirements)
    saved = json.loads(audit.read_text(encoding="utf-8"))
    assert sum(h["action"] == "preserve_content" for h in saved["headings"]) == len(requirements)
    assert all(b["chapter_id"] for b in blocks)


def test_cover_title_and_empty_result_captions_are_not_technical_requirements(tmp_path):
    doc = Document()
    doc.add_paragraph("部  件  规  格  承  认  书")
    doc.add_heading("测试结果", 1)
    doc.add_paragraph("测试结果：")
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "压力：200 kPa"
    doc.add_paragraph("测试结果：不合格，压降超过 2 kPa。")
    doc.add_paragraph("测试结果：")  # No following artifact: do not silently waive it.
    path = tmp_path / "captions.docx"
    doc.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    ledger = parse_docx_to_ledger(str(path))
    assert {b["body_index"] for b in blocks} == {3, 4, 5}
    assert {b.source_body_index for b in ledger.blocks} == {3, 4, 5}


def test_structural_parent_without_direct_body_uses_same_source_position_audit(tmp_path):
    doc = Document()
    doc.add_paragraph("八、测试设备及测试结果")
    doc.add_paragraph("测试压力必须达到 200 kPa。")
    path = tmp_path / "audited-headings.docx"
    doc.save(path)
    classification = {
        "source_blocks": [{"source_path": str(path), "body_index": 1, "text": doc.paragraphs[1].text}],
        "source_chapters": [],
        "source_structure_audit": {
            "source_path": str(path),
            "headings": [
                {"body_index": 0, "action": "structure_only"},
                {"body_index": 1, "action": "structure_only"},
            ],
        },
    }
    ledger = parse_docx_to_ledger(str(path))
    excluded = exclude_semantic_structure_headings(ledger, classification)
    assert len(excluded) == 1
    assert excluded[0]["text"] == "八、测试设备及测试结果"
    assert [b.raw_text for b in ledger.blocks] == [doc.paragraphs[1].text]
    classification["source_structure_audit"]["source_path"] = str(tmp_path / "other.docx")
    ledger = parse_docx_to_ledger(str(path))
    assert exclude_semantic_structure_headings(ledger, classification) == []


@pytest.mark.parametrize("chat", [None, lambda _system, _payload: {"headings": []}, _overzealous_headings])
def test_inline_sibling_exits_material_chapter(tmp_path, chat):
    path = _save(tmp_path, [
        ("5. 外形尺寸与结构要求", 2),
        ("5.1 整体尺寸：符合对应型号国标尺寸。", 0),
        ("5.2 结构材质要求：", 0),
        ("（1）绝缘介质：采用PTFE聚四氟乙烯材质。", 0),
        ("5.3 外观要求：表面无毛刺、无镀层脱落。", 0),
        ("5.4 安装要求：锁紧后无晃动，安装间距符合要求。", 0),
    ])
    blocks = extract_source_blocks(str(path), "tech", chat_json_fn=chat)
    material = next(b for b in blocks if "PTFE" in b["text"])
    assert material["heading_text"] == "结构材质要求"
    for block in blocks:
        if block["text"].startswith(("5.3", "5.4")):
            assert "结构材质要求" not in block["parent_headings"]
            assert block["heading_text"] in {"外观要求", "安装要求"}


def test_chapter_identity_does_not_depend_on_display_number(tmp_path):
    chapter_ids = []
    for number in [2, 9]:
        path = _save(tmp_path, [(f"{number}. 应用背景与使用场景", 2),
                               (f"{number}.1 应用领域：用于无线通信设备。", 0)], f"source-{number}.docx")
        chapter_ids.append(extract_source_blocks(str(path), "tech")[0]["chapter_id"])
    assert chapter_ids[0] == chapter_ids[1]


def test_empty_heading_does_not_reset_source_parent(tmp_path):
    path = _save(tmp_path, [("产品的功能用途", 1), ("", 1), ("其他", 2), ("产品表面无毛刺。", 0)])
    block = extract_source_blocks(str(path), "tech")[0]
    assert block["parent_headings"] == ["产品的功能用途"]
    assert block["heading_text"] == "其他"


def test_real_rf_template_empty_heading_keeps_appearance_parent():
    template = APP_ROOT / "src/service/jonhon_taskbook/resources/templates/rf_connector_taskbook.docx"
    document = Document(template)
    empty_headings = [p for p in document.paragraphs if not p.text.strip() and p.style.name.lower() == "heading 1"]
    assert empty_headings
    assert all(not _is_heading(p._p) and not _is_style_heading(p._p) for p in empty_headings)
    tree = scan_template_tree(str(template))
    assert any(node["title"] == "其他" and node["semantic_path"] == "产品的功能用途 / 其他" for node in tree)


def test_signature_scope_matches_coverage_and_retains_schedule_dates(tmp_path):
    technical = ["2026年9月17日", "日期：2026年10月1日", "产品交付时须提供供方签字的检验报告。"]
    path = _save(tmp_path, [("8. 进度要求", 2)] + [(text, 0) for text in technical] + [
        ("9. 其他约定", 2),
        ("9.1 本协议一式两份，供需双方各执一份，签字盖章后生效。", 0),
        ("10. 双方签字", 2),
        ("需方（盖章）：______________", 0),
        ("代表人签字：______________", 0),
        ("日期：______年____月____日", 0),
        ("供方（盖章）：______________", 0),
        ("2026年9月17日", 0),
        ("|（注：部分内容可能由 AI 生成）", 0),
    ])
    blocks = extract_source_blocks(str(path), "tech")
    ledger = parse_docx_to_ledger(str(path))
    assert [b["text"] for b in blocks] == technical
    assert [b.raw_text for b in ledger.blocks] == technical


def test_signature_table_and_seal_are_excluded_but_following_technical_image_survives(tmp_path):
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5Wk3kAAAAASUVORK5CYII=")
    document = Document()
    document.add_heading("签署", 1)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "使用单位签署"
    table.cell(0, 1).text = "研制单位签署（签字/盖章）"
    document.add_paragraph().add_run().add_picture(BytesIO(png))
    document.add_heading("产品组成", 1)
    document.add_paragraph().add_run().add_picture(BytesIO(png))
    document.add_paragraph("图1 产品组成示意图")
    path = tmp_path / "signature-media.docx"
    document.save(path)
    blocks = extract_source_blocks(str(path), "tech")
    ledger = parse_docx_to_ledger(str(path))
    assert {b["body_index"] for b in blocks} == {4, 5}
    assert {b.source_body_index for b in ledger.blocks} == {4, 5}
    assert sum(b["has_drawing"] for b in blocks) == 1
    assert sum(b.block_type == "image" for b in ledger.blocks) == 1


REFERENCES = ["GB/T 11313《射频同轴连接器通用规范》", "GJB 6815《军用射频连接器通用规范》", "IEC 60169 系列射频连接器标准"]


@pytest.mark.parametrize("output_references,expected", [
    (REFERENCES, True),
    (list(reversed(REFERENCES)), True),
    (REFERENCES[:2], False),
    ([REFERENCES[0], "GJB 6815《不同的规范名称》", REFERENCES[2]], False),
])
def test_all_explicit_standard_references_need_complete_evidence(tmp_path, output_references, expected):
    path = _save(tmp_path, [("1. 总则", 2), ("1.3 适用标准：" + "、".join(REFERENCES) + "。", 0)])
    output = _save(tmp_path, [("适用的法律法规要求", 1)] + [(text, 0) for text in output_references], "output.docx")
    ledger = parse_docx_to_ledger(str(path))
    mark_covered_from_output(ledger, str(output))
    assert len(ledger.blocks) == 1
    assert ledger.blocks[0].covered is expected
    if expected:
        assert len(ledger.blocks[0].output_body_indices) == 3
