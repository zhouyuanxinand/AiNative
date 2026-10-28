"""Isolated real-server smoke for the explicit R&D demo mode.

Run from basic-service/app: ../.venv/Scripts/python.exe tests/rd_demo_browser_smoke.py
Uses the real application, demo cookie, SQLite seed and browser UI. OA verification
is not replaced. Seeded documents are labelled mock; no generation/model is run.
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
EVIDENCE = APP / "runtime/rd-demo-browser"


def json_ok(response):
    assert response.ok, f"{response.status}: {response.text()}"
    return response.json()


def no_overflow(page, name):
    if page.viewport_size["width"] < 780:
        page.wait_for_function("document.querySelector('.platform-sidebar').getBoundingClientRect().right <= 1")
    geometry = page.evaluate("""(() => { const main = document.querySelector('.platform-content');
        return {viewport:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth,
                content:main?.scrollWidth,contentViewport:main?.clientWidth}; })()""")
    assert max(geometry["document"], geometry["body"]) <= geometry["viewport"] + 1, (name, geometry)
    assert geometry["content"] <= geometry["contentViewport"] + 1, (name, geometry)
    return geometry


def switch_identity(page, base, user_id):
    """Exercise the actual shell identity selector, then verify server cookie."""
    status = json_ok(page.context.request.get(base + "/api/demo/status"))
    selected = next(user for user in status["users"] if user["userid"] == user_id)
    selector = page.get_by_label("切换演示角色", exact=True)
    selector.click()
    with page.expect_navigation(wait_until="networkidle"):
        page.get_by_role("option").filter(has_text=selected["display_name"]).click()
    identity = json_ok(page.context.request.get(base + "/api/current-user"))
    assert identity["user"]["userid"] == user_id, identity
    assert identity["demo_mode"] is True and identity["user"]["source"] == "mock"


def run(*, tool_only=False):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rd-demo-browser-") as directory:
        temporary = Path(directory)
        os.environ.update({
            "JTB_DEMO_MODE": "true", "JTB_AUTH_ENABLED": "true", "JTB_AUTH_APP_ID": "9193",
            "JTB_AUTH_PLATFORM_BASE_URL": "http://127.0.0.1:1", "JTB_AUTH_PUBLIC_URL": "",
            "JTB_AUTH_SETTINGS_DB": str(temporary / "auth.sqlite3"),
            "JTB_SERVICE_CREDENTIALS_DB": str(temporary / "credentials.sqlite3"),
            "JTB_RD_DB": str(temporary / "rd.sqlite3"), "JTB_RD_ARTIFACTS": str(temporary / "artifacts"),
            "JTB_UPLOAD_DIR": str(temporary / "uploads"), "JTB_OUTPUT_DIR": str(temporary / "output"),
            "JTB_TEMPLATE_CANDIDATE_DIR": str(temporary / "candidates"),
            "JTB_TEMPLATE_RELEASE_AUDIT_DIR": str(temporary / "releases"), "JTB_ALLOW_LOCAL_PATHS": "0",
            "JTB_SERVICE_CREDENTIAL_PRESETS": "[]", "JTB_LLM_API_KEY": "", "MODEL_API_KEY": "",
            "OPENAI_API_KEY": "", "AZURE_OPENAI_API_KEY": "", "AZURE_API_KEY": "", "AI_API_KEY": "",
        })
        from src.utils.config_loader import load_config
        from src.application.factory import create_app
        from src.controller import taskbook_controller as jobs
        from playwright.sync_api import sync_playwright
        import uvicorn
        config = replace(load_config(), logs_dir=temporary / "logs")
        app = create_app(config)
        jobs.register(app, config)
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
        assert server.started
        proof = {"base": base, "mode": "explicit JTB_DEMO_MODE=true; real demo identity cookie and SQLite",
                 "external_services": "OA and model not called; seeded artifacts and QA explicitly mock"}
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(**browser_options())
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
                page = context.new_page()
                errors, external, generation_calls = [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                def record(request):
                    if not request.url.startswith(base):
                        external.append(request.url)
                    if request.method == "POST" and request.url.split("?")[0].endswith(("/api/submit", "/api/submit_local")):
                        generation_calls.append(request.url)
                page.on("request", record)
                response = page.goto(base + "/")
                assert response.status == 200 and page.url == base + "/", "Demo home redirected to OA"
                page.wait_for_load_state("networkidle")
                identity = json_ok(context.request.get(base + "/api/current-user"))
                assert identity["demo_mode"] and identity["authenticated"] and not identity["auth_enabled"]
                assert identity["user"]["userid"] == "demo-owner"
                status = json_ok(context.request.get(base + "/api/demo/status"))
                assert len(status["users"]) == 4 and status["enabled"]
                workspace = json_ok(context.request.get(base + "/api/rd/workspace"))
                assert len(workspace["projects"]) == 3
                assert {d["project"]["code"] for d in workspace["projects"]} == {"RD-DEMO-001", "RD-DEMO-002", "RD-DEMO-003"}
                if tool_only:
                    json_ok(context.request.post(base + "/api/demo/identity", data={"user_id": "demo-engineer"}))
                    project, task = next((d, t) for d in workspace["projects"] for t in d["tasks"] if t["status"] == "in_progress")
                    page.goto(f"{base}/taskbook?rd_project={project['project']['id']}&rd_task={task['id']}")
                    page.get_by_role("heading", name="研制任务书生成", exact=True).wait_for()
                    page.get_by_label("我已核对本次上传资料和业务选择，确认其对应以上需求基线。", exact=True).wait_for()
                    geometry = page.evaluate("""(() => {
                        const rect = selector => { const r=document.querySelector(selector).getBoundingClientRect(); return {top:r.top,bottom:r.bottom,height:r.height}; };
                        return {header:rect('.taskbook-workspace .header'),flow:rect('.taskbook-workspace .flow-bar'),context:rect('.rd-generation-context')};
                    })()""")
                    assert geometry["flow"]["bottom"] <= geometry["header"]["bottom"] + 1, geometry
                    assert geometry["context"]["top"] >= geometry["header"]["bottom"] - 1, geometry
                    page.screenshot(path=str(EVIDENCE / "tool-header-desktop.png"), full_page=True, animations="disabled")
                    proof.update({"header_flow_geometry": geometry, "header_contains_flowbar": True, "context_not_overlapped": True})
                    (EVIDENCE / "tool-header-proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(json.dumps(proof, ensure_ascii=False, indent=2))
                    browser.close()
                    return
                page.get_by_role("heading", name="研发总览", exact=True).wait_for()
                page.get_by_text("演示环境", exact=True).first.wait_for()
                page.screenshot(path=str(EVIDENCE / "overview-desktop.png"), full_page=True, animations="disabled")
                page.set_viewport_size({"width": 390, "height": 844})
                proof["mobile_overview"] = no_overflow(page, "overview")
                page.screenshot(path=str(EVIDENCE / "overview-mobile.png"), full_page=True, animations="disabled")
                page.get_by_role("button", name="展开平台导航", exact=True).click()
                page.get_by_role("navigation", name="研发业务", exact=True).get_by_role("link", name="需求中心", exact=True).click()
                page.wait_for_url(base + "/requirements")
                page.get_by_role("heading", name="需求中心", exact=True).wait_for()
                proof["mobile_navigation"] = True
                page.set_viewport_size({"width": 1440, "height": 1000})
                navigation = []
                for path, heading in [("/rd", "研发项目"), ("/requirements", "需求中心"), ("/tasks", "研发任务"),
                                      ("/artifacts", "成果中心"), ("/approvals", "审签待办")]:
                    page.locator(f'a[href="{path}"]:visible').first.click()
                    page.wait_for_url(base + path)
                    page.get_by_role("heading", name=heading, exact=True).wait_for()
                    page.wait_for_load_state("networkidle")
                    navigation.append({"path": path, "heading": heading})
                    page.set_viewport_size({"width": 390, "height": 844})
                    no_overflow(page, path)
                    page.set_viewport_size({"width": 1440, "height": 1000})
                pending_project = next(d for d in workspace["projects"] if d["project"]["code"] == "RD-DEMO-002")
                pid = pending_project["project"]["id"]
                pending_review = next(r for r in pending_project["reviews"] if r["status"] == "pending")
                switch_identity(page, base, "demo-engineer")
                response = context.request.post(f"{base}/api/rd/projects/{pid}/commands", headers={"Idempotency-Key": "browser-self-approval"},
                    data={"action": "decide_review", "expected_version": pending_project["project"]["version"],
                          "payload": {"review_id": pending_review["id"], "decision": "approved", "comment": "编制人不能自批"}})
                assert response.status == 403, response.text()
                page.goto(f"{base}/rd/{pid}?tab=artifacts")
                page.get_by_role("heading", name=pending_project["project"]["name"], exact=True).wait_for()
                assert page.get_by_role("button", name="批准固定成果", exact=True).count() == 0
                switch_identity(page, base, "demo-reviewer")
                page.goto(f"{base}/rd/{pid}?tab=artifacts")
                page.get_by_label("审签意见（退回必填）", exact=True).fill("演示浏览器验收：核对固定版本与独立角色权限。")
                page.get_by_role("button", name="批准固定成果", exact=True).click()
                dialog = page.get_by_role("dialog", name="批准固定成果", exact=True)
                dialog.get_by_role("button", name="批准固定成果", exact=True).click()
                dialog.wait_for(state="hidden")
                page.get_by_role("link", name="下载批准版", exact=True).wait_for()
                detail = json_ok(context.request.get(f"{base}/api/rd/projects/{pid}"))
                review = next(r for r in detail["reviews"] if r["id"] == pending_review["id"])
                assert review["status"] == "approved" and review["decided_by"] == "demo-reviewer"
                artifact = next(a for a in detail["artifacts"] if a["id"] == review["artifact_id"])
                assert artifact["quality_evidence"]["source"] == "mock"
                content = context.request.get(f"{base}/api/rd/projects/{pid}/artifacts/{artifact['id']}/download?approved=true")
                assert content.ok and hashlib.sha256(content.body()).hexdigest() == artifact["sha256"]
                page.screenshot(path=str(EVIDENCE / "project-desktop.png"), full_page=True, animations="disabled")
                page.set_viewport_size({"width": 390, "height": 844})
                no_overflow(page, "project")
                page.set_viewport_size({"width": 1440, "height": 1000})
                switch_identity(page, base, "demo-engineer")
                workspace = json_ok(context.request.get(base + "/api/rd/workspace"))
                generation_project, task = next((d, t) for d in workspace["projects"] for t in d["tasks"] if t["status"] == "in_progress")
                page.goto(f"{base}/taskbook?rd_project={generation_project['project']['id']}&rd_task={task['id']}")
                checkbox = page.get_by_label("我已核对本次上传资料和业务选择，确认其对应以上需求基线。", exact=True)
                checkbox.wait_for()
                checkbox.check()
                for selector in ["#f-tech", "#f-spec", "#product-type", "#product-domain", "#development-process", "#cover-phase", "#product-series", "#llm-model"]:
                    assert page.locator(selector).count() == 1, selector
                assert page.get_by_role("button", name="开始受控生成", exact=True).is_disabled()
                from docx import Document
                source = temporary / "browser-input.docx"
                document = Document()
                document.add_paragraph("浏览器上传验证资料，不调用模型。")
                document.save(source)
                for selector in ["#f-tech", "#f-spec"]:
                    page.locator(selector).set_input_files(str(source))
                assert not checkbox.is_checked(), "Changed inputs must invalidate baseline confirmation"
                checkbox.check()
                assert page.get_by_role("button", name="开始受控生成", exact=True).is_disabled(), "Demo mode must not fake model readiness"
                page.screenshot(path=str(EVIDENCE / "generation-desktop.png"), full_page=True, animations="disabled")
                page.set_viewport_size({"width": 390, "height": 844})
                proof["mobile_generation"] = no_overflow(page, "taskbook")
                page.screenshot(path=str(EVIDENCE / "generation-mobile.png"), full_page=True, animations="disabled")
                assert not generation_calls and not external and not errors, (generation_calls, external, errors)
                proof.update({"seed_project_count": 3, "demo_identity_bypasses_oa": True, "navigation": navigation,
                    "roles": ["demo-owner", "demo-engineer", "demo-reviewer"], "self_approval_denied": 403,
                    "independent_review": review["status"], "artifact_sha256": artifact["sha256"],
                    "generation_controls_preserved": True, "model_readiness_not_mocked": True,
                    "changed_files_invalidate_baseline_confirmation": True, "external_requests": external,
                    "generation_requests": generation_calls, "browser_errors": errors})
                browser.close()
            (EVIDENCE / "proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(proof, ensure_ascii=False, indent=2))
        finally:
            server.should_exit = True
            thread.join(timeout=10)


if __name__ == "__main__":
    run(tool_only="--tool-only" in sys.argv)
