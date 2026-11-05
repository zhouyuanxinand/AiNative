/** Real pointer dragging against the isolated companion; no live business/model API. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const output = process.env.SCREENSHOT_DIR || '../runtime/xiaohang-free-drag';
await mkdir(output, { recursive: true });
const checks = [], errors = [], unexpected = [];
const positionKey = 'rd-xiaohang-launcher-position-v1';
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, hasTouch: true });
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'local:drag-fixture', local_mode: true } });
    if (path === '/api/rd/assistant/weather') return route.fulfill({ json: { status: 'unavailable', location: '隔离拖拽验证', notice: '此验证不读取天气' } });
    if (path === '/api/rd/assistant/conversations') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20, active_id: null } });
    unexpected.push(path); return route.fulfill({ status: 500, json: { error: 'Unexpected fixture request' } });
  });
  const launcher = page.getByRole('button', { name: '打开小航助手', exact: true });
  const open = async () => {
    await page.goto(`${process.env.BASE_URL || 'http://127.0.0.1:18370'}/tests/fixtures/xiaohang-companion.html`);
    await launcher.waitFor();
    await page.waitForFunction(() => document.querySelector('.xiaohang-sprite')?.dataset.playing === 'true');
  };
  const closeEnough = (actual, expected, message) => assert(Math.abs(actual.x - expected.x) <= 1 && Math.abs(actual.y - expected.y) <= 1, `${message}: ${JSON.stringify({ actual, expected })}`);
  const resize = async (width, height) => {
    await page.setViewportSize({ width, height });
    // Commit the resize/ResizeObserver layout before aiming a raw pointer at the character.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  };
  const drag = async (x, y) => {
    const box = await launcher.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down(); await page.mouse.move(x, y, { steps: 8 });
    const beforeRelease = await launcher.boundingBox();
    await page.mouse.up();
    return beforeRelease;
  };
  const cases = process.env.TEST_CASE ? [process.env.TEST_CASE] : ['free', 'bounds', 'keyboard', 'legacy', 'touch', 'weather'];
  for (const scenario of cases) {
    assert(['free', 'bounds', 'keyboard', 'legacy', 'touch', 'weather'].includes(scenario));
    await open();
    if (scenario === 'free') {
      const released = await drag(600, 420);
      closeEnough(await launcher.boundingBox(), released, 'releasing in the middle keeps the dropped position instead of snapping to an edge');
      assert.equal(await page.locator('.rd-floating-panel').isVisible(), false, 'dragging must not open chat');
      const saved = await page.evaluate(key => localStorage.getItem(key), positionKey);
      await open();
      closeEnough(await launcher.boundingBox(), released, 'refresh restores both coordinates');
      await launcher.click(); await page.getByRole('textbox', { name: '问问小航' }).waitFor();
      await page.getByRole('button', { name: '收起小航助手', exact: true }).click();
      await launcher.waitFor(); closeEnough(await launcher.boundingBox(), released, 'chat close retains the free position');
      await resize(1000, 720);
      const resized = await launcher.boundingBox();
      assert(resized.x > 150 && resized.x < 700 && resized.y > 100 && resized.y < 550, 'resize preserves an interior placement');
      assert.equal(await page.evaluate(key => localStorage.getItem(key), positionKey), saved, 'resize does not overwrite saved placement');
      await resize(1440, 1000);
      closeEnough(await launcher.boundingBox(), released, 'restoring viewport restores the chosen placement');
      await page.screenshot({ path: join(output, 'desktop-free-placement.png') });
      checks.push('middle drop, refresh, chat close and resize retain free placement without unintended chat');
    }
    if (scenario === 'bounds') {
      for (const width of [1440, 390, 320]) {
        await resize(width, 800);
        const size = (await launcher.boundingBox()).height;
        await drag(width / 2, size / 2 + 24);
        let box = await launcher.boundingBox();
        assert(box.y <= 25, `${width}: character can be placed near the top: ${JSON.stringify(box)}`);
        const greeting = await page.locator('.rd-floating-launcher-label').boundingBox();
        assert(greeting.x >= 0 && greeting.y >= 0 && greeting.x + greeting.width <= width && greeting.y + greeting.height <= 800, 'top greeting fits in the viewport');
        assert(greeting.y >= box.y + box.height, 'greeting moves below a character placed near the top');
        await page.screenshot({ path: join(output, `top-${width}.png`) });
        await drag(width / 2, 800 - size / 2 - 24);
        box = await launcher.boundingBox();
        assert(Math.abs(800 - box.y - box.height - 24) <= 1, `${width}: no reserved bottom strip prevents placement`);
        assert.equal(await page.getByRole('button', { name: '唤回小航助手' }).count(), 0);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      }
      await resize(1440, 1000);
      checks.push('top/bottom placement and visible greeting at desktop, 390px and 320px');
    }
    if (scenario === 'keyboard') {
      await drag(700, 500);
      const before = await launcher.boundingBox();
      await launcher.press('ArrowLeft');
      closeEnough(await launcher.boundingBox(), { x: before.x - 24, y: before.y }, 'left arrow moves a step instead of snapping');
      await launcher.press('Shift+ArrowRight');
      closeEnough(await launcher.boundingBox(), { x: before.x + 48, y: before.y }, 'shift/right uses a larger step');
      await launcher.press('ArrowUp');
      closeEnough(await launcher.boundingBox(), { x: before.x + 48, y: before.y - 24 }, 'up keeps the free horizontal coordinate');
      checks.push('all arrow keys move incrementally at a free position');
    }
    if (scenario === 'legacy') {
      await page.evaluate(key => localStorage.setItem(key, JSON.stringify({ edge: 'left', y: .5, hidden: true })), positionKey);
      await page.reload();
      const dock = page.getByRole('button', { name: '唤回小航助手', exact: true });
      await dock.waitFor(); await dock.click(); await launcher.waitFor();
      assert((await launcher.boundingBox()).x < 60, 'old hidden anchor is restored on its original side');
      await drag(600, 420);
      assert((await launcher.boundingBox()).x > 400, 'old anchors can be moved freely after recall');
      await drag(5, 300); await dock.waitFor();
      await page.reload(); await dock.waitFor();
      await dock.press('Home'); await launcher.waitFor();
      assert((await launcher.boundingBox()).x > 1200, 'Home still restores the default corner');
      checks.push('old hidden preference, free move after recall, explicit edge hiding, refresh and Home');
    }
    if (scenario === 'touch') {
      await resize(390, 800);
      const box = await launcher.boundingBox();
      const session = await page.context().newCDPSession(page);
      await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: box.x + box.width / 2, y: box.y + box.height / 2, id: 1 }] });
      await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 180, y: 350, id: 1 }] });
      await page.waitForFunction(() => document.querySelector('.rd-floating-assistant')?.classList.contains('is-dragging'));
      const beforeRelease = await launcher.boundingBox();
      closeEnough(beforeRelease, { x: 180 - box.width / 2, y: 350 - box.height / 2 }, 'touch movement reaches the requested interior point');
      await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      closeEnough(await launcher.boundingBox(), beforeRelease, 'touch release also retains an interior placement');
      assert.equal(await page.locator('.rd-floating-panel').isVisible(), false, 'touch drag must not become a tap');
      await session.detach();
      checks.push('real touch drag keeps free position without opening chat');
    }
    if (scenario === 'weather') {
      await resize(900, 320);
      const size = (await launcher.boundingBox()).height;
      for (const targetY of [320 - size / 2 - 24, size / 2 + 24]) {
        await drag(450, targetY);
        await page.mouse.move(0, 0); await launcher.hover();
        const weather = page.locator('.rd-weather-nudge'); await weather.waitFor();
        const box = await weather.boundingBox();
        assert(box.x >= 0 && box.y >= 0 && box.x + box.width <= 900 && box.y + box.height <= 320, `weather must stay visible after moving near either short-window edge: ${JSON.stringify(box)}`);
        await page.screenshot({ path: join(output, targetY > 160 ? 'weather-short-bottom.png' : 'weather-short-top.png') });
        await page.mouse.move(0, 0); await weather.waitFor({ state: 'hidden' });
      }
      checks.push('hover weather fits above or below the freely placed character in a 320px-high window');
    }
  }
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
  const receipt = { passed: true, checks, errors, unexpected, realApiRequests: 0 };
  await writeFile(join(output, 'receipt.json'), JSON.stringify(receipt, null, 2)); console.log(JSON.stringify(receipt));
} finally { await browser.close(); }
