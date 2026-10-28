"""Import labelled taskbook samples into the real project workflow, once.

This initializer never calls the generation worker or an external service.
Samples are explicit demo_sample runs, with mock QA evidence; normal API users
cannot inject either a completed run or a QA result.
"""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from pathlib import Path

from filelock import FileLock

from .demo import _actor, demo_mode_enabled, ensure_demo_workspace
from .store import _json, _now

MARKER = "taskbook-native-v1"
CASES = (
    ("RD-DEMO-001", "inputs", "研制任务书 · 输入待确认"),
    ("RD-DEMO-001", "draft", "研制任务书 · 编制与核验"),
    ("RD-DEMO-002", "review", "研制任务书 · 待独立评审"),
    ("RD-DEMO-002", "returned", "研制任务书 · 退回修订"),
    ("RD-DEMO-003", "approved", "研制任务书 · 已批准待发布"),
    ("RD-DEMO-003", "published", "研制任务书 · 计划交接"),
)
CHANGE_MARKER = 'taskbook-native-change-v1'
CHANGE_CASES = (("RD-DEMO-003", "change", "研制任务书 · 变更待复核"),)
SEED_GROUPS = ((MARKER, CASES), (CHANGE_MARKER, CHANGE_CASES))


def ensure_native_demo_workspace(store=None):
    if not demo_mode_enabled():
        return
    if store is None:
        from .runtime import get_store
        store = get_store()
    ensure_demo_workspace(store)
    with FileLock(str(store.db_path) + ".native-demo.lock", timeout=60):
        # Each extension has its own durable marker. A database that already
        # contains v1 skips those six cases, including all later user edits.
        for marker, cases in SEED_GROUPS:
            with sqlite3.connect(store.db_path) as conn:
                if conn.execute("SELECT 1 FROM demo_bootstrap WHERE name=?", (marker,)).fetchone():
                    continue
            for code, case, title in cases:
                tag = marker + ":" + case
                with sqlite3.connect(store.db_path) as conn:
                    complete = conn.execute("SELECT 1 FROM demo_bootstrap WHERE name=?", (tag,)).fetchone()
                if complete:
                    continue
                _seed_case(store, code, case, title, marker=marker)
                with sqlite3.connect(store.db_path) as conn:
                    conn.execute("INSERT INTO demo_bootstrap VALUES (?,?)", (tag, _now()))
            with sqlite3.connect(store.db_path) as conn:
                conn.execute("INSERT INTO demo_bootstrap VALUES (?,?)", (marker, _now()))


