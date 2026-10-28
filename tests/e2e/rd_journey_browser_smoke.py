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
EVIDENCE = APP / "runtime/role-journey-browser"


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


def run():
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
        from src.service.rd_platform.demo_taskbook import ensure_native_demo_workspace
        from src.service.rd_platform.runtime import get_store
        ensure_native_demo_workspace(get_store())
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

        proof = {"external_calls": "OA and model not called; sample evidence explicitly mock"}
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(**browser_options())
                context = browser.new_context(viewport={"width":1440,"height":1000})
                page=context.new_page(); page.set_default_timeout(15000)
                errors=[]; page.on("pageerror",lambda error: errors.append(str(error)))
                page.goto(base+"/");page.wait_for_load_state("networkidle")
                page.get_by_role("heading",name="我的工作",exact=True).wait_for()
                status=json_ok(context.request.get(base+"/api/demo/status"))
                assert len(status["users"])==4,status
                page.locator('.platform-duty-strip').wait_for()
                home_text=page.locator(".platform-content").inner_text()
                assert "发布已批准计划" in home_text, home_text
                page.screenshot(path=str(EVIDENCE/"owner-desktop.png"),full_page=True)
                proof["desktop_home"]=no_overflow(page,"home")
                page.set_viewport_size({"width":390,"height":844})
                proof["mobile_home"]=no_overflow(page,"home")
                page.screenshot(path=str(EVIDENCE/"owner-mobile.png"),full_page=True)
                page.set_viewport_size({"width":1440,"height":1000})
                roles={"demo-engineer":"工程师","demo-reviewer":"独立评审","demo-viewer":"只读成员","demo-owner":"项目负责人"}
                for user,label in roles.items():
                    switch_identity(page,base,user)
                    page.get_by_role("heading",name="我的工作",exact=True).wait_for()
                    assert label in page.get_by_role("region",name="当前职责").inner_text() if page.get_by_role("region",name="当前职责").count() else label in page.locator(".platform-duty-strip").inner_text()
                    proof[user]=label
                workspace=json_ok(context.request.get(base+"/api/rd/workspace"))["projects"]
                assert all({m["user_id"] for m in d["members"]} <= set(roles) for d in workspace)
                assert all("workbench_role" not in d["project"] for d in workspace)
                native_project,native=next((d,t) for d in workspace for t in d["tasks"] if t.get("kind")=="taskbook" and t["status"]=="in_review")
                switch_identity(page,base,"demo-reviewer")
                page.goto(f"{base}/rd/{native_project['project']['id']}/tasks/{native['id']}")
                page.get_by_role("button",name="工程审签",exact=True).wait_for()
                page.wait_for_function("document.querySelector('nav[aria-label=\"任务工作面\"] button[aria-current=page]')?.textContent === '工程审签'")
                proof["native_review_default"]=True
                page.screenshot(path=str(EVIDENCE/"reviewer-task.png"),full_page=True)
                json_ok(context.request.post(base+"/api/demo/identity",data={"user_id":"demo-owner"}))
                detail=json_ok(context.request.post(base+"/api/rd/projects",headers={"Idempotency-Key":"journey-browser-create"},data={"name":"直接选用交接验证（mock）","customer":"演示客户","product":"演示连接器","code":"JOURNEY-BROWSER"}))
                def command(action,payload):
                    nonlocal detail
                    detail=json_ok(context.request.post(base+"/api/rd/projects/"+detail["project"]["id"]+"/commands",headers={"Idempotency-Key":"browser-"+action+"-"+str(detail["project"]["version"])},data={"action":action,"payload":payload,"expected_version":detail["project"]["version"]}))
                    return detail
                command("add_member",{"user_id":"demo-reviewer","display_name":"演示评审","role":"reviewer"})
                command("save_requirement",{"title":"工程适用性核对","content":"按演示需求核对适用性","source":"mock需求文件","acceptance":"mock选型与交付凭据","clarification":"resolved","required":True})
                command("confirm_baseline",{})
                command("create_task",{"title":"交付跟进任务","description":"核对接收条件","assignee_id":"demo-owner","reviewer_id":"demo-reviewer"})
                tid=detail["tasks"][0]["id"]
                pid=detail["project"]["id"]
                page.goto(f"{base}/rd/{pid}?tab=flow")
                nav=page.get_by_role("navigation",name="项目工作区",exact=True)
                nav.get_by_role('button',name='项目流程',exact=True).wait_for()
                assert nav.get_by_role("button").all_text_contents()==["当前成果","项目流程","资料与画像"]
                page.get_by_role("button",name="登记选型路线",exact=True).click()
                def choose(label,value):
                    page.get_by_label(label,exact=True).click()
                    page.get_by_role("option",name=value,exact=True).click()
                choose("业务路线 *","直接选用")
                page.get_by_label("选型依据与差异说明 *",exact=True).fill("满足演示需求，依据mock报告决定直接选用")
                page.get_by_label("依据资料引用",exact=False).fill("mock选型报告-001")
                choose("工程适用性","已确认")
                choose("成本、库存与供货核对","已确认")
                with page.expect_response(lambda r:r.request.method=="POST" and r.url.endswith("/commands")) as saved:
                    page.get_by_role("button",name="保存选型决定",exact=True).click()
                assert saved.value.ok,saved.value.text()
                detail=saved.value.json();assert detail["journey"]["route"]=="direct"
                page.get_by_role("heading",name="直接选用交接",exact=True).wait_for()
                assert page.get_by_role("heading",name="交付跟进任务",exact=True).is_visible(),"Direct route lost existing task entry"
                assert not page.get_by_role("button",name="创建研制任务书工作包",exact=True).is_visible()
                page.locator(".rd-page").evaluate("element => element.scrollTop = 0")
                page.screenshot(path=str(EVIDENCE/"project-flow.png"),full_page=True)
                choose("交接结果","已实际接收")
                page.get_by_label("接收方 *",exact=True).fill("演示接收部门")
                page.get_by_label("实际接收凭据 *",exact=True).fill("mock接收回执-001")
                page.get_by_role("button",name="记录交接结果",exact=True).click()
                with page.expect_response(lambda r:r.request.method=="POST" and r.url.endswith("/commands")) as delivered:
                    page.get_by_role("dialog").get_by_role("button",name="记录交接结果",exact=True).click()
                assert delivered.value.ok,delivered.value.text()
                assert delivered.value.json()["journey"]["stage"]=="delivered"
                nav.get_by_role("button",name="资料与画像",exact=True).click()
                page.get_by_role("heading",name="需求条目",exact=True).wait_for()
                page.get_by_role("button",name="项目资料与上下文",exact=True).click()
                page.get_by_role("heading",name="客户与产品上下文",exact=True).wait_for()
                page.get_by_role("button",name="协作成员",exact=True).click()
                page.get_by_role("heading",name="项目成员",exact=True).wait_for()
                page.get_by_role("button",name="添加或调整协作成员",exact=True).click()
                assert page.get_by_label("工作台视角",exact=True).count()==0
                assert page.get_by_label("项目职责",exact=True).count()==1
                assert not page.get_by_label("账号 *",exact=True).input_value()
                page.get_by_role("button",name="项目资料与上下文",exact=True).click()
                page.locator(".rd-page").evaluate("element => element.scrollTop = 0")
                page.screenshot(path=str(EVIDENCE/"project-materials.png"),full_page=True)
                nav.get_by_role("button",name="项目流程",exact=True).click()
                page.set_viewport_size({"width":390,"height":844})
                proof["mobile_project"]=no_overflow(page,"project")
                page.locator(".rd-page").evaluate("element => element.scrollTop = 0")
                page.screenshot(path=str(EVIDENCE/"project-mobile.png"),full_page=True)
                page.set_viewport_size({"width":1440,"height":1000})
                page.goto(f"{base}/rd/{pid}?tab=tasks#task-{tid}")
                page.get_by_role("heading",name="交付跟进任务",exact=True).wait_for()
                assert page.get_by_role("button",name="项目流程",exact=True).get_attribute("aria-current")=="page"
                page.goto(f"{base}/rd/{pid}?tab=requirements#requirement-{detail['requirements'][0]['id']}")
                page.get_by_role("heading",name="需求条目",exact=True).wait_for()
                assert page.get_by_role("button",name="资料与画像",exact=True).get_attribute("aria-current")=="page"
                proof.update({"core_project_roles_only":True,"no_secondary_role_assignment":True,"three_project_areas":True,"selection_saved_via_ui":True,"direct_receipt_saved_via_ui":True,"existing_direct_tasks_accessible":True,"legacy_deep_links":True,"browser_errors":errors})
                assert not errors,errors
                (EVIDENCE/"proof.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding="utf-8")
                print(json.dumps(proof,ensure_ascii=False,indent=2));browser.close()
        finally:
            server.should_exit=True;thread.join(timeout=10)

if __name__=="__main__":
    run()
