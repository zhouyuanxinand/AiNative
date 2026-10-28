"""Cached classifications must retain readable evidence after upload cleanup."""

import json
import shutil

from docx import Document

from jonhon_taskbook.business_value_gate import audit_indicator_values
from jonhon_taskbook.requirement_classifier import (
    _classification_cache_key,
    build_requirement_classification,
)


def test_cache_hit_rebinds_cleaned_upload_before_source_table_audit(tmp_path):
    previous_upload = tmp_path / "previous-upload" / "tech.docx"
    current_upload = tmp_path / "current-upload" / "tech.docx"
    previous_upload.parent.mkdir()
    current_upload.parent.mkdir()
    source = Document()
    source.add_heading("技术规格", 1)
    table = source.add_table(rows=0, cols=2)
    for values in (("技术特性类型", "特性描述"), ("工作压力", "0.3MPa")):
        for cell, value in zip(table.add_row().cells, values):
            cell.text = value
    source.save(previous_upload)
    shutil.copyfile(previous_upload, current_upload)
    mapping = tmp_path / "categories.yaml"
    mapping.write_text("categories:\n  other:\n    definition: 其他\n", encoding="utf-8")

    output = tmp_path / "taskbook.docx"
    classification_path = output.with_suffix(".effective_requirement_classification.json")
    cache_key = _classification_cache_key(str(previous_upload), str(mapping))
    assert cache_key == _classification_cache_key(str(current_upload), str(mapping))
    cached = {
        "passed": True,
        "source_blocks": [{
            "id": "pressure-table", "source": "tech", "source_path": str(previous_upload),
            "type": "table", "body_index": 1, "heading_text": "技术规格",
        }],
        "classifications": [{
            "source_id": "pressure-table", "category": "performance_indicator",
        }],
    }
    cache_path = tmp_path / f".{cache_key}.classification.cache.json"
    cache_path.write_text(json.dumps({"cache_key": cache_key, "report": cached}), encoding="utf-8")
    previous_upload.unlink()
    assert not previous_upload.exists()

    def unexpected_llm_call(*_args, **_kwargs):
        raise AssertionError("A matching classification cache must be reused")

    report = build_requirement_classification(
        str(current_upload), str(mapping), str(classification_path),
        chat_json_fn=unexpected_llm_call,
    )
    document = Document()
    table = document.add_table(rows=0, cols=4)
    for values in (
        ("项目", "用户要求指标", "拟采用指标", "依据"),
        ("工作压力", "0.3MPa", "0.3MPa", "用户要求"),
    ):
        for cell, value in zip(table.add_row().cells, values):
            cell.text = value
    document.save(output)
    output.with_suffix(".indicator_audit.json").write_text(json.dumps({
        "input_indicator_facts": [{
            "fact_id": "pressure", "indicator_name": "工作压力", "source_label": "工作压力",
            "source_value": "0.3MPa", "source_ids": ["pressure-table"],
        }],
        "comparison_decisions": [{
            "indicator_name": "工作压力", "user_requirement": "0.3MPa",
            "adopted_requirement": "0.3MPa", "basis": "用户要求", "user_fact_ids": ["pressure"],
        }],
    }, ensure_ascii=False), encoding="utf-8")

    audit = audit_indicator_values(output, persist=False)
    assert audit["passed"], audit["blockers"]
    assert report["source_blocks"][0]["source_path"] == str(current_upload.resolve())
    persisted = json.loads(classification_path.read_text(encoding="utf-8"))
    assert persisted == report
    assert report["classifications"] == cached["classifications"]
    assert report["source_blocks"][0]["id"] == "pressure-table"
