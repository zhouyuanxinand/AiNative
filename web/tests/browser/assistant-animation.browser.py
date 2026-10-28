"""Frame-player browser checks; no model calls and no project writes.

Run against a built platform on 18130. Uses the actual local PNG/metadata; only
assistant context is replaced. Visibility is exercised via a controlled document
visibilitychange fixture rather than claiming an operating-system background test.
"""
import asyncio
import json
from pathlib import Path
import sys

from playwright.async_api import async_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
from browser_support import ROOT, BASE, browser_options
EVIDENCE = ROOT / 'basic-service/app/runtime/xiaohang-animation-browser'
WAVE_FRAMES = set(range(4, 16))


async def sample(page):
    return await page.locator('.xiaohang-sprite').evaluate("""node => {
      const canvas = node.querySelector('canvas');
      let hash = 0;
      if (canvas) {
        const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
        for (let i = 0; i < pixels.length; i += 17) hash = ((hash * 31) + pixels[i]) >>> 0;
      }
      return {frame: Number(node.dataset.frame), playing: node.dataset.playing, hash};
    }""")


async def samples(page, duration=1.0):
    result = []
    loop = asyncio.get_running_loop()
    until = loop.time() + duration
    while loop.time() < until:
        result.append(await sample(page))
        await page.wait_for_timeout(55)
    return result


async def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    errors, chat_calls = [], []
    async with async_playwright() as p:
        browser = await p.chromium.launch(**browser_options())
        context = await browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='no-preference')
        page = await context.new_page()
        page.set_default_timeout(15000)
        page.on('pageerror', lambda error: errors.append(str(error)))

        async def context_route(route):
            await route.fulfill(json={'name': '小航', 'model_available': False, 'project': None,
                                      'role_label': '项目负责人', 'quick_actions': [], 'suggested_questions': []})

        async def refuse_chat(route):
            chat_calls.append(route.request.url)
            await route.abort()

        await page.route('**/api/assistant/context**', context_route)
        await page.route('**/api/assistant/chat', refuse_chat)
        await page.goto(BASE + '/', wait_until='networkidle')
        sprite = page.locator('.xiaohang-sprite')
        launcher = page.get_by_role('button', name='打开小航 AI 助手', exact=True)
        await expect(sprite).to_have_class('xiaohang-sprite is-ready')
        await expect(sprite.locator('canvas')).to_be_visible()
        # A single initial entrance greeting may play before quiet idle.
        await page.wait_for_timeout(2300)
        idle = await samples(page, 3.4)
        assert len({item['frame'] for item in idle}) > 1, idle
        assert len({item['hash'] for item in idle}) > 1, 'Frame metadata changes must actually change canvas pixels'

        # Only eyes/rotor/quiet frames belong to idle; frames 4..15 greet.
        idle_cycle = await samples(page, 6.6)
        assert not ({item['frame'] for item in idle_cycle} & WAVE_FRAMES), 'Idle must not accidentally play waving-hand frames'

        await page.emulate_media(reduced_motion='reduce')
        await expect(sprite).to_have_attribute('data-playing', 'false')
        reduced = await samples(page, .5)
        assert len({(item['frame'], item['hash']) for item in reduced}) == 1, reduced
        await launcher.hover()
        reduced_hover = await samples(page, .5)
        assert len({(item['frame'], item['hash']) for item in reduced_hover}) == 1
        await page.mouse.move(0, 0)
        await page.emulate_media(reduced_motion='no-preference')
        await expect(sprite).to_have_attribute('data-playing', 'true')
        await launcher.hover()
        greeting = await samples(page, 2.4)
        assert {item['frame'] for item in greeting} & WAVE_FRAMES, 'One hover should play a greeting'
        assert greeting[-1]['frame'] not in WAVE_FRAMES, 'Greeting must return to idle'

        # Pause/resume should not reuse an already-consumed hover greeting.
        box = await launcher.bounding_box()
        await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + 64)
        await page.mouse.down()
        await page.mouse.move(box['x'] + box['width'] / 2 - 55, box['y'] + 5, steps=6)
        await expect(sprite).to_have_attribute('data-playing', 'false')
        paused = await samples(page, .35)
        assert len({(item['frame'], item['hash']) for item in paused}) == 1
        await page.mouse.up()
        await page.mouse.move(0, 0)
        await expect(sprite).to_have_attribute('data-playing', 'true')
        resumed = await samples(page, 1.6)
        assert not ({item['frame'] for item in resumed} & WAVE_FRAMES), 'Drag resume must not replay a prior hover greeting'
        assert await page.locator('#xiaohang-panel').count() == 0

        await page.evaluate("""() => {
          window.__animationVisibility = 'hidden';
          Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => window.__animationVisibility});
          document.dispatchEvent(new Event('visibilitychange'));
        }""")
        await expect(sprite).to_have_attribute('data-playing', 'false')
        hidden = await samples(page, .4)
        assert len({(item['frame'], item['hash']) for item in hidden}) == 1
        await page.evaluate("""() => {
          window.__animationVisibility = 'visible'; document.dispatchEvent(new Event('visibilitychange'));
        }""")
        await expect(sprite).to_have_attribute('data-playing', 'true')
        visible = await samples(page, 1.6)
        assert not ({item['frame'] for item in visible} & WAVE_FRAMES), 'Visibility resume must not replay a prior hover greeting'

        await launcher.focus()
        await launcher.press('Enter')
        await expect(page.locator('#xiaohang-panel')).to_be_visible()
        assert await page.locator('.xiaohang-sprite').count() == 0
        await page.get_by_role('button', name='收起小航对话', exact=True).click()
        await expect(sprite).to_have_class('xiaohang-sprite is-ready')
        await expect(launcher).to_be_focused()
        await page.screenshot(path=str(EVIDENCE / 'sprite-launcher.png'))

        await context.close()
        fallback_context = await browser.new_context(viewport={'width': 390, 'height': 844})
        fallback = await fallback_context.new_page()
        fallback.on('pageerror', lambda error: errors.append(str(error)))
        await fallback.route('**/assets/xiaohang-idle-sprite.png', lambda route: route.fulfill(status=404, body='asset unavailable'))
        await fallback.route('**/api/assistant/context**', context_route)
        await fallback.route('**/api/assistant/chat', refuse_chat)
        await fallback.goto(BASE + '/', wait_until='networkidle')
        fallback_sprite = fallback.locator('.xiaohang-sprite')
        image = fallback_sprite.locator('img[src="/assets/xiaohang.png"]')
        await expect(image).to_be_visible()
        assert await image.evaluate('image => image.complete && image.naturalWidth > 0')
        assert await fallback_sprite.locator('canvas').count() == 0
        await expect(fallback_sprite).to_have_attribute('data-playing', 'false')
        await fallback.screenshot(path=str(EVIDENCE / 'static-fallback-mobile.png'))
        await fallback_context.close()
        await browser.close()

    assert not errors, errors
    assert not chat_calls, chat_calls
    proof = {'cases': ['actual local sprite decoded', 'canvas pixels change', 'quiet idle excludes wave',
                       'reduced motion remains static', 'hover greeting then idle', 'drag pause',
                       'drag resume consumes prior greeting', 'visibilitychange fixture pause/resume',
                       'sidebar keyboard open/close', 'missing sprite static fallback'],
             'idle_frames': sorted({item['frame'] for item in idle_cycle}),
             'greeting_frames': sorted({item['frame'] for item in greeting}),
             'page_errors': errors, 'model_calls': 0, 'project_writes': 0}
    (EVIDENCE / 'proof.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
