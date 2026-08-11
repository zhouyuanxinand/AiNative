# -*- coding: utf-8 -*-
"""任务书结构化账本与 OOXML 回归比较。"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from deepdiff import DeepDiff
from xmldiff import main as xmldiff_main

DEFAULT_DOCX_PARTS = (
    "word/document.xml",
    "word/_rels/document.xml.rels",
    "word/styles.xml",
    "word/numbering.xml",
    "[Content_Types].xml",
)

# xmldiff 在含大量 Word run/table 节点的 document.xml 上可能非常慢。
# 超过此总字节数时改用确定性 SHA-256 指纹；仍能可靠判定是否变化，
# 只是不会尝试生成逐节点编辑脚本。
MAX_DETAILED_XML_DIFF_BYTES = 256_000
MAX_DETAILED_XML_EDITS = 100


def _fingerprint(data: bytes) -> dict[str, Any]:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def compare_json_files(expected: str, actual: str) -> dict[str, Any]:
    left = json.loads(Path(expected).read_text(encoding="utf-8"))
    right = json.loads(Path(actual).read_text(encoding="utf-8"))
    diff = DeepDiff(left, right, ignore_order=False, verbose_level=2)
    return json.loads(diff.to_json()) if diff else {}


def compare_docx_parts(
    expected: str, actual: str, parts: tuple[str, ...] = DEFAULT_DOCX_PARTS
) -> dict[str, list[str]]:
    differences: dict[str, list[str]] = {}
    with zipfile.ZipFile(expected) as left, zipfile.ZipFile(actual) as right:
        left_names, right_names = set(left.namelist()), set(right.namelist())
        for part in parts:
            if part not in left_names or part not in right_names:
                if (part in left_names) != (part in right_names):
                    differences[part] = [
                        f"part_presence: expected={part in left_names}, actual={part in right_names}"
                    ]
                continue
            left_data, right_data = left.read(part), right.read(part)
            if left_data == right_data:
                continue
            if len(left_data) + len(right_data) > MAX_DETAILED_XML_DIFF_BYTES:
                differences[part] = [
                    json.dumps(
                        {
                            "comparison": "sha256",
                            "reason": "XML part too large for bounded detailed diff",
                            "expected": _fingerprint(left_data),
                            "actual": _fingerprint(right_data),
                        },
                        ensure_ascii=False,
                    )
                ]
                continue
            edits = xmldiff_main.diff_texts(left_data, right_data)
            if edits:
                rendered = [str(edit) for edit in edits[:MAX_DETAILED_XML_EDITS]]
                if len(edits) > MAX_DETAILED_XML_EDITS:
                    rendered.append(
                        json.dumps(
                            {
                                "truncated": True,
                                "shown_edits": MAX_DETAILED_XML_EDITS,
                                "total_edits": len(edits),
                            },
                            ensure_ascii=False,
                        )
                    )
                differences[part] = rendered

        left_media = {
            name: _fingerprint(left.read(name))
            for name in left_names
            if name.startswith("word/media/")
        }
        right_media = {
            name: _fingerprint(right.read(name))
            for name in right_names
            if name.startswith("word/media/")
        }
        media_diff = DeepDiff(left_media, right_media, ignore_order=False)
        if media_diff:
            differences["word/media/*"] = [media_diff.to_json()]
    return differences


def build_regression_report(
    expected_docx: str,
    actual_docx: str,
    expected_json: str | None = None,
    actual_json: str | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "docx_differences": compare_docx_parts(expected_docx, actual_docx),
        "json_differences": {},
    }
    if expected_json and actual_json:
        report["json_differences"] = compare_json_files(expected_json, actual_json)
    report["passed"] = not report["docx_differences"] and not report["json_differences"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="比较两版任务书的 OOXML 和结构化账本")
    parser.add_argument("expected_docx")
    parser.add_argument("actual_docx")
    parser.add_argument("--expected-json")
    parser.add_argument("--actual-json")
    parser.add_argument("--out", default="regression_report.json")
    args = parser.parse_args()
    report = build_regression_report(
        args.expected_docx,
        args.actual_docx,
        args.expected_json,
        args.actual_json,
    )
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
