"""Server-registered assistant abilities with immutable, explicit confirmations.

Only trusted Python code may register abilities; neither chat text nor an API can
register a shell command, import a skill, or choose an executable. Future script
and skill abilities supply reviewed preflight/execute handlers through
``register_capability``. Preflight must be read-only; execute must reuse durable
idempotency with the supplied request key and return a project view. Increment
``version`` whenever a handler's meaning changes, invalidating pending previews.

The built-in abilities delegate every business write to RdStore.execute. Their
previews run _apply on a deep copy: these nine handlers only mutate the aggregate
and read/check fixed files, including native review release freezing/publication.
"""
from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from src.service.rd_platform.store import RdError, RdStore, _actor, _json

Preflight = Callable[[RdStore, dict, dict, dict], None]
Executor = Callable[[RdStore, dict, str, dict, int, str], dict]


@dataclass(frozen=True)
class OperationCapability:
    id: str
    kind: str
    label: str
    description: str
    schema: dict
    permissions: tuple[str, ...]
    prepare_handler: Preflight
    execute_handler: Executor
    requires_confirmation: bool = True
    version: int = 1
    domain_action: str | None = None


_REGISTRY: dict[str, OperationCapability] = {}
_DOMAIN_ACTIONS = frozenset({"save_requirement", "create_task", "reassign_task", "confirm_baseline", "decide_review", "publish_plan", "record_selection", "record_delivery", "start_task"})
_ROLES = {"owner", "engineer", "reviewer", "viewer"}


def register_capability(capability: OperationCapability) -> None:
    """Code-only extension seam. No dynamic loading or command-string handler."""
    if not isinstance(capability, OperationCapability) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", capability.id):
        raise ValueError("A capability requires a fixed server-owned id")
    if capability.id in _REGISTRY:
        raise ValueError("Capability already registered")
    if capability.kind not in {"domain_command", "script", "skill"} or not capability.requires_confirmation:
        raise ValueError("Registered operations require explicit confirmation")
    if not capability.permissions or not set(capability.permissions) <= _ROLES or "viewer" in capability.permissions:
        raise ValueError("Operation permissions must name actionable project roles")
    if type(capability.version) is not int or capability.version < 1:
        raise ValueError("Capability version must be positive")
    if not callable(capability.prepare_handler) or not callable(capability.execute_handler):
        raise ValueError("Reviewed prepare and execute handlers are required")
    if capability.kind == "domain_command" and capability.domain_action not in _DOMAIN_ACTIONS:
        raise ValueError("Domain action is not in the assistant command allowlist")
    if capability.kind != "domain_command" and capability.domain_action is not None:
        raise ValueError("Extension handlers must not masquerade as domain commands")
    schema = capability.schema
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ValueError("A closed object parameter schema is required")
    _REGISTRY[capability.id] = copy.deepcopy(capability)


def _utcnow():
    return datetime.now(timezone.utc)


def _public_capability(capability):
    return {"id": capability.id, "action": capability.id, "kind": capability.kind, "label": capability.label,
            "description": capability.description, "schema": copy.deepcopy(capability.schema),
            "permissions": list(capability.permissions), "requires_confirmation": capability.requires_confirmation,
            "version": capability.version}


def _registered(action):
    if not isinstance(action, str) or action not in _REGISTRY:
        raise RdError(422, "小航不支持此操作；脚本和 skill 须先由服务端登记")
    return _REGISTRY[action]


def _authorize(store, doc, actor, capability):
    member = store._member(doc, actor["user_id"])
    if member is None:
        raise RdError(404, "项目不存在或无权访问")
    if member["role"] not in capability.permissions:
        raise RdError(403, "当前项目职责不能执行此操作")
    if capability.kind == "domain_command":
        store._permission(doc, actor["user_id"], capability.domain_action)


def capabilities(detail, actor):
    actor = _actor(actor)
    member = RdStore._member(detail, actor["user_id"])
    if member is None:
        raise RdError(404, "项目不存在或无权访问")
    return [_public_capability(c) for c in _REGISTRY.values() if member["role"] in c.permissions]


