from __future__ import annotations

import json
import unittest

from jonhon_taskbook.requirement_classifier import (
    _apply_explicit_empty_content_fallback,
    _classify_with_llm,
)


def _chapter(source_id: str, text: str) -> dict:
    return {
        "id": source_id,
        "heading_text": "其余技术要求",
        "parent_headings": ["技术要求"],
        "previous_heading": "工作温度",
        "next_heading": "验收要求",
        "type": "chapter",
        "text": text,
    }


class RequirementClassifierRecoveryTests(unittest.TestCase):
    def test_classification_retries_only_missing_source_ids(self) -> None:
        calls: list[dict] = []

        def fake_chat_json(_system: str, user: str) -> dict:
            payload = json.loads(user)
            calls.append(payload)
            if len(calls) == 1:
                return {
                    "classifications": [
                        {
                            "source_id": "chapter-a",
                            "category": "other",
                            "confidence": 0.9,
                            "reason": "已分类",
                        }
                    ]
                }
            return {
                "classifications": [
                    {
                        "source_id": "chapter-b",
                        "category": "other",
                        "confidence": 0.95,
                        "reason": "补齐遗漏项",
                    }
                ]
            }

        result = _classify_with_llm(
            [_chapter("chapter-a", "有要求。"), _chapter("chapter-b", "无。")],
            {"other": {"definition": "其他内容"}},
            fake_chat_json,
        )

        self.assertEqual({"chapter-a", "chapter-b"}, set(result))
        self.assertEqual("llm_retry_2", result["chapter-b"]["method"])
        self.assertEqual(
            ["chapter-b"],
            [item["source_id"] for item in calls[1]["blocks"]],
        )
        self.assertEqual(
            ["chapter-b"],
            calls[1]["completion_retry"]["required_source_ids"],
        )

    def test_explicit_empty_content_is_recovered_as_other(self) -> None:
        recovered = _apply_explicit_empty_content_fallback(
            [_chapter("tech-chapter-a2abbe0a0475", "无。")],
            {},
            {"other": {"definition": "其他内容"}},
        )

        assignment = recovered["tech-chapter-a2abbe0a0475"]
        self.assertEqual("other", assignment["category"])
        self.assertEqual(1.0, assignment["confidence"])
        self.assertEqual(
            "controlled_empty_content_after_llm_retry",
            assignment["method"],
        )

    def test_non_empty_missing_chapter_is_not_silently_recovered(self) -> None:
        recovered = _apply_explicit_empty_content_fallback(
            [_chapter("chapter-required", "连接器应满足工作温度要求。")],
            {},
            {"other": {"definition": "其他内容"}},
        )

        self.assertEqual({}, recovered)
