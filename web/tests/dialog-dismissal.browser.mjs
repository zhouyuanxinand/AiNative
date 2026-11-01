/** Dialog dismissal uses synthetic settings; no real credentials are read or written. */
import assert from 'node:assert/strict';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const model = { model: { base_url: 'https://example.invalid/', app_id: 'test', api_key: 'synthetic-key', tenant_id: 'test' } };
const auth = { enabled: false, app_id: 9086, platform_base_url: 'https://example.invalid', public_url: null };
let savingStarted = false, releaseSave;
const saveGate = new Promise(resolve => { releaseSave = resolve; });
const errors = [];

async function outside(page, dialog, button = 'left') {
  const box = await dialog.boundingBox();
  assert(box && box.x > 1, 'dialog leaves a clickable backdrop');
  await page.mouse.click(box.x / 2, box.y + box.height / 2, { button });
}
async function closed(dialog) { await dialog.waitFor({ state: 'hidden' }); }

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, hasTouch: true });
  page.setDefaultTimeout(5000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/settings/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path === '/api/settings/credentials') {
      if (request.method() !== 'GET') { savingStarted = true; await saveGate; }
      return route.fulfill({ json: { defaults: model, effective: model, overridden: [], history: [] } });
    }
    if (path === '/api/settings/auth') return route.fulfill({ json: { settings: auth, active: auth, can_edit: true, version: 1, requires_restart: false, presets: { intranet: auth, external: auth } } });
    return route.fulfill({ status: 503, json: { error: 'Synthetic test only' } });
  });
  await page.route('**/api/models', route => route.fulfill({ json: { success: true, models: [] } }));
  await page.goto(`${base}/?rd_view=system`);
  const trigger = page.getByRole('button', { name: '服务凭证设置', exact: true });
  const credentials = page.getByRole('dialog', { name: '服务凭证设置', exact: true });
  await trigger.click();
  await credentials.getByLabel('API Key', { exact: true }).waitFor();
  // The screenshot's unedited settings dialog must close from the backdrop.
  await outside(page, credentials);
  await closed(credentials);
  assert(await trigger.evaluate(e => e === document.activeElement), 'focus returns to trigger');

  await trigger.click();
  await credentials.getByLabel('API Key', { exact: true }).waitFor();
  let box = await credentials.boundingBox();
  await page.mouse.click(box.x + 10, box.y + 10); // Interior padding, not a control.
  assert(await credentials.isVisible(), 'inside whitespace keeps dialog open');
  await page.mouse.move(box.x + 10, box.y + 10);
  await page.mouse.down();
  await page.mouse.move(box.x / 2, box.y + box.height / 2);
  await page.mouse.up();
  assert(await credentials.isVisible(), 'drag from inside to outside does not dismiss');
  await outside(page, credentials, 'right');
  assert(await credentials.isVisible(), 'secondary click does not dismiss');
  await page.keyboard.press('Escape'); // Dismiss a browser context menu if present.
  if (!await credentials.isVisible()) { await trigger.click(); await credentials.getByLabel('API Key', { exact: true }).waitFor(); }

  const key = credentials.getByLabel('API Key', { exact: true });
  await key.fill('synthetic-unsaved');
  await outside(page, credentials);
  await credentials.getByText('尚有未保存的修改，是否放弃？').waitFor();
  await credentials.getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(await key.inputValue(), 'synthetic-unsaved');

  await credentials.getByRole('button', { name: '统一登录设置', exact: true }).click();
  const login = page.getByRole('dialog', { name: '统一登录设置', exact: true });
  await login.getByLabel('登录应用 ID', { exact: true }).waitFor();
  await outside(page, login);
  await closed(login);
  assert(await credentials.isVisible(), 'only topmost dialog closes');
  assert.equal(await key.inputValue(), 'synthetic-unsaved');
  assert.equal(await credentials.getByText('尚有未保存的修改，是否放弃？').count(), 0, 'nested backdrop does not ask parent to close');

  await credentials.getByRole('button', { name: '统一登录设置', exact: true }).click();
  await login.getByLabel('登录应用 ID', { exact: true }).fill('123');
  await outside(page, login);
  await login.getByRole('button', { name: '放弃修改', exact: true }).waitFor();
  await login.getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(await login.getByLabel('登录应用 ID', { exact: true }).inputValue(), '123');
  await page.keyboard.press('Escape');
  await login.getByRole('button', { name: '放弃修改', exact: true }).click();
  await closed(login);

  await credentials.getByRole('button', { name: '保存凭证', exact: true }).click();
  await credentials.getByRole('button', { name: '正在保存…', exact: true }).waitFor();
  assert(savingStarted);
  await outside(page, credentials);
  assert(await credentials.isVisible(), 'pending save cannot be dismissed');
  releaseSave();
  await credentials.getByRole('button', { name: '关闭', exact: true }).waitFor();
  await outside(page, credentials); await closed(credentials);

  await page.getByRole('button', { name: '我的工作', exact: true }).click();
  await page.getByRole('button', { name: '新建项目', exact: true }).click();
  const create = page.getByRole('dialog', { name: '新建项目', exact: true });
  await create.waitFor();
  await outside(page, create); await closed(create);
  await page.getByRole('button', { name: '新建项目', exact: true }).click();
  await create.getByLabel('项目名称', { exact: false }).fill('未保存测试项目');
  await outside(page, create);
  const discard = page.getByRole('dialog', { name: '关闭当前创建', exact: true });
  await discard.waitFor();
  await outside(page, discard); await closed(discard);
  assert.equal(await create.getByLabel('项目名称', { exact: false }).inputValue(), '未保存测试项目', 'cancel confirmation preserves draft');
  await outside(page, create);
  await discard.getByRole('button', { name: '关闭创建', exact: true }).click();
  await closed(create);

  await page.getByRole('button', { name: '打开小航助手', exact: true }).click();
  const assistant = page.getByRole('dialog', { name: '小航助手', exact: true });
  await assistant.getByText('你好，我是小航').click();
  assert(await assistant.isVisible());
  await page.getByRole('heading', { name: '最近项目', exact: true }).click();
  await closed(assistant);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '系统管理', exact: true }).click();
  await trigger.click(); await credentials.getByLabel('API Key', { exact: true }).waitFor();
  box = await credentials.boundingBox();
  await page.touchscreen.tap(box.x / 2, box.y + box.height / 2);
  await closed(credentials);
  assert.deepEqual(errors, []);
  console.log('PASS: settings, nested login, shared create/confirmation, assistant, mobile; inside/drag/right-click, unsaved draft, busy save, focus and Escape preserved.');
} finally { releaseSave(); await browser.close(); }
