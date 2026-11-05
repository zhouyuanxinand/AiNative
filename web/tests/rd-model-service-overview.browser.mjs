/** Settings summary and explicit probes with every /api request isolated. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const stamp = '2026-11-05T08:00:00Z';
const credentials = { model: { base_url: 'https://summary.example.invalid', app_id: 'test-app', tenant_id: 'test-tenant', api_key: 'synthetic-summary-secret' } };
const models = ['model-one', 'model-two'].map((model, index) => ({ model, id: `id-${index}`, provider: 'test', vendor: '测试服务', configured: true }));
let selection = { name: models[0].model, id: models[0].id, provider: 'test' };
let activeId = 'one', failRead = true, failProbe = false, requiresSelection = false;
const writes = [], errors = [], unknown = [];
const settings = () => ({ defaults: credentials, effective: credentials, overridden: ['model'], history: ['one', 'two'].map(id => ({
  id, name: id === 'one' ? '测试环境一' : '测试环境二', base_url: credentials.model.base_url, app_id: 'test-app', tenant_id: 'test-tenant',
  created_at: stamp, last_used_at: null, active: id === activeId, source: 'saved',
})) });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(10000);
page.on('pageerror', error => errors.push(error.message));
await page.route('**/api/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname;
  if (!path.startsWith('/api/')) return route.continue();
  if (request.method() !== 'GET') writes.push(path);
  if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
  if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'local:summary-test', local_mode: true } });
  if (path === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [], actions: [], workpackage_definitions: [] } });
  if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [] } });
  if (path === '/api/rd/assistant/weather') return route.fulfill({ json: { status: 'unavailable', location: '隔离验证' } });
  if (path === '/api/models') return route.fulfill({ json: { success: true, models } });
  if (path === '/api/settings/credentials/default-model') {
    if (request.method() === 'PUT') selection = request.postDataJSON();
    return route.fulfill({ json: { selection, source: 'settings', requires_selection: !selection || requiresSelection } });
  }
  if (path === '/api/settings/credentials') return route.fulfill(failRead ? { status: 503, json: { error: 'not available' } } : { json: settings() });
  if (path.endsWith('/test/models')) return route.fulfill({ json: { success: true, models, response_time_ms: 10, checked_at: stamp, message: '已读取' } });
  if (path.endsWith('/credentials/test')) return route.fulfill({ json: { success: !failProbe, model: request.postDataJSON().model, response_time_ms: 321,
    checked_at: stamp, message: failProbe ? 'synthetic-raw-error-secret' : '测试完成' } });
  if (path.endsWith('/two/activate')) { activeId = 'two'; return route.fulfill({ json: settings() }); }
  unknown.push(`${request.method()} ${path}`);
  return route.fulfill({ status: 503, json: { error: 'Unexpected isolated request' } });
});

