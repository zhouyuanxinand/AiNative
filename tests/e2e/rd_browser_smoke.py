"""Manual real-server R&D browser smoke; no OA or model service is called.

Run from basic-service/app with ../.venv/Scripts/python.exe tests/rd_browser_smoke.py.
Only the enterprise token verifier is replaced, within this test process. All
domain commands, session cookies, revision checks and downloads use real code.
The completed generated DOCX is an explicit local fixture, not model evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from dataclasses import replace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_support import APP, browser_options
sys.path[:0] = [str(APP), str(APP / "src/service")]
EVIDENCE = APP / "runtime/rd-browser"


def assert_ok(response):
    assert response.ok, f"{response.status}: {response.text()}"
    return response.json()


def choose(page, label, text):
    page.get_by_label(label, exact=True).click()
    page.get_by_role("option", name=text, exact=True).click()


def confirm(page, label):
    dialog = page.get_by_role("dialog", name=label, exact=True)
    dialog.wait_for()
    dialog.get_by_role("button", name=label, exact=True).click()
    dialog.wait_for(state="hidden")


def login(browser, base, user):
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    page = context.new_page()
    page.goto(f"{base}/taskbook?userid={user}&token=synthetic-rd-browser-only")
    page.wait_for_url(base + "/taskbook")
    identity = assert_ok(context.request.get(base + "/api/current-user"))
    assert identity["authenticated"] and identity["user"]["userid"] == user
    return context, page


def seed_completed_fixture(store, pid, task, jobs):
    """Prepare a deterministic document, archived input rules and real QA inputs."""
    from docx import Document

    jid = "20261028ab"
    store.bind_generation(pid, task["id"], {"user_id": "engineer", "display_name": "工程师"}, jid,
                          {"confirmed": True, "note": "本地确定性浏览器夹具，不调用模型"})
    jobdir = jobs._STATE.upload_dir / jid
    jobdir.mkdir()
    document = Document()
    document.add_paragraph("固定需求")
    table = document.add_table(rows=2, cols=4)
    for cell, text in zip(table.rows[0].cells, ["项目", "用户要求", "拟采用", "依据"]):
        cell.text = text
    for cell, text in zip(table.rows[1].cells, ["接触电阻", "5mΩ", "5mΩ", "客户协议"]):
        cell.text = text
    output = jobs._STATE.output_dir / "browser-fixture.docx"
    document.save(output)
    replay = {}
    for key, value in {"profile": "{}", "rule_qa_gate": "block_if: {}\nwarn_if: {}\n"}.items():
        path = jobdir / (key + ".yaml")
        path.write_text(value, encoding="utf-8")
        replay[key] = {"name": path.name}
    template = jobdir / "template.docx"
    template.write_bytes(output.read_bytes())
    replay["effective_template"] = {"name": template.name}
    output.with_suffix(".coverage_ledger.json").write_text(json.dumps({"source_file": "tech.docx", "blocks": [
        {"block_id": "s1", "raw_text": "固定需求", "summary": "固定需求", "source_section": "技术要求", "block_type": "paragraph", "covered": True}]}), encoding="utf-8")
    output.with_suffix(".indicator_audit.json").write_text(json.dumps({"comparison_decisions": [
        {"indicator_name": "接触电阻", "user_requirement": "5mΩ", "adopted_requirement": "5mΩ", "basis": "客户协议"}]}), encoding="utf-8")
    jobs._STATE.jobs[jid] = {"jid": jid, "status": "done", "created_ts": time.time(),
        "result": {"out": str(output), "meta": {"qa_ok": True}, "delivery_status": "approved"}, "replay": {"files": replay}}
    return jid


def run():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rd-browser-") as directory:
        temporary = Path(directory)
        os.environ.update({"JTB_DEMO_MODE": "false", "JTB_AUTH_ENABLED": "true", "JTB_AUTH_APP_ID": "9192",
            "JTB_AUTH_PLATFORM_BASE_URL": "http://127.0.0.1:1", "JTB_AUTH_PUBLIC_URL": "",
            "JTB_AUTH_SETTINGS_DB": str(temporary / "auth.sqlite3"),
            "JTB_RD_DB": str(temporary / "rd.sqlite3"), "JTB_RD_ARTIFACTS": str(temporary / "artifacts"),
            "JTB_UPLOAD_DIR": str(temporary / "uploads"), "JTB_OUTPUT_DIR": str(temporary / "output"),
            "JTB_TEMPLATE_CANDIDATE_DIR": str(temporary / "candidates"),
            "JTB_TEMPLATE_RELEASE_AUDIT_DIR": str(temporary / "releases"), "JTB_ALLOW_LOCAL_PATHS": "0"})
        from src.common.platform_auth import PlatformTokenVerifier
        async def verify(_self, userid, token, appid):
            assert appid == 9192 and token == "synthetic-rd-browser-only"
            if userid not in {"owner", "engineer", "reviewer", "outsider"}:
                return None
            return {"code": 0, "data": {"sn": {"owner": "项目负责人", "engineer": "工程师", "reviewer": "独立审核人", "outsider": "非项目成员"}[userid]}}
        original = PlatformTokenVerifier.__call__
        PlatformTokenVerifier.__call__ = verify
        from src.utils.config_loader import load_config
        config = replace(load_config(), logs_dir=temporary / "logs")
        from src.application.factory import create_app
        from src.controller import taskbook_controller as jobs
        from src.service.rd_platform.runtime import get_store
        app = create_app(config)
        jobs.register(app, config)
        store = get_store()
        import uvicorn
        from playwright.sync_api import sync_playwright
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(.1)
        assert server.started, "Loopback server did not start"
        proof = {"base": base, "identity": "Synthetic verifier in test process; real HTTP-only app cookies", "model": "Not called; deterministic DOCX fixture"}
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(**browser_options())
                owner, page = login(browser, base, "owner")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base + "/rd")
                page.get_by_role("heading", name="研发项目", exact=True).wait_for()
                page.get_by_role("button", name="新建项目", exact=True).click()
                page.get_by_label("项目名称 *", exact=True).fill("连接器研发浏览器验收")
                page.get_by_label("客户 *", exact=True).fill("浏览器测试客户")
                page.get_by_label("产品 *", exact=True).fill("J599 连接器")
                page.get_by_role("button", name="创建项目", exact=True).click()
                page.get_by_role("link", name="进入项目工作区", exact=True).click()
                page.get_by_role("heading", name="连接器研发浏览器验收", exact=True).wait_for()
                print("UI project created", flush=True)
                pid = page.url.split("/rd/")[1].split("?")[0]
                page.get_by_role("button", name="项目成员", exact=True).click()
                for userid, name, role in [("engineer", "工程师", "工程师"), ("reviewer", "独立审核人", "审核人")]:
                    page.get_by_label("企业用户 ID *", exact=True).fill(userid)
                    page.get_by_label("显示名称 *", exact=True).fill(name)
                    choose(page, "项目职责", role)
                    page.get_by_role("button", name="保存成员", exact=True).click()
                    confirm(page, "保存成员")
                    page.get_by_role("cell", name=userid, exact=True).wait_for()
                print("UI members saved", flush=True)
                page.get_by_role("button", name="需求与基线", exact=True).click()
                page.get_by_role("button", name="新增需求", exact=True).click()
                page.get_by_label("需求标题 *", exact=True).fill("接触电阻要求")
                page.get_by_label("需求内容 *", exact=True).fill("固定需求：接触电阻不大于5mΩ")
                page.get_by_label("原始来源", exact=True).fill("客户技术协议 2026-10-28")
                page.get_by_label("验收描述", exact=True).fill("按客户协议检查接触电阻5mΩ")
                choose(page, "澄清状态", "已澄清")
                page.get_by_role("button", name="保存需求", exact=True).click()
                page.get_by_role("heading", name="接触电阻要求", exact=True).wait_for()
                page.get_by_role("button", name="确认需求基线", exact=True).click()
                confirm(page, "确认需求基线")
                page.get_by_text("当前需求基线 B1", exact=True).wait_for()
                page.get_by_role("button", name="研发任务", exact=True).click()
                page.get_by_role("button", name="新建任务", exact=True).click()
                page.get_by_label("任务名称 *", exact=True).fill("编制连接器研制任务书")
                choose(page, "执行人 *", "工程师（engineer）")
                choose(page, "审核人 *", "独立审核人（reviewer）")
                page.get_by_role("button", name="创建任务", exact=True).click()
                page.get_by_role("heading", name="编制连接器研制任务书", exact=True).wait_for()
                page.screenshot(path=str(EVIDENCE / "owner-tasks-desktop.png"), full_page=True)
                print("UI requirement/baseline/task created", flush=True)
                detail = assert_ok(owner.request.get(f"{base}/api/rd/projects/{pid}"))
                task = detail["tasks"][0]
                engineer, work = login(browser, base, "engineer")
                work.goto(f"{base}/rd/{pid}?tab=tasks")
                work.get_by_role("button", name="开始任务", exact=True).click()
                # An unrelated running record must not be restored into this task.
                unrelated_reads = []
                work.on("request", lambda request: unrelated_reads.append(request.url) if "/api/status/other-task-job" in request.url else None)
                work.evaluate("""localStorage.setItem('jtb.controlled.ui.runningJob.v1', JSON.stringify({
                    jid: 'other-task-job', rd_context: {project_id: 'another-project', task_id: 'another-task'}
                }))""")
                work.get_by_role("link", name="生成任务书", exact=True).click()
                checkbox = work.get_by_label("我已核对本次上传资料和业务选择，确认其对应以上需求基线。", exact=True)
                checkbox.wait_for()
                checkbox.check()
                assert checkbox.is_checked()
                assert not unrelated_reads, "Another task's job was read in this generation context"
                proof["cross_task_restore_blocked"] = True
                work.screenshot(path=str(EVIDENCE / "generation-context-desktop.png"), full_page=True)
                proof["generation_context_confirmed"] = True
                jid = seed_completed_fixture(store, pid, task, jobs)
                checks = assert_ok(engineer.request.post(f"{base}/api/review/{jid}/revisions/baseline/check"))
                assert checks["status"] == "passed", checks
                work.goto(f"{base}/rd/{pid}?tab=tasks")
                work.get_by_text("生成作业与成果登记（1）", exact=True).click()
                work.get_by_label("关联生成作业", exact=True).click()
                work.get_by_role("option").filter(has_text=jid).click()
                work.get_by_label("文档修订 *", exact=True).click()
                work.get_by_role("option").filter(has_text="baseline ·").click()
                work.get_by_role("button", name="登记固定成果", exact=True).click()
                work.get_by_role("button", name="成果与审签", exact=True).click()
                work.get_by_role("button", name="提交审签", exact=True).click()
                confirm(work, "提交审签")
                work.get_by_role("heading", name="审签记录", exact=True).wait_for()
                detail = assert_ok(engineer.request.get(f"{base}/api/rd/projects/{pid}"))
                assert detail["tasks"][0]["status"] == "in_review"
                assert work.get_by_role("button", name="批准固定成果", exact=True).count() == 0
                reviewer, review = login(browser, base, "reviewer")
                review.goto(f"{base}/rd/{pid}?tab=artifacts")
                review.get_by_label("审签意见（退回必填）", exact=True).fill("已核对固定文件、来源、当前基线与自动检查。")
                review.get_by_role("button", name="批准固定成果", exact=True).click()
                confirm(review, "批准固定成果")
                review.get_by_role("link", name="下载批准版", exact=True).wait_for()
                detail = assert_ok(reviewer.request.get(f"{base}/api/rd/projects/{pid}"))
                assert detail["tasks"][0]["status"] == "done"
                artifact = detail["artifacts"][0]
                download = f"{base}/api/rd/projects/{pid}/artifacts/{artifact['id']}/download?approved=true"
                response = reviewer.request.get(download)
                assert response.ok
                digest = hashlib.sha256(response.body()).hexdigest()
                assert digest == artifact["sha256"]
                review.screenshot(path=str(EVIDENCE / "approved-desktop.png"), full_page=True)
                review.set_viewport_size({"width": 390, "height": 844})
                review.screenshot(path=str(EVIDENCE / "approved-mobile.png"), full_page=True)
                assert review.evaluate("document.querySelector('.rd-page').scrollWidth <= innerWidth + 1"), "Page-wide mobile overflow"
                outsider, other = login(browser, base, "outsider")
                assert assert_ok(outsider.request.get(base + "/api/rd/projects"))["total"] == 0
                for path in [f"/api/rd/projects/{pid}", f"/api/status/{jid}", f"/api/review/{jid}", download.removeprefix(base)]:
                    assert outsider.request.get(base + path).status == 404, path
                proof.update({"project": pid, "task": task["id"], "jid": jid, "artifact_sha256": digest,
                    "ui_workflow": "project → members → requirement/baseline → task → start → capture → submit → independent approve",
                    "real_revision_qa": checks["status"], "outsider_denials": 4, "mobile_page_overflow": False, "browser_errors": errors})
                assert not errors, errors
                browser.close()
            (EVIDENCE / "proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(proof, ensure_ascii=False, indent=2))
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            PlatformTokenVerifier.__call__ = original


if __name__ == "__main__":
    run()
