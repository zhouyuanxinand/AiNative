from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docx import Document

from jonhon_taskbook.extractor import parse_doc
from jonhon_taskbook.document_identity import read_document_identity
from jonhon_taskbook.fill import _apply_compilation_basis, _collect_standards


class InlineStandardsAndIdentityTests(unittest.TestCase):
    def test_numbered_applicable_standards_split_into_exact_references(self):
        tech = Document()
        tech.add_paragraph(
            "1.3 适用标准：GB/T 11313《射频同轴连接器通用规范》、"
            "GJB 6815《军用射频连接器通用规范》、IEC 60169 系列射频连接器标准。"
        )
        audit = {}
        lines = _collect_standards(
            tech, None, parse_doc(tech), [], ["GJB", "GB", "IEC"],
            include_template=False, domain="military", audit=audit,
        )
        self.assertEqual([
            "GJB 6815《军用射频连接器通用规范》",
            "GB/T 11313《射频同轴连接器通用规范》",
            "IEC 60169 系列射频连接器标准",
        ], lines)

    def test_standard_cell_and_repeated_inline_reference_are_deduplicated(self):
        tech = Document()
        tech.add_paragraph("适用标准：IEC 60169 系列射频连接器标准。")
        table = tech.add_table(rows=1, cols=1)
        table.cell(0, 0).text = "引用标准：IEC 60169 系列射频连接器标准；ISO 9001:2015 质量管理体系。"
        lines = _collect_standards(
            tech, None, parse_doc(tech), [], [], include_template=False, domain="military",
        )
        self.assertEqual(2, len(lines))
        self.assertIn("IEC 60169 系列射频连接器标准", lines)
        self.assertIn("ISO 9001:2015 质量管理体系", lines)

    def test_requirement_value_is_not_promoted_to_standard(self):
        tech = Document()
        tech.add_paragraph("电缆型号RG174；工作频率DC～6GHz，阻抗50Ω。")
        self.assertEqual([], _collect_standards(
            tech, None, parse_doc(tech), [], [], include_template=False, domain="military",
        ))

    def test_agreement_title_wins_over_clause_containing_technical_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tech.docx"
            doc = Document()
            doc.add_paragraph("射频连接器技术协议")
            doc.add_paragraph("1.2 本协议适用于本次采购，产品需完全满足本协议规定的各项技术要求。")
            doc.save(path)
            self.assertEqual("射频连接器技术协议", read_document_identity(path, "tech")["title"])

    def test_internal_upload_name_does_not_become_document_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tech.docx"
            doc = Document()
            doc.add_paragraph("1.2 产品应满足技术要求，且具备良好的电气性能。")
            doc.save(path)
            self.assertEqual("", read_document_identity(path, "tech")["title"])
            spec_path = Path(tmp) / "spec.docx"
            spec = Document()
            spec.add_paragraph("射频连接器产品规范")
            spec.save(spec_path)
            output = Document()
            output.add_heading("任务书编制依据", level=1)
            audit = _apply_compilation_basis(output, str(path), str(spec_path), str(Path(tmp) / "out.docx"))
            self.assertFalse(audit["passed"])
            self.assertNotIn("《tech》", "".join(p.text for p in output.paragraphs))


if __name__ == "__main__":
    unittest.main()
