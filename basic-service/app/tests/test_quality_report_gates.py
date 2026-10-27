import json
import tempfile
import unittest
from pathlib import Path

from docx import Document
from jonhon_taskbook.html_reporter import generate_report


class QualityReportGatesTests(unittest.TestCase):
    def test_a_partial_success_cannot_replace_missing_coverage_qa(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.docx"
            Document().save(path)
            path.with_suffix(".delivery_gate.json").write_text('{"passed": true, "blockers": []}', encoding="utf-8")
            result = Path(generate_report(str(path))).read_text(encoding="utf-8")
            self.assertIn("检查未完成", result)
            self.assertNotIn("全部门禁通过", result)

    def test_delivery_failure_is_visible_when_coverage_qa_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.docx"
            Document().save(path)
            path.with_suffix(".qa_gate_report.md").write_text("# QA\n**状态**: ✅ 通过\n", encoding="utf-8")
            path.with_suffix(".delivery_gate.json").write_text(json.dumps({
                "passed": False, "blockers": [{"code": "FILL_ZONE", "label": "签字占位符", "location": "段落#3"}],
            }, ensure_ascii=False), encoding="utf-8")
            result = Path(generate_report(str(path))).read_text(encoding="utf-8")
            self.assertIn("签字占位符", result)
            self.assertIn("正式交付", result)
            self.assertNotIn("全部门禁通过", result)

    def test_inapplicable_specification_has_a_visible_explanation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.docx"
            Document().save(path)
            path.with_suffix(".indicator_audit.json").write_text(json.dumps({
                "comparison_decisions": [{"indicator_name": "耐电压", "status": "SPEC_MODEL_NOT_APPLICABLE", "reason": "规范型号与本次产品不匹配。"}],
            }, ensure_ascii=False), encoding="utf-8")
            result = Path(generate_report(str(path))).read_text(encoding="utf-8")
            self.assertIn("规范型号与本次产品不匹配", result)
            self.assertIn("仅采用用户要求", result)


if __name__ == "__main__":
    unittest.main()
