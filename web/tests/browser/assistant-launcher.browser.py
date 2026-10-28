"""Launcher drag/placement checks; no model calls or project writes."""
import asyncio
import json
from pathlib import Path
import sys

from playwright.async_api import async_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
from browser_support import ROOT, BASE, browser_options
EVIDENCE = ROOT / 'basic-service/app/runtime/xiaohang-launcher-drag'


async def visual_bounds(page):
    return await page.evaluate("""() => {
      const boxes = [...document.querySelectorAll('.xiaohang-launcher, .xiaohang-launcher .xiaohang-figure, .xiaohang-launcher img, .xiaohang-launcher svg')].map(e => e.getBoundingClientRect());
      return {left: Math.min(...boxes.map(b=>b.left)), top: Math.min(...boxes.map(b=>b.top)),
        right: Math.max(...boxes.map(b=>b.right)), bottom: Math.max(...boxes.map(b=>b.bottom)), width: innerWidth, height: innerHeight};
    }""")


async def assert_inside(page):
    bounds = await visual_bounds(page)
    assert bounds['left'] >= -1 and bounds['top'] >= -1, bounds
    assert bounds['right'] <= bounds['width'] + 1 and bounds['bottom'] <= bounds['height'] + 1, bounds
    return bounds


async def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(**browser_options())
        context = await browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        page = await context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.route('**/api/assistant/context**', lambda route: route.fulfill(json={'name': '小航', 'model_available': False, 'project': None, 'role_label': '项目负责人', 'quick_actions': [], 'suggested_questions': []}))
        await page.goto(BASE + '/', wait_until='networkidle')
        launcher = page.get_by_role('button', name='打开小航 AI 助手', exact=True)
        await expect(launcher).to_be_visible()
        initial = await assert_inside(page)
        box = await launcher.bounding_box()
        await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        await page.mouse.down()
        await page.mouse.move(110, 350, steps=12)
        await expect(page.locator('.xiaohang-assistant')).to_have_class('xiaohang-assistant  is-launcher-dragging')
        assert await page.locator('#xiaohang-panel').count() == 0, 'Dragging must not open the assistant'
        await page.mouse.up()
        await expect(page.locator('.xiaohang-assistant')).not_to_have_class('xiaohang-assistant  is-launcher-dragging')
        left = await assert_inside(page)
        assert left['left'] <= 26, left
        assert await page.locator('#xiaohang-panel').count() == 0, 'Release click must not open the assistant'
        stored = await page.evaluate("JSON.parse(localStorage.getItem('xiaohang-launcher-position-v1'))")
        assert set(stored) == {'edge', 'y'} and stored['edge'] == 'left'
        await page.reload(wait_until='networkidle')
        reloaded = await assert_inside(page)
        assert abs(reloaded['top'] - left['top']) < 3
        await launcher.focus()
        await launcher.press('ArrowRight')
        right = await assert_inside(page)
        assert right['right'] >= 1414
        await launcher.press('ArrowUp')
        up = await assert_inside(page)
        assert abs(up['top'] - (right['top'] - 24)) < 2
        await launcher.press('Enter')
        await expect(page.locator('#xiaohang-panel')).to_be_visible()
        await page.get_by_role('button', name='收起小航对话', exact=True).click()
        await expect(launcher).to_be_focused()
        after_close = await assert_inside(page)
        assert abs(after_close['top'] - up['top']) < 3
        await launcher.press('Home')
        reset = await assert_inside(page)
        assert reset['right'] >= 1414 and reset['bottom'] >= 974
        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.wait_for_timeout(100)
        mobile = await assert_inside(page)
        await page.screenshot(path=str(EVIDENCE / 'mouse-mobile.png'))
        # A small pointer jitter remains a normal activation.
        box = await launcher.bounding_box()
        await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        await page.mouse.down()
        await page.mouse.move(box['x'] + box['width'] / 2 + 3, box['y'] + box['height'] / 2 + 2)
        await page.mouse.up()
        await expect(page.locator('#xiaohang-panel')).to_be_visible()
        await context.close()

        touch_context = await browser.new_context(viewport={'width': 390, 'height': 844}, has_touch=True, is_mobile=True, reduced_motion='reduce')
        touch = await touch_context.new_page()
        touch.on('pageerror', lambda error: errors.append(str(error)))
        await touch.goto(BASE + '/', wait_until='networkidle')
        touch_launcher = touch.get_by_role('button', name='打开小航 AI 助手', exact=True)
        await expect(touch_launcher).to_be_visible()
        box = await touch_launcher.bounding_box()
        client = await touch_context.new_cdp_session(touch)
        start_x, start_y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
        await client.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': start_x, 'y': start_y, 'id': 1}]})
        for step in range(1, 9):
            await client.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{'x': start_x + (65 - start_x) * step / 8, 'y': start_y + (280 - start_y) * step / 8, 'id': 1}]})
        await client.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        assert await touch.locator('#xiaohang-panel').count() == 0
        touch_bounds = await assert_inside(touch)
        assert touch_bounds['left'] <= 26, touch_bounds
        await touch_launcher.tap()
        await expect(touch.locator('#xiaohang-panel')).to_be_visible()
        await touch_context.close()
        await browser.close()
    assert not errors, errors
    proof = {'cases': ['mouse drag', 'touch drag', '6px threshold', 'drag release does not click', 'edge snap', 'refresh position', 'keyboard positions', 'Home reset', 'close position retained', 'narrow viewport clamp'], 'initial': initial, 'mobile': mobile, 'page_errors': errors, 'external_calls': 0, 'project_writes': 0}
    (EVIDENCE / 'proof.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
