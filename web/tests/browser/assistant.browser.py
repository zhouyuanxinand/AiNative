"""Exercise assistant UI states against the local app with isolated model/operation fixtures.

No model request or business write leaves the browser: /api/assistant/* is intercepted.
Run with the repository Python environment while the built main app is on 18130.
"""
import asyncio
import json
from pathlib import Path
import sys

from playwright.async_api import async_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
from browser_support import ROOT, BASE, browser_options
EVIDENCE = ROOT / "basic-service/app/runtime/xiaohang-browser"


async def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    requests = []
    errors = []
    confirmations = []
    failures = 0

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**browser_options())
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        page = await context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))

        async def assistant_route(route):
            nonlocal failures
            request = route.request
            if "/context" in request.url:
                await route.fulfill(json={
                    "name": "小航", "model_available": False, "role_label": "项目负责人", "project": None,
                    "quick_actions": [{"id": "projects", "label": "项目空间", "description": "查看项目流程", "href": "/rd", "prompt": "项目怎么推进？"}],
                    "suggested_questions": ["研发管理平台怎么使用？", "我要修改需求", "如何发布计划？"],
                })
            elif "/operations/" in request.url:
                confirmations.append({"url": request.url.split("/api/")[1], "body": request.post_data_json})
                await route.fulfill(json={"status": "executed", "proposal_id": "proposal-1", "message": "需求已更新，项目版本为 8。", "project_id": "p-123", "project_version": 8, "href": "/rd/p-123?tab=materials"})
            elif "/chat" in request.url:
                body = request.post_data_json
                requests.append(body)
                if body["message"] == "测试失败" and failures == 0:
                    failures += 1
                    await route.fulfill(status=502, json={"detail": "模型暂不可用，请重试。"})
                elif body["message"] == "等待测试":
                    await asyncio.sleep(3)
                    try:
                        await route.fulfill(json={"reply": "这是已取消请求的迟到回复", "mode": body["mode"], "source": "model", "actions": []})
                    except Exception:
                        pass
                elif body["message"] == "我要修改需求":
                    await route.fulfill(json={"reply": "已整理需求修改草案，请核对后执行。", "mode": "platform", "source": "platform-guide", "actions": [], "proposal": {
                        "id": "proposal-1", "project_id": "p-123", "project_name": "高可靠连接器", "action": "update_requirement", "label": "修改需求", "summary": "将需求标题调整为高可靠性要求。", "expected_version": 7, "payload": {}, "expires_at": "2026-10-28T15:10:00Z", "fields": [{"label": "需求", "value": "可靠性要求"}, {"label": "新标题", "value": "高可靠性要求"}], "warnings": ["确认后将新增需求修订。"],
                    }})
                else:
                    await route.fulfill(json={"reply": f"收到：{body['message']}。从项目空间查看需求、流程与成果。", "mode": "general" if body["message"] == "解释一个技术问题" else "platform", "source": "platform-guide", "actions": [
                        {"id": "rd", "label": "进入项目空间", "description": "", "href": "/rd"},
                        {"id": "unsafe", "label": "不应出现的外部链接", "description": "", "href": "https://example.com"},
                    ]})
            else:
                await route.abort()

        await page.route("**/api/assistant/**", assistant_route)
        await page.goto(BASE + '/rd', wait_until="networkidle")
        await page.get_by_role("button", name="新建业务空间", exact=True).click()
        business_input = page.get_by_role("textbox", name="项目名称 *", exact=True)
        await business_input.fill("未保存的业务草稿")
        launcher = page.get_by_role("button", name="打开小航 AI 助手", exact=True)
        await expect(launcher).to_be_visible()
        await expect(launcher.get_by_text("有事问小航", exact=True)).to_be_visible()
        assert await launcher.get_by_text("拖动可移动", exact=True).count() == 0
        await expect(page.locator(".xiaohang-sprite")).to_have_class("xiaohang-sprite is-ready")
        await expect(page.locator(".xiaohang-sprite")).to_have_attribute("data-playing", "true")
        main_before = await page.locator(".platform-main-column").bounding_box()
        await launcher.click()
        panel = page.locator("#xiaohang-panel")
        await expect(panel).to_be_visible()
        textbox = page.get_by_role("textbox", name="向小航发送问题", exact=True)
        await expect(textbox).to_be_focused()
        await expect(panel.get_by_role("link", name="项目空间 查看项目流程")).to_be_visible()
        assert await page.get_by_role("button", name="平台助手", exact=True).count() == 0
        assert await page.get_by_role("button", name="通用助手", exact=True).count() == 0
        main_open = await page.locator(".platform-main-column").bounding_box()
        panel_box = await panel.bounding_box()
        sidebar_box = await page.locator(".platform-sidebar").bounding_box()
        assert main_before and main_open and panel_box and sidebar_box
        assert abs(main_before["width"] - main_open["width"] - 420) < 2
        assert abs(main_open["x"] + main_open["width"] - panel_box["x"]) < 2
        assert abs(panel_box["x"] + panel_box["width"] - 1440) < 2 and panel_box["y"] == 0
        assert sidebar_box["width"] == 228
        assert await panel.get_by_role("button", name="加宽小航侧栏").count() == 0
        assert await panel.get_by_role("button", name="收窄小航侧栏").count() == 0
        assert await panel.locator(".xiaohang-header").get_by_role("button").count() == 1
        await expect(panel.get_by_role("button", name="收起小航对话", exact=True)).to_be_visible()
        separator = page.get_by_role("separator", name="调整小航侧栏宽度")
        await separator.focus()
        await separator.press("ArrowLeft")
        assert (await panel.bounding_box())["width"] == 452
        await separator.press("ArrowRight")
        edge = await separator.bounding_box()
        await page.mouse.move(edge["x"] + edge["width"] / 2, 300)
        await page.mouse.down()
        await page.mouse.move(edge["x"] - 90, 300, steps=6)
        await page.mouse.up()
        assert 510 <= (await panel.bounding_box())["width"] <= 520
        await separator.press("Home")
        assert (await panel.bounding_box())["width"] == 320
        await separator.press("End")
        assert (await panel.bounding_box())["width"] == 640
        await separator.press("Home")
        await separator.press("ArrowLeft")
        assert (await panel.bounding_box())["width"] == 352
        await page.set_viewport_size({"width": 1200, "height": 1000})
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        panel_1200 = await panel.bounding_box()
        main_1200 = await page.locator(".platform-main-column").bounding_box()
        assert panel_1200 and main_1200 and main_1200["width"] >= 420
        await page.set_viewport_size({"width": 1440, "height": 1000})
        await page.screenshot(path=str(EVIDENCE / "desktop-welcome.png"))

        await textbox.fill("中文组合输入")
        before = len(requests)
        await textbox.dispatch_event("compositionstart")
        await textbox.press("Enter")
        await textbox.dispatch_event("compositionend")
        assert len(requests) == before, "IME confirmation must not send"
        await textbox.fill("测试成功")
        await textbox.press("Enter")
        await expect(panel.get_by_text("收到：测试成功。从项目空间查看需求、流程与成果。", exact=True)).to_be_visible()
        assert await panel.get_by_text("不应出现的外部链接").count() == 0

        await textbox.fill("测试失败")
        await textbox.press("Enter")
        await expect(panel.get_by_text("模型暂不可用，请重试。", exact=True)).to_be_visible()
        await expect(textbox).to_have_value("测试失败")
        await panel.get_by_role("button", name="重试这个问题").click()
        await expect(panel.get_by_text("收到：测试失败。从项目空间查看需求、流程与成果。", exact=True)).to_be_visible()
        assert len(requests[-1]["history"]) == 2, "failed turns must not pollute history"

        await textbox.fill("等待测试")
        await textbox.press("Enter")
        await expect(panel.get_by_role("button", name="停止等待")).to_be_visible()
        await panel.get_by_role("button", name="停止等待").click()
        await expect(textbox).to_have_value("等待测试")
        await expect(panel.get_by_text("已停止等待回复，问题已保留。", exact=True)).to_be_visible()

        await textbox.fill("解释一个技术问题")
        await textbox.press("Enter")
        await expect(panel.get_by_text("收到：解释一个技术问题。从项目空间查看需求、流程与成果。", exact=True)).to_be_visible()
        assert requests[-1]["mode"] == "auto"
        assert len(requests[-1]["history"]) == 4
        assert requests[-1]["history"][-1]["content"].startswith("收到：测试失败")
        await textbox.press("Escape")
        await expect(business_input).to_have_value("未保存的业务草稿")
        await business_input.fill("")
        await launcher.click()

        await textbox.fill("我要修改需求")
        await textbox.press("Enter")
        await expect(panel.get_by_text("待你确认的操作", exact=True)).to_be_visible()
        assert len(confirmations) == 0, "showing a proposal must not execute it"
        await panel.get_by_role("button", name="确认执行", exact=True).click()
        confirmation = page.get_by_role("dialog", name="确认修改需求？", exact=True)
        await expect(confirmation).to_be_visible()
        assert len(confirmations) == 0
        await confirmation.get_by_role("button", name="返回核对", exact=True).click()
        await expect(confirmation).not_to_be_visible()
        assert len(confirmations) == 0
        await panel.get_by_role("button", name="确认执行", exact=True).click()
        await confirmation.get_by_role("button", name="确认执行", exact=True).click()
        await expect(panel.get_by_text("操作已完成", exact=True)).to_be_visible()
        assert len(confirmations) == 1 and confirmations[0]["body"] == {}
        await expect(panel.get_by_role("link", name="查看最新项目记录 →")).to_be_visible()
        await page.screenshot(path=str(EVIDENCE / "desktop-operation.png"))

        await textbox.press("Escape")
        await expect(panel).not_to_be_visible()
        await expect(launcher).to_be_focused()
        await expect(page.locator(".xiaohang-sprite")).to_have_attribute("data-playing", "true")
        await page.emulate_media(reduced_motion="reduce")
        await expect(page.locator(".xiaohang-sprite")).to_have_attribute("data-playing", "false")
        await page.set_viewport_size({"width": 980, "height": 900})
        await launcher.click()
        await expect(panel).to_be_visible()
        box = await panel.bounding_box()
        assert box and box["x"] == 0 and box["width"] == 980 and box["height"] == 900
        await expect(page.locator(".platform-main-column")).not_to_be_visible()
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        await page.set_viewport_size({"width": 390, "height": 844})
        box = await panel.bounding_box()
        assert box and box["x"] == 0 and box["width"] == 390 and box["y"] == 0 and box["height"] == 844
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        await page.screenshot(path=str(EVIDENCE / "mobile-operation.png"))
        assert not errors, errors
        assert all(body["mode"] == "auto" for body in requests)
        await textbox.press("Escape")
        await expect(page.locator(".platform-main-column")).to_be_visible()
        await expect(business_input).to_have_value("")
        proof = {"cases": ["animated transparent figure", "friendly launcher label", "header close only", "single conversation auto intent", "desktop third column no overlap", "resize drag", "resize keyboard", "1440/1200/980/390 layouts", "business DOM and drafts preserved", "IME", "success", "unsafe link rejected", "failure and retry", "completed history only", "stop waiting", "proposal preview", "confirmation cancel", "one execution with empty body", "result link", "Escape figure and focus restore", "reduced motion", "narrow full-width drawer"], "chat_requests": len(requests), "fixture_operations": len(confirmations), "page_errors": errors, "real_business_writes": 0, "external_model_requests": 0}
        (EVIDENCE / "proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(proof, ensure_ascii=False))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
