"""Explicit, isolated demonstration identities and persistent sample records.

No OA or model call is made here. Business examples use the real command and
approval service; their documents and QA snapshots are labelled mock data.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime, timezone

from filelock import FileLock

DEMO_COOKIE = "jtb_demo_user"
DEMO_LOGGED_OUT_COOKIE = "jtb_demo_logged_out"
DEMO_USERS = (
    {"userid": "demo-owner", "display_name": "陈明", "role": "owner"},
    {"userid": "demo-engineer", "display_name": "李工", "role": "engineer"},
    {"userid": "demo-reviewer", "display_name": "王工", "role": "reviewer"},
    {"userid": "demo-viewer", "display_name": "赵工", "role": "viewer"},
)

# Original migration values identify untouched automatic memberships only.
_RETIRED_WORKBENCH_USERS = (
    {"userid": "demo-technical", "display_name": "刘工 · 演示技术负责人", "role": "engineer", "workbench_role": "technical_lead"},
    {"userid": "demo-leader", "display_name": "张总 · 演示领导", "role": "viewer", "workbench_role": "leadership"},
    {"userid": "demo-knowledge", "display_name": "孙工 · 演示知识治理", "role": "viewer", "workbench_role": "knowledge"},
    {"userid": "demo-operations", "display_name": "周工 · 演示IT运营", "role": "viewer", "workbench_role": "operations"},
)


def demo_mode_enabled() -> bool:
    return os.environ.get("JTB_DEMO_MODE", "false").strip().lower() == "true"


def demo_user(user_id: str | None = None) -> dict:
    if user_id in {user['userid'] for user in _RETIRED_WORKBENCH_USERS}:
        user_id = 'demo-viewer'
    user = next((item for item in DEMO_USERS if item["userid"] == user_id), DEMO_USERS[0])
    return {**user, "name": user["display_name"], "source": "mock", "verified": True}


def _actor(user_id):
    user = demo_user(user_id)
    return {"user_id": user["userid"], "display_name": user["display_name"]}


def ensure_demo_workspace(store=None):
    """Initialize once at application startup; preserve subsequent user edits.

    A filesystem lock serializes initializers, and a durable SQLite marker avoids
    running seed commands after completion. Stable command keys allow a stopped
    initializer to resume; ordinary workspace requests never seed or acquire it.
    """
    if not demo_mode_enabled():
        return
    if store is None:
        from .runtime import get_store
        store = get_store()
    with FileLock(str(store.db_path) + ".demo-seed.lock", timeout=60):
        with sqlite3.connect(store.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS demo_bootstrap (name TEXT PRIMARY KEY, completed_at TEXT NOT NULL)")
            initialized = conn.execute("SELECT 1 FROM demo_bootstrap WHERE name='workspace-v1'").fetchone()
        if not initialized:
            _seed(store)
            with sqlite3.connect(store.db_path) as conn:
                conn.execute("INSERT INTO demo_bootstrap VALUES (?,?)", ("workspace-v1", datetime.now(timezone.utc).isoformat()))
        _remove_unused_workbench_members(store)


def _remove_unused_workbench_members(store):
    """Undo only proven, untouched, unused automatic demo memberships."""
    import json

    def references(value, user_id):
        if isinstance(value, dict):
            return any(references(item, user_id) for item in value.values())
        if isinstance(value, list):
            return any(references(item, user_id) for item in value)
        return value == user_id

    marker = 'workspace-role-scope-cleanup-v1'
    with store._transaction() as conn:
        if conn.execute('SELECT 1 FROM demo_bootstrap WHERE name=?', (marker,)).fetchone():
            return
        drafts = [json.loads(row[0]) for row in conn.execute('SELECT scope FROM taskbook_drafts')]
        for row in conn.execute('SELECT document FROM projects').fetchall():
            doc = json.loads(row[0])
            if doc['project']['owner_id'] != 'demo-owner' or doc['project']['code'] not in {'RD-DEMO-001', 'RD-DEMO-002', 'RD-DEMO-003'}:
                continue
            evidence = [event for event in doc['events'] if event['action'] == 'migrate_demo_workbench_members'
                        and event['actor_id'] == 'demo-owner' and event.get('detail', {}).get('source') == 'mock']
            if not evidence:
                continue
            pid = doc['project']['id']
            external = [json.loads(row[0]) for row in conn.execute('SELECT binding FROM generations WHERE project_id=?', (pid,))]
            external += [json.loads(row[0]) for row in conn.execute('SELECT document FROM taskbook_runs WHERE project_id=?', (pid,))]
            external += [scope for scope in drafts if isinstance(scope, list) and scope and scope[0] == pid]
            business = {key: value for key, value in doc.items() if key not in {'members', 'events'}}
            business['events'] = [event for event in doc['events'] if event not in evidence]
            removed = []
            for user in _RETIRED_WORKBENCH_USERS:
                uid = user['userid']
                if not any(uid in event['detail'].get('added_user_ids', []) for event in evidence):
                    continue
                expected = {'user_id': uid, **{key: user[key] for key in ('display_name', 'role', 'workbench_role')}}
                member = next((item for item in doc['members'] if item['user_id'] == uid), None)
                if member != expected or references(business, uid) or references(external, uid):
                    continue
                doc['members'].remove(member)
                removed.append(uid)
            if removed:
                store._save(conn, doc, 'remove_unused_demo_workbench_members', 'demo-owner', {'removed_user_ids': removed, 'source': 'mock'})
        conn.execute('INSERT INTO demo_bootstrap VALUES (?,?)', (marker, datetime.now(timezone.utc).isoformat()))


def _seed(store):
    owner, engineer, reviewer = (_actor(uid) for uid in ("demo-owner", "demo-engineer", "demo-reviewer"))
    specs = (
        ("RD-DEMO-001", "航空圆形连接器可靠性升级", "华东航空客户", "耐环境圆形连接器", "done", "in_progress"),
        ("RD-DEMO-002", "新能源高压连接器开发", "新能源整车客户", "高压大电流连接器", "in_review", "todo"),
        ("RD-DEMO-003", "高速背板连接器国产化", "通信设备客户", "高速背板连接器", "changes_requested", "todo"),
    )
    for code, name, customer, product, first_status, second_status in specs:
        prefix = "demo-v1:" + code
        d = store.create_project(owner, {"code": code, "name": name, "customer": customer, "product": product}, prefix + ":project")
        def step(detail, action, payload, tag, actor=owner):
            return store.execute(detail["project"]["id"], actor, action, payload, detail["project"]["version"], prefix + ":" + tag)
        for user in DEMO_USERS[1:4]:
            d = step(d, "add_member", {"user_id": user["userid"], "display_name": user["display_name"], "role": user["role"]}, "member:" + user["userid"])
        for index, (title, content, acceptance) in enumerate((
            ("环境与可靠性要求", "按客户演示技术协议核对温度、振动和密封指标；所有数值待真实项目确认。", "形成环境试验计划与指标核对表"),
            ("接口与装配要求", "核对演示接口定义及装配空间，保留差异记录。", "完成接口清单与设计评审记录"),
            ("交付与追溯要求", "研制任务书需包含资料来源、需求基线和审签记录。", "固定成果与需求及修订记录可追溯"),
        )):
            d = step(d, "save_requirement", {"title": title, "content": content, "source": "演示数据 · 客户技术协议示例", "acceptance": acceptance, "clarification": "resolved", "required": True}, "requirement:" + str(index))
        d = step(d, "confirm_baseline", {}, "baseline")
        for index, (title, status) in enumerate((("研制任务书编制与审签", first_status), ("验证计划及资料核对", second_status))):
            d = step(d, "create_task", {"title": title, "description": "演示数据 · 用于查看任务办理与独立审签流程，不代表真实工程结论。", "assignee_id": engineer["user_id"], "reviewer_id": reviewer["user_id"], "due_date": "2026-11-12" if index else "2026-11-05"}, "task:" + str(index))
            task = d["tasks"][-1]
            tag = "task:" + str(index)
            if status == "todo":
                continue
            d = step(d, "start_task", {"task_id": task["id"]}, tag + ":start", engineer)
            if status == "in_progress":
                continue
            jid = hashlib.sha256((prefix + tag).encode()).hexdigest()[:10]
            binding = store.generation(jid)
            if binding is None:
                store.bind_generation(d["project"]["id"], task["id"], engineer, jid, {"source": "mock", "demo": True, "note": "演示数据，未调用模型生成", "rd_baseline_id": d["project"]["current_baseline_id"]})
            # Binding consumes exactly one project version. Reconstructing this
            # expected value also makes an interrupted seed replay deterministic.
            expected_version = d["project"]["version"] + 1
            path = store.artifact_root / "demo_seed" / (code + ".docx")
            if not path.exists():
                from docx import Document
                path.parent.mkdir(parents=True, exist_ok=True)
                document = Document()
                document.add_heading("演示数据 · 研制任务书样例", 0)
                document.add_paragraph(name)
                document.add_paragraph("本文件由本地演示初始化创建，未调用模型或外部工程服务。所有内容及QA证据均为mock数据，不作为真实设计、试验或交付依据。")
                document.add_heading("需求与工作范围", level=1)
                document.add_paragraph("核对接口、环境条件及交付清单，展示固定成果与独立审签的业务关系。")
                document.save(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            revision_id = "demo-fixed-r1"
            d = store.register_artifact(d["project"]["id"], task["id"], engineer, {
                "jid": jid, "source_revision_id": revision_id, "filename": code + "-演示数据.docx", "sha256": digest, "file_ref": str(path), "quality_status": "passed",
                "quality_evidence": {"source": "mock", "demo": True, "note": "演示QA证据，未运行真实生成或工程验证", "revision_id": revision_id, "sha256": digest,
                                     "checks": {"source": "mock", "status": "passed", "revision_id": revision_id, "sha256": digest, "scope": "revision_deterministic", "findings": [], "note": "演示数据"}, "rules_fingerprint": "mock-demo-rules-v1"},
            }, expected_version, prefix + ":" + tag + ":artifact")
            d = step(d, "submit_review", {"task_id": task["id"], "artifact_id": d["artifacts"][-1]["id"]}, tag + ":submit", engineer)
            if status != "in_review":
                d = step(d, "decide_review", {"review_id": d["reviews"][-1]["id"], "decision": "approved" if status == "done" else "rejected", "comment": "演示数据 · 独立审核流程示例" if status == "done" else "演示数据 · 请补充接口核对与验证条件。"}, tag + ":decision", reviewer)
