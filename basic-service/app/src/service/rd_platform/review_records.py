"""Fixed review objects and owner decisions, independent from execution success."""
from __future__ import annotations

from copy import deepcopy

from .lifecycle import digest
from .store import RdError, _id, _now, _text


class ReviewRecords:
    COMMANDS = {"prepare_selection_review", "record_selection_decision", "authorize_rd_start",
                "prepare_taskbook_scope_review", "record_taskbook_scope_decision", "confirm_engineering_stage"}
    DECISION_COMMANDS = {"record_selection_decision", "authorize_rd_start", "record_taskbook_scope_decision", "confirm_engineering_stage"}

    def __init__(self, store):
        self.store = store

    def command(self, project, case, command, data, actor):
        self.store.lifecycle.require_v2(case)
        return getattr(self, command)(project, case, data, actor)

    @staticmethod
    def _fields(data, allowed):
        if set(data) - {"case_id", *allowed}:
            raise RdError(422, "办理命令不接受客户端签署身份、政策或固定业务快照。")

    def _qualification(self, project, actor):
        self.store.lifecycle.require_owner(project, actor)
        if not self.store.local_review_enabled:
            raise RdError(403, "企业工程决定政策与正式审签尚未配置，不能以本地记录满足正式批准。")
        return {"review_mode": "local_review", "policy_ref": "local-project-owner-v1",
                "qualification": {"role": "project_owner", "project_id": project["id"], "actor": actor},
                "electronic_signature": False}

    def _selection_snapshot(self, case):
        baseline = self.store.lifecycle.current_baseline(case)
        comparisons = {}
        for axis in ("product", "composition"):
            route = case.get(axis + "_route")
            if not route:
                raise RdError(422, "请分别完成产品研制分类与任务书编制策略的逐项核对。")
            self.store.records.route_binding(case, axis, route["value"], route.get("comparison_id"))
            comparisons[axis] = deepcopy(next(row for row in case["comparisons"] if row["id"] == route["comparison_id"]))
        used_sources = {row["id"] for row in baseline["source_refs"]}
        for axis, comparison in comparisons.items():
            used_sources.update(case[axis + "_route"]["source_ids"])
            used_sources.update(comparison["source_ids"])
            for row in comparison["rows"]:
                used_sources.update(row["source_ids"])
        sources = [row for row in self.store._active_sources(case) if row["role"] != "reference" or row["id"] in used_sources]
        for source in sources:
            self.store._checked_path(source)
        return {"requirement_baseline_id": baseline["id"], "requirement_baseline_digest": baseline["digest"],
                "input_revision": case["input_revision"], "context": deepcopy(case["context"]),
                "business_context": deepcopy(case["business_context"]), "requirements": deepcopy(baseline["items"]),
                "source_refs": self.store.records._sources(case, [row["id"] for row in sources]),
                "comparisons": comparisons, "product_route": deepcopy(case["product_route"]),
                "composition_route": deepcopy(case["composition_route"]),
                "report_template": {"id": "selection-report", "version": "1"},
                "workflow_template": {"id": "taskbook-selection-v2", "version": "2"}}

    def prepare_selection_review(self, project, case, data, actor):
        self._fields(data, {"expected_input_revision"})
        self.store.lifecycle.expected_input(case, data)
        if case["stage"] != "selection":
            raise RdError(422, "请在选型阶段形成固定选型报告。")
        fixed = self._selection_snapshot(case)
        self.store.lifecycle.invalidate(case, "选型报告已形成新的送审包。", requirements=False)
        self.store._stale_taskbook_binding(case, "选型报告已形成新的送审包。")
        bundle_id = _id()
        comparison = fixed["comparisons"]["product"]
        report = {"id": "selection-report-" + bundle_id, "format": "structured_selection_report", "title": "固定选型报告",
                  "rows": deepcopy(comparison["rows"]), "statistics": deepcopy(comparison["statistics"]),
                  "requirements": deepcopy(fixed["requirements"]), "product_route": deepcopy(fixed["product_route"]),
                  "composition_route": deepcopy(fixed["composition_route"]), "template": fixed["report_template"]}
        payload = {"fixed_objects": fixed, "report": report}
        bundle = {"id": bundle_id, "kind": "selection", **payload, "input_digest": digest(fixed), "digest": digest(payload),
                  "input_revision": case["input_revision"], "review_mode": case["business_lifecycle"]["review_mode"],
                  "required_policy_ref": case["business_lifecycle"]["required_policy_ref"], "status": "submitted",
                  "actor": actor, "created_at": _now()}
        case["review_bundles"].append(bundle)
        case["business_lifecycle"]["current_selection_bundle_id"] = bundle_id
        return {"review_bundle_id": bundle_id, "bundle_digest": bundle["digest"]}

    def _bundle(self, case, data, kind):
        bundle = next((row for row in case["review_bundles"] if row["id"] == data.get("bundle_id") and row["kind"] == kind), None)
        if not bundle or bundle.get("invalidated_at") or data.get("bundle_digest") != bundle["digest"]:
            raise RdError(409, "送审包或摘要已变化，请核对当前固定版本。")
        if bundle["input_revision"] != case["input_revision"]:
            raise RdError(409, "送审包输入版本已变化，请重新形成报告。")
        if kind == "selection":
            if case["business_lifecycle"]["current_selection_bundle_id"] != bundle["id"] or bundle["input_digest"] != digest(self._selection_snapshot(case)):
                raise RdError(409, "需求、产品证据、路线或报告版本已变化，请重新送审。")
        elif kind == "taskbook_scope":
            if bundle["input_digest"] != digest(self._taskbook_snapshot(case, bundle["fixed_objects"]["workpackage_id"])):
                raise RdError(409, "任务书成果、输入或质量结果发生变化，请重新形成范围送审包。")
        return bundle

    def _record_decision(self, project, case, data, actor, kind):
        self._fields(data, {"bundle_id", "bundle_digest", "verdict", "scope", "rationale"})
        qualification = self._qualification(project, actor)
        bundle = self._bundle(case, data, kind)
        if bundle["review_mode"] != qualification["review_mode"] or bundle["required_policy_ref"] != qualification["policy_ref"]:
            raise RdError(409, "送审包政策不匹配当前有效的决定资格。")
        if data.get("verdict") not in {"approved", "rejected"}:
            raise RdError(422, "决定必须为approved或rejected。")
        for old in case["decisions"]:
            if old.get("kind") == kind and not old.get("invalidated_at"):
                old.update(invalidated_at=_now(), invalidated_reason="该范围已形成新的具名决定。")
        decision = {"id": _id(), "kind": kind, "bundle_id": bundle["id"], "bundle_digest": bundle["digest"],
                    "verdict": data["verdict"], "scope": _text(data.get("scope"), "决定范围", 4000, True),
                    "rationale": _text(data.get("rationale"), "决定依据", 4000, True), "actor": actor, "created_at": _now(),
                    "input_revision": case["input_revision"], **qualification}
        case["decisions"].append(decision)
        bundle["status"] = data["verdict"]
        return decision

    def record_selection_decision(self, project, case, data, actor):
        if case["stage"] != "selection":
            raise RdError(422, "请在选型阶段办理固定选型报告决定。")
        decision = self._record_decision(project, case, data, actor, "selection")
        case["business_lifecycle"]["current_selection_decision_id"] = decision["id"]
        if decision["verdict"] == "approved" and case["product_route"]["value"] == "direct":
            case["stage"] = "delivery"
        return {"selection_decision_id": decision["id"], "bundle_digest": decision["bundle_digest"], "verdict": decision["verdict"]}

    def current_selection_decision(self, case, decision_id):
        if decision_id != case["business_lifecycle"]["current_selection_decision_id"]:
            raise RdError(409, "请引用当前有效选型决定。")
        decision = next((row for row in case["decisions"] if row["id"] == decision_id and row["kind"] == "selection"), None)
        if not decision or decision.get("invalidated_at") or decision["verdict"] != "approved":
            raise RdError(409, "尚无当前有效的选型批准，不能启动研发。")
        self._bundle(case, decision, "selection")
        if decision["review_mode"] != case["business_lifecycle"]["review_mode"]:
            raise RdError(409, "原选型决定不满足当前审查政策。")
        return decision

    def authorize_rd_start(self, project, case, data, actor):
        self._fields(data, {"selection_decision_id", "scope", "rationale"})
        qualification = self._qualification(project, actor)
        if (case.get("product_route") or {}).get("value") == "direct":
            raise RdError(422, "成熟产品直接选用不创建研发项目或任务书工作包。")
        decision = self.current_selection_decision(case, data.get("selection_decision_id"))
        if case["stage"] != "selection":
            raise RdError(422, "当前案例不在待启动选型关口。")
        baseline = self.store.lifecycle.current_baseline(case)
        aid = _id()
        record = {"id": aid, "selection_decision_id": decision["id"], "requirement_baseline_id": baseline["id"],
                  "bundle_id": decision["bundle_id"], "bundle_digest": decision["bundle_digest"],
                  "scope": _text(data.get("scope"), "研发启动范围", 4000, True),
                  "rationale": _text(data.get("rationale"), "研发启动依据", 4000, True), "actor": actor, "created_at": _now(),
                  "status": "active", "input_revision": case["input_revision"],
                  "rd_project_code": case["business_lifecycle"].get("rd_project_code") or "RD-" + aid[:12].upper(), **qualification}
        case["rd_activations"].append(record)
        case["business_lifecycle"].update(current_activation_id=aid, rd_activation_state="active", rd_project_code=record["rd_project_code"])
        case["stage"] = "planning"
        return {"activation_id": aid, "rd_project_code": record["rd_project_code"]}

    def current_activation(self, case):
        lifecycle = case["business_lifecycle"]
        activation = next((row for row in case["rd_activations"] if row["id"] == lifecycle["current_activation_id"]), None)
        if lifecycle["rd_activation_state"] != "active" or not activation or activation.get("invalidated_at") or activation["input_revision"] != case["input_revision"]:
            raise RdError(409, "当前研发尚无有效独立启动授权。")
        self.current_selection_decision(case, activation["selection_decision_id"])
        if activation["requirement_baseline_id"] != self.store.lifecycle.current_baseline(case)["id"]:
            raise RdError(409, "研发启动依据的需求基线已变化。")
        return activation

    def _taskbook_snapshot(self, case, workpackage_id):
        refs = self.store.lifecycle.execution_refs(case)
        binding = self.store._current_taskbook_binding(case)
        package = self.store._package(case, workpackage_id)
        submitted = [row for row in case["workpackages"] if row["definition_id"] == "taskbook" and row["definition_version"] == "2"
                     and row.get("snapshot") and row["status"] != "cancelled" and row["snapshot"].get("lifecycle_refs") == refs]
        if any(row["status"] in {"submitted", "running"} and row["id"] != workpackage_id for row in submitted):
            raise RdError(409, "当前范围仍有任务书在途运行，请完成或取消后再办理范围决定。")
        latest = max(submitted, key=lambda row: row["snapshot"]["submitted_at"], default=None)
        if latest and latest["id"] != workpackage_id:
            raise RdError(409, "已有较新的任务书运行或成果，请核对当前版本；旧成果不能代替在途修订。")
        if package["definition_id"] != "taskbook" or package["definition_version"] != "2" or package["status"] != "completed" or not self.store._same_inputs(package["snapshot"], case):
            raise RdError(422, "任务书范围核对需要当前输入下已完成的策划任务书。")
        if package["snapshot"]["taskbook_binding"]["id"] != binding["id"]:
            raise RdError(409, "任务书采用版本已变化，请使用当前成果。")
        quality = next((node["result"] for node in package["nodes"] if node["action_id"] == "verify" and node["status"] == "completed" and node["result"].get("delivery_approved") is True), None)
        if not quality or not any(row["kind"] in {"taskbook", "docx"} for row in package["artifacts"]):
            raise RdError(422, "文件生成不能替代质量门禁；请先取得当前任务书的有效校验结果。")
        artifacts = self.store.records._artifacts(case, [row["id"] for row in package["artifacts"]], deliverable=True)
        return {"workpackage_id": package["id"], "run_id": package["run_id"], "input_revision": case["input_revision"],
                "binding_id": binding["id"], "binding_fingerprint": binding["fingerprint"], "lifecycle_refs": refs,
                "artifacts": artifacts, "quality_result": deepcopy(quality)}

    def prepare_taskbook_scope_review(self, project, case, data, actor):
        self._fields(data, {"workpackage_id"})
        if case["stage"] != "planning":
            raise RdError(422, "请在研发策划阶段办理任务书范围。")
        fixed = self._taskbook_snapshot(case, data.get("workpackage_id"))
        for row in case["review_bundles"]:
            if row["kind"] == "taskbook_scope" and not row.get("invalidated_at"):
                row.update(invalidated_at=_now(), invalidated_reason="任务书范围已形成新的送审包。", status="needs_review")
        for row in case["decisions"]:
            if row["kind"] == "taskbook_scope" and not row.get("invalidated_at"):
                row.update(invalidated_at=_now(), invalidated_reason="任务书范围已形成新的送审包。")
        bundle = {"id": _id(), "kind": "taskbook_scope", "fixed_objects": fixed, "digest": digest(fixed),
                  "input_digest": digest(fixed), "input_revision": case["input_revision"], "status": "submitted",
                  "review_mode": case["business_lifecycle"]["review_mode"], "required_policy_ref": case["business_lifecycle"]["required_policy_ref"],
                  "actor": actor, "created_at": _now()}
        case["review_bundles"].append(bundle)
        case["business_lifecycle"]["current_taskbook_scope_decision_id"] = None
        return {"review_bundle_id": bundle["id"], "bundle_digest": bundle["digest"]}

    def record_taskbook_scope_decision(self, project, case, data, actor):
        if case["stage"] != "planning":
            raise RdError(422, "请在研发策划阶段办理任务书范围决定。")
        decision = self._record_decision(project, case, data, actor, "taskbook_scope")
        case["business_lifecycle"]["current_taskbook_scope_decision_id"] = decision["id"]
        if decision["verdict"] == "approved":
            case["stage"] = "design"
        return {"taskbook_scope_decision_id": decision["id"], "bundle_digest": decision["bundle_digest"], "verdict": decision["verdict"]}

    def confirm_engineering_stage(self, project, case, data, actor):
        qualification = self._qualification(project, actor)
        if case["stage"] not in {"design", "verification", "delivery", "knowledge"}:
            raise RdError(422, "后续工程办理仅用于设计、验证、交付与知识阶段。")
        if (case.get("product_route") or {}).get("value") == "direct":
            if case["stage"] not in {"delivery", "knowledge"}:
                raise RdError(422, "直接选用不进入研发设计阶段。")
            self.current_selection_decision(case, case["business_lifecycle"]["current_selection_decision_id"])
        else:
            self.current_activation(case)
            scope_id = case["business_lifecycle"]["current_taskbook_scope_decision_id"]
            scope = next((row for row in case["decisions"] if row["id"] == scope_id and row["kind"] == "taskbook_scope"), None)
            if not scope or scope.get("invalidated_at") or scope["verdict"] != "approved":
                raise RdError(409, "请先办理当前任务书范围批准，再推进工程阶段。")
            self._bundle(case, scope, "taskbook_scope")
        self.store._advance_stage(case, data, actor, lifecycle_checked=True)
        decision = case["decisions"][-1]
        decision.update(**qualification, scope_decision_id=case["business_lifecycle"]["current_taskbook_scope_decision_id"])
        return {"engineering_stage_decision_id": decision["id"], "stage": case["stage"]}
