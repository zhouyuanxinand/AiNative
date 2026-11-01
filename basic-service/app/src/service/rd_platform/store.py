"""Research case storage and lease-fenced execution state.

Each transaction records the business command, its receipt and any run intent.
Only committed file metadata grants downloads; uncommitted files stay invisible.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timezone
from functools import cache
from pathlib import Path

from . import catalog as definitions

_RULE_ROOT = Path(__file__).resolve().parents[1] / "config"
_PROJECT_PROFILE_FIELDS = {"brief": ("研发目标", 4000), "customer_name": ("客户名称", 200), "product_name": ("产品名称", 200)}


class RdError(RuntimeError):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail
        super().__init__(detail)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _id():
    return uuid.uuid4().hex


def _actor(actor):
    if isinstance(actor, dict):
        actor = actor.get("id") or actor.get("user_id") or actor.get("username") or actor.get("sub")
    if not isinstance(actor, str) or not actor.strip():
        raise RdError(401, "请先登录。")
    return actor.strip()


def _text(value, label, maximum=4000, required=False):
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise RdError(422, f"{label}必须是有效文本。")
    value = value.strip()
    if required and not value:
        raise RdError(422, f"请填写{label}。")
    return value


def _context(value, fields=definitions.CONTEXT_FIELDS):
    if not isinstance(value, dict) or set(value) - set(fields):
        raise RdError(422, "上下文只接受六项受控参数。")
    return {key: _text(item, key, 1000) for key, item in value.items()}


def _project_profile_defaults(project):
    # These are manually supplied descriptions, not references to master data.
    for field in _PROJECT_PROFILE_FIELDS:
        project.setdefault(field, "")
    return project


def _project_profile(values, allow_title=False):
    fields = {**_PROJECT_PROFILE_FIELDS, **({"title": ("项目名称", 200)} if allow_title else {})}
    if not values or set(values) - set(fields):
        raise RdError(422, "请提供项目名称、研发目标、客户名称或产品名称。")
    return {key: _text(value, *fields[key], required=key == "title") for key, value in values.items()}


def _safe_name(name):
    return _text(name, "文件名", 255, True).replace("\\", "/").split("/")[-1] or "资料"


def _planned_date(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise RdError(422, "计划日期必须为YYYY-MM-DD或null。")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise RdError(422, "计划日期不是有效的日历日期。") from error


def _public(value):
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items()
                if not key.startswith("_") and key not in {"path", "work_dir", "token", "lease_until"}
                and (not key.endswith("_path") or key in {"semantic_path", "target_path"})}
    if isinstance(value, list):
        return [_public(item) for item in value]
    if isinstance(value, str) and (re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("/", "\\\\"))):
        return value.replace("\\", "/").rsplit("/", 1)[-1]
    return value


def _example(value):
    if isinstance(value, dict):
        return value.get("execution_mode") == "contract_example" or any(_example(item) for item in value.values())
    if isinstance(value, list):
        return any(_example(item) for item in value)
    return False


def _reject_raw_credentials(value):
    secret_fields = {"secret", "password", "passwd", "apikey", "apisecret", "accesstoken", "refreshtoken", "idtoken",
                     "authorization", "clientsecret", "privatekey", "secretkey", "signingkey", "bearertoken", "authtoken", "sessiontoken", "token"}
    if isinstance(value, dict):
        for key, item in value.items():
            if re.sub(r"[-_\s]", "", key).casefold() in secret_fields:
                raise RdError(422, "Workspace配置不能保存原始凭证，请通过现有凭证设置保存机密，并使用credentials_ref、secret_ref或model_config_ref引用。")
            _reject_raw_credentials(item)
    elif isinstance(value, list):
        for item in value:
            _reject_raw_credentials(item)


class Store:
    def __init__(self, path: Path, asset_root: Path):
        from .case_records import CaseRecords
        self.records = CaseRecords(self)
        self.path, self.asset_root = Path(path).resolve(), Path(asset_root).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.asset_root.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts(actor TEXT, project_id TEXT, key TEXT, fingerprint TEXT NOT NULL, response TEXT NOT NULL,
                    PRIMARY KEY(actor, project_id, key));
                CREATE TABLE IF NOT EXISTS resource_versions(id TEXT, version INTEGER, payload TEXT NOT NULL, PRIMARY KEY(id, version));
                CREATE TABLE IF NOT EXISTS resource_heads(id TEXT PRIMARY KEY, version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, case_id TEXT NOT NULL,
                    workpackage_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL, created_at REAL NOT NULL, snapshot TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS claims(run_id TEXT, node_id TEXT, token TEXT NOT NULL, lease_until REAL NOT NULL,
                    PRIMARY KEY(run_id, node_id));
            """)
        with self._transaction() as db:
            for action in definitions.ACTIONS:
                resource = {"id": action["id"], "version": 1, "kind": "skill", "name": action["title"], "description": "本地发布的实际执行动作。",
                            "configuration": {"action_id": action["id"], "execution_mode": "local_real", "provider_id": "local-taskbook"},
                            "execution_mode": "local_real", "status": "published", "executable": True,
                            "created_at": _now(), "actor": "system"}
                db.execute("INSERT OR IGNORE INTO resource_versions VALUES(?,?,?)", (resource["id"], 1, _json(resource)))
                db.execute("INSERT OR IGNORE INTO resource_heads VALUES(?,?)", (resource["id"], 1))

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def catalog(self):
        return definitions.get_catalog()

    @staticmethod
    def _business_context(project):
        return {"project_id": project["id"], **{key: project.get(key, "") for key in ("title", "brief", "customer_name", "product_name")}}

    def _load(self, db, pid, actor=None):
        row = db.execute("SELECT payload FROM projects WHERE id=?", (pid,)).fetchone()
        if row is None:
            raise RdError(404, "项目不存在或无权访问。")
        project = _project_profile_defaults(json.loads(row["payload"]))
        for case in project["cases"]:
            case["business_context"] = self._business_context(project)
            case.setdefault("engineering_records", [])
            if "source_selection" not in case:
                case["source_selection"] = {role: candidates[0]["id"] for role in ("tech", "spec")
                    if len(candidates := [source for source in case["sources"] if source["role"] == role]) == 1}
            case.setdefault("taskbook_binding", None)
            case.setdefault("taskbook_binding_history", [])
            case.setdefault("input_revision", 1)
            case.setdefault("source_analysis", None)
            case.setdefault("source_analysis_history", [])
            self.records.initialize(case)
            self._warnings(case)
            for package in case["workpackages"]:
                for key, default in (("planned_start", None), ("planned_end", None), ("plan_note", ""), ("schedule_revision", 0),
                                     ("schedule_history", []), ("started_at", None), ("completed_at", None), ("ended_at", None)):
                    package.setdefault(key, default)
                for node in package["nodes"]:
                    for key in ("started_at", "completed_at", "ended_at"):
                        node.setdefault(key, None)
        if actor is not None and actor != project["owner_id"] and actor not in project["members"]:
            raise RdError(404, "项目不存在或无权访问。")
        return project

    def _save(self, db, project, event, actor, **data):
        project["version"] += 1
        project["updated_at"] = _now()
        project["events"].append({"id": _id(), "type": event, "actor": actor, "created_at": project["updated_at"], "data": data})
        db.execute("UPDATE projects SET payload=? WHERE id=?", (_json(project), project["id"]))

    @staticmethod
    def _case(project, cid):
        case = next((item for item in project["cases"] if item["id"] == cid), None)
        if case is None:
            raise RdError(404, "案例不存在。")
        return case

    @staticmethod
    def _package(case, wid):
        package = next((item for item in case["workpackages"] if item["id"] == wid), None)
        if package is None:
            raise RdError(404, "工作包不存在。")
        return package

    def create_project(self, actor, title, context=None, key=None, *, brief="", customer_name="", product_name=""):
        actor = _actor(actor)
        title = _text(title, "项目名称", 200, True)
        context = _context({} if context is None else context)
        profile = _project_profile({"brief": brief, "customer_name": customer_name, "product_name": product_name})
        stamp = _now()
        project = {"id": _id(), "title": title, "version": 1, "owner_id": actor, "members": [],
                   "cases": [], "events": [{"id": _id(), "type": "project_created", "actor": actor, "created_at": stamp, "data": {}}],
                   "created_at": stamp, "updated_at": stamp, "_initial_context": context, **profile}
        with self._transaction() as db:
            if key is not None:
                key, fingerprint, replay = self._receipt(db, actor, "__project_create__", key,
                    {"command": "create_project", "title": title, "context": context,
                     **{field: value for field, value in profile.items() if value}})
                if replay is not None:
                    return _project_profile_defaults(replay)
            db.execute("INSERT INTO projects VALUES(?,?)", (project["id"], _json(project)))
            if key is not None:
                db.execute("INSERT INTO receipts VALUES(?,?,?,?,?)", (actor, "__project_create__", key, fingerprint, _json(_public(project))))
        return _public(project)

    def get_project(self, actor, pid):
        with self._connection() as db:
            return _public(self._load(db, pid, _actor(actor)))

    def list_projects(self, actor):
        actor = _actor(actor)
        with self._connection() as db:
            projects = [json.loads(row[0]) for row in db.execute("SELECT payload FROM projects ORDER BY rowid DESC")]
        visible = [project for project in projects if actor == project["owner_id"] or actor in project["members"]]
        for project in visible:
            _project_profile_defaults(project)
            for case in project["cases"]:
                self._warnings(case)
        return [_public(project) for project in visible]

    def _receipt(self, db, actor, pid, key, intent):
        key = _text(key, "Idempotency-Key", 200, True)
        try:
            fingerprint = hashlib.sha256(_json(intent).encode()).hexdigest()
        except (TypeError, ValueError) as error:
            raise RdError(422, "请求必须包含有效JSON数据。") from error
        receipt = db.execute("SELECT fingerprint,response FROM receipts WHERE actor=? AND project_id=? AND key=?", (actor, pid, key)).fetchone()
        if receipt:
            if receipt["fingerprint"] != fingerprint:
                raise RdError(409, "同一幂等键不能用于不同请求。")
            return key, fingerprint, json.loads(receipt["response"])
        return key, fingerprint, None

    @staticmethod
    def _cas(project, expected_version):
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version != project["version"]:
            raise RdError(409, "项目已更新，请刷新后重试。")

    @staticmethod
    def _save_receipt(db, actor, project, key, fingerprint):
        public = _public(project)
        db.execute("INSERT INTO receipts VALUES(?,?,?,?,?)", (actor, project["id"], key, fingerprint, _json(public)))
        return public

    def command(self, actor, pid, expected_version, key, command, data):
        actor = _actor(actor)
        if not isinstance(data, dict):
            raise RdError(422, "命令数据必须是对象。")
        with self._transaction() as db:
            project = self._load(db, pid, actor)
            event_extra = {}
            key, fingerprint, replay = self._receipt(db, actor, pid, key, {"command": command, "data": data})
            if replay is not None:
                return _project_profile_defaults(replay)
            self._cas(project, expected_version)
            cid = None
            if command == "save_project_profile":
                profile = _project_profile(data, allow_title=True)
                changed = any(project.get(field, "") != value for field, value in profile.items())
                project.update(profile)
                if changed:
                    for case in project["cases"]:
                        if case["status"] == "completed":
                            self._stale_taskbook_binding(case, "项目业务信息已变化，封存成果仅保留历史用途。")
                            case["input_revision"] += 1
                        else:
                            self._invalidate_inputs(case, "项目名称、目标、客户或产品业务信息发生变化。")
                        case["business_context"] = self._business_context(project)
                event_extra = {"fields": list(profile)}
            elif command == "create_case":
                self._create_case(project, data, actor)
                cid = project["cases"][-1]["id"]
            else:
                cid = data.get("case_id")
                case = self._case(project, cid)
                if case["status"] == "completed" and command != "cancel_workpackage":
                    raise RdError(409, "已完成案例的事实和决定已封存，请创建新的案例修订。")
                if command == "save_context":
                    event_extra = self._save_context(case, data, actor)
                elif command == "adopt_source_analysis":
                    event_extra = self._adopt_source_analysis(case, data, actor)
                elif command == "select_source":
                    event_extra = self._select_source(case, data)
                elif command == "save_requirement":
                    event_extra = self._save_requirement(case, data, actor)
                elif command in self.records.COMMANDS:
                    event_extra = self.records.command(case, command, data, actor)
                elif command == "record_route_decision":
                    self._route_decision(case, data, actor)
                elif command == "adopt_taskbook_flow":
                    event_extra = self._adopt_taskbook_flow(case, data, actor)
                elif command == "advance_stage":
                    self._advance_stage(case, data, actor)
                elif command == "pull_workpackage":
                    self._pull_package(case, data)
                elif command == "save_plan":
                    package = self._package(case, data.get("workpackage_id"))
                    if package["status"] != "draft":
                        raise RdError(409, "提交后的计划不可修改；请建立新的工作包修订。")
                    package["nodes"] = self._validate_plan(db, package["definition_id"], data.get("nodes"))
                    package["plan_revision"] += 1
                elif command == "save_schedule":
                    event_extra = self._save_schedule(case, data, actor)
                elif command == "submit_workpackage":
                    self._submit(db, project, case, data, actor)
                elif command == "cancel_workpackage":
                    self._cancel(db, case, data)
                else:
                    raise RdError(422, "未知的研发命令。")
            if cid is not None:
                event_extra["case_id"] = cid
            self._save(db, project, command, actor, **event_extra)
            return self._save_receipt(db, actor, project, key, fingerprint)

    def _create_case(self, project, data, actor):
        scenario = definitions.scenario(data.get("scenario_id"))
        if scenario is None:
            raise RdError(422, "未知的案例场景。")
        context = deepcopy(project.get("_initial_context", {})) if not project["cases"] else {}
        context = _context(context, scenario["context_fields"])
        project["cases"].append({"id": _id(), "scenario_id": scenario["id"], "title": _text(data.get("title"), "案例名称", 200, True),
            "stage": scenario["initial_stage"], "status": "active", "context": context,
            "context_provenance": {key: {"kind": "user", "actor": actor, "created_at": _now(), "source_ids": []} for key in context},
            "model_selection": {"provider": "", "name": "", "id": ""}, "product_route": None, "composition_route": None,
            "sources": [], "source_selection": {}, "input_revision": 1, "requirements": [], "workpackages": [], "decisions": [], "warnings": [],
            "clarifications": [], "comparisons": [], "deliveries": [], "reuse_candidates": [], "reuse_disposition": None,
            "taskbook_binding": None, "taskbook_binding_history": [], "engineering_records": [],
            "source_analysis": None, "source_analysis_history": [],
            "business_context": self._business_context(project)})

    @staticmethod
    def _active_sources(case):
        selected = set()
        for role in ("tech", "spec"):
            candidates = [source for source in case["sources"] if source["role"] == role]
            sid = case.get("source_selection", {}).get(role)
            if sid is None and len(candidates) == 1:
                sid = candidates[0]["id"]
            if candidates and sid not in {source["id"] for source in candidates}:
                raise RdError(422, f"请先为{role}明确选择当前活动资料版本。")
            if sid:
                selected.add(sid)
        return [source for source in case["sources"] if source["role"] == "reference" or source["id"] in selected]

    def _invalidate_inputs(self, case, reason):
        case["input_revision"] = case.get("input_revision", 1) + 1
        if case.get("source_analysis"):
            case["source_analysis"].update(status="stale", invalidated_reason=reason)
        invalidated = []
        for decision in case["decisions"]:
            if not decision.get("invalidated_at") and (decision.get("verdict") == "approved" or decision["kind"] == "route"):
                decision.update(invalidated_at=_now(), invalidated_reason=reason)
                invalidated.append(decision["id"])
        self._stale_taskbook_binding(case, reason)
        case["stage"] = "input"
        case["product_route"] = case["composition_route"] = None
        self.records.invalidate_inputs(case, reason)
        self._warnings(case)
        return invalidated

    def _select_source(self, case, data):
        role = data.get("role")
        if role not in {"tech", "spec"}:
            raise RdError(422, "活动资料角色必须为tech或spec。")
        source = next((item for item in case["sources"] if item["id"] == data.get("source_id") and item["role"] == role), None)
        if source is None:
            raise RdError(422, "所选资料不属于当前案例的指定角色。")
        self._checked_path(source)
        previous = case["source_selection"].get(role)
        case["source_selection"][role] = source["id"]
        invalidated = self._invalidate_inputs(case, "用户重新选择了正式输入资料版本。") if previous != source["id"] else []
        return {"role": role, "previous_source_id": previous, "selected_source_id": source["id"],
                "input_revision": case["input_revision"], "invalidated_decision_ids": invalidated}

    @staticmethod
    def _warnings(case):
        process = case["context"].get("development_process", "").lower()
        aliases = {"new": "new", "全新": "new", "新研": "new", "新研制": "new", "新产品研制": "new", "modification": "modification", "改型": "modification", "direct": "direct", "直接选用": "direct"}
        if process.startswith("改型"):
            aliases[process] = "modification"
        route = case.get("product_route")
        case["warnings"] = []
        if route and process in aliases and aliases[process] != route["value"]:
            case["warnings"].append({"code": "product_route_context_conflict", "message": "产品研制分类与 development_process 不一致，请依据资料核对；任务书编制策略不会覆盖产品过程。"})
        for axis in ("product", "composition"):
            if case.get(f"{axis}_route") and not case[f"{axis}_route"].get("comparison_id"):
                case["warnings"].append({"code": f"{axis}_route_without_comparison", "message": "该人工决定未关联固定逐项比对；保留历史决定，不推定已经逐项核验。"})

    def _save_context(self, case, data, actor):
        context = _context(data.get("context"))
        selection = data.get("model_selection")
        changed_context = {key: value for key, value in context.items() if case["context"].get(key, "") != value}
        changed_fields = list(changed_context)
        if selection is not None:
            if not isinstance(selection, dict) or set(selection) != {"provider", "name", "id"}:
                raise RdError(422, "模型选择应包含 provider、name、id 三项文本。")
            selection = {key: _text(value, key, 200) for key, value in selection.items()}
            if selection != case["model_selection"]:
                case["model_selection"] = selection
                changed_fields.append("model_selection")
        case["context"].update(changed_context)
        case["context_provenance"].update({key: {"kind": "user", "actor": actor, "created_at": _now(), "source_ids": []} for key in changed_context})
        invalidated = self._invalidate_inputs(case, "用户实质修改了案例参数或模型选择，需要重新确认。") if changed_fields else []
        self._warnings(case)
        return {"input_revision": case["input_revision"], "changed_fields": changed_fields, "invalidated_decision_ids": invalidated}

    def _evidence(self, case, source_ids, artifact_ids=None, required=True):
        if not isinstance(source_ids, list) or any(not isinstance(sid, str) for sid in source_ids):
            raise RdError(422, "请提供来源标识列表。")
        artifact_ids = artifact_ids or []
        if not isinstance(artifact_ids, list) or any(not isinstance(aid, str) for aid in artifact_ids):
            raise RdError(422, "请提供成果标识列表。")
        if set(source_ids) - {source["id"] for source in self._active_sources(case)}:
            raise RdError(422, "来源不属于当前案例的活动资料；历史版本需求需按当前资料更新。")
        artifacts = {artifact["id"] for package in case["workpackages"] for artifact in package["artifacts"]}
        if set(artifact_ids) - artifacts:
            raise RdError(422, "成果不属于当前案例。")
        if required and not source_ids and not artifact_ids:
            raise RdError(422, "真实决定必须关联来源或成果依据。")
        for source in case["sources"]:
            if source["id"] in source_ids:
                self._checked_path(source)
        for package in case["workpackages"]:
            for artifact in package["artifacts"]:
                if artifact["id"] in artifact_ids:
                    self._checked_path(artifact)

    def _save_requirement(self, case, data, actor):
        return self.records.save_requirement(case, data, actor)

    def analyze_sources(self, actor, pid, cid, expected_version, key):
        """Release the database lock before reading/converting files or calling a model."""
        from .analysis import propose
        actor = _actor(actor)
        payload = {"command": "analyze_sources", "case_id": cid, "expected_version": expected_version}
        with self._transaction() as db:
            project = self._load(db, pid, actor)
            key, fingerprint, replay = self._receipt(db, actor, pid, key, payload)
            if replay is not None:
                return replay
            self._cas(project, expected_version)
            case = self._case(project, cid)
            if case["status"] == "completed":
                raise RdError(409, "已封存案例不能重新分析，请创建案例修订。")
            sources = self._active_sources(case)
            if not any(item["role"] == "tech" for item in sources):
                raise RdError(422, "请先上传本次技术要求或需求文件。")
            for source in sources:
                self._checked_path(source)
            snapshot = deepcopy(case)
            snapshot["sources"] = deepcopy(sources)
        aid = _id()
        directory = self.asset_root / "source_analysis" / pid / cid / aid
        directory.mkdir(parents=True, exist_ok=True)
        proposal = propose(snapshot, directory, actor)
        with self._transaction() as db:
            project = self._load(db, pid, actor)
            key, fingerprint, replay = self._receipt(db, actor, pid, key, payload)
            if replay is not None:
                return replay
            self._cas(project, expected_version)
            case = self._case(project, cid)
            hashes = {source["id"]: source["sha256"] for source in self._active_sources(case)}
            if hashes != {source["id"]: source["sha256"] for source in snapshot["sources"]}:
                raise RdError(409, "分析期间来源版本已变化，请重新分析。")
            for source in self._active_sources(case):
                self._checked_path(source)
            if case.get("source_analysis"):
                case["source_analysis_history"].append(deepcopy(case["source_analysis"]))
            case["source_analysis"] = {"id": aid, "status": "proposed", "input_revision": case["input_revision"],
                "created_at": _now(), "actor": actor, "source_hashes": hashes, **proposal}
            self._save(db, project, "source_analysis_proposed", actor, case_id=cid, analysis_id=aid)
            return self._save_receipt(db, actor, project, key, fingerprint)

    def _adopt_source_analysis(self, case, data, actor):
        proposal = case.get("source_analysis")
        if not proposal or proposal["id"] != data.get("analysis_id"):
            raise RdError(404, "资料分析提案不存在。")
        if proposal["status"] != "proposed" or proposal["input_revision"] != case["input_revision"]:
            raise RdError(409, "分析提案已采用或输入已变化，请重新分析。")
        sources = self._active_sources(case)
        if proposal["source_hashes"] != {source["id"]: source["sha256"] for source in sources}:
            raise RdError(409, "来源已变化，请重新分析。")
        for source in sources:
            self._checked_path(source)
        changed = []
        for field, item in proposal["context"].items():
            if item["status"] != "proposed" or not item["value"] or case["context"].get(field):
                continue
            case["context"][field] = item["value"]
            case["context_provenance"][field] = {"kind": "source_analysis", "actor": actor, "created_at": _now(),
                "analysis_id": proposal["id"], "source_ids": [e["source_id"] for e in item["evidence"] if e["source_id"] in proposal["source_hashes"]],
                "evidence": deepcopy(item["evidence"]), "reason": item["reason"]}
            changed.append(field)
        invalidated = self._invalidate_inputs(case, "用户明确采用来源分析参数，需要按新基线确认。") if changed else []
        requirements = []
        known_requirements = [
            (re.sub(r"\s+", "", version["title"]), re.sub(r"\s+", "", version["content"]), set(version["source_ids"]))
            for requirement in case["requirements"]
            for version in [requirement, *requirement.get("history", [])]
        ]
        for candidate in proposal["requirements"]:
            # Re-reading an original source must not resurrect a requirement that
            # a later clarification replaced. Additional confirmation sources do
            # not turn the same quoted requirement into a new engineering fact;
            # distinct tests with an equal acceptance value remain separate.
            title = re.sub(r"\s+", "", candidate["title"])
            content = re.sub(r"\s+", "", candidate["content"])
            source_ids = set(candidate["source_ids"])
            if any(title == known_title and content == known_content and source_ids <= known_sources
                   for known_title, known_content, known_sources in known_requirements):
                continue
            result = self.records.save_requirement(case, candidate, actor)
            requirement = next(item for item in case["requirements"] if item["id"] == result["requirement_id"])
            requirement["analysis_id"] = proposal["id"]
            requirement["evidence"] = deepcopy(candidate["evidence"])
            requirements.append(requirement["id"])
            known_requirements.append((title, content, source_ids))
            invalidated.extend(result["invalidated_decision_ids"])
        proposal.update(status="adopted", adopted_at=_now(), adopted_by=actor, adopted_input_revision=case["input_revision"])
        proposal.pop("invalidated_reason", None)
        self._warnings(case)
        return {"analysis_id": proposal["id"], "changed_fields": changed, "requirement_ids": requirements,
                "input_revision": case["input_revision"], "invalidated_decision_ids": list(dict.fromkeys(invalidated))}

    def _route_decision(self, case, data, actor):
        if case["stage"] not in {"selection", "planning"}:
            raise RdError(422, "请在选型或策划阶段记录产品研制分类和任务书编制策略。")
        axis = data.get("axis")
        values = {"product": {"direct", "modification", "new"}, "composition": {"direct", "adapt", "new"}}
        if axis not in values or data.get("value") not in values[axis]:
            raise RdError(422, "研制分类或编制策略选项无效。")
        self._evidence(case, data.get("source_ids"))
        binding = self.records.route_binding(case, axis, data["value"], data.get("comparison_id"))
        decision = {"value": data["value"], "rationale": _text(data.get("rationale"), "决定理由", 4000, True),
                    "source_ids": list(dict.fromkeys(data["source_ids"])), "actor": actor, "created_at": _now(), "input_revision": case["input_revision"], **binding}
        if case.get(f"{axis}_route") != decision:
            self._stale_taskbook_binding(case, "研发路线决定已变化。")
        case[f"{axis}_route"] = decision
        case["decisions"].append({"id": _id(), "kind": "route", "stage": case["stage"], "axis": axis, **deepcopy(decision)})
        self._warnings(case)

    @staticmethod
    def _stale_taskbook_binding(case, reason):
        binding = case.get("taskbook_binding")
        if binding and binding["status"] == "current":
            binding.update(status="stale", invalidated_at=_now(), invalidated_reason=reason)

    def _current_taskbook_binding(self, case):
        binding = case.get("taskbook_binding")
        if not binding or binding["status"] != "current" or binding["input_revision"] != case["input_revision"]:
            raise RdError(422, "请在研发策划阶段采用当前需求对应的研发流程与任务书模板。")
        for key, current in (("context", case["context"]), ("requirements_snapshot", case["requirements"]),
                             ("product_route", case["product_route"]), ("composition_route", case["composition_route"]),
                             ("business_context", case["business_context"])):
            if binding[key] != current:
                raise RdError(409, "任务书业务绑定与当前需求、路线或资料不一致，请重新采用模板。")
        active = self._active_sources(case)
        fixed = binding["source_snapshots"]
        if [item for item in fixed if item["role"] != "reference"] != [item for item in active if item["role"] != "reference"] or any(item not in active for item in fixed):
            raise RdError(409, "任务书采用的正式输入资料已变化，请重新采用模板。")
        for source in fixed:
            self._checked_path(source)
        for asset in binding["document_template"]["assets"].values():
            path = Path(asset["path"])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
                raise RdError(422, "已采用的任务书模板资产发生变化，请重新采用模板。")
        return binding

    def _adopt_taskbook_flow(self, case, data, actor):
        from .business_binding import document_template, business_fingerprint
        allowed = {"case_id", "workflow_id", "workflow_version", "scope", "rationale"}
        if set(data) - allowed:
            raise RdError(422, "模板采用只接受目录版本、范围及依据，不接受客户端业务快照。")
        if case["stage"] != "planning":
            raise RdError(422, "请在研发策划阶段采用研发流程模板。")
        workflow = next((item for item in definitions.RESEARCH_WORKFLOW_TEMPLATES
                         if item["id"] == data.get("workflow_id") and item["version"] == data.get("workflow_version")
                         and item["status"] == "published"), None)
        if not workflow or not case.get("product_route") or not case.get("composition_route"):
            raise RdError(422, "请先完成当前需求的产品路线与任务书编制策略决定。")
        if workflow["product_route"] != case["product_route"]["value"]:
            raise RdError(422, "研发流程模板与当前产品研制分类不一致。")
        context = _context(case["context"])
        if set(context) != set(definitions.CONTEXT_FIELDS) or not all(context.values()):
            raise RdError(422, "请明确确认全部六项任务书参数。")
        from .completion import canonical_value
        try:
            for field in ("development_process", "cover_phase", "organization_scope"):
                canonical_value(field, context[field])
        except ValueError as error:
            raise RdError(422, str(error)) from error
        sources = self._active_sources(case)
        if not {"tech", "spec"}.issubset({source["role"] for source in sources}):
            raise RdError(422, "采用模板需要当前技术要求和规范两类真实输入资料。")
        for source in sources:
            self._checked_path(source)
        if not case["requirements"]:
            raise RdError(422, "采用模板需要有来源的当前确认需求。")
        for requirement in case["requirements"]:
            self._evidence(case, requirement["source_ids"])
        comparisons = []
        for axis in ("product", "composition"):
            route = case[axis + "_route"]
            self.records.route_binding(case, axis, route["value"], route["comparison_id"])
            comparisons.append(deepcopy(next(item for item in case["comparisons"] if item["id"] == route["comparison_id"])))
        try:
            document = document_template(context)
        except (ValueError, OSError) as error:
            raise RdError(422, str(error)) from error
        binding = {"id": _id(), "revision": len(case["taskbook_binding_history"]) + 1,
            "input_revision": case["input_revision"], "context": deepcopy(context), "business_context": deepcopy(case["business_context"]),
            "source_ids": [item["id"] for item in sources], "source_snapshots": deepcopy(sources),
            "requirements_snapshot": deepcopy(case["requirements"]), "comparison_snapshots": comparisons,
            "product_route": deepcopy(case["product_route"]), "composition_route": deepcopy(case["composition_route"]),
            "workflow": deepcopy(workflow), "document_template": document,
            "scope": _text(data.get("scope"), "研发范围", 4000, True),
            "rationale": _text(data.get("rationale"), "采用依据", 4000, True),
            "adopted_by": actor, "adopted_at": _now(), "status": "current"}
        binding["fingerprint"] = business_fingerprint(binding)
        case["taskbook_binding"] = binding
        case["taskbook_binding_history"].append(deepcopy(binding))
        return {"taskbook_binding_id": binding["id"], "taskbook_binding_revision": binding["revision"], "fingerprint": binding["fingerprint"]}

    def _advance_stage(self, case, data, actor):
        stage = data.get("stage")
        if stage != case["stage"] or case["status"] == "completed":
            raise RdError(422, "只能记录当前活动阶段的决定。")
        verdict = data.get("verdict")
        if verdict not in {"approved", "rejected"}:
            raise RdError(422, "决定必须为 approved 或 rejected。")
        rationale = _text(data.get("rationale"), "决定理由", 4000, True)
        self._evidence(case, data.get("source_ids", []), data.get("artifact_ids", []), required=verdict == "approved")
        if verdict == "approved":
            self.records.check_stage(case, data, actor)
            current_packages = [package for package in case["workpackages"] if package["stage"] == stage]
            if any(package["status"] in {"submitted", "running"} for package in current_packages):
                raise RdError(422, "当前阶段仍有已提交或运行中的工作包，请完成或取消后再作阶段决定。")
            if any(package.get("required", package["definition_id"] == "taskbook")
                   and package["status"] not in {"completed", "cancelled"} for package in current_packages):
                raise RdError(422, "当前阶段的必需工作包尚未完成。")
            if stage == "requirements" and not case["requirements"]:
                raise RdError(422, "需求确认需要有来源的非空需求。")
            if stage == "requirements":
                for requirement in case["requirements"]:
                    self._evidence(case, requirement["source_ids"])
            if stage == "selection" and (not case["product_route"] or not case["composition_route"]):
                raise RdError(422, "请分别决定产品研制分类和任务书编制策略。")
            if stage == "planning":
                if (case.get("product_route") or {}).get("value") == "direct":
                    _text(data.get("scope"), "成熟产品选用收尾范围", 4000, True)
                    self._evidence(case, data.get("source_ids", []))
                    for axis in ("product", "composition"):
                        route = case[axis + "_route"]
                        self.records.route_binding(case, axis, route["value"], route["comparison_id"])
                else:
                    self._current_taskbook_binding(case)
            if stage == "design":
                self.records.check_engineering_nodes(case)
            if stage in {"design", "verification"}:
                checked = [package for package in case["workpackages"] if package["status"] == "completed"
                           and (stage != "design" or package["definition_id"] == "taskbook")
                           and self._same_inputs(package["snapshot"], case)
                           and any(node["action_id"] == "verify" and node["status"] == "completed"
                                   and node["result"].get("delivery_approved") is True for node in package["nodes"])]
                deliverables = [item for package in checked for item in package["artifacts"] + package["snapshot"].get("upstream_artifacts", [])
                                if item["kind"] in {"docx", "taskbook"}]
                if not deliverables:
                    raise RdError(422, "离开设计或验证阶段需要当前输入下已生成并校验通过的任务书成果。")
                for item in deliverables:
                    self._checked_path(item)
        decision = {"id": _id(), "kind": "stage", "stage": stage, "verdict": verdict, "rationale": rationale,
                    "source_ids": list(dict.fromkeys(data.get("source_ids", []))), "artifact_ids": list(dict.fromkeys(data.get("artifact_ids", []))),
                    "actor": actor, "created_at": _now(), "input_revision": case["input_revision"]}
        if stage == "planning" and (case.get("product_route") or {}).get("value") == "direct":
            decision.update(scope=_text(data.get("scope", ""), "成熟产品选用收尾范围", 4000, verdict == "approved"), inventory_connected=False)
        case["decisions"].append(decision)
        if verdict == "approved":
            if stage == "knowledge":
                case["status"] = "completed"
            elif stage == "planning" and (case.get("product_route") or {}).get("value") == "direct":
                case["stage"] = "delivery"
            else:
                case["stage"] = definitions.STAGE_IDS[definitions.STAGE_IDS.index(stage) + 1]

    def _pull_package(self, case, data):
        definition = definitions.definition(data.get("definition_id"))
        if not definition or case["stage"] not in definition["stages"] or case["status"] == "completed":
            raise RdError(422, "当前案例阶段不支持这个工作包。")
        case["workpackages"].append({"id": _id(), "definition_id": definition["id"], "definition_version": definition["version"],
            "required": definition["required"],
            "title": definition["title"], "stage": case["stage"], "status": "draft", "plan_revision": 1,
            "planned_start": None, "planned_end": None, "plan_note": "", "schedule_revision": 0, "schedule_history": [],
            "started_at": None, "completed_at": None, "ended_at": None,
            "nodes": definitions.default_nodes(definition["id"]), "snapshot": None, "run_id": None, "artifacts": [], "obligations": [],
            "blocked_reasons": [], "request_ref": _text(data.get("request_ref", ""), "请求引用", 200)})

    def _save_schedule(self, case, data, actor):
        package = self._package(case, data.get("workpackage_id"))
        if package["status"] != "draft":
            raise RdError(409, "日期计划仅可在工作包草稿中修改；提交后的计划只读。")
        start = _planned_date(data.get("planned_start", package["planned_start"]))
        end = _planned_date(data.get("planned_end", package["planned_end"]))
        if start is not None and end is not None and start > end:
            raise RdError(422, "计划结束日期不能早于开始日期。")
        schedule = {"planned_start": start, "planned_end": end, "plan_note": _text(data.get("plan_note", package["plan_note"]), "计划说明", 4000)}
        if any(package[key] != value for key, value in schedule.items()):
            package.update(schedule)
            package["schedule_revision"] += 1
            package["schedule_history"].append({"revision": package["schedule_revision"], **schedule, "actor": actor, "created_at": _now()})
        return {"workpackage_id": package["id"], "schedule_revision": package["schedule_revision"]}

    @staticmethod
    def _same_inputs(snapshot, case):
        if snapshot.get("business_context") != case.get("business_context"):
            return False
        if not all(snapshot.get(key) == case.get(key) for key in (
            "context", "product_route", "composition_route", "model_selection", "requirements")):
            return False
        current = Store._active_sources(case)
        fixed = snapshot.get("sources", [])
        if [item for item in fixed if item["role"] != "reference"] != [item for item in current if item["role"] != "reference"]:
            return False
        by_id = {item["id"]: item for item in current}
        return all(by_id.get(item["id"]) == item for item in fixed)

    def _fixed_upstream(self, case, package):
        if package["definition_id"] != "quality_check":
            return {}
        candidates = [item for item in case["workpackages"] if item["definition_id"] == "taskbook" and item["status"] == "completed"]
        if package["request_ref"]:
            candidates = [item for item in candidates if item["id"] == package["request_ref"]]
            if not candidates:
                raise RdError(422, "校验引用必须指向同一案例已完成的任务书工作包。")
        if not candidates:
            return {}
        upstream = candidates[-1]
        if not self._same_inputs(upstream["snapshot"], case):
            raise RdError(422, "当前资料、需求、参数、研制分类或编制策略已变更，请重新生成任务书后校验。")
        return {"upstream_workpackage_id": upstream["id"], "upstream_artifacts": deepcopy(upstream["artifacts"]),
                "sources": deepcopy(upstream["snapshot"]["sources"]),
                "source_selection": deepcopy(upstream["snapshot"]["source_selection"]),
                "taskbook_binding": deepcopy(upstream["snapshot"].get("taskbook_binding")),
                "business_context": deepcopy(upstream["snapshot"].get("business_context")),
                "upstream_results": {node["action_id"]: deepcopy(node["result"]) for node in upstream["nodes"] if node["status"] == "completed"}}

    def _validate_plan(self, db, definition_id, nodes):
        definition = definitions.definition(definition_id)
        if not isinstance(nodes, list) or not nodes or len(nodes) > 32:
            raise RdError(422, "计划应包含1至32个动作。")
        result, identifiers = [], set()
        required = definition["required_actions"]
        allowed = set(required + definition["optional_actions"])
        for node in nodes:
            if not isinstance(node, dict):
                raise RdError(422, "节点必须是对象。")
            nid = _text(node.get("id"), "节点ID", 100, True)
            if nid in identifiers or not re.fullmatch(r"[A-Za-z0-9_-]+", nid):
                raise RdError(422, "节点ID重复或无效。")
            identifiers.add(nid)
            aid = node.get("action_id")
            if aid not in allowed or node.get("action_version") != "1":
                raise RdError(422, "动作或发布版本不受当前工作包支持。")
            deps = node.get("depends_on")
            if not isinstance(deps, list) or any(not isinstance(item, str) for item in deps) or len(set(deps)) != len(deps):
                raise RdError(422, "节点依赖必须是唯一ID列表。")
            if not isinstance(node.get("required"), bool):
                raise RdError(422, "节点required必须为布尔值。")
            if aid in required and node["required"] is not True:
                raise RdError(422, "不能关闭必需检查。")
            result.append({"id": nid, "action_id": aid, "action_version": "1", "depends_on": deps[:],
                           "required": node["required"], "status": "draft", "result": None, "attempt": 0,
                           "started_at": None, "completed_at": None, "ended_at": None})
        for aid in required:
            if sum(node["action_id"] == aid for node in result) != 1:
                raise RdError(422, "所有必需动作必须保留一次。")
        by_id = {node["id"]: node for node in result}
        visiting, visited = set(), set()

        def visit(nid):
            if nid not in by_id or nid in visiting:
                raise RdError(422, "计划存在未知依赖或循环。")
            if nid in visited:
                return
            visiting.add(nid)
            for dep in by_id[nid]["depends_on"]:
                visit(dep)
            visiting.remove(nid)
            visited.add(nid)

        for nid in by_id:
            visit(nid)

        @cache
        def ancestors(nid):
            found = set(by_id[nid]["depends_on"])
            for dep in by_id[nid]["depends_on"]:
                found.update(ancestors(dep))
            return found

        for earlier, later in zip(required, required[1:]):
            first = next(node["id"] for node in result if node["action_id"] == earlier)
            last = next(node["id"] for node in result if node["action_id"] == later)
            if first not in ancestors(last):
                raise RdError(422, "计划不能绕过必需动作的前置检查。")
        return result

    def _submit(self, db, project, case, data, actor):
        package = self._package(case, data.get("workpackage_id"))
        if package["status"] != "draft" or package["stage"] != case["stage"]:
            raise RdError(409, "只能提交可执行的草稿工作包。")
        package["nodes"] = self._validate_plan(db, package["definition_id"], package["nodes"])
        binding = self._current_taskbook_binding(case) if package["definition_id"] == "taskbook" else None
        actions = []
        for node in package["nodes"]:
            resource = self._resource(db, node["action_id"], 1)
            if resource["status"] != "published" or not self._resource_enabled(db, node["action_id"]) or resource["execution_mode"] not in {"local_real", "remote_real"}:
                raise RdError(422, "计划绑定的能力版本不可执行。")
            actions.append({"id": node["action_id"], "version": node["action_version"], "resource_id": resource["id"], "resource_version": 1,
                            "execution_mode": resource["execution_mode"], "configuration": resource["configuration"]})
        snapshot = {"project_id": project["id"], "case_id": case["id"], "scenario_id": case["scenario_id"], "workpackage_id": package["id"],
            "actor_id": actor, "business_context": deepcopy(case["business_context"]),
            "stage": case["stage"], "definition_id": package["definition_id"], "definition_version": package["definition_version"],
            "request_ref": package["request_ref"], "context": deepcopy(case["context"]), "parameters": deepcopy(case["context"]),
            "context_provenance": deepcopy(case["context_provenance"]), "product_route": deepcopy(case["product_route"]),
            "composition_route": deepcopy(case["composition_route"]), "model_selection": deepcopy(case["model_selection"]),
            "sources": deepcopy(self._active_sources(case)), "source_selection": deepcopy(case["source_selection"]), "input_revision": case["input_revision"],
            "requirements": deepcopy(case["requirements"]), "clarifications": deepcopy(case["clarifications"]), "plan": deepcopy(package["nodes"]),
            "actions": actions, "rule_versions": deepcopy(definitions.RULE_VERSIONS), "execution_mode": "local_real",
            "schedule": {"revision": package["schedule_revision"], "planned_start": package["planned_start"], "planned_end": package["planned_end"], "plan_note": package["plan_note"]},
            "budget": {"max_attempts_per_node": 3, "max_total_attempts": len(package["nodes"]) * 3, "max_seconds": 1800}, "submitted_at": _now()}
        if binding is not None:
            snapshot["taskbook_binding"] = deepcopy(binding)
            snapshot["sources"] = deepcopy(binding["source_snapshots"])
        snapshot.update(self._fixed_upstream(case, package))
        snapshot["rule_assets"] = [{"name": path.name, "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                                   for path in sorted(_RULE_ROOT.glob("*.yaml"))]
        snapshot["rule_versions"].update({item["name"]: item["sha256"] for item in snapshot["rule_assets"]})
        package.update(status="submitted", snapshot=snapshot, run_id=_id())
        for node in package["nodes"]:
            node["status"] = "submitted"
        db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (package["run_id"], project["id"], case["id"], package["id"], "submitted", time.time(), _json(snapshot)))

    def _cancel(self, db, case, data):
        package = self._package(case, data.get("workpackage_id"))
        if package["status"] == "completed":
            raise RdError(409, "已完成的工作包不能取消。")
        package["status"] = "cancelled"
        ended_at = _now()
        package["ended_at"] = package.get("ended_at") or ended_at
        package["completed_at"] = None
        for node in package["nodes"]:
            if node["status"] != "completed":
                node["status"] = "cancelled"
                node["ended_at"] = node.get("ended_at") or ended_at
                node["completed_at"] = None
        if package["run_id"]:
            db.execute("UPDATE runs SET status='cancelled' WHERE id=?", (package["run_id"],))
            db.execute("DELETE FROM claims WHERE run_id=?", (package["run_id"],))

    def add_source(self, actor, pid, cid, expected_version, key, role, name, content):
        actor = _actor(actor)
        if role not in {"tech", "spec", "reference"} or not isinstance(content, bytes) or not content:
            raise RdError(422, "请上传非空资料并指定tech/spec/reference角色。")
        original_name = name
        name = _safe_name(name)
        digest = hashlib.sha256(content).hexdigest()
        with self._transaction() as db:
            project = self._load(db, pid, actor)
            key, fingerprint, replay = self._receipt(db, actor, pid, key, {"command": "add_source", "case_id": cid, "role": role, "name": original_name, "sha256": digest, "size": len(content)})
            if replay is not None:
                return replay
            self._cas(project, expected_version)
            case = self._case(project, cid)
            if case["status"] == "completed":
                raise RdError(409, "已完成案例的资料已封存，请创建新的案例修订。")
            sid = _id()
            path = self.asset_root / "sources" / pid / cid / sid
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            version = 1 + max((source["version"] for source in case["sources"] if source["name"] == name and source["role"] == role), default=0)
            case["sources"].append({"id": sid, "role": role, "name": name, "sha256": digest, "size": len(content), "version": version, "created_at": _now(), "path": str(path)})
            previous = case["source_selection"].get(role)
            invalidated = []
            if role in {"tech", "spec"}:
                case["source_selection"][role] = sid
                invalidated = self._invalidate_inputs(case, "用户上传并采用了新的正式输入资料版本。")
            elif case.get("source_analysis"):
                case["source_analysis"].update(status="stale", invalidated_reason="新增参考资料，请重新分析完整来源。")
            self._save(db, project, "source_added", actor, case_id=cid, source_id=sid, role=role,
                previous_source_id=previous, selected_source_id=sid if role in {"tech", "spec"} else None,
                input_revision=case["input_revision"], invalidated_decision_ids=invalidated)
            return self._save_receipt(db, actor, project, key, fingerprint)

    def _checked_path(self, item):
        path = Path(item["path"]).resolve()
        if not path.is_relative_to(self.asset_root) or not path.is_file():
            raise RdError(404, "资产文件不存在。")
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise RdError(409, "资产哈希不符，不能采用被改动的资料或成果。")
        return path

    def source_path(self, actor, pid, cid, sid):
        with self._connection() as db:
            case = self._case(self._load(db, pid, _actor(actor)), cid)
            source = next((item for item in case["sources"] if item["id"] == sid), None)
            if source is None:
                raise RdError(404, "资料不存在。")
            return self._checked_path(source)

    def artifact_path(self, actor, pid, cid, wid, aid):
        with self._connection() as db:
            case = self._case(self._load(db, pid, _actor(actor)), cid)
            package = self._package(case, wid)
            artifact = next((item for item in package["artifacts"] if item["id"] == aid), None)
            if artifact is None:
                raise RdError(404, "成果不存在。")
            return self._checked_path(artifact)

    @staticmethod
    def _resource(db, rid, version=None):
        if version is None:
            row = db.execute("SELECT v.payload FROM resource_versions v JOIN resource_heads h ON h.id=v.id AND h.version=v.version WHERE v.id=?", (rid,)).fetchone()
        else:
            row = db.execute("SELECT payload FROM resource_versions WHERE id=? AND version=?", (rid, version)).fetchone()
        if row is None:
            raise RdError(404, "资源版本不存在。")
        return json.loads(row[0])

    def get_resource(self, rid, version=None):
        with self._connection() as db:
            return _public(self._resource(db, rid, version))

    @staticmethod
    def _resource_enabled(db, rid):
        for row in db.execute("SELECT payload FROM resource_versions WHERE id=? ORDER BY version DESC", (rid,)):
            status = json.loads(row[0])["status"]
            if status != "draft":
                return status == "published"
        return False

    def list_resources(self):
        with self._connection() as db:
            return [_public(json.loads(row[0])) for row in db.execute("SELECT v.payload FROM resource_versions v JOIN resource_heads h ON h.id=v.id AND h.version=v.version ORDER BY v.id")]

    def save_resource(self, actor, payload, can_manage=False):
        actor = _actor(actor)
        if not can_manage:
            raise RdError(403, "只有资源管理员可以修改Workspace。")
        if not isinstance(payload, dict) or payload.get("kind") not in {"agent", "skill", "team"}:
            raise RdError(422, "资源类型必须为agent/skill/team。")
        operation = payload.get("operation", "save")
        if operation not in {"save", "publish", "retire"}:
            raise RdError(422, "资源操作无效。")
        config = payload.get("configuration", {})
        if not isinstance(config, dict):
            raise RdError(422, "资源配置必须是对象。")
        _reject_raw_credentials(config)
        mode = config.get("execution_mode", "local_real")
        if mode not in {"local_real", "remote_real", "contract_example"}:
            raise RdError(422, "执行模式无效。")
        rid = payload.get("id") or _id()
        if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", rid):
            raise RdError(422, "资源ID无效。")
        with self._transaction() as db:
            head = db.execute("SELECT version FROM resource_heads WHERE id=?", (rid,)).fetchone()
            if head and payload.get("expected_version") != head[0]:
                raise RdError(409, "资源版本已更新。")
            version = head[0] + 1 if head else 1
            resource = {"id": rid, "version": version, "kind": payload["kind"], "name": _text(payload.get("name"), "资源名称", 200, True),
                        "description": _text(payload.get("description", ""), "资源说明", 10000), "configuration": deepcopy(config),
                        "execution_mode": mode, "status": {"save": "draft", "publish": "published", "retire": "retired"}[operation],
                        "executable": False, "actor": actor, "created_at": _now()}
            db.execute("INSERT INTO resource_versions VALUES(?,?,?)", (rid, version, _json(resource)))
            db.execute("INSERT INTO resource_heads VALUES(?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version", (rid, version))
            return _public(resource)

    def _blocked(self, db, project, case, package, reason):
        package["status"] = "blocked"
        package["blocked_reasons"] = [reason]
        ended_at = _now()
        package["ended_at"] = package.get("ended_at") or ended_at
        package["completed_at"] = None
        for node in package["nodes"]:
            if node.get("started_at") and node["status"] in {"running", "submitted"}:
                node.update(status="blocked", ended_at=node.get("ended_at") or ended_at, completed_at=None)
        db.execute("UPDATE runs SET status='blocked' WHERE id=?", (package["run_id"],))
        db.execute("DELETE FROM claims WHERE run_id=?", (package["run_id"],))
        self._save(db, project, "run_blocked", "worker", case_id=case["id"], workpackage_id=package["id"], reason=reason)

    def _valid_bindings(self, db, snapshot):
        try:
            binding = snapshot.get("taskbook_binding")
            if binding:
                from .business_binding import verify_binding
                verify_binding(snapshot)
            rules = snapshot.get("rule_assets", [])
            if {path.name for path in _RULE_ROOT.glob("*.yaml")} != {item["name"] for item in rules}:
                return "提交后受控规则清单发生变化，请建立新工作包修订。"
            for item in rules:
                path = Path(item["path"])
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                    return "提交后受控规则哈希发生变化，禁止静默采用新规则。"
            for source in snapshot["sources"] + snapshot.get("upstream_artifacts", []):
                self._checked_path(source)
            for action in snapshot["actions"]:
                bound = self._resource(db, action["resource_id"], action["resource_version"])
                if bound["status"] != "published" or not self._resource_enabled(db, action["resource_id"]) or bound["execution_mode"] not in {"local_real", "remote_real"}:
                    return "固定能力版本已停用或不允许用于真实执行。"
            return None
        except (RdError, ValueError, OSError):
            return "固定来源、业务模板绑定或能力版本失效，请创建新工作包修订。"

    def claim_node(self, lease_seconds=60):
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        with self._transaction() as db:
            runs = db.execute("SELECT * FROM runs WHERE status IN ('submitted','running') ORDER BY created_at,id").fetchall()
            for run in runs:
                project = self._load(db, run["project_id"])
                case = self._case(project, run["case_id"])
                package = self._package(case, run["workpackage_id"])
                if package["status"] not in {"submitted", "running"}:
                    continue
                now = time.time()
                snapshot = json.loads(run["snapshot"])
                reason = self._valid_bindings(db, snapshot)
                if reason:
                    self._blocked(db, project, case, package, reason)
                    continue
                budget = snapshot["budget"]
                if now - run["created_at"] >= budget["max_seconds"]:
                    self._blocked(db, project, case, package, "累计运行预算已耗尽。")
                    continue
                claims = {row["node_id"]: row for row in db.execute("SELECT * FROM claims WHERE run_id=?", (run["id"],))}
                if sum(node["attempt"] for node in package["nodes"]) >= budget["max_total_attempts"]:
                    if any(row["lease_until"] > now for row in claims.values()):
                        continue
                    self._blocked(db, project, case, package, "累计运行预算已耗尽。")
                    continue
                for node in package["nodes"]:
                    if node["status"] == "running" and node["id"] in claims and claims[node["id"]]["lease_until"] > now:
                        continue
                    if node["status"] == "running":
                        # An expired generation may have reached the external engine.
                        # Fence late completion and require a new explicit revision;
                        # automatically replaying it can duplicate remote side effects.
                        if node["action_id"] == "generate":
                            self._blocked(db, project, case, package, "生成节点执行租约已失效，外部执行结果尚不确定；请核对已有成果后创建新的工作包修订，禁止自动重复生成。")
                            break
                        node["status"] = "submitted"
                    if node["status"] not in {"draft", "submitted"}:
                        continue
                    by_id = {item["id"]: item for item in package["nodes"]}
                    if any(by_id[dep]["status"] != "completed" for dep in node["depends_on"]):
                        continue
                    if node["attempt"] >= budget["max_attempts_per_node"]:
                        self._blocked(db, project, case, package, "节点累计尝试预算已耗尽。")
                        break
                    token = _id()
                    node.update(status="running", attempt=node["attempt"] + 1)
                    started_at = _now()
                    node["started_at"] = node.get("started_at") or started_at
                    package["started_at"] = package.get("started_at") or started_at
                    package["status"] = "running"
                    work_dir = self.asset_root / "runs" / run["id"] / node["id"] / token
                    work_dir.mkdir(parents=True, exist_ok=True)
                    db.execute("INSERT INTO claims VALUES(?,?,?,?) ON CONFLICT(run_id,node_id) DO UPDATE SET token=excluded.token,lease_until=excluded.lease_until",
                               (run["id"], node["id"], token, now + lease_seconds))
                    db.execute("UPDATE runs SET status='running' WHERE id=?", (run["id"],))
                    self._save(db, project, "node_claimed", "worker", case_id=case["id"], workpackage_id=package["id"], node_id=node["id"], attempt=node["attempt"])
                    previous = deepcopy(snapshot.get("upstream_results", {}))
                    for item in package["nodes"]:
                        if item["status"] == "completed":
                            previous[item["action_id"]] = deepcopy(item["result"])
                            if item["id"] != item["action_id"]:
                                previous[item["id"]] = deepcopy(item["result"])
                    return {"project_id": project["id"], "case_id": case["id"], "workpackage_id": package["id"], "run_id": run["id"],
                            "node_id": node["id"], "action_id": node["action_id"], "attempt": node["attempt"], "token": token,
                            "snapshot": snapshot, "previous_results": previous, "work_dir": str(work_dir)}
        return None

    def _active_claim(self, db, claim):
        row = db.execute("SELECT * FROM claims WHERE run_id=? AND node_id=?", (claim["run_id"], claim["node_id"])).fetchone()
        if row is None or row["token"] != claim["token"] or row["lease_until"] <= time.time():
            return None
        run = db.execute("SELECT status,created_at,snapshot FROM runs WHERE id=?", (claim["run_id"],)).fetchone()
        if run is None or run["status"] != "running" or time.time() - run["created_at"] >= json.loads(run["snapshot"])["budget"]["max_seconds"]:
            return None
        project = self._load(db, claim["project_id"])
        case = self._case(project, claim["case_id"])
        package = self._package(case, claim["workpackage_id"])
        node = next(item for item in package["nodes"] if item["id"] == claim["node_id"])
        if package["status"] != "running" or node["status"] != "running" or node["attempt"] != claim["attempt"]:
            return None
        return project, case, package, node

    def renew_claim(self, claim, lease_seconds=60):
        with self._transaction() as db:
            if self._active_claim(db, claim) is None:
                return False
            db.execute("UPDATE claims SET lease_until=? WHERE run_id=? AND node_id=? AND token=?", (time.time() + lease_seconds, claim["run_id"], claim["node_id"], claim["token"]))
            return True

    def is_claim_active(self, claim):
        with self._connection() as db:
            return self._active_claim(db, claim) is not None

    def progress(self, claim, payload):
        with self._transaction() as db:
            current = self._active_claim(db, claim)
            if current is None:
                return False
            project, case, package, node = current
            node["progress"] = _public(payload) if isinstance(payload, dict) else {"message": str(payload)[:2000]}
            self._save(db, project, "node_progress", "worker", case_id=case["id"], workpackage_id=package["id"], node_id=node["id"])
            return True

    def _register_artifacts(self, claim, artifacts):
        if not isinstance(artifacts, list):
            raise RdError(422, "执行器成果清单无效。")
        result, ids = [], set()
        work_dir = Path(claim["work_dir"]).resolve()
        for item in artifacts:
            if not isinstance(item, dict):
                raise RdError(422, "成果元数据无效。")
            aid = _text(item.get("id"), "成果ID", 100, True)
            if not re.fullmatch(r"[A-Za-z0-9_-]+", aid) or aid in ids:
                raise RdError(422, "成果ID无效或重复。")
            ids.add(aid)
            path = Path(item.get("path", "")).resolve()
            if not path.is_relative_to(work_dir) or not path.is_file():
                raise RdError(422, "成果必须位于当前尝试的受控目录。")
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if item.get("sha256") and item["sha256"] != digest:
                raise RdError(422, "成果哈希核验失败。")
            dest = self.asset_root / "artifacts" / claim["run_id"] / claim["node_id"] / claim["token"] / aid
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            result.append({"id": aid, "name": _safe_name(item.get("name", path.name)), "kind": _text(item.get("kind", "file"), "成果类型", 100),
                           "sha256": digest, "size": len(content), "path": str(dest), "created_at": _now()})
        return result

    def complete_node(self, claim, outcome):
        with self._transaction() as db:
            current = self._active_claim(db, claim)
            if current is None:
                return False
            project, case, package, node = current
            if not isinstance(outcome, dict) or outcome.get("status") not in {"completed", "blocked", "failed"} or not isinstance(outcome.get("result", {}), dict):
                outcome = {"status": "failed", "result": {}, "blocked_reasons": ["执行器返回了无效结果。"]}
            outcome = deepcopy(outcome)
            if _example(outcome):
                outcome = {"status": "blocked", "result": {}, "obligations": outcome.get("obligations", []), "blocked_reasons": ["结果依赖示例模式，不能作为真实研发证据。"]}
            binding_error = self._valid_bindings(db, package["snapshot"])
            if binding_error:
                outcome = {"status": "blocked", "result": {}, "blocked_reasons": [binding_error]}
            registered = []
            try:
                registered = self._register_artifacts(claim, outcome.get("artifacts", []))
                known = {item["id"] for item in package["artifacts"]}
                if any(item["id"] in known for item in registered):
                    raise RdError(422, "成果ID与已有固定成果冲突。")
            except (RdError, OSError, TypeError, ValueError):
                outcome = {"status": "failed", "result": {}, "blocked_reasons": ["成果登记失败：文件、目录或哈希不符合受控资产要求。"]}
                registered = []
            if self._active_claim(db, claim) is None:
                return False
            ended_at = _now()
            node["status"] = outcome["status"]
            node["ended_at"] = ended_at
            node["completed_at"] = ended_at if outcome["status"] == "completed" else None
            node["result"] = deepcopy(outcome.get("result", {}))
            node["result"]["artifacts"] = deepcopy(registered)
            node["obligations"] = deepcopy(outcome.get("obligations", []))
            node["blocked_reasons"] = deepcopy(outcome.get("blocked_reasons", []))
            package["artifacts"].extend(registered)
            obligations = {}
            for item in package["obligations"] + node["obligations"]:
                if isinstance(item, dict):
                    obligations[item.get("id") or _json(item)] = item
            package["obligations"] = list(obligations.values())
            if node["status"] in {"blocked", "failed"}:
                package["status"] = node["status"]
                package["ended_at"] = ended_at
                package["completed_at"] = None
                package["blocked_reasons"] = node["blocked_reasons"] or ["动作未完成，请查看结果与义务。"]
            elif all(item["status"] == "completed" for item in package["nodes"]):
                package["status"] = "completed"
                package["completed_at"] = package["ended_at"] = ended_at
            else:
                package["status"] = "running"
            db.execute("DELETE FROM claims WHERE run_id=? AND node_id=? AND token=?", (claim["run_id"], claim["node_id"], claim["token"]))
            db.execute("UPDATE runs SET status=? WHERE id=?", (package["status"], package["run_id"]))
            self._save(db, project, "node_finished", "worker", case_id=case["id"], workpackage_id=package["id"], node_id=node["id"], status=node["status"])
            return True
