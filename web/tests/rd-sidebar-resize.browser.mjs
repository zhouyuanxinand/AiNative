/** Sidebar geometry only. All API responses are fixtures; no real business requests. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const errors = [], unexpected = [], checks = [];
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, hasTouch: true });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (route.request().method() !== 'GET') {
      unexpected.push(`${route.request().method()} ${path}`);
      return route.fulfill({ status: 503, json: { error: 'No writes in sidebar fixture' } });
    }
    if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: true, authenticated: true, user: { userid: 'sidebar-fixture', name: '测试工程师长姓名', display_name: '测试工程师长姓名', source: 'smartvision', verified: true } } });
    if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'sidebar-fixture', local_mode: false } });
    if (path === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [], actions: [], workpackage_definitions: [] } });
    if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [] } });
    if (path === '/api/rd/assistant/weather') return route.fulfill({ status: 503, json: { error: 'Weather disabled in layout fixture' } });
    unexpected.push(`GET ${path}`);
    return route.fulfill({ status: 503, json: { error: 'Unexpected fixture request' } });
  });
  await page.goto(base);
  const handle = page.getByRole('separator', { name: '调整侧栏宽度' });
  const sidebar = page.locator('.rd-sidebar');
  const collapse = () => page.getByRole('button', { name: '收起侧栏', exact: true });
  const expand = () => page.getByRole('button', { name: '展开侧栏', exact: true });
  const waitWidth = expected => page.waitForFunction(expected => Math.abs(document.querySelector('.rd-sidebar').getBoundingClientRect().width - expected) < 1, expected);
  const savedWidth = () => page.evaluate(() => localStorage.getItem('rd.sidebar.width.v1'));
  const geometry = () => page.evaluate(() => {
    const rail = document.querySelector('.rd-sidebar').getBoundingClientRect();
    const main = document.querySelector('.rd-main').getBoundingClientRect();
    const shell = document.querySelector('.rd-application-shell');
    return { rail: rail.width, main: main.width, mainX: main.x, client: shell.clientWidth, overflow: shell.scrollWidth > shell.clientWidth + 1 };
  });
  async function drag(delta) {
    const box = await handle.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + delta, box.y + box.height / 2, { steps: 8 });
    await page.mouse.up();
  }

  await handle.waitFor().catch(async error => { console.error({ pageErrors: errors, unexpectedRequests: unexpected, body: (await page.locator('body').innerText()).slice(0, 1800) }); throw error; });
  await waitWidth(216);
  assert.equal(await handle.getAttribute('aria-orientation'), 'vertical');
  assert.equal(await handle.getAttribute('aria-valuemin'), '200');
  assert.equal(await handle.getAttribute('aria-valuemax'), '360');
  await drag(84); await waitWidth(300);
  assert.equal(await savedWidth(), '300');
  const wide = await geometry();
  assert.equal(wide.mainX, 300); assert.equal(wide.overflow, false);
  await collapse().click(); await waitWidth(64);
  assert.equal(await handle.count(), 0); assert.equal(await savedWidth(), '300');
  await expand().click(); await waitWidth(300);
  await page.reload(); await waitWidth(300);
  checks.push('mouse drag updates both columns; collapse stays 64px; expansion and reload restore saved width');

  await drag(900); await waitWidth(360);
  await drag(-900); await waitWidth(200);
  for (const name of ['退出登录', '系统管理']) {
    const action = page.getByRole('button', { name, exact: true });
    await action.waitFor();
    assert(await action.evaluate(element => { const a = element.getBoundingClientRect(), s = element.closest('.rd-sidebar').getBoundingClientRect(); return a.x >= s.x && a.right <= s.right && a.bottom <= innerHeight; }), `${name} stays inside the minimum-width rail`);
  }
  assert(await page.locator('.rd-brand img').evaluate(image => image.getBoundingClientRect().right + 7 <= document.querySelector('.rd-sidebar-toggle').getBoundingClientRect().left), 'brand and collapse control do not overlap');
  await handle.focus(); await page.keyboard.press('ArrowRight'); await waitWidth(208);
  await page.keyboard.press('ArrowLeft'); await waitWidth(200);
  await page.keyboard.press('Home'); await waitWidth(216);
  assert.equal(await savedWidth(), '216');
  await page.keyboard.press('End'); await waitWidth(360);
  assert.equal(await handle.getAttribute('aria-valuenow'), '360');
  checks.push('200–360px limits preserve account controls; keyboard arrows, Home and End expose accurate ARIA values');

  await page.setViewportSize({ width: 800, height: 700 });
  await page.waitForFunction(() => {
    const shell = document.querySelector('.rd-application-shell');
    return Math.abs(document.querySelector('.rd-sidebar').getBoundingClientRect().width - (shell.clientWidth - 480)) < 1;
  });
  const constrained = await geometry();
  assert(constrained.main >= 480); assert.equal(constrained.overflow, false); assert.equal(await savedWidth(), '360');
  assert.equal(Number(await handle.getAttribute('aria-valuemax')), constrained.rail);
  await page.setViewportSize({ width: 701, height: 650 });
  await page.waitForFunction(() => Number(document.querySelector('.rd-sidebar-resizer')?.getAttribute('aria-valuemax')) <= 221);
  assert((await geometry()).main >= 480);
  await page.setViewportSize({ width: 700, height: 650 });
  await handle.waitFor({ state: 'detached' });
  assert.equal(await sidebar.evaluate(element => getComputedStyle(element).position), 'static');
  assert.equal((await geometry()).overflow, false);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await handle.count(), 0); assert.equal((await geometry()).overflow, false);
  if (output) await page.screenshot({ path: join(output, 'sidebar-mobile.png') });
  await page.setViewportSize({ width: 1440, height: 1000 }); await waitWidth(360);
  checks.push('constrained desktop retains 480px main content without overwriting preference; 700px/mobile keeps top navigation');

  await handle.focus(); await page.keyboard.press('Home'); await waitWidth(216);
  let box = await handle.boundingBox();
  await page.mouse.move(box.x + 6, box.y + 300); await page.mouse.down();
  await page.mouse.move(box.x + 66, box.y + 300); await waitWidth(276);
  await page.keyboard.press('Escape'); await page.mouse.up(); await waitWidth(216);
  assert.equal(await savedWidth(), '216');
  assert.equal(await page.locator('.is-sidebar-resizing').count(), 0);
  await drag(80); await waitWidth(296);
  await handle.dblclick(); await waitWidth(216);

  const cdp = await page.context().newCDPSession(page);
  box = await handle.boundingBox();
  const touch = { x: box.x + 6, y: box.y + 300, id: 1 };
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [touch] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ ...touch, x: touch.x + 64 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await waitWidth(280); assert.equal(await savedWidth(), '280');
  box = await handle.boundingBox();
  const cancelledTouch = { x: box.x + 6, y: box.y + 300, id: 2 };
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [cancelledTouch] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ ...cancelledTouch, x: cancelledTouch.x + 40 }] });
  await waitWidth(320);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchCancel', touchPoints: [] });
  await waitWidth(280); assert.equal(await savedWidth(), '280');
  checks.push('Escape and touch cancellation restore previous width; double click resets; real touch pointer capture commits correctly');
  if (output) await page.screenshot({ path: join(output, 'sidebar-desktop.png') });
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
  const receipt = { passed: true, checks, pageErrors: errors, unexpectedRequests: unexpected, realApiRequests: 0 };
  if (output) await writeFile(join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt));
} finally { await browser.close(); }
