"""Human case records: clarification adoption, comparison, receipts and candidates.

These records live inside the existing case transaction. They do not infer
engineering facts, impersonate recipients, publish knowledge or start workers.
"""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy

from .catalog import STAGE_IDS
from .store import RdError, _id, _json, _now, _text


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _version(record):
    return deepcopy({key: value for key, value in record.items() if key != "history"})


def _is_placeholder(value):
    """Match an empty value, or a bare placeholder with an optional metric label."""
    value = value.strip()
    return not value or re.fullmatch(
        r"(?:[^:：\n。.!！?？;；，,]{1,200}[:：]\s*)?"
        r"(?:待澄清|待确认|待定|待补充|未明确|待填写|待采纳|待核对|【人工填写】)"
        r"(?:\s*[（(][^()（）\n]*[)）])?[。．.!！?？;；,，\s]*",
        value,
    ) is not None


class CaseRecords:
    COMMANDS = {"open_clarification", "answer_clarification", "adopt_clarification", "save_comparison", "record_delivery", "prepare_reuse", "record_engineering_node", "review_requirement"}

    def __init__(self, store):
        self.store = store

    def command(self, case, command, data, actor):
        return getattr(self, command)(case, data, actor)

    @staticmethod
    def initialize(case):
        for field in ("clarifications", "comparisons", "deliveries", "reuse_candidates"):
            case.setdefault(field, [])
        case.setdefault("reuse_disposition", None)
        for requirement in case["requirements"]:
            requirement.setdefault("revision", 1)
            requirement.setdefault("history", [])

    def _sources(self, case, ids):
        selected = set(ids)
        return [{key: source[key] for key in ("id", "role", "name", "version", "sha256")}
                for source in case["sources"] if source["id"] in selected]

    @staticmethod
    def _requirement(case, rid):
        requirement = next((item for item in case["requirements"] if item["id"] == rid), None)
        if requirement is None:
            raise RdError(422, "需求不属于当前案例。")
        return requirement

    @staticmethod
    def _requirements(case):
        return [{"id": item["id"], "revision": item["revision"], "sha256": _hash({key: item[key] for key in ("id", "revision", "title", "content", "source_ids")})}
                for item in case["requirements"]]

    def save_requirement(self, case, data, actor, *, clarification_id=None, review=None, specification_result=None):
        self.store._evidence(case, data.get("source_ids"))
        rid = data.get("id")
        previous = self._requirement(case, rid) if rid else None
        values = {"title": _text(data.get("title"), "需求标题", 200, True),
                  "content": _text(data.get("content"), "需求内容", 20000, True), "source_ids": list(dict.fromkeys(data["source_ids"]))}
        unchanged = previous and all(previous[key] == values[key] for key in ("title", "content")) and set(previous["source_ids"]) == set(values["source_ids"])
        if unchanged and clarification_id is None and review is None and specification_result is None:
            return {"requirement_id": previous["id"], "input_revision": case["input_revision"], "invalidated_decision_ids": []}
        history = deepcopy(previous["history"]) if previous else []
        if previous and not history:
            # Legacy content is known; its missing author/time must stay unknown.
            history.append({"revision": previous["revision"], **{key: previous[key] for key in ("title", "content", "source_ids")},
                            "actor": None, "created_at": None, "source_snapshots": self._sources(case, previous["source_ids"])})
        revision = previous["revision"] + 1 if previous else 1
        entry = {"revision": revision, **deepcopy(values), "actor": actor, "created_at": _now(), "source_snapshots": self._sources(case, values["source_ids"])}
        if clarification_id:
            entry["clarification_id"] = clarification_id
        if specification_result:
            entry.update(actual_value_source="specification", recommendation_batch_id=specification_result["recommendation_batch_id"])
        history.append(entry)
        requirement = {"id": rid or _id(), **values, "revision": revision, "history": history}
        if previous:
            for field in ("analysis_id", "evidence", "review_history"):
                if field in previous:
                    requirement[field] = deepcopy(previous[field])
            case["requirements"][case["requirements"].index(previous)] = requirement
        else:
            case["requirements"].append(requirement)
        invalidated = self.store._invalidate_inputs(case, "用户明确修改或采用了需求及其依据，需要重新确认。",
            reviewed_requirement_id=rid if review or clarification_id or specification_result else None,
            retain_review_stage=review is not None or specification_result is not None)
        if review:
            decision = {**review, "actor": actor, "created_at": entry["created_at"], "requirement_revision": revision, "input_revision": case["input_revision"]}
            requirement["review"] = decision
            requirement.setdefault("review_history", []).append(deepcopy(decision))
        if specification_result:
            requirement["specification_result"] = {**deepcopy(specification_result), "actor": actor,
                "created_at": entry["created_at"], "requirement_revision": revision, "input_revision": case["input_revision"]}
        return {"requirement_id": requirement["id"], "requirement_revision": revision,
                "input_revision": case["input_revision"], "invalidated_decision_ids": invalidated}

    def review_requirement(self, case, data, actor):
        if (case["stage"] not in {"input", "requirements"} or case["status"] == "completed"
                or case.get("business_lifecycle", {}).get("current_requirement_baseline_id")):
            raise RdError(409, "需求确认后只读；请先建立新的需求修订。")
        if set(data) - {"case_id", "requirement_id", "requirement_revision", "analysis_id", "recommendation_batch_id", "decision", "actual_value", "reason"}:
            raise RdError(422, "只接受当前需求的逐项决定，原文和推荐依据由服务端读取。")
        row = self._requirement(case, data.get("requirement_id"))
        expected = data.get("requirement_revision")
        if type(expected) is not int or expected != row["revision"]:
            raise RdError(409, "需求版本已变化，请保留草稿并核对新版本。")
        kind = data.get("decision")
        if kind == "manual":
            raise RdError(422, "实际结果不能直接手工填写，请办理澄清、保存有来源的答复后明确采用。")
        if kind not in ("accept", "reject"):
            raise RdError(422, "请选择采纳、不采纳；其他实际结果请通过澄清采用。")
        analysis = case.get("source_analysis") or {}
        aid = data.get("analysis_id")
        batch_id = data.get("recommendation_batch_id")
        batch = case.get("requirement_recommendations")
        if batch and not batch_id:
            raise RdError(409, "请基于当前规范建议批次核对需求，不能使用历史分析建议。")
        if not batch_id:
            raise RdError(422, "请先在需求确认中生成独立的规范建议批次，再采纳或不采纳；资料识别结果仅用于提取原文。")
        matches = [item for item in analysis.get("requirements", []) if item.get("requirement_id") == row["id"] and item.get("status") != "rejected"]
        if aid or batch_id or matches:
            if not aid or aid != analysis.get("id") or analysis.get("status") != "adopted" or analysis.get("adopted_input_revision") != case["input_revision"]:
                raise RdError(409, "需求分析版本已变更或未采用，请先核对当前资料。")
            if analysis["source_hashes"] != {source["id"]: source["sha256"] for source in self.store._active_sources(case)}:
                raise RdError(409, "增强建议的来源已变化，请重新分析。")
        recommendation = None
        if batch_id:
            self._check_recommendation_batch(case, batch_id)
            items = [item for item in batch.get("items", []) if item.get("requirement_id") == row["id"]]
            recommendation = items[0] if len(items) == 1 else None
            previous = row.get("review") or {}
            already_reviewed = (previous.get("recommendation_batch_id") == batch_id
                                and previous.get("requirement_revision") == row["revision"])
            if not recommendation or (recommendation.get("requirement_revision") != row["revision"] and not already_reviewed):
                raise RdError(409, "此项需求已变化，请重新核对规范后再处理建议。")
            if kind == "accept" and (recommendation.get("status") not in {"matched", "needs_review"}
                    or (recommendation.get("status") == "matched" and not recommendation.get("proposed_value"))):
                raise RdError(422, "规范差异或待核对内容不能直接采纳，请办理澄清并明确采用。")
            if kind == "reject" and recommendation.get("status") == "not_found":
                raise RdError(422, "规范未找到对应指标，无需拒绝建议，请办理澄清并明确采用。")
        if not recommendation:
            raise RdError(422, "此项没有可核实的增强建议，请办理澄清并明确采用。")
        reason = _text(data.get("reason", ""), "不采纳原因" if kind == "reject" else "决定说明", 4000, kind == "reject")
        source_ids = list(row["source_ids"])
        refs = []
        if recommendation:
            refs = list(dict.fromkeys(e["source_id"] for e in recommendation["evidence"]))
            self.store._evidence(case, refs, required=kind == "accept")
        original = self._original_requirement(case, row) if kind == "accept" and recommendation.get("status") == "needs_review" else None
        if kind == "accept" and recommendation.get("status") == "needs_review" and original is None:
            raise RdError(422, "没有可核实的原始指标，不能直接采纳，请办理澄清并明确采用。")
        actual = (original["content"] if original else recommendation.get("proposed_value")) if kind == "accept" else None
        if "actual_value" in data and data["actual_value"] != actual:
            raise RdError(422, "此决定不能改写实际结果；如需修改请办理澄清并明确采用。")
        if kind == "accept":
            source_ids = list(dict.fromkeys([*source_ids, *refs, *((original or {}).get("source_ids", []))]))
        previous = row.get("review") or {}
        review = {"decision": kind, "reason": reason, "actual_value": actual, "analysis_id": aid, "recommendation": deepcopy(recommendation),
                  "recommendation_sources": self._sources(case, refs)}
        if original:
            review["actual_value_source"] = "original"
        if batch_id:
            review["recommendation_batch_id"] = batch_id
        if previous.get("requirement_revision") == row["revision"] and all(previous.get(k) == v for k, v in review.items()):
            return {"requirement_id": row["id"], "requirement_revision": row["revision"], "decision": kind}
        result = self.save_requirement(case, {"id": row["id"], "title": row["title"],
            "content": actual if kind == "accept" else row["content"], "source_ids": source_ids}, actor, review=review)
        return {**result, "decision": kind}

    def _check_recommendation_batch(self, case, batch_id):
        batch = case.get("requirement_recommendations") or {}
        if (batch.get("id") != batch_id or batch.get("status") != "current"
                or batch.get("input_revision") != case["input_revision"]):
            raise RdError(409, "规范建议批次已变化或过期，请重新核对当前资料。")
        sources = self.store._active_sources(case)
        if batch.get("source_hashes") != {s["id"]: s["sha256"] for s in sources}:
            raise RdError(409, "规范建议的来源已变化，请重新核对。")
        for source in sources:
            self.store._checked_path(source)
        return batch

    def check_requirement_reviews(self, case):
        if (case.get("business_lifecycle") or {}).get("policy_version") == "v2":
            batch = case.get("requirement_recommendations")
            if batch:
                self._check_recommendation_batch(case, batch["id"])
            for row in case["requirements"]:
                if self.explicit_requirement_result(case, row) is None:
                    item = next((item for item in (batch or {}).get("items", []) if item.get("requirement_id") == row["id"]), {})
                    if item.get("status") in {"difference", "needs_review"} and (row.get("review") or {}).get("decision") != "reject":
                        raise RdError(422, f"「{row['title']}」的规范建议尚未处理，请核对适用性或完成需求澄清。")
                    raise RdError(422, f"「{row['title']}」缺少明确采用值，请先完成需求澄清。")
            return
        self._check_legacy_requirement_reviews(case)

    def _original_requirement(self, case, row):
        """Return the adopted source snapshot, never a mutable result or model proposal."""
        analysis = case.get("source_analysis") or {}
        active_hashes = {source["id"]: source["sha256"] for source in self.store._active_sources(case)}
        if (analysis.get("status") != "adopted" or analysis.get("adopted_input_revision") != case["input_revision"]
                or analysis.get("source_hashes") != active_hashes):
            return None
        originals = [item for item in analysis.get("requirements", [])
                     if item.get("requirement_id") == row["id"] and item.get("status") != "rejected"]
        if len(originals) != 1:
            return None
        original = originals[0]
        value = original.get("content", "")
        source_ids = original.get("source_ids", [])
        if (not isinstance(value, str) or _is_placeholder(value) or value.strip() == "--" or not source_ids
                or not set(source_ids).issubset(active_hashes)):
            return None
        return original

    def _specification_result(self, case, row, batch, item, active_hashes):
        """A verified match is ready for unified confirmation without a per-row vote."""
        value = item.get("proposed_value", "")
        if item.get("status") != "matched" or not isinstance(value, str) or _is_placeholder(value) or value.strip() == "--":
            return None
        review = row.get("review") or {}
        if (review.get("recommendation_batch_id") == batch.get("id")
                and review.get("requirement_revision") == row["revision"]
                and review.get("decision") in {"reject", "manual"}):
            return None
        spec_ids = {source["id"] for source in self.store._active_sources(case) if source["role"] == "spec"}
        evidence = item.get("evidence") or []
        if not evidence or any(entry.get("source_id") not in spec_ids or not entry.get("quote", "").strip() for entry in evidence):
            return None
        persisted = row.get("specification_result") or {}
        persisted_current = (persisted.get("actual_value_source") == "specification"
            and persisted.get("recommendation_batch_id") == batch.get("id")
            and persisted.get("requirement_revision") == row["revision"]
            and persisted.get("source_requirement_revision") == item.get("requirement_revision")
            and persisted.get("source_hashes") == active_hashes
            and persisted.get("actual_value") == row["content"] == value)
        if item.get("requirement_revision") != row["revision"] and not persisted_current:
            return None
        return value

    def explicit_requirement_result(self, case, row):
        """Resolve clarification, explicit original adoption, or a current verified match."""
        batch = case.get("requirement_recommendations") or {}
        review = row.get("review") or {}
        active_hashes = {source["id"]: source["sha256"] for source in self.store._active_sources(case)}
        if not set(row.get("source_ids", [])).issubset(active_hashes):
            return None
        batch_current = (batch.get("status") == "current" and batch.get("input_revision") == case["input_revision"]
                         and batch.get("source_hashes") == active_hashes)
        if batch and not batch_current:
            return None
        items = [item for item in batch.get("items", []) if item.get("requirement_id") == row["id"]]
        item = items[0] if len(items) == 1 else {}
        for record in case.get("clarifications", []):
            adoption = record.get("adoption") or {}
            if (record.get("status") != "adopted" or record.get("requirement_id") != row["id"]
                    or adoption.get("requirement_revision") != row["revision"]
                    or adoption.get("requirement_content") != row["content"]
                    or (batch and adoption.get("recommendation_batch_id") != batch.get("id"))):
                continue
            if not any(entry.get("revision") == row["revision"] and entry.get("clarification_id") == record.get("id")
                       for entry in row.get("history", [])):
                continue
            if (record.get("answer_source_snapshots") != self._sources(case, record.get("answer_source_ids", []))
                    or not set(record.get("answer_source_ids", [])).issubset(active_hashes)
                    or (adoption.get("source_hashes") is not None and adoption["source_hashes"] != active_hashes)):
                continue
            if not _is_placeholder(row.get("content", "")) and row["content"].strip() != "--":
                return row["content"]
        if (batch_current and review.get("decision") == "accept"
                and review.get("recommendation_batch_id") == batch.get("id")
                and review.get("requirement_revision") == row["revision"]
                and review.get("actual_value") == row["content"]
                and not _is_placeholder(row["content"]) and row["content"].strip() != "--"):
            if item.get("status") == "matched" and item.get("proposed_value") == row["content"]:
                return row["content"]
            original = self._original_requirement(case, row)
            if (item.get("status") == "needs_review" and review.get("actual_value_source") == "original"
                    and review.get("analysis_id") == (case.get("source_analysis") or {}).get("id")
                    and original is not None and original["content"] == row["content"]):
                return row["content"]
        if batch_current:
            return self._specification_result(case, row, batch, item, active_hashes)
        return None

    def materialize_specification_results(self, case, actor):
        """Freeze automatic matches only as part of the owner's unified confirmation."""
        batch = case.get("requirement_recommendations") or {}
        if not batch:
            return
        active_hashes = {source["id"]: source["sha256"] for source in self.store._active_sources(case)}
        for row in list(case["requirements"]):
            items = [item for item in batch.get("items", []) if item.get("requirement_id") == row["id"]]
            if len(items) != 1:
                continue
            item = items[0]
            value = self._specification_result(case, row, batch, item, active_hashes)
            review = row.get("review") or {}
            # An adopted clarification or existing explicit decision is authoritative.
            if (value is None or self.explicit_requirement_result(case, row) != value
                    or item.get("requirement_revision") != row["revision"]
                    or (review.get("recommendation_batch_id") == batch["id"] and review.get("requirement_revision") == row["revision"])
                    or any(record.get("status") == "adopted" and record.get("requirement_id") == row["id"]
                           and (record.get("adoption") or {}).get("requirement_revision") == row["revision"]
                           and (record.get("adoption") or {}).get("recommendation_batch_id") == batch["id"]
                           for record in case.get("clarifications", []))):
                continue
            refs = [entry["source_id"] for entry in item["evidence"]]
            self.save_requirement(case, {"id": row["id"], "title": row["title"], "content": value,
                "source_ids": list(dict.fromkeys([*row["source_ids"], *refs]))}, actor, specification_result={
                    "actual_value_source": "specification", "actual_value": value,
                    "recommendation_batch_id": batch["id"], "source_requirement_revision": item["requirement_revision"],
                    "source_hashes": active_hashes})

    def _check_legacy_requirement_reviews(self, case):
        rows = {r["id"]: r for r in case["requirements"]}
        batch = case.get("requirement_recommendations")
        if batch:
            actionable = [item for item in batch.get("items", []) if item.get("status") != "not_found"]
            if actionable:
                self._check_recommendation_batch(case, batch["id"])
            for item in actionable:
                row = rows.get(item["requirement_id"])
                if row is None or self.explicit_requirement_result(case, row) is None:
                    title = row["title"] if row else "需求"
                    raise RdError(422, f"「{title}」的规范建议尚未处理，请填写决定或采用澄清结果。")
        for row in rows.values():
            value = self.explicit_requirement_result(case, row) or row.get("content", "")
            if _is_placeholder(value) or value.strip() == "--":
                raise RdError(422, f"「{row['title']}」缺少明确采用值，请先完成需求澄清。")

    def open_clarification(self, case, data, actor):
        if case["stage"] not in {"input", "requirements"}:
            raise RdError(422, "请在资料澄清或需求确认阶段提出澄清。")
        requirement = self._requirement(case, data.get("requirement_id"))
        self.store._evidence(case, data.get("source_ids"))
        record = {"id": _id(), "requirement_id": requirement["id"], "requirement_revision": requirement["revision"],
                  "requirement_snapshot": {key: deepcopy(requirement[key]) for key in ("id", "revision", "title", "content", "source_ids")},
                  "question": _text(data.get("question"), "澄清问题", 10000, True), "required": True, "status": "open", "revision": 1,
                  "input_revision": case["input_revision"], "source_ids": list(dict.fromkeys(data["source_ids"])),
                  "source_snapshots": self._sources(case, data["source_ids"]), "actor": actor, "created_at": _now(),
                  "answer": None, "answer_source_ids": [], "answered_by": None, "answered_at": None, "adoption": None, "history": []}
        record["history"].append(_version(record))
        case["clarifications"].append(record)
        return {"clarification_id": record["id"], "clarification_revision": 1}

    def _clarification(self, case, cid, *, refresh=False):
        record = next((item for item in case["clarifications"] if item["id"] == cid), None)
        if record is None:
            raise RdError(404, "澄清记录不存在。")
        requirement = self._requirement(case, record["requirement_id"])
        if not refresh and (record.get("invalidated_at") or record["input_revision"] != case["input_revision"] or record["requirement_revision"] != requirement["revision"]):
            raise RdError(409, "澄清所针对的输入或需求版本已变化，请针对当前版本重新澄清。")
        if record["status"] == "adopted":
            raise RdError(409, "已采用澄清不可覆盖，请形成新记录。")
        return record, requirement

    def answer_clarification(self, case, data, actor):
        record, requirement = self._clarification(case, data.get("clarification_id"), refresh=True)
        self.store._evidence(case, data.get("source_ids"))
        record.pop("invalidated_at", None)
        record.pop("invalidated_reason", None)
        record["input_revision"] = case["input_revision"]
        record["requirement_revision"] = requirement["revision"]
        record["requirement_snapshot"] = {key: deepcopy(requirement[key]) for key in ("id", "revision", "title", "content", "source_ids")}
        record.update(answer=_text(data.get("answer"), "澄清答复", 20000, True), answer_source_ids=list(dict.fromkeys(data["source_ids"])),
                      answer_source_snapshots=self._sources(case, data["source_ids"]), answered_by=actor, answered_at=_now(),
                      status="answered", revision=record["revision"] + 1)
        record["history"].append(_version(record))
        return {"clarification_id": record["id"], "clarification_revision": record["revision"]}

    def adopt_clarification(self, case, data, actor):
        record, requirement = self._clarification(case, data.get("clarification_id"))
        if record["status"] != "answered":
            raise RdError(409, "请先保存有来源的澄清答复，再明确采用。")
        content = _text(data.get("requirement_content"), "明确采用的需求正文", 20000, True)
        batch = case.get("requirement_recommendations") or {}
        batch_id = None
        if batch.get("status") == "current" and batch.get("input_revision") == case["input_revision"]:
            item = next((item for item in batch.get("items", []) if item.get("requirement_id") == requirement["id"]), {})
            review = requirement.get("review") or {}
            reviewed_current = (review.get("recommendation_batch_id") == batch["id"]
                                and review.get("requirement_revision") == requirement["revision"])
            # A further clarification can continue an already adopted, source-valid
            # revision of this batch without losing its original comparison binding.
            adopted_current = self.explicit_requirement_result(case, requirement) is not None
            if item and (item.get("requirement_revision") == requirement["revision"] or reviewed_current or adopted_current):
                self._check_recommendation_batch(case, batch["id"])
                batch_id = batch["id"]
        record["status"] = "adopted"
        result = self.save_requirement(case, {"id": requirement["id"], "title": requirement["title"], "content": content,
            "source_ids": list(dict.fromkeys(requirement["source_ids"] + record["answer_source_ids"]))}, actor, clarification_id=record["id"])
        record["revision"] += 1
        record["adoption"] = {"requirement_revision": result["requirement_revision"], "requirement_content": content,
                              "input_revision": case["input_revision"], "actor": actor, "created_at": _now(),
                              "source_hashes": {source["id"]: source["sha256"] for source in self.store._active_sources(case)}}
        if batch_id:
            record["adoption"]["recommendation_batch_id"] = batch_id
        record["history"].append(_version(record))
        return {**result, "clarification_id": record["id"], "clarification_revision": record["revision"]}

    @staticmethod
    def invalidate_inputs(case, reason, *, reviewed_requirement_id=None):
        for record in case["clarifications"]:
            if record["status"] in {"open", "answered"} and not record.get("invalidated_at"):
                if reviewed_requirement_id and record["requirement_id"] != reviewed_requirement_id and record["input_revision"] == case["input_revision"] - 1:
                    record["input_revision"] = case["input_revision"]
                    continue
                record.update(invalidated_at=_now(), invalidated_reason=reason)
        for record in case["comparisons"]:
            if not record.get("invalidated_at"):
                record.update(invalidated_at=_now(), invalidated_reason=reason)
        case["reuse_disposition"] = None

    def save_comparison(self, case, data, actor):
        if data.get("kind") not in {"product", "document"}:
            raise RdError(422, "比对类型必须为product或document。")
        self.store._evidence(case, data.get("source_ids"))
        requirements = self._requirements(case)
        rows = data.get("rows")
        if not requirements or not isinstance(rows, list) or len(rows) != len(requirements):
            raise RdError(422, "逐项比对必须覆盖当前全部需求，不能遗漏未知项。")
        by_requirement = {}
        for row in rows:
            if not isinstance(row, dict) or row.get("requirement_id") in by_requirement:
                raise RdError(422, "比对条目必须为不重复的需求记录。")
            self._requirement(case, row.get("requirement_id"))
            if row.get("assessment") not in {"match", "partial", "gap", "unknown"}:
                raise RdError(422, "逐项结论必须为match/partial/gap/unknown。")
            self.store._evidence(case, row.get("source_ids"))
            by_requirement[row["requirement_id"]] = {"requirement_id": row["requirement_id"], "assessment": row["assessment"],
                "candidate_value": _text(row.get("candidate_value", ""), "候选值", 10000), "reason": _text(row.get("reason"), "逐项依据说明", 10000, True),
                "source_ids": sorted(set(row["source_ids"])), "source_snapshots": self._sources(case, row["source_ids"])}
        ordered = [by_requirement[item["id"]] for item in requirements]
        values = {"kind": data["kind"], "title": _text(data.get("title"), "比对名称", 200, True), "source_ids": sorted(set(data["source_ids"])),
                  "source_snapshots": self._sources(case, data["source_ids"]), "rows": ordered,
                  "requirements_snapshot": requirements, "input_revision": case["input_revision"]}
        previous = next((item for item in case["comparisons"] if item["id"] == data.get("id")), None)
        if data.get("id") and previous is None:
            raise RdError(404, "比对记录不存在。")
        if previous and previous["kind"] != values["kind"]:
            raise RdError(422, "已有比对不能改变类型，请创建独立记录。")
        if previous and not previous.get("invalidated_at") and all(previous[key] == value for key, value in values.items()):
            return {"comparison_id": previous["id"], "comparison_revision": previous["revision"], "invalidated_decision_ids": []}
        counts = {assessment: sum(row["assessment"] == assessment for row in ordered) for assessment in ("match", "partial", "gap", "unknown")}
        record = {"id": previous["id"] if previous else _id(), **values, "status": "manual_record", "revision": previous["revision"] + 1 if previous else 1,
                  "actor": actor, "created_at": _now(), "statistics": {"matches": counts["match"], "total": len(ordered), "partial": counts["partial"],
                    "gap": counts["gap"], "unknown": counts["unknown"], "match_ratio": counts["match"] / len(ordered)}}
        record["sha256"] = _hash(record)
        record["history"] = deepcopy(previous["history"]) if previous else []
        record["history"].append(_version(record))
        invalidated = self._invalidate_comparison_use(case, previous) if previous else []
        if previous:
            case["comparisons"][case["comparisons"].index(previous)] = record
        else:
            case["comparisons"].append(record)
        self.store._warnings(case)
        return {"comparison_id": record["id"], "comparison_revision": record["revision"], "comparison_sha256": record["sha256"], "invalidated_decision_ids": invalidated}

    @staticmethod
    def _invalidate_comparison_use(case, previous):
        affected = [axis for axis in ("product", "composition") if (case.get(f"{axis}_route") or {}).get("comparison_id") == previous["id"]]
        if not affected:
            return []
        from .store import Store
        from .lifecycle import Lifecycle
        Lifecycle.invalidate(case, "已采用的逐项比对形成新修订。", requirements=False)
        Store._stale_taskbook_binding(case, "已采用的逐项比对形成新修订。")
        invalidated = []
        for decision in case["decisions"]:
            stage_approval = decision["kind"] == "stage" and decision.get("verdict") == "approved" and STAGE_IDS.index(decision["stage"]) >= STAGE_IDS.index("selection")
            if not decision.get("invalidated_at") and (decision.get("comparison_id") == previous["id"] or stage_approval):
                decision.update(invalidated_at=_now(), invalidated_reason="所采用的逐项比对已形成新修订，请重新决定。")
                invalidated.append(decision["id"])
        for axis in affected:
            case[f"{axis}_route"] = None
        if STAGE_IDS.index(case["stage"]) >= STAGE_IDS.index("selection"):
            case["stage"] = "selection"
        return invalidated

    def route_binding(self, case, axis, value, comparison_id):
        if not isinstance(comparison_id, str) or not comparison_id.strip():
            raise RdError(422, "请先完成当前需求的逐项比对，再关联比对记录作出决定。")
        comparison_id = comparison_id.strip()
        record = next((item for item in case["comparisons"] if item["id"] == comparison_id), None)
        if record is None or record["kind"] != {"product": "product", "composition": "document"}.get(axis):
            raise RdError(422, "选择的比对记录不属于当前案例或与决定类型不一致。")
        if record.get("invalidated_at") or record["input_revision"] != case["input_revision"] or record["requirements_snapshot"] != self._requirements(case):
            raise RdError(409, "比对所依据的输入或需求已变化，请重新逐项核对。")
        if axis == "product" and value == "direct" and any(row["assessment"] != "match" for row in record["rows"]):
            raise RdError(422, "产品直接选用不能把部分符合、差异或未知项视为已经满足。")
        return {"comparison_id": record["id"], "comparison_revision": record["revision"], "comparison_sha256": record["sha256"]}

    def _artifacts(self, case, ids, *, deliverable=False):
        if not isinstance(ids, list) or any(not isinstance(aid, str) for aid in ids):
            raise RdError(422, "请提供成果标识列表。")
        result = []
        for aid in dict.fromkeys(ids):
            matches = [(package, artifact) for package in case["workpackages"] for artifact in package["artifacts"] if artifact["id"] == aid]
            if deliverable:
                matches = [(package, artifact) for package, artifact in matches if package["status"] == "completed" and self.store._same_inputs(package["snapshot"], case)
                    and any(node["action_id"] == "verify" and node["status"] == "completed" and node["result"].get("delivery_approved") is True for node in package["nodes"])]
            if len(matches) != 1:
                raise RdError(422, "成果不属于当前案例的唯一有效固定版本。")
            package, artifact = matches[0]
            self.store._checked_path(artifact)
            result.append({"id": aid, "workpackage_id": package["id"], **{key: artifact[key] for key in ("name", "kind", "sha256")}})
        if deliverable and not any(item["kind"] in {"taskbook", "docx"} for item in result):
            raise RdError(422, "交付记录需要本次已校验的任务书成果。")
        return result

    def _engineering_chain(self, case):
        binding = self.store._current_taskbook_binding(case)
        return binding, [node for node in binding["workflow"]["nodes"] if node in {"scheme", "detail", "integration"}]

    def _current_engineering(self, case, binding):
        records = {}
        for record in case["engineering_records"]:
            if record["binding_id"] == binding["id"] and record["input_revision"] == case["input_revision"]:
                records[record["node_id"]] = record
        return records

    def _verified_taskbook(self, case, binding):
        packages = [package for package in case["workpackages"] if package["definition_id"] == "taskbook"
            and package["status"] == "completed" and self.store._same_inputs(package["snapshot"], case)
            and (package["snapshot"].get("taskbook_binding") or {}).get("id") == binding["id"]
            and any(node["action_id"] == "verify" and node["status"] == "completed" and node["result"].get("delivery_approved") is True for node in package["nodes"])]
        if not packages:
            raise RdError(422, "请先完成当前采用版本的任务书生成与成果校验，再办理工程节点。")
        if not any(artifact["kind"] in {"docx", "taskbook"} for package in packages for artifact in package["artifacts"]):
            raise RdError(422, "工程节点需要当前已校验的实际任务书文件。")
        for package in packages:
            for artifact in package["artifacts"]:
                self.store._checked_path(artifact)
        return packages[-1]

    def record_engineering_node(self, case, data, actor):
        if case["stage"] != "design":
            raise RdError(422, "请在方案与零配件设计阶段办理工程节点。")
        binding, chain = self._engineering_chain(case)
        self._verified_taskbook(case, binding)
        node = data.get("node_id")
        if node not in chain or data.get("verdict") not in {"approved", "rejected"}:
            raise RdError(422, "工程节点或人工办理结论无效。")
        current = self._current_engineering(case, binding)
        for prerequisite in chain[:chain.index(node)]:
            if prerequisite not in current or current[prerequisite]["verdict"] != "approved":
                raise RdError(422, "请先完成研发流程中前置工程节点。")
        source_ids, artifact_ids = data.get("source_ids", []), data.get("artifact_ids", [])
        self.store._evidence(case, source_ids, artifact_ids)
        artifacts = self._artifacts(case, artifact_ids)
        if data["verdict"] == "approved":
            original_ids = set(binding["source_ids"])
            supplementary = any(source["id"] in source_ids and source["role"] == "reference" and source["id"] not in original_ids for source in case["sources"])
            engineering = any(package["status"] == "completed" and self.store._same_inputs(package["snapshot"], case)
                and artifact["id"] in artifact_ids and artifact["kind"] in {"scheme", "drawing", "design", "engineering", "integration", "report"}
                for package in case["workpackages"] for artifact in package["artifacts"])
            if not supplementary and not engineering:
                raise RdError(422, "工程节点批准需要采用任务书后补充上传的专业成果资料，或当前工程成果；原始需求与任务书本身不能证明设计已完成。")
        record = {"id": _id(), "record_type": "manual_engineering_review", "binding_id": binding["id"], "input_revision": case["input_revision"],
            "node_id": node, "verdict": data["verdict"], "summary": _text(data.get("summary"), "人工办理说明", 20000, True),
            "source_ids": list(dict.fromkeys(source_ids)), "source_snapshots": self._sources(case, source_ids),
            "artifact_ids": list(dict.fromkeys(artifact_ids)), "artifacts": artifacts,
            "actor": actor, "created_at": _now(), "electronic_signature": False, "execution_mode": "manual_record",
            "prerequisite_record_ids": [current[prior]["id"] for prior in chain[:chain.index(node)]]}
        case["engineering_records"].append(record)
        return {"engineering_record_id": record["id"], "node_id": node, "verdict": record["verdict"]}

    def check_engineering_nodes(self, case):
        binding, chain = self._engineering_chain(case)
        self._verified_taskbook(case, binding)
        current = self._current_engineering(case, binding)
        for index, node in enumerate(chain):
            record = current.get(node)
            if not record or record["verdict"] != "approved":
                raise RdError(422, "已采用研发流程的方案、详细设计及整合节点尚未全部人工确认通过。")
            if record["prerequisite_record_ids"] != [current[prior]["id"] for prior in chain[:index]]:
                raise RdError(422, "前置工程记录已修订，请重新核对后续工程节点。")
            self.store._evidence(case, record["source_ids"], record["artifact_ids"])
            if self._sources(case, record["source_ids"]) != record["source_snapshots"] or self._artifacts(case, record["artifact_ids"]) != record["artifacts"]:
                raise RdError(409, "工程节点依据的资料或成果版本已变化。")

    def record_delivery(self, case, data, actor):
        if case["stage"] != "delivery":
            raise RdError(422, "请在交付与反馈阶段登记回执。")
        if data.get("outcome") not in {"accepted", "revision_required"}:
            raise RdError(422, "回执结论必须为accepted或revision_required。")
        self.store._evidence(case, data.get("source_ids", []), data.get("artifact_ids", []))
        direct = (case.get("product_route") or {}).get("value") == "direct"
        artifact_ids = data.get("artifact_ids", [])
        if direct and not artifact_ids:
            if not data.get("source_ids"):
                raise RdError(422, "成熟产品交付需要上传的真实接收回执资料。")
            artifacts = []
        else:
            artifacts = self._artifacts(case, artifact_ids, deliverable=True)
        feedback = _text(data.get("feedback", ""), "反馈", 20000, required=data["outcome"] == "revision_required")
        record = {"id": _id(), "status": "manual_record", "outcome": data["outcome"], "recipient": _text(data.get("recipient"), "接收方", 200, True),
            "receipt": _text(data.get("receipt"), "人工登记回执", 20000, True), "feedback": feedback,
            "source_ids": list(dict.fromkeys(data.get("source_ids", []))), "source_snapshots": self._sources(case, data.get("source_ids", [])),
            "artifact_ids": list(dict.fromkeys(artifact_ids)), "artifacts": artifacts, "inventory_connected": False, "input_revision": case["input_revision"],
            "actor": actor, "created_at": _now(), "electronic_signature": False}
        case["deliveries"].append(record)
        return {"delivery_id": record["id"], "outcome": record["outcome"]}

    def prepare_reuse(self, case, data, actor):
        if case["stage"] != "knowledge":
            raise RdError(422, "请在知识治理与再次复用阶段准备案例候选。")
        source_ids, artifact_ids = data.get("source_ids", []), data.get("artifact_ids", [])
        self.store._evidence(case, source_ids, artifact_ids)
        record = {"id": _id(), "title": _text(data.get("title"), "候选名称", 200, True), "content": _text(data.get("content"), "候选内容", 30000, True),
                  "status": "candidate", "scope": "case", "published": False, "source_ids": list(dict.fromkeys(source_ids)),
                  "source_snapshots": self._sources(case, source_ids), "artifact_ids": list(dict.fromkeys(artifact_ids)), "artifacts": self._artifacts(case, artifact_ids),
                  "input_revision": case["input_revision"], "actor": actor, "created_at": _now()}
        case["reuse_candidates"].append(record)
        return {"reuse_candidate_id": record["id"], "status": "candidate"}

    def check_stage(self, case, data, actor):
        stage = case["stage"]
        if stage == "requirements" and any(record["required"] and record["status"] != "adopted" for record in case["clarifications"]):
            raise RdError(422, "必需澄清尚未明确采用，不能确认需求。")
        if stage == "requirements":
            self.check_requirement_reviews(case)
            self.materialize_specification_results(case, actor)
        if stage == "delivery":
            current = [record for record in case["deliveries"] if record["input_revision"] == case["input_revision"]]
            if not current or current[-1]["outcome"] != "accepted":
                raise RdError(422, "交付尚无当前成果的接受记录，或最新反馈要求整改。")
            direct_receipt = (case.get("product_route") or {}).get("value") == "direct" and not current[-1]["artifact_ids"]
            if direct_receipt:
                self.store._evidence(case, current[-1]["source_ids"])
                if self._sources(case, current[-1]["source_ids"]) != current[-1]["source_snapshots"]:
                    raise RdError(409, "成熟产品接收回执资料版本已变化。")
            elif self._artifacts(case, current[-1]["artifact_ids"], deliverable=True) != current[-1]["artifacts"]:
                raise RdError(409, "登记回执所对应的成果版本已变化。")
        if stage == "knowledge":
            candidates = [record for record in case["reuse_candidates"] if record["input_revision"] == case["input_revision"]]
            reason = data.get("no_publish_reason")
            if "no_publish_reason" in data:
                reason = _text(reason, "不发布理由", 4000, True)
                sources = data.get("no_publish_source_ids", [])
                self.store._evidence(case, sources)
                case["reuse_disposition"] = {"kind": "not_publish", "reason": reason, "source_ids": list(dict.fromkeys(sources)),
                    "input_revision": case["input_revision"], "actor": actor, "created_at": _now(), "published": False}
            elif candidates:
                for record in candidates:
                    self.store._evidence(case, record["source_ids"], record["artifact_ids"])
                    if self._artifacts(case, record["artifact_ids"]) != record["artifacts"]:
                        raise RdError(409, "复用候选引用的成果版本已变化，请重新准备。")
                case["reuse_disposition"] = {"kind": "candidate_prepared", "candidate_ids": [record["id"] for record in candidates],
                    "input_revision": case["input_revision"], "actor": actor, "created_at": _now(), "published": False}
            else:
                raise RdError(422, "请先形成有来源的本案例复用候选，或依据资料明确记录不发布理由。")