def _sample_document():
    from docx import Document
    from .taskbook_coverage import load_mapping
    document = Document()
    document.add_heading("演示预置文档 · 滤波连接器研制任务书", 0)
    document.add_paragraph("本文件是本地预置样例，未调用模型。所有技术内容及核验依据仅用于演示流程，不作为实际设计或试验依据。")
    sections = load_mapping()["sections"]
    for index, section in enumerate(sections, 1):
        document.add_heading(f"{index} {section['label']}", 1)
        document.add_paragraph(
            f"演示约定：{section['label']}由项目责任人按样例技术协议核对；"
            "采用当前需求固定版，保留本段来源及相应验证记录。真实数值和制度要求由实际项目确认。"
        )
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def _seed_case(store, code, case, title, *, marker=MARKER):
    from src.controller import taskbook_controller as jobs, review_controller
    from .taskbook_inputs import add_project_source, create_input_package
    from .taskbook_models import work_unit
    from .taskbook_workflow import select_taskbook_revision
    from .taskbook_coverage import check_taskbook_coverage, load_mapping
    from .taskbook_release import submit_taskbook_review
    from .integration import prepare_artifact_payload
    from jonhon_taskbook.review_document import document_projection

    owner, engineer, reviewer = (_actor(user) for user in ("demo-owner", "demo-engineer", "demo-reviewer"))
    listing = store.list_projects(owner["user_id"], q=code)
    project = next(p for p in listing["items"] if p["code"] == code)
    pid = project["id"]
    prefix = marker + ":" + case

    def current():
        return store.detail(pid, owner["user_id"])

    def command(action, payload, tag, actor=owner):
        return store.execute(pid, actor, action, payload, current()["project"]["version"], prefix + ":" + tag)

    detail = current()
    approval_ref = "演示批准记录 / " + prefix
    adoption = next((a for a in detail["development_adoptions"] if a["approval_ref"] == approval_ref), None)
    if adoption is None:
        detail = command("adopt_development", {
            "route": "modified", "approval_ref": approval_ref,
            "scope": "演示范围：滤波连接器接口、环境和验证资料核对；不表示企业真实批准。",
            "process_template_ref": {"id": "WF-A8", "version": "1.0"},
            "provenance": "mock",
        }, "adoption")
        adoption = detail["development_adoptions"][-1]
    unit = next((w for w in detail["taskbook_work_units"] if w["adoption_id"] == adoption["id"]), None)
    if unit is None:
        detail = command("create_taskbook", {
            "adoption_id": adoption["id"], "title": title,
            "description": "演示样例 · 输入、编制、验证策划、独立评审和下游接收。",
            "assignee_id": engineer["user_id"], "reviewer_id": reviewer["user_id"], "due_date": "2026-11-12",
        }, "create")
        unit = detail["taskbook_work_units"][-1]
    tid = unit["task_id"]
    task = next(t for t in current()["tasks"] if t["id"] == tid)
    if task["status"] == "todo":
        command("start_task", {"task_id": tid}, "start", engineer)
    if case == "inputs":
        return

    # A stable input name identifies the imported version across interrupted
    # initialization. Existing source bytes are never overwritten by a restart.
    data = _sample_document()
    refs = []
    for role, label in (("tech", "技术协议"), ("spec", "产品规范")):
        name = prefix + "-" + label + ".docx"
        source = next((s for s in current()["project_sources"] if s["name"] == name and s["role"] == role), None)
        if source is None:
            source = add_project_source(store, pid, engineer, role, name, data, current()["project"]["version"], prefix + ":source:" + role, "mock")["source"]
        refs.append({"source_id": source["source_id"], "version": source["version"]})
    detail = current()
    unit = work_unit(detail, tid)
    if not unit["input_package_id"]:
        create_input_package(store, pid, tid, engineer, {
            "source_refs": refs, "confirmed": True,
            "parameters": {"product_type": "filter_connector", "product_domain": "military", "development_process": "改型I", "cover_phase": "F", "organization_scope": "non_central_research", "use_llm": True},
            "model_selection": {"provider": "demo", "name": "演示预置资料（未调用模型）", "id": "demo-not-configured"},
        }, detail["project"]["version"], prefix + ":package")
    with store._connection() as conn:
        doc = store._load(conn, pid, owner["user_id"])
        unit = work_unit(doc, tid)
        package = store._find(doc, "taskbook_input_packages", unit["input_package_id"])
    run_id = hashlib.sha256((prefix + ":run").encode()).hexdigest()[:32]
    jid = run_id[:10]
    output = jobs._STATE.output_dir / "native-demo" / (jid + ".docx")
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists():
        output.write_bytes(data)
    reviews = review_controller.get_store()
    bundle = reviews.ensure_review(jid, {"status": "done", "result": {"out": str(output), "meta": {"demo": True}}}, {
        "output_dir": jobs._STATE.output_dir, "upload_dir": jobs._STATE.upload_dir,
    })
    # ReviewStore needs a source document to import; no job is registered. Its
    # provenance says this is a preloaded sample, never an actual completed run.
    bundle["generation_status"] = "demo_sample"
    bundle["generation_summary"] = {"source": "mock", "note": "演示预置资料，未调用生成或工程核验服务"}
    revision = next(r for r in bundle["revisions"] if r["id"] == "baseline")
    revision.update(actor="演示样例导入", reason="预置文档，未调用模型")
    revision["checks"] = {"source": "mock", "status": "passed", "revision_id": "baseline", "sha256": revision["sha256"], "scope": "revision_deterministic", "checked_at": _now(), "issues": [], "note": "仅用于演示的核验记录"}
    reviews._write(jid, bundle)
    with store._transaction() as conn:
        existing = conn.execute("SELECT 1 FROM taskbook_runs WHERE run_id=?", (run_id,)).fetchone()
        if not existing:
            doc = store._load(conn, pid, owner["user_id"])
            run = {"run_id": run_id, "jid": jid, "project_id": pid, "task_id": tid, "package_id": package["id"], "parent_run_id": None, "attempt": 1, "status": "demo_sample", "provenance": "mock", "execution_kind": "preloaded_document", "request_key": prefix, "created_at": _now(), "actor_id": engineer["user_id"], "runtime_fingerprint": package["runtime_fingerprint"], "result_ref": {"jid": jid}}
            binding = {"jid": jid, "project_id": pid, "task_id": tid, "baseline_id": package["baseline_id"], "actor_id": engineer["user_id"], "created_at": _now(), "inputs": {"package_id": package["id"], "fingerprint": package["fingerprint"], "rd_baseline_id": package["baseline_id"], "run_id": run_id, "demo": True, "source": "mock"}}
            conn.execute("INSERT INTO taskbook_runs VALUES (?,?,?,?)", (run_id, pid, tid, _json(run)))
            conn.execute("INSERT INTO generations VALUES (?,?,?)", (jid, pid, _json(binding)))
            doc["generations"].append(binding)
            store._save(conn, doc, "import_demo_taskbook", engineer["user_id"], {"task_id": tid, "run_id": run_id, "source": "mock"})
    if not work_unit(current(), tid)["selected_revision_id"]:
        select_taskbook_revision(store, pid, tid, engineer, run_id, "baseline", current()["project"]["version"], prefix + ":select", revision=revision)
    if case == "draft":
        return

    projection = document_projection(reviews.revision_path(jid, "baseline"), revision_id="baseline")
    body = [b for b in projection["blocks"] if b["kind"] == "paragraph" and not b.get("heading_level") and b.get("text", "").startswith("演示约定")]
    evidence = package["source_refs"][0]
    decisions = [{
        "section_key": section["section_key"], "status": "evidenced", "output_anchor": body[i]["id"],
        "evidence_ref": evidence["source_id"] + "@" + str(evidence["version"]),
        "requirement_ref": package["requirement_ids"][0], "checked_by": engineer["user_id"], "reason": "演示资料：对应样例段落与输入固定版，仅用于演示办理。",
    } for i, section in enumerate(load_mapping()["sections"])]
    coverage = next((c for c in current()["taskbook_coverages"] if c["task_id"] == tid), None)
    if coverage is None:
        coverage = check_taskbook_coverage(package, revision, projection, load_mapping(), decisions)
        coverage.update(task_id=tid, run_id=run_id, provenance="mock")
        with store._transaction() as conn:
            doc = store._load(conn, pid, engineer["user_id"])
            doc["taskbook_coverages"].append(coverage)
            store._save(conn, doc, "import_demo_coverage", engineer["user_id"], {"coverage_id": coverage["id"], "source": "mock"})
    unit = work_unit(current(), tid)
    if unit["current_stage"] == "ND13":
        command("advance_taskbook_stage", {"task_id": tid, "target_stage": "ND14"}, "nd14", engineer)
    draft = next((d for d in current()["taskbook_wbs_drafts"] if d["task_id"] == tid), None)
    if draft is None:
        items = [{
            "id": "design-input" if i == 0 else "verification", "title": name, "kind": kind,
            "assignee_id": engineer["user_id"], "reviewer_id": reviewer["user_id"],
            "requirement_ids": package["requirement_ids"], "output_anchor": body[3 if i == 0 else 12]["id"],
            "deliverable": "演示 · " + name + "记录", "acceptance": "核对固定输入与审签版本并保留证据",
            "acceptance_owner_id": reviewer["user_id"], "verification_method": "文档及接口逐项核对",
            "predecessor_ids": [], "planned_start": "2026-11-02", "planned_end": "2026-11-12",
        } for i, (name, kind) in enumerate((("方案设计输入确认", "design"), ("环境验证策划", "verification")))]
        command("save_wbs", {"task_id": tid, "expected_wbs_revision": 0, "source_revision_id": "baseline", "items": items}, "wbs", engineer)
        draft = next(d for d in current()["taskbook_wbs_drafts"] if d["task_id"] == tid)
    if work_unit(current(), tid)["current_stage"] == "ND14":
        command("advance_taskbook_stage", {"task_id": tid, "target_stage": "ND15"}, "nd15", engineer)
    review = next((r for r in current()["reviews"] if r["task_id"] == tid), None)
    if review is None:
        artifact = prepare_artifact_payload(store, jid, "baseline")
        artifact["quality_evidence"].update(source="mock", note="演示预置文件与模拟核验记录")
        detail = submit_taskbook_review(store, pid, tid, engineer, {
            "run_id": run_id, "revision_id": "baseline", "coverage_id": coverage["id"], "wbs_revision": draft["revision"], "artifact_payload": artifact,
        }, current()["project"]["version"], prefix + ":submit")
        review = detail["reviews"][-1]
    if case == "review":
        return
    if review["status"] == "pending":
        command("decide_review", {"review_id": review["id"], "decision": "rejected" if case == "returned" else "approved", "comment": "演示退回：请复核接口来源和验证安排。" if case == "returned" else "演示批准：仅用于本地业务流程样例，不代表企业真实批准。"}, "decision", reviewer)
    if case not in {"published", "change"}:
        return
    detail = current()
    release = next(r for r in detail["taskbook_releases"] if r["task_id"] == tid)
    if not any(p["release_id"] == release["id"] for p in detail["plan_releases"]):
        command("publish_plan", {"task_id": tid, "release_id": release["id"]}, "publish")
    handoffs = [h for h in current()["handoffs"] if h["source_task_id"] == tid]
    first = handoffs[0]
    if first["status"] == "pending":
        command("accept_handoff", {"handoff_id": first["id"]}, "accept", engineer)
    task = next(t for t in current()["tasks"] if t["id"] == first["task_id"])
    if task["status"] == "todo":
        command("start_task", {"task_id": task["id"]}, "start-child", engineer)
    if case == 'change':
        source = next(s for s in package['source_refs'] if s['role']=='tech')
        # Same logical source, new immutable bytes: the real source command
        # computes impact for this package and its published uses only. Reuse
        # an existing replacement on interrupted initialization.
        replacements=[s for s in current()['project_sources'] if s['source_id']==source['source_id'] and s['version']>source['version']]
        if not replacements:
            from docx import Document
            changed=Document(io.BytesIO(Path(source['file_ref']).read_bytes()))
            changed.add_heading('演示变更记录 · 待影响复核',1)
            changed.add_paragraph('演示技术协议新增接口核对及验证证据要求；本次仅登记资料新版本，原批准包与已接收交接保留，须由负责人复核关联用途。')
            changed_bytes=io.BytesIO();changed.save(changed_bytes)
            add_project_source(store,pid,engineer,'tech',source['name'],changed_bytes.getvalue(),current()['project']['version'],prefix+':source-change','mock')
