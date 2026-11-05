/** Settings navigation and credential callbacks; all credentials and writes are fixtures. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const defaults = { model: { base_url: 'https://settings.example.invalid/', app_id: 'test-app', api_key: 'synthetic-key', tenant_id: 'test-tenant' } };
let effective = structuredClone(defaults);
let settingsReads = 0, modelReads = 0, saves = 0, activations = 0;
let failSave = true, failModels = false, activeId = 'first';
const history = ['first', 'second'].map(id => ({ id, name: id === 'first' ? '测试环境一' : '测试环境二', base_url: defaults.model.base_url, app_id: 'test-app', tenant_id: 'test-tenant', created_at: '2026-10-31T00:00:00Z', last_used_at: null, source: 'saved' }));
const response = () => ({ defaults, effective, overridden: ['model'], history: history.map(item => ({ ...item, active: item.id === activeId })) });

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  // Block every settings write from reaching the running platform.
  await page.route('**/api/settings/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path === '/api/settings/credentials/default-model') return route.fulfill({ json: {
      selection: { provider: 'test', name: 'test-model', id: 'test' }, source: 'settings', requires_selection: false,
    } });
    if (path === '/api/settings/credentials') {
      if (request.method() === 'PUT') {
        if (failSave) { failSave = false; return route.fulfill({ status: 503, json: { error: '测试保存失败，请重试。' } }); }
        effective = { model: request.postDataJSON().model ?? defaults.model }; saves += 1;
      } else settingsReads += 1;
      return route.fulfill({ json: response() });
    }
    if (path.endsWith('/second/activate')) {
      assert.equal(request.method(), 'POST'); activeId = 'second'; activations += 1;
      return route.fulfill({ json: response() });
    }
    return route.fulfill({ status: 503, json: { error: '测试设置服务暂不可用' } });
  });
  await page.route('**/api/models', route => {
    modelReads += 1;
    return route.fulfill({ json: failModels ? { success: false, error: '测试模型目录不可用' } : { success: true, models: [{ provider: 'test', model: 'test-model', id: 'test' }] } });
  });
  await page.route('**/api/rd/workspace/resources', route => route.fulfill({ json: { can_manage: true, resources: [] } }));
  await page.goto(base);
  const gear = page.getByRole('button', { name: '系统管理', exact: true });
  await gear.waitFor();
  assert.equal(await page.getByRole('navigation', { name: '研发平台导航' }).getByRole('button', { name: '系统管理', exact: true }).count(), 0);
  const gearBox = await gear.boundingBox();
  assert(gearBox.x < 240 && gearBox.y > 900, 'settings is in the lower-left account dock');
  assert.equal(settingsReads, 0, 'navigation alone must not read credentials');
  await gear.click();
  await page.getByRole('heading', { name: '系统管理', exact: true }).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('rd_view'), 'system');
  assert.equal(await gear.getAttribute('aria-current'), 'page');
  for (const name of ['账号与登录', '模型服务', '管理员工作区', '能力与数据接入']) await page.getByRole('heading', { name, exact: true }).waitFor();
  assert.equal(await page.getByRole('link', { name: '打开管理员页面 ↗' }).getAttribute('href'), '/admin');
  if (output) await page.screenshot({ path: join(output, 'system-desktop.png') });

  const trigger = page.getByRole('button', { name: '服务凭证设置', exact: true });
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: '服务凭证设置', exact: true });
  const key = dialog.getByLabel('API Key', { exact: true });
  await key.waitFor(); assert.equal(await key.getAttribute('type'), 'password');
  await key.fill('synthetic-updated-key');
  await page.keyboard.press('Escape');
  await dialog.getByText('尚有未保存的修改，是否放弃？').waitFor();
  await dialog.getByRole('button', { name: '继续编辑', exact: true }).click();
  await dialog.getByRole('button', { name: '保存凭证', exact: true }).click();
  await dialog.getByRole('alert').filter({ hasText: '测试保存失败' }).waitFor();
  assert.equal(await key.inputValue(), 'synthetic-updated-key'); assert.equal(saves, 0);
  await dialog.getByRole('button', { name: '保存凭证', exact: true }).click();
  await page.getByText('模型目录已刷新，共 1 项。', { exact: true }).waitFor({ state: 'attached' });
  assert.equal(saves, 1); assert.equal(modelReads, 1);
  await dialog.locator('#credentials-history-picker').focus();
  await page.keyboard.press('ArrowDown');
  await page.getByRole('option', { name: /测试环境二/ }).click();
  await dialog.getByRole('button', { name: '使用此凭证', exact: true }).click();
  await dialog.getByRole('status').filter({ hasText: '已切换到' }).waitFor();
  assert.equal(activations, 1); assert.equal(modelReads, 2);
  failModels = true;
  await key.fill('synthetic-second-key');
  await dialog.getByRole('button', { name: '保存凭证', exact: true }).click();
  await dialog.getByRole('alert').filter({ hasText: '凭证已生效，但模型目录刷新失败' }).waitFor();
  assert.equal(saves, 2); assert.equal(modelReads, 3);
  await dialog.getByRole('button', { name: '关闭凭证设置', exact: true }).click();
  assert(await trigger.evaluate(element => element === document.activeElement));

  await page.getByRole('button', { name: '收起侧栏', exact: true }).click();
  await page.getByRole('button', { name: '我的工作', exact: true }).click();
  await gear.click(); await page.getByRole('heading', { name: '系统管理', exact: true }).waitFor();
  await page.goBack(); await page.getByRole('heading', { name: '最近项目', exact: true }).waitFor();
  await page.goForward(); await page.getByRole('heading', { name: '系统管理', exact: true }).waitFor();
  await page.reload(); await page.getByRole('heading', { name: '系统管理', exact: true }).waitFor();
  assert.equal(await gear.getAttribute('aria-current'), 'page');
  await page.setViewportSize({ width: 390, height: 844 });
  assert(await gear.isVisible()); assert(await page.locator('.rd-application-shell').evaluate(e => e.scrollWidth <= e.clientWidth + 1));
  if (output) await page.screenshot({ path: join(output, 'system-mobile.png') });

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: '资源工作台', exact: true }).click();
  await page.getByLabel('资源名称', { exact: true }).fill('未保存的测试资源');
  await gear.click();
  const leave = page.getByRole('dialog', { name: '离开前保存填写', exact: true });
  await leave.getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(await page.getByLabel('资源名称', { exact: true }).inputValue(), '未保存的测试资源');
  await gear.click(); await leave.getByRole('button', { name: '放弃填写并切换', exact: true }).click();
  await page.getByRole('heading', { name: '系统管理', exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log('PASS: footer settings, deep links/back-forward, desktop/mobile, credential save/retry/history/refresh failure, draft protection; all settings writes mocked.');
} finally { await browser.close(); }
