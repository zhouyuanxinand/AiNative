"""Native workbench UI against a real isolated service and persistent domain.

Uses clearly marked preloaded sample documents; no OA/model/Office call.
"""
from __future__ import annotations
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_support import APP, browser_options
sys.path[:0] = [str(APP), str(APP / "src/service")]
EVIDENCE = APP / "runtime/taskbook-native-browser"


def ok(response):
    assert response.ok, f"{response.status} {response.text()[:1600]}"
    return response.json()


def run():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-taskbook-browser-", ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        os.environ.update({
            "JTB_DEMO_MODE": "true", "JTB_AUTH_ENABLED": "true",
            "JTB_AUTH_APP_ID": "9193", "JTB_AUTH_PLATFORM_BASE_URL": "http://127.0.0.1:1",
            "JTB_AUTH_PUBLIC_URL": "", "JTB_AUTH_SETTINGS_DB": str(root / "auth.sqlite3"),
            "JTB_SERVICE_CREDENTIALS_DB": str(root / "credentials.sqlite3"),
            "JTB_RD_DB": str(root / "rd.sqlite3"), "JTB_RD_ARTIFACTS": str(root / "artifacts"),
            "JTB_UPLOAD_DIR": str(root / "uploads"), "JTB_OUTPUT_DIR": str(root / "outputs"),
            "JTB_SERVICE_CREDENTIAL_PRESETS": "[]", "JTB_ALLOW_LOCAL_PATHS": "0",
            "JTB_LLM_API_KEY": "", "MODEL_API_KEY": "", "OPENAI_API_KEY": "",
            "AZURE_OPENAI_API_KEY": "", "AZURE_API_KEY": "", "AI_API_KEY": "",
        })
        from src.utils.config_loader import load_config
        from src.application.factory import create_app
        from src.controller import taskbook_controller as jobs
        from src.service.rd_platform.demo_taskbook import ensure_native_demo_workspace
        from src.service.rd_platform.runtime import get_store
        from playwright.sync_api import sync_playwright
        import uvicorn
        config = replace(load_config(), logs_dir=root / "logs")
        app = create_app(config)
        jobs.register(app, config)
        ensure_native_demo_workspace(get_store())
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(.1)
        assert server.started
        proof = {"mode": "real isolated API/SQLite, explicit demo identities and imported mock documents", "base": base}
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(**browser_options())
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
                page = context.new_page()
                errors, external = [], []
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.on("request", lambda request: external.append(request.url) if not request.url.startswith(base) else None)

                def identity(uid):
                    ok(context.request.post(base + "/api/demo/identity", data={"user_id": uid}))

                def projects():
                    return ok(context.request.get(base + "/api/rd/workspace"))["projects"]

                def pick(phrase):
                    return next((d, t) for d in projects() for t in d["tasks"] if t.get("kind") == "taskbook" and phrase in t["title"])

                def open_task(project, task, view):
                    page.goto(f"{base}/rd/{project['project']['id']}/tasks/{task['id']}?view={view}")
                    try:
                        page.get_by_role("heading", name=task["title"], exact=True).wait_for(timeout=12000)
                    except Exception:
                        page.screenshot(path=str(EVIDENCE / "failure.png"), full_page=True)
                        print(json.dumps({"url": page.url, "errors": errors, "body": page.locator('body').inner_text()[:6000]}, ensure_ascii=False))
                        raise
                    page.wait_for_load_state("networkidle")
                    return f"{base}/api/rd/projects/{project['project']['id']}/tasks/{task['id']}/taskbook"

                def action(label):
                    page.get_by_role("button", name=label, exact=True).first.click()
                    page.get_by_role("dialog").get_by_role("button", name=label, exact=True).click()
                    page.get_by_role("dialog").wait_for(state="hidden")

                def geometry(name):
                    if page.viewport_size['width'] < 780:
                        page.wait_for_function("document.querySelector('.platform-sidebar').getBoundingClientRect().right <= 1")
                    result = page.evaluate("({viewport:innerWidth,document:document.documentElement.scrollWidth,content:document.querySelector('.platform-content')?.scrollWidth,client:document.querySelector('.platform-content')?.clientWidth})")
                    assert result["document"] <= result["viewport"] + 1, (name, result)
                    assert result["content"] <= result["client"] + 1, (name, result)
                    proof[name] = result

                identity("demo-engineer")
                d, t = pick("编制与核验")
                task_api = open_task(d, t, "document")
                page.get_by_text("演示预置文档 · 未调用模型", exact=False).wait_for()
                page.get_by_role("heading", name="任务阶段", exact=True).wait_for()
                page.get_by_text("功能用途", exact=False).first.wait_for()
                geometry("document_desktop")
                page.screenshot(path=str(EVIDENCE / "document-desktop.png"), full_page=True)
                for view in ("inputs", "document", "planning", "review", "handoff"):
                    open_task(d, t, view)
                    page.set_viewport_size({"width": 390, "height": 844})
                    geometry(view + "_mobile")
                    page.screenshot(path=str(EVIDENCE / (view + "-mobile.png")), full_page=True)
                    page.set_viewport_size({"width": 1440, "height": 1000})
                proof["native_tabs"] = 5

                # Private input drafts survive refresh without changing package.
                open_task(d, t, "inputs")
                series = page.get_by_label("产品系列", exact=False)
                series.fill("演示浏览器草稿系列")
                page.get_by_text("私有草稿已保存", exact=False).wait_for()
                page.reload()
                page.get_by_role("heading", name=t["title"], exact=True).wait_for()
                page.wait_for_function("document.querySelector('input') !== null")
                assert page.get_by_label("产品系列", exact=False).input_value() == "演示浏览器草稿系列"
                proof["private_draft_refresh"] = True

                # Imported WBS is a local candidate, not a saved/published plan.
                # Returned sample already has the complete coverage required by ND14.
                d, t = pick("退回修订")
                task_api = open_task(d, t, "document")
                detail = ok(context.request.get(f"{base}/api/rd/projects/{d['project']['id']}"))
                ok(context.request.post(f"{base}/api/rd/projects/{d['project']['id']}/commands", headers={"Idempotency-Key": "native-browser-nd14"}, data={"action": "advance_taskbook_stage", "payload": {"task_id": t["id"], "target_stage": "ND14"}, "expected_version": detail["project"]["version"]}))
                open_task(d, t, "planning")
                page.get_by_text("从JSON模板导入草案", exact=True).click()
                with page.expect_download() as downloading:
                    page.get_by_role("button", name="下载WBS示例JSON", exact=True).click()
                template = root / "wbs-template.json"
                downloading.value.save_as(template)
                initial_wbs = ok(context.request.get(task_api))["wbs"]
                page.get_by_label("选择WBS模板JSON", exact=True).set_input_files(template)
                page.get_by_role("dialog").get_by_role("button", name="替换本页草案", exact=True).click()
                page.get_by_text("条未保存草案", exact=False).wait_for()
                assert page.get_by_label("工作名称", exact=False).count() == 2
                assert ok(context.request.get(task_api))["wbs"] == initial_wbs
                bad_template = root / "invalid-wbs.json"
                bad_template.write_text('{"items":"invalid"}', encoding="utf-8")
                page.get_by_label("选择WBS模板JSON", exact=True).set_input_files(bad_template)
                page.get_by_role("alert").filter(has_text="模板").wait_for()
                assert page.get_by_label("工作名称", exact=False).count() == 2
                proof["wbs_template_import_draft_and_failed_import_preserves"] = True
                page.once("dialog", lambda dialog: dialog.accept())
                page.reload()
                page.get_by_role("heading", name=t["title"], exact=True).wait_for()

                # Independent approval, then explicit owner publication.
                d, t = pick("待独立评审")
                task_api = open_task(d, t, "review")
                assert page.get_by_role("button", name="批准固定包", exact=True).count() == 0
                identity("demo-reviewer")
                open_task(d, t, "review")
                page.get_by_label("审签意见（退回必填）", exact=True).fill("浏览器验收：已核对演示固定包")
                action("批准固定包")
                latest = ok(context.request.get(task_api))
                assert latest["task"]["status"] == "done" and len(latest["releases"]) == 1
                assert not latest["plan_releases"]
                release = latest["releases"][0]
                download = context.request.get(f"{base}/api/rd/projects/{d['project']['id']}/artifacts/{release['artifact_id']}/download?approved=true")
                assert download.ok and hashlib.sha256(download.body()).hexdigest() == release["sha256"]
                page.screenshot(path=str(EVIDENCE / "approved-desktop.png"), full_page=True)
                identity("demo-owner")
                open_task(d, t, "handoff")
                action("发布正式计划")
                latest = ok(context.request.get(task_api))
                assert len(latest["plan_releases"]) == 1 and len(latest["handoffs"]) == 2
                proof["independent_approval_exact_download_and_publish"] = True

                identity("demo-engineer")
                open_task(d, t, "handoff")
                action("接收交接包")
                latest = ok(context.request.get(task_api))
                accepted = next(h for h in latest["handoffs"] if h["status"] == "accepted")
                detail = ok(context.request.get(f"{base}/api/rd/projects/{d['project']['id']}"))
                child = next(x for x in detail["tasks"] if x["id"] == accepted["task_id"])
                assert child["status"] == "todo" and not child.get("actual_start")
                ok(context.request.post(f"{base}/api/rd/projects/{d['project']['id']}/commands", headers={"Idempotency-Key": "native-browser-start"}, data={"action": "start_task", "payload": {"task_id": child["id"]}, "expected_version": detail["project"]["version"]}))
                page.goto(f"{base}/rd/{d['project']['id']}?tab=flow")
                page.get_by_role("heading", name="项目流程与正式计划", exact=True).wait_for()
                assert page.get_by_role("region", name="正式计划依赖流程", exact=True).is_visible()
                assert page.get_by_role("region", name="正式计划甘特", exact=True).is_visible()
                geometry("project_plan_desktop")
                page.screenshot(path=str(EVIDENCE / "project-plan-desktop.png"), full_page=True)
                proof["explicit_handoff_then_start"] = True

                changed_project, changed_task = pick("变更待复核")
                changed_api = open_task(changed_project, changed_task, "handoff")
                page.get_by_role("heading", name="输入变化影响", exact=True).wait_for()
                changed = ok(context.request.get(changed_api))
                assert changed["releases"] and changed["change_impacts"]
                assert any(impact["status"] == "pending" for impact in changed["change_impacts"])
                proof["source_change_preserves_approved_history"] = True

                identity("demo-viewer")
                open_task(d, t, "review")
                assert page.get_by_role("button", name="批准固定包", exact=True).count() == 0
                assert page.get_by_role("button", name="提交固定包审签", exact=True).count() == 0
                proof["viewer_read_only"] = True
                assert not errors, errors
                assert not external, external
                proof.update(page_errors=errors, external_requests=external)
                (EVIDENCE / "proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(proof, ensure_ascii=False, indent=2))
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)


if __name__ == "__main__":
    run()
