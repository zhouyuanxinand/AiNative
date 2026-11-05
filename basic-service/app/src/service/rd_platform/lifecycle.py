"""Versioned business gates; reads never manufacture historical authorization."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass

from .store import RdError, _id, _json, _now, _text


def digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LifecyclePolicy:
    version: str
    required_decisions: tuple[str, ...]
    applicable_stages: tuple[str, ...]

    @classmethod
    def resolve(cls, case):
        version = (case.get("business_lifecycle") or {}).get("policy_version", "legacy_v1")
        if version not in {"legacy_v1", "v2"}:
            raise RdError(422, "未知业务政策版本，不能使用旧流程继续办理。")
        return cls(version, ("selection", "rd_start", "taskbook_scope") if version == "v2" else ("stage",),
                   ("input", "requirements", "selection", "planning", "design", "verification", "delivery", "knowledge"))


class Lifecycle:
    def __init__(self, store):
        self.store = store

    def initialize(self, case, *, new=False):
        if "business_lifecycle" not in case:
            case["business_lifecycle"] = {
                "policy_version": "v2" if new else "legacy_v1",
                "selection_order_id": "SEL-" + _id() if new else None,
                "rd_activation_state": "not_started" if new else "historical_unverified", "rd_project_code": None,
                "current_requirement_baseline_id": None, "current_selection_bundle_id": None,
                "current_selection_decision_id": None, "current_activation_id": None,
                "current_taskbook_scope_decision_id": None,
            }
        lifecycle = case["business_lifecycle"]
        is_new_policy = LifecyclePolicy.resolve(case).version == "v2"
        lifecycle["local_review_enabled"] = self.store.local_review_enabled if is_new_policy else False
        lifecycle["review_mode"] = ("local_review" if self.store.local_review_enabled else "formal_review") if is_new_policy else "legacy_history"
        lifecycle["required_policy_ref"] = ("local-project-owner-v1" if self.store.local_review_enabled else "enterprise-review-unconfigured") if is_new_policy else "legacy_v1"
        for field in ("requirement_baselines", "review_bundles", "rd_activations"):
            case.setdefault(field, [])

    @staticmethod
    def require_v2(case):
        if LifecyclePolicy.resolve(case).version != "v2":
            raise RdError(422, "历史案例保持原办理语义；请先进行明确的迁移预检与采用。")

    @staticmethod
    def require_owner(project, actor):
        if actor != project["owner_id"]:
            raise RdError(403, "本地业务确认仅由项目负责人办理；成员和管理员身份不授予工程决定资格。")

    @staticmethod
    def expected_input(case, data):
        expected = data.get("expected_input_revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected != case["input_revision"]:
            raise RdError(409, "输入版本已变化，请保留草稿并核对当前资料后重试。")

    def confirm_requirements(self, project, case, data, actor):
        self.require_v2(case)
        self.require_owner(project, actor)
        self.expected_input(case, data)
        if set(data) - {"case_id", "expected_input_revision", "scope", "source_ids"}:
            raise RdError(422, "需求确认不接受客户端批准对象或业务快照。")
        if case["stage"] not in {"input", "requirements", "selection"}:
            raise RdError(422, "请在输入、需求或选型阶段确认当前需求。")
        if not case["requirements"]:
            raise RdError(422, "需求确认需要有来源的非空需求。")
        if any(row.get("required") and row.get("status") != "adopted" for row in case["clarifications"]):
            raise RdError(422, "必需澄清尚未明确采用，不能确认需求。")
        self.store.records.check_requirement_reviews(case)
        self.store._evidence(case, data.get("source_ids"))
        for requirement in case["requirements"]:
            if requirement.get("status") in {"conflict", "rejected"}:
                raise RdError(422, "采用需求仍有冲突或拒绝项，请先核对。")
            self.store._evidence(case, requirement["source_ids"])
        source_ids = set(data["source_ids"]) | {sid for row in case["requirements"] for sid in row["source_ids"]}
        scope = _text(data.get("scope"), "需求确认范围", 4000, True)
        self.invalidate(case, "需求已形成新的固定确认基线。")
        fixed = {"input_revision": case["input_revision"], "items": deepcopy(case["requirements"]),
                 "source_refs": self.store.records._sources(case, source_ids), "scope": scope}
        baseline = {"id": _id(), "revision": len(case["requirement_baselines"]) + 1, **fixed,
                    "actor": actor, "created_at": _now(), "digest": digest(fixed), "status": "current"}
        case["requirement_baselines"].append(baseline)
        case["business_lifecycle"]["current_requirement_baseline_id"] = baseline["id"]
        case["stage"] = "selection"
        return {"requirement_baseline_id": baseline["id"], "baseline_digest": baseline["digest"], "input_revision": case["input_revision"]}

    def current_baseline(self, case):
        ref = case["business_lifecycle"]["current_requirement_baseline_id"]
        baseline = next((row for row in case["requirement_baselines"] if row["id"] == ref), None)
        if not baseline or baseline.get("invalidated_at") or baseline["input_revision"] != case["input_revision"] or baseline["items"] != case["requirements"]:
            raise RdError(409, "当前需求尚无有效固定确认，请先确认需求。")
        source_ids = [row["id"] for row in baseline["source_refs"]]
        self.store._evidence(case, source_ids)
        if self.store.records._sources(case, source_ids) != baseline["source_refs"]:
            raise RdError(409, "已确认需求的来源版本发生变化。")
        return baseline

    def execution_refs(self, case):
        baseline = self.current_baseline(case)
        activation = self.store.reviews.current_activation(case)
        decision = self.store.reviews.current_selection_decision(case, activation["selection_decision_id"])
        return {"policy_version": "v2", "requirement_baseline_id": baseline["id"], "requirement_baseline_digest": baseline["digest"],
                "selection_decision_id": decision["id"], "selection_bundle_id": decision["bundle_id"],
                "selection_bundle_digest": decision["bundle_digest"], "activation_id": activation["id"]}

    @staticmethod
    def invalidate(case, reason, *, requirements=True):
        if LifecyclePolicy.resolve(case).version != "v2":
            return
        fields = ("review_bundles", "rd_activations") + (("requirement_baselines",) if requirements else ())
        for field in fields:
            for row in case[field]:
                if not row.get("invalidated_at"):
                    row.update(invalidated_at=_now(), invalidated_reason=reason, status="needs_review")
        for row in case["decisions"]:
            if row.get("kind") in {"selection", "taskbook_scope"} and not row.get("invalidated_at"):
                row.update(invalidated_at=_now(), invalidated_reason=reason)
        lifecycle = case["business_lifecycle"]
        if lifecycle.get("current_activation_id"):
            lifecycle["rd_activation_state"] = "needs_review"
        lifecycle["current_selection_decision_id"] = None
        lifecycle["current_taskbook_scope_decision_id"] = None
