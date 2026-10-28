"""Transactional R&D aggregates, isolated from technical generation jobs.

Each project is one versioned aggregate. SQLite serializes commands across store
instances; the aggregate, event and idempotent response commit together. Baseline
snapshots and completed decisions are only appended, never replaced by drafts.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from .taskbook_models import COMMAND_FIELDS, normalize
from .journey import COMMAND_FIELDS as JOURNEY_COMMAND_FIELDS


class RdError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id():
    return uuid.uuid4().hex


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value, label, required=True, maximum=20000):
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise RdError(422, f"{label}格式不正确")
    return value.strip()


def _actor(actor):
    if not isinstance(actor, dict):
        raise RdError(401, "需要经过验证的登录身份")
    uid = _text(actor.get("user_id"), "用户ID", maximum=256)
    return {"user_id": uid, "display_name": _text(actor.get("display_name") or uid, "姓名", maximum=256)}


_FIELDS = {
    "add_member": {"user_id", "display_name", "role"},
    "remove_member": {"user_id"},
    "save_requirement": {"id", "title", "content", "source", "acceptance", "clarification", "required"},
    "confirm_baseline": set(),
    "create_task": {"title", "description", "assignee_id", "reviewer_id", "due_date"},
    "start_task": {"task_id"},
    "reassign_task": {"task_id", "assignee_id", "reviewer_id"},
    "adopt_baseline": {"task_id"},
    "submit_review": {"task_id", "artifact_id"},
    "decide_review": {"review_id", "decision", "comment"},
    "withdraw_review": {"review_id", "comment"},
}
_FIELDS.update(COMMAND_FIELDS)
_FIELDS.update(JOURNEY_COMMAND_FIELDS)


class RdStore:
    def __init__(self, db_path: Path, artifact_root: Path | None = None):
        self.db_path = Path(db_path).resolve()
        self.artifact_root = Path(artifact_root or self.db_path.parent / "rd_artifacts").resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        with self._transaction() as conn:
            from .migrations import migrate
            migrate(conn)

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def _load(self, conn, pid, actor_id):
        row = conn.execute("SELECT document FROM projects WHERE id=?", (pid,)).fetchone()
        if row is None:
            raise RdError(404, "项目不存在或无权访问")
        doc = normalize(json.loads(row[0]))
        if not any(m["user_id"] == actor_id for m in doc["members"]):
            raise RdError(404, "项目不存在或无权访问")
        return doc

    @staticmethod
    def _public_artifacts(result):
        # New service responses may contain only a package/run/version. Never
        # assume that every idempotent response is a complete project view.
        pid = result.get('project', {}).get('id')
        for artifact in result.get("artifacts", []):
            if pid:
                artifact["file_ref"] = f"/api/rd/projects/{pid}/artifacts/{artifact['id']}/download"
        native_tasks={t['id'] for t in result.get('tasks',[]) if t.get('kind')=='taskbook'}
        def redact(value,native=False):
            if isinstance(value,dict):
                native=native or value.get('task_id') in native_tasks
                for key in list(value):
                    if key.endswith('_path') or key in {'path','api_key','token','password','credential','base_url','workbench_role'} or (key == 'file_ref' and isinstance(value[key],str) and not value[key].startswith('/api/')):
                        value.pop(key)
                    elif key=='quality_evidence' and not native:
                        # Preserve the existing generic QA evidence API verbatim;
                        # native snapshots use the sanitized fixed-input view.
                        continue
                    else: redact(value[key],native)
            elif isinstance(value,list):
                for item in value: redact(item,native)
        redact(result)
        return result

    @staticmethod
    def _view(doc, actor_id, conn=None):
        result = copy.deepcopy(normalize(doc))
        member = next(m for m in doc["members"] if m["user_id"] == actor_id)
        result["project"]["role"] = member["role"]
        result["current_user_id"] = actor_id
        from .plan_handoff import build_project_plan
        result['project_plan']=build_project_plan(doc)
        from .journey import build_journey, pending_releases
        result['journey'] = build_journey(result)
        result['project_plan']['pending_releases'] = pending_releases(result)
        return RdStore._public_artifacts(result)

    def detail(self, pid, actor_id):
        with self._connection() as conn:
            return self._view(self._load(conn, pid, actor_id), actor_id, conn)

    def list_projects(self, actor_id, q="", page=1, page_size=20):
        if type(page) is not int or type(page_size) is not int or page < 1 or not 1 <= page_size <= 100:
            raise RdError(422, "页码须为正整数，每页数量须为1至100")
        q = _text(q, "搜索条件", required=False, maximum=256).casefold()
        with self._connection() as conn:
            docs = [json.loads(r[0]) for r in conn.execute("SELECT document FROM projects ORDER BY rowid DESC")]
        items = []
        for doc in docs:
            member = next((m for m in doc["members"] if m["user_id"] == actor_id), None)
            p = doc["project"]
            if member and (not q or any(q in str(p.get(k, "")).casefold() for k in ("code", "name", "customer", "product"))):
                items.append({**p, "role": member["role"]})
        offset = (page - 1) * page_size
        return self._public_artifacts({"items": items[offset:offset + page_size], "total": len(items), "page": page, "page_size": page_size})

    def workspace(self, actor_id):
        """One consistent read snapshot, bounded to 200 visible projects."""
        projects = []
        with self._connection() as conn:
            for row in conn.execute("SELECT document FROM projects ORDER BY rowid DESC"):
                doc = json.loads(row[0])
                if any(member["user_id"] == actor_id for member in doc["members"]):
                    projects.append(self._view(doc, actor_id, conn))
                    if len(projects) == 200:
                        break
        return {"projects": projects}

    @staticmethod
    def _replay(conn, scope, actor_id, key, fingerprint):
        _text(key, "Idempotency-Key", maximum=256)
        row = conn.execute("SELECT fingerprint,response FROM requests WHERE scope=? AND actor_id=? AND request_key=?", (scope, actor_id, key)).fetchone()
        if row:
            if row[0] != fingerprint:
                raise RdError(409, "相同请求键不能用于不同操作，请刷新后重试")
            return RdStore._public_artifacts(json.loads(row[1]))
        return None

    @staticmethod
    def _remember(conn, scope, actor_id, key, fingerprint, response):
        conn.execute("INSERT INTO requests VALUES (?,?,?,?,?)", (scope, actor_id, key, fingerprint, _json(response)))

    @staticmethod
    def _event(doc, action, actor_id, detail):
        doc["events"].append({"id": _id(), "action": action, "actor_id": actor_id, "created_at": _now(), "detail": copy.deepcopy(detail)})

    def _save(self, conn, doc, action, actor_id, detail):
        doc["project"]["version"] += 1
        self._event(doc, action, actor_id, detail)
        conn.execute("UPDATE projects SET version=?,document=? WHERE id=?", (doc["project"]["version"], _json(doc), doc["project"]["id"]))

    @staticmethod
    def _version(doc, expected):
        if type(expected) is not int or expected < 1:
            raise RdError(422, "expected_version须为正整数")
        if doc["project"]["version"] != expected:
            raise RdError(409, "项目已被其他操作更新，请刷新并比较后重试")

    def create_project(self, actor, payload, request_key):
        actor = _actor(actor)
        if not isinstance(payload, dict) or set(payload) - {"name", "code", "customer", "product"}:
            raise RdError(422, "项目字段不正确")
        values = {k: _text(payload.get(k), k, required=k != "code", maximum=1000) for k in ("name", "code", "customer", "product")}
        fingerprint = _json(payload)
        with self._transaction() as conn:
            replay = self._replay(conn, "create", actor["user_id"], request_key, fingerprint)
            if replay is not None:
                return replay
            pid = _id()
            doc = {"project": {"id": pid, **values, "owner_id": actor["user_id"], "version": 1, "current_baseline_id": None, "created_at": _now()}, "members": [{**actor, "role": "owner"}], **{k: [] for k in ("requirements", "baselines", "tasks", "artifacts", "reviews", "events", "generations")}}
            if not doc["project"]["code"]:
                doc["project"]["code"] = "RD-" + pid[:8].upper()
            self._event(doc, "create_project", actor["user_id"], values)
            conn.execute("INSERT INTO projects VALUES (?,?,?)", (pid, 1, _json(doc)))
            result = self._view(doc, actor["user_id"], conn)
            self._remember(conn, "create", actor["user_id"], request_key, fingerprint, result)
            return result

    @staticmethod
    def _find(doc, collection, object_id):
        row = next((v for v in doc[collection] if v["id"] == object_id), None)
        if row is None:
            raise RdError(404, "指定业务记录不存在")
        return row

    @staticmethod
    def _member(doc, uid):
        return next((m for m in doc["members"] if m["user_id"] == uid), None)

    def _permission(self, doc, uid, action):
        member = self._member(doc, uid)
        if member is None:
            raise RdError(404, "项目不存在或无权访问")
        owner_actions = {"add_member", "remove_member", "confirm_baseline", "create_task", "reassign_task", "adopt_baseline", "adopt_development", "create_taskbook", "publish_plan", "resolve_change_impact", "reopen_taskbook"}
        owner_actions.update(JOURNEY_COMMAND_FIELDS)
        if action in owner_actions and member["role"] != "owner":
            raise RdError(403, "此操作需要项目负责人权限")
        if action == "save_requirement" and member["role"] not in {"owner", "engineer"}:
            raise RdError(403, "此角色不能维护需求")
        if action in {"start_task", "submit_review", "register_artifact", "bind_generation", "save_wbs", "advance_taskbook_stage"} and member["role"] not in {"owner", "engineer"}:
            raise RdError(403, "此角色不能办理工程任务")
        if action == "decide_review" and member["role"] not in {"owner", "reviewer"}:
            raise RdError(403, "此角色不能审签")
        if action == "withdraw_review" and member["role"] == "viewer":
            raise RdError(403, "只读成员不能撤回送审")

    def _assignments(self, doc, assignee, reviewer):
        assignee = _text(assignee, "执行人ID", maximum=256)
        reviewer = _text(reviewer, "审核人ID", maximum=256)
        a, r = self._member(doc, assignee), self._member(doc, reviewer)
        if not a or not r or a["role"] not in {"owner", "engineer"} or r["role"] not in {"owner", "reviewer"} or assignee == reviewer:
            raise RdError(422, "须指定不同且具备相应职责的当前执行人和审核人")

    @staticmethod
    def _cancel_reviews(doc, task, status, comment):
        for review in doc["reviews"]:
            if review["task_id"] == task["id"] and review["status"] == "pending":
                review.update(status=status, comment=comment, decided_at=_now())
                artifact = next(a for a in doc["artifacts"] if a["id"] == review["artifact_id"])
                artifact["status"] = status
                if task["status"] == "in_review":
                    task["status"] = "in_progress"

    def execute(self, pid, actor, action, payload, expected_version, request_key):
        actor = _actor(actor)
        uid = actor["user_id"]
        if action not in _FIELDS or not isinstance(payload, dict) or set(payload) - _FIELDS[action]:
            raise RdError(422, "操作或字段不正确")
        fingerprint = _json({"action": action, "payload": payload, "expected_version": expected_version})
        with self._transaction() as conn:
            doc = self._load(conn, pid, uid)
            self._permission(doc, uid, action)
            replay = self._replay(conn, pid, uid, request_key, fingerprint)
            if replay is not None:
                return replay
            self._version(doc, expected_version)
            self._apply(doc, actor, action, payload)
            self._save(conn, doc, action, uid, {**payload, "request_key": request_key})
            result = self._view(doc, uid, conn)
            self._remember(conn, pid, uid, request_key, fingerprint, result)
            return result

    def _apply(self, doc, actor, action, p):
        uid = actor["user_id"]
        if action in JOURNEY_COMMAND_FIELDS:
            from .journey import apply_journey_command
            apply_journey_command(doc, actor, action, p)
            return
        if action in COMMAND_FIELDS:
            from .taskbook_workflow import apply_taskbook_command
            apply_taskbook_command(doc,actor,action,p)
            return
        if action == "add_member":
            member_id = _text(p.get("user_id"), "成员ID", maximum=256)
            role = p.get("role")
            if role not in ("engineer", "reviewer", "viewer"):
                raise RdError(422, "成员职责不正确")
            if member_id == doc["project"]["owner_id"]:
                raise RdError(409, "不能修改负责人的职责")
            member = self._member(doc, member_id)
            values = {"user_id": member_id, "display_name": _text(p.get("display_name"), "成员姓名", maximum=256), "role": role}
            if member:
                member.update(values)
                for task in doc["tasks"]:
                    if (task["assignee_id"] == member_id and role != "engineer") or (task["reviewer_id"] == member_id and role != "reviewer"):
                        self._cancel_reviews(doc, task, "withdrawn", "成员职责已变化，需重新分派")
            else:
                doc["members"].append(values)
        elif action == "remove_member":
            member_id = _text(p.get("user_id"), "成员ID", maximum=256)
            if member_id == doc["project"]["owner_id"]:
                raise RdError(409, "不能移除项目负责人")
            member = self._member(doc, member_id)
            if not member:
                raise RdError(404, "成员不存在")
            doc["members"].remove(member)
            for task in doc["tasks"]:
                if member_id in {task["assignee_id"], task["reviewer_id"]}:
                    self._cancel_reviews(doc, task, "withdrawn", "任务成员已移除，需重新分派")
        elif action == "save_requirement":
            if p.get("clarification", "open") not in ("open", "resolved") or type(p.get("required", True)) is not bool:
                raise RdError(422, "需求澄清状态或必需标志不正确")
            values = {k: _text(p.get(k, ""), k, required=k in {"title", "content"}) for k in ("title", "content", "source", "acceptance")}
            values.update(clarification=p.get("clarification", "open"), required=p.get("required", True))
            if p.get("id"):
                row = self._find(doc, "requirements", p["id"])
                row["history"].append({k: copy.deepcopy(v) for k, v in row.items() if k != "history"})
                row.update(values)
                row["revision"] += 1
            else:
                doc["requirements"].append({"id": _id(), **values, "revision": 1, "history": []})
        elif action == "confirm_baseline":
            if not doc["requirements"] or any(r["required"] and (r["clarification"] != "resolved" or not r["source"] or not r["acceptance"]) for r in doc["requirements"]):
                raise RdError(409, "确认基线需要非空需求，且必需项已澄清并填写来源和验收要求")
            old_baseline=next((b for b in doc['baselines'] if b['id']==doc['project']['current_baseline_id']),None)
            baseline = {"id": _id(), "number": len(doc["baselines"]) + 1, "requirements": copy.deepcopy(doc["requirements"]), "confirmed_by": uid, "created_at": _now()}
            doc["baselines"].append(baseline)
            doc["project"]["current_baseline_id"] = baseline["id"]
            for task in doc["tasks"]:
                if task.get('kind') in {'taskbook','plan_item'}:
                    continue
                previous = task.get("previous_status", task["status"]) if task["status"] == "needs_revalidation" else task["status"]
                self._cancel_reviews(doc, task, "input_changed", "需求基线已变化")
                task.update(previous_status=previous, status="needs_revalidation")
            if old_baseline:
                old={r['id']:r for r in old_baseline['requirements']}
                new={r['id']:r for r in baseline['requirements']}
                changed=[{'kind':'requirement','requirement_id':rid,'old_revision':old.get(rid,{}).get('revision'),'new_revision':new.get(rid,{}).get('revision'),'baseline_id':baseline['id']} for rid in old.keys() | new.keys() if old.get(rid)!=new.get(rid)]
                from .taskbook_changes import assess_taskbook_impact
                assess_taskbook_impact(doc,changed)
        elif action == "create_task":
            if not doc["project"]["current_baseline_id"]:
                raise RdError(409, "请先确认需求基线")
            self._assignments(doc, p.get("assignee_id"), p.get("reviewer_id"))
            due = p.get("due_date") or None
            if due:
                try:
                    date.fromisoformat(due)
                except (TypeError, ValueError):
                    raise RdError(422, "计划日期须为YYYY-MM-DD") from None
            doc["tasks"].append({"id": _id(), "title": _text(p.get("title"), "任务名称", maximum=1000), "description": _text(p.get("description", ""), "任务说明", required=False), "assignee_id": p["assignee_id"], "reviewer_id": p["reviewer_id"], "due_date": due, "baseline_id": doc["project"]["current_baseline_id"], "status": "todo", "created_at": _now()})
        elif action in {"start_task", "reassign_task", "adopt_baseline", "submit_review"}:
            task = self._find(doc, "tasks", p.get("task_id"))
            if action == "reassign_task":
                self._assignments(doc, p.get("assignee_id"), p.get("reviewer_id"))
                if (task["assignee_id"], task["reviewer_id"]) != (p["assignee_id"], p["reviewer_id"]):
                    self._cancel_reviews(doc, task, "withdrawn", "任务分派已变化")
                    if task.get('kind')=='plan_item':
                        from .plan_handoff import reassign_handoff
                        reassign_handoff(doc,task,p['assignee_id'],p['reviewer_id'])
                    if task["status"] == "done":
                        task["status"] = "in_progress"
                task.update(assignee_id=p["assignee_id"], reviewer_id=p["reviewer_id"])
                if task.get('kind')=='taskbook':
                    from .taskbook_models import work_unit
                    for stage in work_unit(doc,task['id'])['stages']:
                        stage.update(assignee_id=p['assignee_id'],reviewer_id=p['reviewer_id'])
            elif action == "adopt_baseline":
                if task.get('kind') in {'taskbook','plan_item'}:
                    raise RdError(409,'原生工作包须先完成关联变更影响复核')
                if task["status"] != "needs_revalidation":
                    raise RdError(409, "任务无需采用新基线")
                task.update(baseline_id=doc["project"]["current_baseline_id"], status="todo" if task.get("previous_status") == "todo" else "in_progress")
                task.pop("previous_status", None)
            else:
                self._assignee(doc, task, uid)
                if action == "start_task":
                    if task.get('kind')=='plan_item':
                        from .plan_handoff import require_handoff
                        require_handoff(doc,task)
                    if task["status"] not in {"todo", "changes_requested"}:
                        raise RdError(409, "当前任务状态不能开始")
                    task["status"] = "in_progress"
                    task.setdefault('actual_start',_now())
                    if task.get('kind') == 'taskbook':
                        from .taskbook_models import work_unit
                        w=work_unit(doc,task['id'])
                        for stage in w['stages']:
                            if stage['node_code']==w['current_stage']:
                                stage.update(status='in_progress',started_at=stage.get('started_at') or _now())
                else:
                    self._submit(doc, task, uid, p.get("artifact_id"))
        elif action in {"decide_review", "withdraw_review"}:
            review = self._find(doc, "reviews", p.get("review_id"))
            task = self._find(doc, "tasks", review["task_id"])
            artifact = self._find(doc, "artifacts", review["artifact_id"])
            native = task.get('kind') == 'taskbook'
            native_inputs = task.get('kind') in {'taskbook','plan_item'}
            if review["status"] != "pending" or task["status"] != "in_review" or (not native_inputs and review["baseline_id"] != doc["project"]["current_baseline_id"]):
                raise RdError(409, "送审已结束或输入已变化，请刷新")
            if native_inputs:
                from .taskbook_models import native_validity
                native_validity(doc,task)
                if task.get('kind')=='plan_item':
                    from .plan_handoff import require_handoff
                    require_handoff(doc,task)
            if action == "withdraw_review":
                if uid not in {review["submitter_id"], doc["project"]["owner_id"]}:
                    raise RdError(403, "只有送审人或负责人可以撤回")
                status, task_status = "withdrawn", "in_progress"
            else:
                self._assignments(doc, task["assignee_id"], task["reviewer_id"])
                if uid != review["reviewer_id"] or uid != task["reviewer_id"] or uid in {review["submitter_id"], artifact["author_id"]}:
                    raise RdError(403, "只有当前指定的独立审核人可以审签")
                status = p.get("decision")
                if status not in ("approved", "rejected"):
                    raise RdError(422, "审签决定不正确")
                self._verify_file(artifact)
                self._verify_quality(artifact)
                if native:
                    from .taskbook_release import validate_review_snapshot
                    validate_review_snapshot(doc,review)
                task_status = "done" if status == "approved" else "changes_requested"
            comment = _text(p.get("comment", ""), "意见", required=status == "rejected")
            review.update(status=status, comment=comment, decided_by=uid, decided_at=_now())
            artifact["status"] = status
            task["status"] = task_status
            if task_status=='done':task['actual_end']=_now()
            if native:
                if status=='approved':
                    from .taskbook_release import freeze_taskbook_release
                    freeze_taskbook_release(doc,review)
                elif status=='rejected':
                    from .taskbook_models import work_unit
                    w=work_unit(doc,task['id']);w['current_stage']='ND13'
                    for stage in w['stages']:
                        stage.update(status='in_progress' if stage['node_code']=='ND13' else 'pending',completed_at=None)

    def _assignee(self, doc, task, uid):
        if uid != task["assignee_id"]:
            raise RdError(403, "只有当前任务执行人可以办理")
        member=self._member(doc,uid)
        if not member or member['role'] not in {'owner','engineer'}:
            raise RdError(403,'当前执行人已不具备工程办理职责')
        if task.get('kind') in {'taskbook','plan_item'}:
            from .taskbook_models import native_validity
            native_validity(doc,task)
            if task.get('kind')=='plan_item':
                from .plan_handoff import require_handoff
                require_handoff(doc,task)
        elif task["baseline_id"] != doc["project"]["current_baseline_id"] or task["status"] == "needs_revalidation":
            raise RdError(409, "任务必须先采用当前需求基线")

    def _submit(self, doc, task, uid, aid, *, native_snapshot=None):
        if task.get('kind') == 'taskbook' and native_snapshot is None:
            raise RdError(409,'任务书须在ND15通过固定包送审入口办理')
        if task["status"] not in {"in_progress", "changes_requested"} or any(r["task_id"] == task["id"] and r["status"] == "pending" for r in doc["reviews"]):
            raise RdError(409, "当前任务状态不能送审或已有待办审签")
        self._assignments(doc, task["assignee_id"], task["reviewer_id"])
        artifact = self._find(doc, "artifacts", aid)
        if artifact["task_id"] != task["id"] or artifact["baseline_id"] != task["baseline_id"] or artifact["author_id"] != uid:
            raise RdError(409, "成果须由当前执行人基于本任务当前基线编制")
        self._verify_quality(artifact)
        if artifact["status"] == "approved":
            raise RdError(409, "已批准成果不能再次送审，请创建新版本")
        self._verify_file(artifact)
        doc["reviews"].append({"id": _id(), "task_id": task["id"], "artifact_id": aid, "baseline_id": task["baseline_id"], "submitter_id": uid, "reviewer_id": task["reviewer_id"], "status": "pending", "comment": "", "created_at": _now(), "decided_at": None})
        if native_snapshot is not None:
            doc['reviews'][-1]['taskbook_snapshot']=copy.deepcopy(native_snapshot)
        task["status"] = "in_review"
        artifact["status"] = "in_review"

    def generation(self, jid):
        with self._connection() as conn:
            row = conn.execute("SELECT binding FROM generations WHERE jid=?", (jid,)).fetchone()
            return json.loads(row[0]) if row else None

    def bind_generation(self, pid, task_id, actor, jid, inputs):
        actor = _actor(actor)
        jid = _text(jid, "生成作业ID", maximum=256)
        with self._transaction() as conn:
            doc = self._load(conn, pid, actor["user_id"])
            self._permission(doc, actor["user_id"], "bind_generation")
            task = self._find(doc, "tasks", task_id)
            self._assignee(doc, task, actor["user_id"])
            if task.get('kind') == 'taskbook':
                raise RdError(409,'原生任务书须通过固定输入运行入口生成')
            if not isinstance(inputs, dict):
                raise RdError(422, "生成输入须为对象")
            if "rd_baseline_id" in inputs and inputs["rd_baseline_id"] != task["baseline_id"]:
                raise RdError(409, "上传资料核对时的基线已变化，请重新核对后生成")
            if task["status"] != "in_progress":
                raise RdError(409, "任务须开始办理后再发起生成")
            if conn.execute("SELECT 1 FROM generations WHERE jid=?", (jid,)).fetchone():
                raise RdError(409, "生成作业已绑定，不能重复绑定或变更基线")
            binding = {"jid": jid, "project_id": pid, "task_id": task_id, "baseline_id": task["baseline_id"], "actor_id": actor["user_id"], "created_at": _now(), "inputs": copy.deepcopy(inputs)}
            conn.execute("INSERT INTO generations VALUES (?,?,?)", (jid, pid, _json(binding)))
            doc["generations"].append(binding)
            self._save(conn, doc, "bind_generation", actor["user_id"], binding)
            return binding

    def authorize_generation(self, jid, actor_id, write=False):
        with self._connection() as conn:
            row = conn.execute("SELECT binding FROM generations WHERE jid=?", (jid,)).fetchone()
            if not row:
                return None
            binding = json.loads(row[0])
            doc = self._load(conn, binding["project_id"], actor_id)
            if write:
                self._permission(doc, actor_id, "bind_generation")
                task = self._find(doc, "tasks", binding["task_id"])
                self._assignee(doc, task, actor_id)
                if task.get('kind') == 'taskbook' and task['status'] not in {'in_progress','changes_requested'}:
                    raise RdError(409,'送审或已批准任务书不能修改，请先撤回或办理新版本')
                if binding["actor_id"] != actor_id:
                    raise RdError(403, "只有当前编制人可以修改生成作业")
                if binding["baseline_id"] != task["baseline_id"] or task["status"] not in {"in_progress", "changes_requested", "in_review"}:
                    raise RdError(409, "生成作业输入已变化或任务已结束")
            return binding

    def _verify_file(self, artifact):
        path = Path(artifact["file_ref"]).resolve()
        if not path.is_relative_to(self.artifact_root) or not path.is_file():
            raise RdError(404, "固定成果文件不存在")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != artifact["sha256"]:
            raise RdError(409, "成果文件完整性校验失败，禁止使用此版本")
        return path

    @staticmethod
    def _verify_quality(artifact):
        evidence = artifact.get("quality_evidence")
        checks = evidence.get("checks") if isinstance(evidence, dict) else None
        if (artifact["quality_status"] != "passed" or not isinstance(checks, dict)
                or evidence.get("revision_id") != artifact["source_revision_id"]
                or evidence.get("sha256") != artifact["sha256"]
                or checks.get("status") != "passed"
                or checks.get("revision_id") != artifact["source_revision_id"]
                or checks.get("sha256") != artifact["sha256"]
                or checks.get("scope") != "revision_deterministic"):
            raise RdError(409, "固定成果缺少对应修订和文件哈希的完整通过QA证据")

    def register_artifact(self, pid, task_id, actor, payload, expected_version, request_key):
        actor = _actor(actor)
        uid = actor["user_id"]
        # QA may be rerun for the same immutable bytes between network retries.
        # The public capture intent names jid/revision/version, while the first
        # successful transaction retains its original complete evidence snapshot.
        intent = {k: v for k, v in payload.items() if k != "quality_evidence"}
        fingerprint = _json({"action": "register_artifact", "task_id": task_id, "payload": intent, "expected_version": expected_version})
        with self._transaction() as conn:
            doc = self._load(conn, pid, uid)
            self._permission(doc, uid, "register_artifact")
            replay = self._replay(conn, pid, uid, request_key, fingerprint)
            if replay is not None:
                return replay
            self._version(doc, expected_version)
            task = self._find(doc, "tasks", task_id)
            self._assignee(doc, task, uid)
            if task.get('kind') == 'taskbook':
                raise RdError(409,'原生任务书须通过固定包送审入口登记成果')
            if task["status"] not in {"in_progress", "changes_requested"}:
                raise RdError(409, "请先撤回当前送审再登记新成果")
            binding_row = conn.execute("SELECT binding FROM generations WHERE jid=?", (payload.get("jid"),)).fetchone()
            binding = json.loads(binding_row[0]) if binding_row else None
            if not binding or any(binding[k] != v for k, v in (("project_id", pid), ("task_id", task_id), ("baseline_id", task["baseline_id"]), ("actor_id", uid))):
                raise RdError(409, "成果生成作业未绑定本任务当前基线和执行人")
            values = {k: _text(payload.get(k), k, maximum=4000) for k in ("jid", "source_revision_id", "filename", "sha256", "file_ref", "quality_status")}
            if values["quality_status"] not in {"passed", "failed", "unknown", "running"}:
                raise RdError(422, "质量状态不正确")
            if Path(values["filename"]).name != values["filename"] or any(c in values["filename"] for c in ("/", "\\")):
                raise RdError(422, "成果文件名不正确")
            values["file_ref"] = str(Path(values["file_ref"]).resolve())
            self._verify_file(values)
            evidence = payload.get("quality_evidence", {})
            if not isinstance(evidence, dict):
                raise RdError(422, "质量证据须为对象")
            values["quality_evidence"] = copy.deepcopy(evidence)
            if values["quality_status"] == "passed":
                self._verify_quality(values)
            artifact = {"id": _id(), "task_id": task_id, "baseline_id": task["baseline_id"], **values, "author_id": uid, "status": "draft", "created_at": _now()}
            doc["artifacts"].append(artifact)
            self._save(conn, doc, "register_artifact", uid, {"artifact_id": artifact["id"], "task_id": task_id, "request_key": request_key})
            result = self._view(doc, uid, conn)
            self._remember(conn, pid, uid, request_key, fingerprint, result)
            return result

    def artifact(self, pid, aid, actor_id, approved=False):
        with self._connection() as conn:
            doc = self._load(conn, pid, actor_id)
            artifact = self._find(doc, "artifacts", aid)
            if approved and not any(r["artifact_id"] == aid and r["status"] == "approved" for r in doc["reviews"]):
                raise RdError(409, "该固定成果尚未经过人工批准")
            self._verify_file(artifact)
            return copy.deepcopy(artifact)
