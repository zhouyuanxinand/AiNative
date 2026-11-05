"""Immutable capability content, publication state and application grants.

This service never dispatches configuration. Built-in executors keep their v1
binding; custom resources are catalog declarations until an executor is added.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone

from . import catalog as definitions
from .store import RdError, _actor, _id, _json, _now, _public, _reject_raw_credentials, _text

DEFAULT_APPLICATION = "rd-platform-local"


def content_digest(resource):
    content = {key: resource.get(key) for key in ("id", "version", "kind", "name", "description", "configuration", "execution_mode", "executable")}
    return hashlib.sha256(_json(content).encode("utf-8")).hexdigest()


class Workspace:
    def __init__(self, store, application_id):
        self.store = store
        self.application_id = _text(application_id, "应用ID", 200, True)

    def initialize(self):
        with self.store._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS workspace_publications(
                    id TEXT, version INTEGER, status TEXT NOT NULL, revision INTEGER NOT NULL,
                    actor TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS workspace_controls(
                    id TEXT PRIMARY KEY, retired INTEGER NOT NULL, revision INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS workspace_grants(
                    application_id TEXT, id TEXT, version INTEGER, digest TEXT NOT NULL,
                    status TEXT NOT NULL, revision INTEGER NOT NULL, expires_at TEXT,
                    actor TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(application_id,id,version));
                CREATE TABLE IF NOT EXISTS workspace_receipts(
                    actor TEXT, key TEXT, fingerprint TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(actor,key));
                CREATE TABLE IF NOT EXISTS workspace_audit(
                    id TEXT PRIMARY KEY, actor TEXT NOT NULL, created_at TEXT NOT NULL, operation TEXT NOT NULL,
                    target TEXT NOT NULL, before_state TEXT NOT NULL, after_state TEXT NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS workspace_initializations(id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workspace_grant_visibility(
                    application_id TEXT, id TEXT, version INTEGER, dependency_only INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(application_id,id,version));
            """)
        with self.store._transaction() as db:
            if not db.execute("SELECT 1 FROM workspace_initializations WHERE id='phase2-teams-v1'").fetchone():
                for seed in definitions.builtin_teams():
                    resource = {**seed, "created_at": _now(), "actor": "system-bootstrap"}
                    resource["content_digest"] = content_digest(resource)
                    db.execute("INSERT OR IGNORE INTO resource_versions VALUES(?,?,?)", (resource["id"], 1, _json(resource)))
                    db.execute("INSERT OR IGNORE INTO resource_heads VALUES(?,1)", (resource["id"],))
                    db.execute("INSERT OR IGNORE INTO workspace_publications VALUES(?,1,'published',1,'system-bootstrap',?)", (resource["id"], _now()))
                    db.execute("INSERT OR IGNORE INTO workspace_controls(id,retired) VALUES(?,0)", (resource["id"],))
                    db.execute("INSERT OR IGNORE INTO workspace_grants VALUES(?,?,1,?,'granted',1,NULL,'system-bootstrap',?)",
                        (DEFAULT_APPLICATION, resource["id"], content_digest(resource), _now()))
                db.execute("INSERT INTO workspace_initializations VALUES('phase2-teams-v1',?)", (_now(),))
            if "revision" not in {row["name"] for row in db.execute("PRAGMA table_info(workspace_controls)")}:
                db.execute("ALTER TABLE workspace_controls ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
            if db.execute("SELECT 1 FROM workspace_initializations WHERE id='phase2a-v1'").fetchone():
                db.execute("INSERT OR IGNORE INTO workspace_controls(id,retired,revision) SELECT id,0,1 FROM resource_heads")
                return
            versions = [json.loads(row[0]) for row in db.execute("SELECT payload FROM resource_versions ORDER BY version DESC")]
            seen = set()
            for resource in versions:
                rid, version = resource["id"], resource["version"]
                db.execute("INSERT OR IGNORE INTO workspace_publications VALUES(?,?,?,?,?,?)",
                           (rid, version, resource["status"], 1, "system-migration", _now()))
                if resource["status"] != "draft" and rid not in seen:
                    db.execute("INSERT OR IGNORE INTO workspace_controls(id,retired,revision) VALUES(?,?,1)", (rid, int(resource["status"] == "retired")))
                    seen.add(rid)
            db.execute("INSERT OR IGNORE INTO workspace_controls(id,retired,revision) SELECT id,0,1 FROM resource_heads")
            for action in definitions.ACTIONS:
                resource = self.store._resource(db, action["id"], 1)
                db.execute("INSERT OR IGNORE INTO workspace_grants VALUES(?,?,?,?,?,?,?,?,?)",
                           (DEFAULT_APPLICATION, action["id"], 1, content_digest(resource), "granted", 1, None, "system-bootstrap", _now()))
            db.execute("INSERT INTO workspace_initializations VALUES('phase2a-v1',?)", (_now(),))

    @staticmethod
    def _permission(permissions, *names):
        if not isinstance(permissions, dict) or not any(permissions.get(name) is True for name in names):
            raise RdError(403, "当前主体没有此Workspace操作权限。")

    @staticmethod
    def _version(value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise RdError(422, "资源固定版本必须为正整数。")
        return value

    @staticmethod
    def _page(items, q="", kind=None, page=1, page_size=5):
        if isinstance(page, bool) or not isinstance(page, int) or page < 1 or isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 50:
            raise RdError(422, "分页参数无效，每页应为1至50条。")
        q = _text(q, "搜索词", 200).casefold()
        if kind is not None and kind not in {"agent", "skill", "team"}:
            raise RdError(422, "资源类型无效。")
        filtered = [item for item in items if (kind is None or item.get("kind") == kind)
                    and (not q or q in " ".join(str(item.get(key, "")) for key in ("id", "name", "title", "description")).casefold())]
        total = len(filtered)
        return {"items": filtered[(page - 1) * page_size:page * page_size], "total": total,
                "page": page, "page_size": page_size, "total_pages": (total + page_size - 1) // page_size}

    def _publication(self, db, rid, version):
        row = db.execute("SELECT * FROM workspace_publications WHERE id=? AND version=?", (rid, version)).fetchone()
        if row is None:
            raise RdError(404, "资源版本不存在。")
        return dict(row)

    def _grant(self, db, rid, version, application_id=None):
        app = self.application_id if application_id is None else application_id
        row = db.execute("SELECT * FROM workspace_grants WHERE application_id=? AND id=? AND version=?", (app, rid, version)).fetchone()
        if row:
            result = dict(row)
            result["content_digest"] = result.pop("digest")
            visibility = db.execute("SELECT dependency_only FROM workspace_grant_visibility WHERE application_id=? AND id=? AND version=?", (app, rid, version)).fetchone()
            result["dependency_only"] = bool(visibility[0]) if visibility else False
            return result
        return {"application_id": app, "id": rid, "version": version, "status": "not_granted", "revision": 0, "expires_at": None}

    def _detail(self, db, rid, version=None, summary=False):
        resource = deepcopy(self.store._resource(db, rid, version))
        state = self._publication(db, rid, resource["version"])
        resource.update(status=state["status"], content_digest=content_digest(resource))
        if summary:
            fields = {"id", "version", "kind", "name", "description", "execution_mode", "status", "executable", "content_digest"}
            return {key: value for key, value in resource.items() if key in fields}
        control = db.execute("SELECT retired,revision FROM workspace_controls WHERE id=?", (rid,)).fetchone()
        resource.update(publication_revision=state["revision"], state_revision=state["revision"],
                        control_revision=control["revision"], resource_retired=bool(control["retired"]),
                        grant=self._grant(db, rid, resource["version"]))
        resource["head_version"] = db.execute("SELECT version FROM resource_heads WHERE id=?", (rid,)).fetchone()[0]
        resource["available_versions"] = [row[0] for row in db.execute("SELECT version FROM resource_versions WHERE id=? ORDER BY version DESC", (rid,))]
        return _public(resource)

    def management_detail(self, actor, permissions, rid, version=None):
        _actor(actor)
        self._permission(permissions, "can_edit_resources", "can_publish_resources", "can_manage_application_grants")
        if version is not None:
            self._version(version)
        with self.store._connection() as db:
            return self._detail(db, rid, version)

    def management_list(self, actor, permissions, *, q="", kind=None, page=1, page_size=5):
        _actor(actor)
        self._permission(permissions, "can_edit_resources", "can_publish_resources", "can_manage_application_grants")
        with self.store._connection() as db:
            items = [self._detail(db, row[0], row[1]) for row in db.execute("SELECT id,version FROM resource_heads ORDER BY id")]
        result = self._page(items, q, kind, page, page_size)
        result["resources"] = result["items"]
        return result

    def _published(self, db, rid, version):
        state = self._publication(db, rid, version)
        control = db.execute("SELECT retired FROM workspace_controls WHERE id=?", (rid,)).fetchone()
        return state["status"] == "published" and not (control and control[0])

    def _members(self, resource):
        if resource["kind"] != "team":
            return []
        members = resource["configuration"].get("members")
        if not isinstance(members, list) or not members or len(members) > 32:
            raise RdError(422, "专家团须包含1至32个固定成员引用。")
        fixed = []
        for member in members:
            if not isinstance(member, dict) or set(member) != {"resource_id", "resource_version"} or not isinstance(member["resource_id"], str):
                raise RdError(422, "专家团成员只能使用resource_id及resource_version固定引用。")
            fixed.append((member["resource_id"], self._version(member["resource_version"])))
        if len(set(fixed)) != len(fixed):
            raise RdError(422, "专家团成员不能重复。")
        return fixed

    def _closure(self, db, rid, version, *, app=None, grants=False, visiting=None, root=False):
        visiting = set() if visiting is None else visiting
        target = (rid, version)
        if target in visiting:
            return False
        resource = self.store._resource(db, rid, version)
        if not root and not self._published(db, rid, version):
            return False
        if grants and not root:
            grant = self._grant(db, rid, version, app)
            if grant["status"] != "granted" or grant.get("content_digest") != content_digest(resource):
                return False
            expiry = grant.get("expires_at")
            if expiry and datetime.fromisoformat(expiry) <= datetime.now(timezone.utc):
                return False
        visiting.add(target)
        valid = all(self._closure(db, mid, mv, app=app, grants=grants, visiting=visiting) for mid, mv in self._members(resource))
        visiting.remove(target)
        return valid

    def capability_available(self, rid, version=1, *, application_id=None, db=None):
        try:
            self._version(version)
            if db is None:
                with self.store._connection() as connection:
                    return self._closure(connection, rid, version, app=application_id, grants=True)
            return self._closure(db, rid, version, app=application_id, grants=True)
        except (RdError, ValueError, TypeError):
            return False

    def catalog_detail(self, rid, version):
        self._version(version)
        with self.store._connection() as db:
            if not self.capability_available(rid, version, db=db) or self._grant(db, rid, version).get("dependency_only"):
                raise RdError(404, "资源版本不存在或未授权。")
            result = self._detail(db, rid, version, summary=True)
            resource = self.store._resource(db, rid, version)
            if resource["kind"] == "team":
                result["configuration"] = _public({key: deepcopy(resource["configuration"].get(key)) for key in ("members", "inputs", "outputs", "execution_graph")})
            result["available_versions"] = self._available_versions(db, rid)
            return result

    def root_available(self, rid, version=1, *, db=None):
        if db is None:
            with self.store._connection() as connection:
                return self.root_available(rid, version, db=connection)
        return self.capability_available(rid, version, db=db) and not self._grant(db, rid, version).get("dependency_only")

    def _available_versions(self, db, rid):
        return [row[0] for row in db.execute("SELECT version FROM resource_versions WHERE id=? ORDER BY version DESC", (rid,))
                if self.capability_available(rid, row[0], db=db) and not self._grant(db, rid, row[0]).get("dependency_only")]

    def catalog_list(self, *, q="", kind=None, page=1, page_size=5):
        with self.store._connection() as db:
            items = []
            for row in db.execute("SELECT id FROM resource_heads ORDER BY id"):
                versions = self._available_versions(db, row[0])
                if versions:
                    item = self._detail(db, row[0], versions[0], summary=True)
                    item["available_versions"] = versions
                    items.append(item)
        return self._page(items, q, kind, page, page_size)

    def _receipt(self, db, actor, key, intent):
        key = _text(key, "Idempotency-Key", 200, True)
        try:
            fingerprint = hashlib.sha256(_json({"application_id": self.application_id, **intent}).encode()).hexdigest()
        except (TypeError, ValueError) as error:
            raise RdError(422, "资源命令必须包含有效JSON数据。") from error
        row = db.execute("SELECT fingerprint,response FROM workspace_receipts WHERE actor=? AND key=?", (actor, key)).fetchone()
        if row and row[0] != fingerprint:
            raise RdError(409, "相同幂等键已用于其他内容。")
        return key, fingerprint, json.loads(row[1]) if row else None

    @staticmethod
    def _audit(db, actor, operation, target, before, after, revision):
        db.execute("INSERT INTO workspace_audit VALUES(?,?,?,?,?,?,?,?)",
                   (_id(), actor, _now(), operation, target, _json(before), _json(after), revision))

    @staticmethod
    def _finish(db, actor, key, fingerprint, response):
        db.execute("INSERT INTO workspace_receipts VALUES(?,?,?,?)", (actor, key, fingerprint, _json(response)))
        return response

    def save_resource(self, actor, permissions, payload, key):
        actor = _actor(actor)
        if not isinstance(payload, dict):
            raise RdError(422, "资源命令必须是对象。")
        operation = payload.get("operation", "save")
        if operation not in {"save", "publish", "retire"}:
            raise RdError(422, "资源操作无效。")
        self._permission(permissions, "can_edit_resources" if operation == "save" else "can_publish_resources")
        if "application_id" in payload:
            raise RdError(422, "目标应用由服务端固定。")
        with self.store._transaction() as db:
            key, fingerprint, replay = self._receipt(db, actor, key, {"command": "resource", "payload": payload})
            if replay is not None:
                return replay
            rid = payload.get("id") or _id()
            if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", rid):
                raise RdError(422, "资源ID无效。")
            head = db.execute("SELECT version FROM resource_heads WHERE id=?", (rid,)).fetchone()
            current = head[0] if head else 0
            if type(payload.get("expected_version")) is not int or payload["expected_version"] != current:
                raise RdError(409, "资源内容版本已更新，请重新读取。")
            if operation == "save":
                kind, config = payload.get("kind"), payload.get("configuration", {})
                if kind not in {"agent", "skill", "team"} or not isinstance(config, dict):
                    raise RdError(422, "资源类型或配置无效。")
                _reject_raw_credentials(config)
                mode = config.get("execution_mode", "local_real")
                if mode not in {"local_real", "remote_real", "contract_example"}:
                    raise RdError(422, "执行模式无效。")
                version = current + 1
                resource = {"id": rid, "version": version, "kind": kind, "name": _text(payload.get("name"), "资源名称", 200, True),
                            "description": _text(payload.get("description", ""), "资源说明", 10000), "configuration": deepcopy(config),
                            "execution_mode": mode, "status": "draft", "executable": False, "actor": actor, "created_at": _now()}
                if current and self.store._resource(db, rid, current)["kind"] != kind:
                    raise RdError(422, "资源类型不能随版本改变。")
                self._members(resource)
                if kind == "team" and "execution_graph" in config:
                    self.validate_team_graph(db, resource)
                    resource["executable"] = True
                resource["content_digest"] = content_digest(resource)
                db.execute("INSERT INTO resource_versions VALUES(?,?,?)", (rid, version, _json(resource)))
                db.execute("INSERT INTO resource_heads VALUES(?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version", (rid, version))
                db.execute("INSERT INTO workspace_publications VALUES(?,?,?,?,?,?)", (rid, version, "draft", 1, actor, _now()))
                db.execute("INSERT OR IGNORE INTO workspace_controls(id,retired,revision) VALUES(?,0,1)", (rid,))
                self._audit(db, actor, operation, f"{rid}/{version}", {}, {"status": "draft", "content_digest": content_digest(resource)}, 1)
            else:
                version = self._version(payload.get("version", payload.get("resource_version", current)))
                state = self._publication(db, rid, version)
                if type(payload.get("expected_state_revision")) is not int or payload["expected_state_revision"] != state["revision"]:
                    raise RdError(409, "发布状态已更新，请重新读取。")
                control = dict(db.execute("SELECT retired,revision FROM workspace_controls WHERE id=?", (rid,)).fetchone())
                if type(payload.get("expected_control_revision")) is not int or payload["expected_control_revision"] != control["revision"]:
                    raise RdError(409, "资源整体状态已更新，请重新读取。")
                if operation == "publish" and not self._closure(db, rid, version, root=True):
                    raise RdError(422, "专家团包含未发布成员或循环依赖。")
                status = "published" if operation == "publish" else "retired"
                db.execute("UPDATE workspace_publications SET status=?,revision=revision+1,actor=?,updated_at=? WHERE id=? AND version=?",
                           (status, actor, _now(), rid, version))
                retired = int(operation == "retire")
                db.execute("UPDATE workspace_controls SET retired=?,revision=revision+1 WHERE id=?", (retired, rid))
                self._audit(db, actor, operation, f"{rid}/{version}", {**state, "control": control},
                            {"status": status, "control": {"retired": retired, "revision": control["revision"] + 1}}, state["revision"] + 1)
            return self._finish(db, actor, key, fingerprint, self._detail(db, rid, version))

    def set_grant(self, actor, permissions, payload, key):
        actor = _actor(actor)
        self._permission(permissions, "can_manage_application_grants")
        if not isinstance(payload, dict) or set(payload) - {"id", "version", "operation", "expected_revision", "expires_at", "dependency_only"}:
            raise RdError(422, "授权只接受固定资源版本、操作、修订及到期时间。")
        operation = payload.get("operation")
        if "dependency_only" in payload and type(payload["dependency_only"]) is not bool:
            raise RdError(422, "dependency_only须为布尔值。")
        if operation not in {"grant", "revoke"}:
            raise RdError(422, "授权操作无效。")
        version = self._version(payload.get("version"))
        rid = payload.get("id")
        if not isinstance(rid, str):
            raise RdError(422, "资源ID无效。")
        expiry = payload.get("expires_at")
        if expiry is not None:
            try:
                parsed = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
                    raise ValueError()
                expiry = parsed.astimezone(timezone.utc).isoformat()
            except (ValueError, TypeError, AttributeError):
                raise RdError(422, "到期时间必须是UTC时间。") from None
        with self.store._transaction() as db:
            key, fingerprint, replay = self._receipt(db, actor, key, {"command": "grant", "payload": payload})
            if replay is not None:
                return replay
            resource = self.store._resource(db, rid, version)
            before = self._grant(db, rid, version)
            if type(payload.get("expected_revision")) is not int or payload["expected_revision"] != before["revision"]:
                raise RdError(409, "应用授权已更新，请重新读取。")
            if operation == "grant" and (not self._published(db, rid, version) or not self._closure(db, rid, version, grants=True, root=True)):
                raise RdError(422, "只能投放已发布且成员许可完整的固定版本。")
            db.execute("INSERT INTO workspace_grants VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(application_id,id,version) DO UPDATE SET digest=excluded.digest,status=excluded.status,revision=excluded.revision,expires_at=excluded.expires_at,actor=excluded.actor,updated_at=excluded.updated_at",
                       (self.application_id, rid, version, content_digest(resource), "granted" if operation == "grant" else "revoked", before["revision"] + 1, expiry, actor, _now()))
            db.execute("INSERT INTO workspace_grant_visibility VALUES(?,?,?,?) ON CONFLICT(application_id,id,version) DO UPDATE SET dependency_only=excluded.dependency_only",
                       (self.application_id, rid, version, int(payload.get("dependency_only", before.get("dependency_only", False)))))
            after = self._grant(db, rid, version)
            self._audit(db, actor, operation, f"{self.application_id}/{rid}/{version}", before, after, after["revision"])
            return self._finish(db, actor, key, fingerprint, after)

    def require_actions(self, action_ids, *, db=None):
        if not all(self.capability_available(aid, 1, db=db) for aid in action_ids):
            raise RdError(422, "当前应用缺少所需固定能力的有效授权。")

    def validate_team_graph(self, db, resource):
        from .designer import graph_value, topological, Designer, REQUIRED_INPUTS
        config = resource["configuration"]
        if resource["execution_mode"] != "local_real":
            raise RdError(422, "可执行专家团当前仅绑定本地真实Skill图，远端或示例声明不能执行。")
        if any(not isinstance(config.get(field), list) or any(not isinstance(v, str) or not v for v in config[field]) for field in ("inputs", "outputs")):
            raise RdError(422, "可执行专家团须声明输入、输出合同。")
        graph = graph_value(config.get("execution_graph"))
        order, deps = topological(graph)
        if {(n["resource_id"], n["resource_version"]) for n in graph["nodes"]} != set(self._members(resource)):
            raise RdError(422, "专家团内部图须精确覆盖固定成员。")
        plan = []
        nodes = {n["id"]: n for n in graph["nodes"]}
        for nid in order:
            n = nodes[nid]
            if 'route' in n or 'business_node_id' in n or n.get('action_version') != '1':
                raise RdError(422, "专家团内部图不支持业务路线/业务节点映射或未绑定动作版本。")
            r = self.store._resource(db, n["resource_id"], n["resource_version"])
            aid = r["configuration"].get("action_id")
            if r["kind"] != "skill" or aid != r["id"] or r["version"] != 1 or aid not in definitions.ACTION_TITLES or not r.get("executable"):
                raise RdError(422, "专家团内部节点必须绑定已注册的固定Skill执行器。")
            if n.get('action_id', aid) != aid or any(field in n and n[field] != expected for field, expected in
                (("inputs", list(REQUIRED_INPUTS[aid])), ("outputs", [aid]))):
                raise RdError(422, "专家团内部动作标识或输入输出合同与固定Skill不匹配。")
            plan.append({"id": nid, "action_id": aid, "depends_on": list(deps[nid]), "input_bindings": deepcopy(n.get("input_bindings", {}))})
        Designer.bind_inputs(plan, "input_check")
        return graph

    def default_team_versions(self, *, db=None):
        if db is None:
            with self.store._connection() as connection:
                return self.default_team_versions(db=connection)
        values = {}
        for rid in ("taskbook-authoring-team", "consistency-team", "context-team", "quality-team"):
            versions = self._available_versions(db, rid)
            if versions:
                values[rid] = versions[0]
        return values

    def require_definition(self, definition_id, version="1", *, db=None, workflow=None):
        definition = definitions.definition(definition_id, version)
        if definition is None:
            raise RdError(422, "工作包固定版本不存在。")
        self.require_actions(definition["required_actions"], db=db)
        refs = [n['action_resource'] for n in (workflow or {}).get('graph', {}).get('nodes', []) if n.get('action_resource')
            and n.get('workpackage_definition_id', 'input_check' if (workflow or {}).get('category') == 'selection' else 'taskbook') == definition_id]
        if refs:
            if not all(self.root_available(r['resource_id'], r['resource_version'], db=db) for r in refs):
                raise RdError(422, "已采用业务模板的工作包固定专家团缺少当前应用授权。")
            return
        team = {"taskbook": "taskbook-authoring-team", "input_check": "consistency-team", "context_resolve": "context-team", "quality_check": "quality-team"}[definition_id]
        if team not in self.default_team_versions(db=db):
            raise RdError(422, "工作包专家团根资源缺少有效应用授权。")

    def filtered_catalog(self):
        catalog = definitions.get_catalog()
        with self.store._connection() as db:
            available = {action["id"] for action in definitions.ACTIONS if self.capability_available(action["id"], 1, db=db)}
        catalog["actions"] = [item for item in catalog["actions"] if item["id"] in available]
        team_versions = self.default_team_versions()
        workflows = (self.store.workflow_templates.list("catalog", page_size=50)["items"] if hasattr(self.store, "workflow_templates") else [])
        scoped_definitions = {n.get('workpackage_definition_id', 'input_check' if w['category'] == 'selection' else 'taskbook')
            for w in workflows for n in w['graph']['nodes'] if n.get('action_resource')}
        packages = []
        for definition in catalog["workpackage_definitions"]:
            if not set(definition["required_actions"]) <= available:
                continue
            team = {"taskbook": "taskbook-authoring-team", "input_check": "consistency-team", "context_resolve": "context-team", "quality_check": "quality-team"}[definition["id"]]
            if team not in team_versions and definition['id'] not in scoped_definitions:
                continue
            definition["optional_actions"] = [aid for aid in definition["optional_actions"] if aid in available]
            definition["nodes"] = [node for node in definition["nodes"] if node["action_id"] in available]
            packages.append(definition)
        catalog["workpackage_definitions"] = packages
        taskbook_allowed = any(item["id"] == "taskbook" for item in packages)
        if not taskbook_allowed:
            catalog["scenarios"] = []
            catalog["research_workflow_templates"] = []
            catalog["selection_workflow_templates"] = []
            catalog["project_workflow_templates"] = []
        elif hasattr(self.store, "workflow_templates"):
            for category, key in (("research", "research_workflow_templates"), ("selection", "selection_workflow_templates"),
                                  ("project", "project_workflow_templates")):
                catalog[key] = self.store.workflow_templates.list("catalog", category=category, page_size=50)["items"]
        return catalog

    def catalog_items(self, category, *, q="", page=1, page_size=5):
        mapping = {"actions": "actions", "workpackages": "workpackage_definitions", "research": "research_workflow_templates", "selection": "selection_workflow_templates", "project": "project_workflow_templates"}
        if category not in mapping:
            raise RdError(422, "目录分类无效。")
        if category == "actions":
            result = self.catalog_list(q=q, kind="team", page=page, page_size=page_size)
            for item in result["items"]:
                item["resource_id"], item["resource_version"] = item["id"], item["version"]
                item["title"] = item["name"]
            return result
        if category in {"research", "selection", "project"} and hasattr(self.store, "workflow_templates"):
            if not any(item['id'] == 'taskbook' for item in self.filtered_catalog()['workpackage_definitions']):
                return self._page([], q=q, page=page, page_size=page_size)
            return self.store.workflow_templates.list('catalog', category=category, q=q, page=page, page_size=page_size)
        return self._page(self.filtered_catalog()[mapping[category]], q=q, page=page, page_size=page_size)

    def snapshot_permission_error(self, db, snapshot):
        app = snapshot.get("application_id", DEFAULT_APPLICATION)
        for action in snapshot.get("actions", []) + snapshot.get("resource_locks", []):
            rid, version = action["resource_id"], action["resource_version"]
            if not self.capability_available(rid, version, application_id=app, db=db):
                return "固定能力的应用授权已撤销、到期或停用。"
            if action.get("dependency_only") is False and self._grant(db, rid, version, app).get("dependency_only"):
                return "固定根资源的独立应用授权已撤销。"
            if action.get("content_digest") and content_digest(self.store._resource(db, rid, version)) != action["content_digest"]:
                return "固定能力内容摘要已变化。"
        return None