def _ensure_table(store):
    with store._transaction() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS assistant_operation_proposals (
            id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, project_id TEXT NOT NULL,
            capability_id TEXT NOT NULL, definition TEXT NOT NULL, document TEXT NOT NULL,
            response TEXT
        )""")


def _validate_payload(capability, payload):
    if not isinstance(payload, dict):
        raise RdError(422, "操作参数须为对象")
    properties = capability.schema["properties"]
    if set(payload) - set(properties) or set(capability.schema.get("required", [])) - set(payload):
        raise RdError(422, "操作参数不完整或包含未登记字段")
    for name, value in payload.items():
        field = properties[name]
        if field["type"] == "string" and not isinstance(value, str):
            raise RdError(422, f"{field['description']}须为文本")
        if field["type"] == "boolean" and type(value) is not bool:
            raise RdError(422, f"{field['description']}须为布尔值")
        if "enum" in field and value not in field["enum"]:
            raise RdError(422, f"{field['description']}取值不正确")
    try:
        encoded = _json(payload)
    except (TypeError, ValueError):
        raise RdError(422, "操作参数格式不正确") from None
    if len(encoded.encode("utf-8")) > 100_000:
        raise RdError(422, "操作参数过长，请缩短后重试")
    return json.loads(encoded)


def _preview(doc, capability, payload):
    action = capability.domain_action
    previous = {}
    if action == "save_requirement" and payload.get("id"):
        previous = RdStore._find(doc, "requirements", payload["id"])
    elif action in {"start_task", "reassign_task"}:
        previous = RdStore._find(doc, "tasks", payload.get("task_id"))
    elif action == "decide_review":
        previous = RdStore._find(doc, "reviews", payload.get("review_id"))
        previous = {**previous, "decision": previous["status"]}
    elif action == "record_selection":
        previous = (doc.get("selection_decisions") or [{}])[-1]
    changes = [{"field": k, "label": capability.schema["properties"][k]["description"],
                "before": copy.deepcopy(previous.get(k)), "after": copy.deepcopy(v)} for k, v in payload.items()]
    display_values = {"approved": "批准", "rejected": "退回", "open": "待澄清", "resolved": "已澄清", "direct": "直接选用", "modification": "改型研制", "new": "全新研制", "pending": "待核实", "confirmed": "已确认", "accepted": "已接受", "blocked": "交接受阻"}
    def display(field, value):
        if type(value) is bool:
            return "是" if value else "否"
        if field in {"assignee_id", "reviewer_id"}:
            member = RdStore._member(doc, value)
            return f"{member['display_name']}（{value}）" if member else str(value)
        if field == "task_id":
            task = next((t for t in doc["tasks"] if t["id"] == value), None)
            return f"{task['title']}（{value}）" if task else str(value)
        return display_values.get(value, value) if field in {"decision", "clarification", "route", "suitability", "supply_status", "outcome"} else str(value)
    fields = [{"label": change["label"], "value": display(change["field"], change["after"])} for change in changes]
    if action == "decide_review":
        review = RdStore._find(doc, "reviews", payload["review_id"])
        task = RdStore._find(doc, "tasks", review["task_id"])
        artifact = RdStore._find(doc, "artifacts", review["artifact_id"])
        fields = [{"label": "审签任务", "value": task["title"]}, {"label": "固定成果", "value": artifact["filename"]}, {"label": "成果修订", "value": artifact["source_revision_id"]}, *fields]
    if action == "confirm_baseline":
        fields = [{"label": "需求数量", "value": str(len(doc["requirements"]))}, {"label": "新基线编号", "value": str(len(doc["baselines"]) + 1)}]
    warnings = {
        "confirm_baseline": ["确认后将形成新的需求基线；关联任务和批准成果仍按现有变更影响规则复核。"],
        "decide_review": ["审签决定将写入工程记录；批准将固定当前送审版本，退回须填写具体意见。"],
        "publish_plan": ["将从当前批准任务书发布计划与交接；下游仍须由指定执行人接受输入后才能开工。"],
        "reassign_task": ["重新分派可能撤回待审记录，并要求新的交接接收。"],
        "save_requirement": ["保存需求不会自动确认新基线，历史基线和批准成果继续保留。"],
    }.get(action, [])
    return {"summary": f"在项目“{doc['project']['name']}”中{capability.label}，确认后按当前项目版本执行。", "changes": changes, "fields": fields, "warnings": warnings}


def prepare_operation(store, actor, pid, action, payload, *, expected_version: int | None = None):
    actor = _actor(actor)
    capability = _registered(action)
    payload = _validate_payload(capability, payload)
    _ensure_table(store)
    with store._transaction() as conn:
        doc = store._load(conn, pid, actor["user_id"])
        _authorize(store, doc, actor, capability)
        if expected_version is not None:
            # A model operation is based on the snapshot sent before its network
            # call. Never silently rebase that old intent onto newer project
            # data, including partially edited requirements merged below.
            store._version(doc, expected_version)
        if capability.domain_action == "save_requirement" and payload.get("id"):
            current = store._find(doc, "requirements", payload["id"])
            # A conversational edit must not silently reset omitted sources,
            # acceptance or clarification. Freeze the completed payload and
            # show those preserved values in the same confirmation preview.
            payload = {**{key: copy.deepcopy(current[key]) for key in capability.schema["properties"] if key in current}, **payload}
        capability.prepare_handler(store, copy.deepcopy(doc), actor, payload)
        now = _utcnow()
        proposal_id = uuid.uuid4().hex
        proposal = {"id": proposal_id, "proposal_id": proposal_id, "capability_id": capability.id, "action": capability.id,
                    "kind": capability.kind, "label": capability.label, "description": capability.description,
                    "project_id": pid, "project_name": doc["project"]["name"], "expected_version": doc["project"]["version"],
                    "payload": payload, "requires_confirmation": True, "status": "pending",
                    "created_at": now.isoformat(), "expires_at": (now + timedelta(minutes=10)).isoformat(),
                    **_preview(doc, capability, payload)}
        conn.execute("INSERT INTO assistant_operation_proposals VALUES (?,?,?,?,?,?,NULL)",
                     (proposal_id, actor["user_id"], pid, capability.id, _json(_public_capability(capability)), _json(proposal)))
    return proposal


def _receipt(proposal, result):
    return {"status": "executed", "proposal_id": proposal["id"], "capability_id": proposal["capability_id"],
            "message": f"已{proposal['label']}。", "project_id": proposal["project_id"],
            "project_version": result["project"]["version"], "href": f"/rd/{proposal['project_id']}?tab=flow"}


def confirm_operation(store, actor, proposal_id):
    actor = _actor(actor)
    if not isinstance(proposal_id, str) or not re.fullmatch(r"[a-f0-9]{32}", proposal_id):
        raise RdError(404, "操作草案不存在或无权访问")
    _ensure_table(store)
    # Do not hold a SQLite writer while execute opens its own transaction. The
    # fixed request key serializes concurrent confirmations in RdStore itself.
    with store._transaction() as conn:
        row = conn.execute("SELECT * FROM assistant_operation_proposals WHERE id=? AND actor_id=?", (proposal_id, actor["user_id"])).fetchone()
        if row is None:
            raise RdError(404, "操作草案不存在或无权访问")
        proposal = json.loads(row["document"])
        capability = _registered(row["capability_id"])
        if row["definition"] != _json(_public_capability(capability)):
            raise RdError(409, "此能力定义已更新，请重新生成操作草案")
        doc = store._load(conn, row["project_id"], actor["user_id"])
        _authorize(store, doc, actor, capability)
        if row["response"] is not None:
            return json.loads(row["response"])
        # Recover a committed domain operation if the process stopped before its
        # compact assistant receipt was recorded. This is a read/replay, so an
        # expired preview can recover its result but never initiate a new write.
        recovered = None
        if capability.kind == "domain_command":
            fingerprint = _json({"action": capability.domain_action, "payload": proposal["payload"], "expected_version": proposal["expected_version"]})
            recovered = store._replay(conn, row["project_id"], actor["user_id"], f"assistant:{proposal_id}", fingerprint)
        if recovered is not None:
            receipt = _receipt(proposal, recovered)
            conn.execute("UPDATE assistant_operation_proposals SET response=? WHERE id=?", (_json(receipt), proposal_id))
            return receipt
        if _utcnow() >= datetime.fromisoformat(proposal["expires_at"]):
            raise RdError(410, "操作草案已超过10分钟，请重新生成并确认")
        store._version(doc, proposal["expected_version"])
    result = capability.execute_handler(store, actor, proposal["project_id"], proposal["payload"], proposal["expected_version"], f"assistant:{proposal_id}")
    receipt = _receipt(proposal, result)
    with store._transaction() as conn:
        conn.execute("UPDATE assistant_operation_proposals SET response=? WHERE id=? AND actor_id=?", (_json(receipt), proposal_id, actor["user_id"]))
    return receipt


def _schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _string(description, choices=None):
    return {"type": "string", "description": description, **({"enum": list(choices)} if choices else {})}


def _register_domain(action, label, description, permissions, properties, required):
    def preflight(store, doc, actor, payload):
        store._apply(doc, actor, action, payload)
    def execute(store, actor, pid, payload, expected_version, request_key):
        return store.execute(pid, actor, action, payload, expected_version, request_key)
    register_capability(OperationCapability(id=action, kind="domain_command", label=label, description=description,
                         schema=_schema(properties, required), permissions=permissions, prepare_handler=preflight,
                         execute_handler=execute, domain_action=action))


_TASK = {"task_id": _string("任务ID")}
_ASSIGNMENTS = {"assignee_id": _string("当前项目执行人ID"), "reviewer_id": _string("独立审核人ID")}
_register_domain("save_requirement", "保存需求", "新增必须提供title和content；修改只提供现有需求id及需要变更的字段。其余字段从存储中的完整需求保留并列入确认草案，不能复制截断上下文覆盖原文。不会自动确认基线。", ("owner", "engineer"),
                 {"id": _string("现有需求ID；新增时省略"), "title": _string("需求标题；新增必填，修改标题时填写"), "content": _string("需求完整内容；新增必填，仅明确修改正文时填写"), "source": _string("来源依据"), "acceptance": _string("验收要求"), "clarification": _string("澄清状态", ["open", "resolved"]), "required": {"type": "boolean", "description": "是否必需"}}, [])
_register_domain("create_task", "创建项目任务", "在已确认基线下创建任务，执行人与审核人须为不同的有效成员。", ("owner",),
                 {"title": _string("任务名称"), "description": _string("任务说明"), **_ASSIGNMENTS, "due_date": _string("计划结束日期 YYYY-MM-DD；可省略")}, ["title", "assignee_id", "reviewer_id"])
_register_domain("reassign_task", "重新分派任务", "改变现有任务执行人与审核人，沿用待审撤回和交接重收规则。", ("owner",), {**_TASK, **_ASSIGNMENTS}, ["task_id", "assignee_id", "reviewer_id"])
_register_domain("confirm_baseline", "确认需求基线", "所有必需需求须已澄清，具备来源和验收要求。", ("owner",), {}, [])
_register_domain("decide_review", "办理工程审签", "仅当前指定的独立审核人可对有效固定送审版本批准或退回。", ("owner", "reviewer"),
                 {"review_id": _string("待审记录ID"), "decision": _string("审签决定", ["approved", "rejected"]), "comment": _string("审签意见；退回时必填")}, ["review_id", "decision"])
_register_domain("publish_plan", "发布批准计划", "仅发布当前有效的最新批准任务书包，不将模型答复作为批准依据。", ("owner",), {**_TASK, "release_id": _string("当前批准任务书包ID")}, ["task_id", "release_id"])
_register_domain("record_selection", "登记选型决定", "选型必须依据当前已确认且未变化的需求基线。", ("owner",),
                 {"route": _string("研制路线", ["direct", "modification", "new"]), "selected_product": _string("选用产品；全新研制可为空"), "rationale": _string("选型依据说明"), "evidence_ref": _string("真实选型资料引用；待核实时可为空"), "suitability": _string("适配性状态", ["pending", "confirmed"]), "supply_status": _string("供货状态", ["pending", "confirmed"])}, ["route", "rationale", "selected_product", "evidence_ref", "suitability", "supply_status"])
_register_domain("record_delivery", "登记直接选用交接", "当前直接选用路线具备选型证据和确认状态后才可接受交接。", ("owner",),
                 {"selection_id": _string("当前选型决定ID"), "outcome": _string("交接结果", ["blocked", "accepted"]), "recipient": _string("交接接收方"), "reference": _string("交接凭据；接受交接时必填"), "note": _string("交接说明；受阻时必填")}, ["selection_id", "outcome", "recipient"])
_register_domain("start_task", "开始项目任务", "仅当前任务执行人办理；原生工作包继续校验固定输入和交接前置条件。", ("owner", "engineer"), _TASK, ["task_id"])
