/** Real settings UI, synthetic transport: never changes live credentials or calls a model. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
const screenshotDir = process.env.SCREENSHOT_DIR;
if (screenshotDir) await mkdir(screenshotDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const gateways = {
  public: { base_url: 'https://public.example/open/', app_id: 'test-public', api_key: 'synthetic-public-secret', tenant_id: 'test-tenant' },
  internal: { base_url: 'http://internal.example/open/', app_id: 'test-internal', api_key: 'synthetic-internal-secret', tenant_id: 'test-internal-tenant' },
};
let active = 'public';
let mode = 'success';
let held;
const probes = [], catalogs = [], mutations = [], errors = [];
const models = [
  { model: 'deepseek-v4-flash', id: 'ds-test-id', provider: 'smartvision', vendor: '测试网关', configured: true },
  { model: 'qwen3.8', id: 'qwen-test-id', provider: 'smartvision', vendor: '测试网关', configured: true },
];
const stamp = '2026-09-21T08:00:00Z';
function settings() {
  return { defaults: { model: gateways.public }, effective: { model: gateways[active] },
    overridden: active === 'public' ? [] : ['model'],
    history: Object.entries(gateways).map(([id, item]) => ({ id, name: id === 'public' ? '测试外网' : '测试内网',
      base_url: item.base_url, app_id: item.app_id, tenant_id: item.tenant_id,
      created_at: stamp, last_used_at: stamp, source: 'saved', active: id === active })) };
}
const success = model => ({ success: true, model, response_time_ms: 1234, checked_at: stamp, message: '模型已返回有效响应。' });
async function releaseHeld() {
  const current = held;
  held = undefined;
  if (current) {
    current.release();
    await current.done;
  }
}
async function waitForHeld() {
  for (let attempt = 0; attempt < 100 && !held; attempt++) await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(held, 'the pending test reached the transport');
}
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000);
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/api/settings/credentials**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    assert.equal(request.headers()['x-credential-settings'], '1');
    if (path.endsWith('/test/models')) {
      catalogs.push(request.postDataJSON());
      if (mode === 'catalog-error') return route.fulfill({ json: { success: false, models: [], response_time_ms: 105,
        checked_at: stamp, message: '鉴权失败，请检查 App ID、API Key 和租户 ID。', error_code: 'authentication_failed' } });
      return route.fulfill({ json: { success: true, models, response_time_ms: 87, checked_at: stamp, message: '已读取模型列表。' } });
    }
    if (path.endsWith('/test')) {
      const body = request.postDataJSON();
      probes.push(body);
      if (mode === 'hold') {
        let release;
        const wait = new Promise(resolve => { release = resolve; });
        let resolveDone;
        const done = new Promise(resolve => { resolveDone = resolve; });
        held = { release, done };
        await wait;
        try { await route.fulfill({ json: success(body.model) }); } catch { /* Request may already be cancelled. */ }
        resolveDone();
        return;
      }
      if (mode === 'failure') return route.fulfill({ json: { success: false, model: body.model,
        response_time_ms: 265, checked_at: stamp, message: '鉴权失败，请检查 App ID、API Key 和租户 ID。', error_code: 'authentication_failed' } });
      return route.fulfill({ json: success(body.model) });
    }
    if (path.endsWith('/activate')) {
      mutations.push(path);
      active = path.split('/').at(-2);
      return route.fulfill({ json: settings() });
    }
    assert.equal(request.method(), 'GET', 'probing must never save settings');
    return route.fulfill({ json: settings() });
  });
  await page.route('**/api/models', route => route.fulfill({ json: { success: true, models } }));
  await page.route('**/api/llm/status?*', route => route.fulfill({ json: { configured: true, provider: 'smartvision', model: models[0].model } }));
  await page.goto(base);
  const trigger = page.getByRole('button', { name: '服务凭证设置', exact: true });
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: '服务凭证设置' });
  const section = dialog.getByRole('region', { name: '模型连通性与响应时间' });
  const name = section.getByLabel('模型名称', { exact: true });
  const test = section.getByRole('button', { name: '测试连通性', exact: true });
  const catalog = section.getByRole('button', { name: '读取模型列表', exact: true });
  const result = section.locator('.credentials-probe-result');
  await name.waitFor();
  assert.equal(probes.length, 0);
  assert.equal(catalogs.length, 0, 'opening settings does not initiate a network test');
  await catalog.click();
  const picker = section.locator('#model-test-selection-native');
  const pickerTrigger = section.locator('#model-test-selection');
  await pickerTrigger.waitFor();
  assert.deepEqual(catalogs[0].credentials, { model: null });
  assert.equal(await picker.evaluate(element => getComputedStyle(element).opacity), '0');
  await pickerTrigger.click();
  const modelMenu = dialog.locator('#model-test-selection-menu');
  const modelOption = modelMenu.getByRole('option', { name: /qwen3\.8/ });
  await modelOption.waitFor();
  const menuBox = await modelMenu.boundingBox();
  const dialogBox = await dialog.boundingBox();
  assert.ok(menuBox && dialogBox && menuBox.y >= dialogBox.y && menuBox.y + menuBox.height <= dialogBox.y + dialogBox.height,
    'the styled menu stays inside the dialog instead of being clipped by its scroll body');
  if (screenshotDir) await page.screenshot({ path: join(screenshotDir, 'model-select-menu-desktop.png') });
  await modelOption.click();
  await test.click();
  await result.filter({ hasText: '模型已返回有效响应' }).waitFor();
  assert.equal(await result.getAttribute('data-status'), 'success');
  assert.deepEqual(probes[0].credentials, { model: null });
  assert.equal(probes[0].model, 'qwen3.8');
  assert.equal(probes[0].model_id, 'qwen-test-id');
  assert.match(await result.innerText(), /1\.23|1,234|1234/);
  assert.equal(mutations.length, 0);

  await name.fill('qwen3.6');
  assert.equal(await result.count(), 0, 'old result is invalid after changing model');
  await test.click();
  await result.waitFor();
  assert.equal(probes.at(-1).model_id || '', '', 'manual model cannot inherit the previous model ID');
  await dialog.getByLabel('API Key', { exact: true }).fill('synthetic-draft-secret');
  assert.equal(await result.count(), 0);
  assert.equal(await section.getByLabel('选择可用模型').count(), 0, 'credential editing invalidates the catalog');
  await name.fill('deepseek-v4-flash');
  mode = 'failure';
  await test.click();
  await result.filter({ hasText: '鉴权失败' }).waitFor();
  assert.equal(await result.getAttribute('data-status'), 'error');
  assert.equal(probes.at(-1).credentials.model.api_key, 'synthetic-draft-secret');
  assert.equal(await dialog.getByLabel('API Key', { exact: true }).getAttribute('type'), 'password');
  mode = 'success';
  await test.click();
  await result.filter({ hasText: '模型已返回有效响应' }).waitFor();

  // A late success must not attach itself to edited credentials.
  mode = 'hold';
  await test.click();
  await section.getByRole('button', { name: '正在测试…', exact: true }).waitFor();
  await waitForHeld();
  assert.equal(await section.getByRole('button', { name: '正在测试…', exact: true }).isDisabled(), true);
  await dialog.getByLabel('租户 ID（Tenant ID）').fill('changed-tenant');
  await releaseHeld();
  assert.equal(await result.count(), 0);
  await name.fill('deepseek-v4-flash');
  await test.click();
  await waitForHeld();
  await section.getByRole('button', { name: '取消测试', exact: true }).click();
  await releaseHeld();
  assert.equal(await result.count(), 0);
  assert.equal(await test.isEnabled(), true);

  await dialog.locator('#credentials-history-picker').click();
  await dialog.locator('#credentials-history-picker-menu').getByRole('option', { name: /测试内网/ }).click();
  await dialog.getByRole('button', { name: '使用此凭证', exact: true }).click();
  await dialog.getByRole('button', { name: '放弃修改并切换', exact: true }).click();
  await dialog.getByRole('status').filter({ hasText: '已切换到“测试内网”' }).waitFor();
  assert.equal(await result.count(), 0);
  mode = 'catalog-error';
  await catalog.click();
  await section.locator('.credentials-probe-catalog').filter({ hasText: '鉴权失败' }).waitFor();
  assert.equal(catalogs.at(-1).credentials.model.base_url, gateways.internal.base_url);
  await name.fill('deepseek-v4-flash');
  mode = 'success';
  await test.click();
  await result.filter({ hasText: '模型已返回有效响应' }).waitFor();
  assert.equal(probes.at(-1).credentials.model.api_key, gateways.internal.api_key);
  if (screenshotDir) {
    await result.scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(screenshotDir, 'model-probe-desktop.png') });
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await result.scrollIntoViewIfNeeded();
  const bounds = await dialog.boundingBox();
  assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 390);
  assert.equal(await dialog.evaluate(el => el.scrollWidth > el.clientWidth), false);
  assert.equal(await section.evaluate(el => el.scrollWidth > el.clientWidth), false);
  if (screenshotDir) await page.screenshot({ path: join(screenshotDir, 'model-probe-mobile.png') });
  mode = 'hold';
  await test.click();
  await waitForHeld();
  await section.getByRole('button', { name: '取消测试', exact: true }).waitFor();
  await dialog.getByRole('button', { name: '关闭凭证设置' }).click();
  await releaseHeld();
  await dialog.waitFor({ state: 'detached' });
  await trigger.click();
  await name.waitFor();
  assert.equal(await result.count(), 0, 'closing and reopening never retains an old success');
  assert.equal(await page.evaluate(() => [...Object.values(localStorage), ...Object.values(sessionStorage)]
    .some(item => /synthetic-.*secret/.test(item))), false);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ passed: true, tests: ['draft/default isolation', 'catalog vs generation', 'model identity',
    'failure and retry', 'credential edits clear stale responses', 'cancel and close', 'history switching',
    'manual model when catalog fails', 'desktop/mobile', 'no browser credential storage'],
    probes: probes.length, catalogs: catalogs.length, historySwitches: mutations.length }));
} finally {
  await releaseHeld();
  await browser.close();
}