try {
  await page.goto(base + '/settings');
  const summary = page.getByLabel('模型服务摘要', { exact: true });
  await summary.getByText('读取失败，待核对', { exact: true }).waitFor();
  assert.equal(writes.length, 0, 'opening settings never probes or writes');
  failRead = false;
  await summary.getByRole('button', { name: '重新读取模型设置' }).click();
  await summary.getByText('测试环境一', { exact: true }).waitFor();
  assert.match(await summary.innerText(), /model-one/);
  assert.equal(writes.length, 0, 'retry is read only');

  await summary.getByRole('button', { name: '服务凭证设置', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '服务凭证设置', exact: true });
  const section = dialog.getByRole('region', { name: '模型连通性与响应时间' });
  await section.getByRole('button', { name: '读取模型列表', exact: true }).click();
  await section.getByText(/已读取 2 个模型/).waitFor();
  await section.getByRole('button', { name: '测试连通性', exact: true }).click();
  await summary.getByText('与当前环境和默认模型匹配，仅代表当次响应。', { exact: true }).waitFor({ state: 'attached' });
  assert.match(await summary.innerText(), /历史测试 · 响应成功/);
  assert.match(await summary.locator('time').getAttribute('datetime'), /2026-11-05/);
  assert.equal(writes.length, 2);

  // A changed default invalidates the prior completed test even within the same environment.
  await dialog.getByRole('button', { name: '更改默认模型', exact: true }).click();
  await dialog.locator('#default-model-picker').focus();
  await page.keyboard.press('ArrowDown');
  await dialog.getByRole('option', { name: /model-two/ }).click();
  await dialog.getByRole('button', { name: '确认默认模型', exact: true }).click();
  await summary.getByText(/与当前环境或默认模型未匹配/).waitFor({ state: 'attached' });
  assert.equal(selection.name, 'model-two');

  await section.getByRole('button', { name: '读取模型列表', exact: true }).click();
  await section.getByText(/已读取 2 个模型/).waitFor();
  await section.getByLabel('模型名称', { exact: true }).fill('model-two');
  await section.getByRole('button', { name: '测试连通性', exact: true }).click();
  await summary.getByText('与当前环境和默认模型匹配，仅代表当次响应。', { exact: true }).waitFor({ state: 'attached' });
  await dialog.locator('#credentials-history-picker').focus();
  await page.keyboard.press('ArrowDown');
  await dialog.getByRole('option', { name: /测试环境二/ }).click();
  await dialog.getByRole('button', { name: '使用此凭证', exact: true }).click();
  await summary.getByText('测试环境二', { exact: true }).waitFor({ state: 'attached' });
  await summary.getByText(/与当前环境或默认模型未匹配/).waitFor({ state: 'attached' });

  // Unsaved credential tests remain explicitly draft results, even when their model matches.
  await dialog.getByLabel('API Key', { exact: true }).fill('synthetic-draft-summary-secret');
  await section.getByLabel('模型名称', { exact: true }).fill('model-two');
  failProbe = true;
  await section.getByRole('button', { name: '测试连通性', exact: true }).click();
  await summary.getByText('未保存草稿测试 · 响应失败', { exact: true }).waitFor({ state: 'attached' });
  assert.match(await summary.innerText(), /不代表已保存环境或默认模型/);
  assert.equal((await summary.innerText()).includes('synthetic-raw-error-secret'), false);
  await dialog.getByRole('button', { name: '关闭凭证设置', exact: true }).click();
  await dialog.getByRole('button', { name: '放弃修改', exact: true }).click();
  await dialog.waitFor({ state: 'detached' });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await summary.evaluate(element => element.scrollWidth > element.clientWidth), false);
  if (output) { await summary.scrollIntoViewIfNeeded(); await page.screenshot({ path: join(output, 'summary-mobile.png') }); }
  assert.equal(await page.evaluate(() => [...Object.values(localStorage), ...Object.values(sessionStorage)].some(value => /synthetic-.*secret/.test(value))), false);

  const count = writes.length;
  await page.reload();
  await summary.getByText('本次打开设置页期间尚无完成的模型测试', { exact: true }).waitFor();
  assert.equal(writes.length, count, 'reload does not run probes');
  // A successful empty read is distinct from failed or pending reads.
  selection = null;
  await page.reload();
  await summary.getByText('尚未选择，请在服务凭证设置中确认', { exact: true }).waitFor();
  selection = { name: models[0].model, id: models[0].id, provider: 'test' };
  requiresSelection = true;
  await page.reload();
  await summary.getByText('model-one（待确认）', { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  assert.deepEqual(unknown, []);
  console.log(JSON.stringify({ passed: true, checks: ['read failure/retry', 'no auto probe', 'actual result and timestamp', 'saved model/env mismatch', 'draft failure isolation', 'mobile', 'no browser credential storage', 'reload clears visit-only receipt', 'unconfigured default'], explicitWrites: writes.length }));
} finally { await browser.close(); }
