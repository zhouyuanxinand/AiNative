/** Current Ant Design settings controls. All settings/probe traffic is synthetic. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const credentials = { model: { base_url: 'https://models.example.invalid/open/', app_id: 'demo-app', tenant_id: 'demo-tenant', api_key: 'synthetic-key' } };
const models = [{ provider: 'smartvision', model: 'azure/gpt-5.4', id: '5505', vendor: 'Azure', configured: true }];
const probes = [], loginWrites = [], errors = [];
const initialLogin = { enabled: false, app_id: 9192, platform_base_url: 'https://login.example.invalid', public_url: null };
let login = { ...initialLogin }, version = 1, probeFails = false, authFails = false;
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/settings/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    assert.equal(request.headers()['x-credential-settings'], '1');
    if (path === '/api/settings/credentials') {
      assert.equal(request.method(), 'GET', 'tools never save model credentials');
      return route.fulfill({ json: { defaults: credentials, effective: credentials, overridden: ['model'], history: [] } });
    }
    if (path === '/api/settings/credentials/default-model') {
      assert.equal(request.method(), 'GET', 'tools never switch the default model');
      return route.fulfill({ json: { selection: { provider: 'smartvision', name: 'azure/gpt-5.4', id: '5505' }, source: 'settings', requires_selection: false } });
    }
    if (path === '/api/settings/credentials/test/models') return route.fulfill({ json: { success: true, models, response_time_ms: 60, checked_at: '2026-11-04T08:00:00Z', message: '已读取模型列表。' } });
    if (path === '/api/settings/credentials/test') {
      probes.push(request.postDataJSON());
      return route.fulfill({ json: { success: !probeFails, model: request.postDataJSON().model, response_time_ms: 1240, checked_at: '2026-11-04T08:00:00Z', message: probeFails ? '测试服务暂不可用。' : '模型已返回有效响应。' } });
    }
    if (path === '/api/settings/auth') {
      if (request.method() === 'PUT') {
        const body = request.postDataJSON(); loginWrites.push(body);
        if (authFails) return route.fulfill({ status: 503, json: { error: '测试登录配置未保存。' } });
        assert.equal(body.expected_version, version);
        const { expected_version, ...saved } = body; login = saved; version += 1;
      }
      return route.fulfill({ json: { settings: login, active: initialLogin, can_edit: true, version, requires_restart: version > 1,
        presets: { intranet: { app_id: 127, platform_base_url: 'http://intranet.example.invalid', public_url: null }, external: { app_id: 9086, platform_base_url: 'https://external.example.invalid', public_url: null } } } });
    }
    return route.fulfill({ status: 503, json: { error: '未提供的测试设置操作' } });
  });
  await page.route('**/api/models', route => route.fulfill({ json: { success: true, models } }));
  await page.goto(`${base}/?rd_view=system`);
  await page.getByRole('button', { name: '服务凭证设置', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '服务凭证设置', exact: true });
  const probe = dialog.getByRole('region', { name: '模型连通性与响应时间', exact: true });
  await probe.getByLabel('模型名称', { exact: true }).waitFor();
  assert.equal(probes.length, 0);
  await probe.getByRole('button', { name: '读取模型列表', exact: true }).click();
  const picker = probe.getByRole('combobox', { name: '选择可用模型', exact: true });
  await picker.focus(); await page.keyboard.press('ArrowDown');
  await dialog.getByRole('option', { name: 'Azure · azure/gpt-5.4', exact: true }).click();
  await probe.getByRole('button', { name: '测试连通性', exact: true }).click();
  await probe.locator('.credentials-probe-result[data-status=success]').waitFor();
  assert.equal(probes[0].model_id, '5505');
  assert.equal(probes[0].model, 'azure/gpt-5.4');
  await probe.getByLabel('模型名称', { exact: true }).fill('manual-test-model');
  assert.equal(await probe.locator('.credentials-probe-result').count(), 0);
  probeFails = true;
  await probe.getByRole('button', { name: '测试连通性', exact: true }).click();
  await probe.locator('.credentials-probe-result[data-status=error]').waitFor();
  assert.equal(probes.at(-1).model_id || '', '', 'manual choice does not inherit an unrelated model ID');
  probeFails = false;
  await probe.getByRole('button', { name: '测试连通性', exact: true }).click();
  await probe.locator('.credentials-probe-result[data-status=success]').waitFor();
  if (output) await page.screenshot({ path: join(output, 'model-connection-desktop.png') });
  await dialog.getByLabel('API Key', { exact: true }).fill('synthetic-unsaved-key');
  assert.equal(await probe.locator('.credentials-probe-result').count(), 0, 'editing credentials clears stale probe results');
  await dialog.getByRole('button', { name: '统一登录设置', exact: true }).click();
  const auth = page.getByRole('dialog', { name: '统一登录设置', exact: true });
  const mode = auth.getByRole('combobox', { name: '回跳方式', exact: true });
  await mode.waitFor();
  async function chooseMode(name) { await mode.focus(); await page.keyboard.press('ArrowDown'); await auth.getByRole('option', { name, exact: true }).click(); }
  await chooseMode('手动指定地址');
  await auth.getByRole('button', { name: '保存登录配置', exact: true }).click();
  await auth.getByRole('alert').filter({ hasText: '手动指定时' }).waitFor();
  assert.equal(loginWrites.length, 0);
  await auth.getByLabel('回跳地址', { exact: true }).fill('https://callback.example.invalid/path');
  await auth.getByRole('button', { name: '保存登录配置', exact: true }).click();
  await auth.getByRole('alert').filter({ hasText: '回跳地址仅填写' }).waitFor();
  assert.equal(loginWrites.length, 0);
  await auth.getByLabel('回跳地址', { exact: true }).fill('https://callback.example.invalid:18130');
  authFails = true;
  await auth.getByRole('button', { name: '保存登录配置', exact: true }).click();
  await auth.getByRole('alert').filter({ hasText: '测试登录配置未保存' }).waitFor();
  assert.equal(await auth.getByLabel('回跳地址', { exact: true }).inputValue(), 'https://callback.example.invalid:18130');
  authFails = false;
  await auth.getByRole('button', { name: '保存登录配置', exact: true }).click();
  await auth.getByText('已保存，重启平台后生效', { exact: true }).waitFor();
  assert.equal(login.public_url, 'https://callback.example.invalid:18130');
  await auth.getByRole('button', { name: '使用内网配置', exact: true }).click();
  assert.equal(await auth.getByLabel('登录应用 ID', { exact: true }).inputValue(), '127');
  assert.equal(await auth.getByLabel('启用统一登录', { exact: true }).isChecked(), false);
  await auth.getByRole('button', { name: '使用外网配置', exact: true }).click();
  assert.equal(await auth.getByLabel('登录应用 ID', { exact: true }).inputValue(), '9086');
  await page.keyboard.press('Escape');
  await auth.getByText('尚有未保存的统一登录配置，是否放弃？', { exact: true }).waitFor();
  await auth.getByRole('button', { name: '继续编辑', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await chooseMode('手动指定地址');
  const callback = auth.getByLabel('回跳地址', { exact: true });
  await callback.scrollIntoViewIfNeeded();
  const box = await callback.boundingBox(), footer = await auth.locator('.credentials-footer').boundingBox();
  assert(box.y + box.height <= footer.y + 1);
  assert(await auth.locator('.credentials-body').evaluate(element => element.scrollWidth <= element.clientWidth + 1));
  if (output) await page.screenshot({ path: join(output, 'auth-settings-edit-mobile.png') });
  await page.keyboard.press('Escape');
  await auth.getByRole('button', { name: '放弃修改', exact: true }).click();
  assert.equal(await dialog.getByLabel('API Key', { exact: true }).inputValue(), 'synthetic-unsaved-key');
  assert.equal(await dialog.locator('form form').count(), 0);
  await probe.getByLabel('模型名称', { exact: true }).fill('mobile-test');
  await probe.getByRole('button', { name: '测试连通性', exact: true }).click();
  await probe.locator('.credentials-probe-result[data-status=success]').waitFor();
  assert(await probe.evaluate(element => element.scrollWidth <= element.clientWidth + 1));
  if (output) await page.screenshot({ path: join(output, 'model-connection-mobile.png') });
  assert.deepEqual(errors, []);
  console.log('PASS settings tools: complete model IDs, manual model isolation, success/failure/retry, stale-result invalidation, independent login save, origin validation, presets, dirty close, mobile and nested dialog preservation.');
} finally { await browser.close(); }
