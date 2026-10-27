/** Interactive contract regression. Run against Vite; API responses are local fixtures. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(6000);
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
page.on('console', (message) => { if (message.type() === 'error' && /same key|unique.*key/.test(message.text())) errors.push(message.text()); });

let canSave = true;
let conflict = false;
let failedDirectory = false;
let saves = 0;
let restores = 0;
let revision = 'v1';
let nextEvent = 1;
let current = {
  enabled: true,
  domains: ['military'],
  checks: { threshold: 0, policy: '阻断输出', keywords: ['适用时保留', '不适用请删除'] },
  definitions: [{ text: '检查生成文档中的模板提示内容，避免未经确认的示例文本进入交付文档。' }],
};
const initial = structuredClone(current);
let history = [{ revision: 'v1', event_id: 'event1', created_at: '2026-09-17 16:20:00', note: '初始业务规则', actor: 'web-user', is_current: true }];
const fields = [
  { path: ['enabled'], label: '启用模板文字检查', section: '交付检查', type: 'boolean', description: '启用后，对生成的研制任务书执行模板提示检查。' },
  { path: ['checks', 'threshold'], label: '允许残留的红字数量', section: '交付检查', type: 'number', description: '超过该数量时阻断输出，0 表示不允许残留。' },
  { path: ['checks', 'policy'], label: '检查不通过时的处理', section: '交付检查', type: 'enum', options: ['阻断输出', '仅提示复核'] },
  { path: ['checks', 'keywords'], label: '模板提示关键词', section: '文字检查', type: 'string_list', description: '命中任一关键词时进入交付检查。' },
  { path: ['definitions', 0, 'text'], label: '检查说明', section: '文字检查', type: 'string' },
  { path: ['domains'], label: '适用领域', section: '文字检查', type: 'string_list', options: ['military', 'civil_aviation'], option_labels: { military: '军品', civil_aviation: '民机' } },
];
const listItems = [
  { id: 'quality_gate', title: '质量门禁', group: '生成与交付', description: '配置交付前的检查内容、阻断条件和提示规则。', revision: 'v1', field_count: fields.length },
  { id: 'rf_categories', title: '射频连接器分类', group: '产品识别', description: '射频产品的分类定义及识别关键词。', revision: 'v1', field_count: fields.length },
];
const availability = () => ({ can_save: canSave, blocking_reason: canSave ? '' : '当前有生成任务正在运行，可继续编辑，任务结束后再保存。' });
const detail = (id) => ({ ...listItems.find((item) => item.id === id), revision, updated_at: '2026-09-17 16:20:00', data: current, fields, history, ...availability() });
const get = (data, path) => path.reduce((value, key) => value[key], data);
const set = (data, path, value) => { get(data, path.slice(0, -1))[path.at(-1)] = value; };

try {
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/rules') {
      return route.fulfill(failedDirectory ? { status: 503, json: { error: '规则服务暂时不可用' } } : { json: { items: listItems, ...availability() } });
    }
    const ruleMatch = path.match(/^\/api\/rules\/([^/]+)(\/validate|\/restore)?$/);
    if (ruleMatch) {
      const [, id, action] = ruleMatch;
      if (route.request().method() === 'GET') return route.fulfill({ json: detail(id) });
      const body = route.request().postDataJSON();
      if (conflict) return route.fulfill({ status: 409, json: { error: '规则版本已更新，请重新读取当前版本后再保存。' } });
      assert.equal(body.expected_revision, revision);
      if (action === '/validate') return route.fulfill({ json: { valid: true, changes: body.changes.map((change) => ({ ...change, label: fields.find((field) => JSON.stringify(field.path) === JSON.stringify(change.path)).label, before: get(current, change.path), after: change.value })) } });
      assert.equal(canSave, true, 'mutations must not be submitted while a task is running');
      if (action === '/restore') {
        restores += 1;
        assert.equal(body.revision, 'v1');
        current = structuredClone(initial);
        revision = body.revision;
      } else {
        saves += 1;
        for (const change of body.changes) {
          assert.ok(fields.some((field) => JSON.stringify(field.path) === JSON.stringify(change.path)), 'only advertised business fields are sent');
          set(current, change.path, change.value);
        }
        revision = `v${nextEvent + 1}`;
      }
      nextEvent += 1;
      history = [{ revision, event_id: `event${nextEvent}`, created_at: '2026-09-17 16:30:00', note: body.note, actor: 'web-user', is_current: true }, ...history.map((item) => ({ ...item, is_current: false }))];
      return route.fulfill({ json: detail(id) });
    }
    let json = {};
    if (path === '/api/product_catalog') json = { product_types: [] };
    if (path === '/api/models') json = { success: true, models: [] };
    if (path === '/api/history' || path === '/api/local_defaults') json = [];
    return route.fulfill({ json });
  });

  await page.goto(process.env.TEST_BASE_URL || 'http://127.0.0.1:5173/');
  await page.locator('button[data-page="rules"]').click();
  await page.getByRole('heading', { name: '质量门禁', exact: true }).waitFor();
  assert.equal(await page.locator('#management-title').innerText(), '规则中心');
  assert.equal(await page.getByRole('button', { name: '保存并生效', exact: true }).isDisabled(), true);
  await page.getByLabel('查找规则', { exact: true }).fill('射频');
  assert.equal(await page.locator('.rules-nav-item').count(), 1);
  await page.getByLabel('查找规则', { exact: true }).fill('');
  await page.getByLabel('模板提示关键词', { exact: true }).fill('适用时保留\n不适用请删除\n测试模板文字\n');
  await page.getByLabel('检查说明', { exact: true }).fill('新增业务说明');
  await page.getByLabel('允许残留的红字数量', { exact: true }).fill('2');
  await page.getByLabel('检查不通过时的处理', { exact: true }).selectOption('仅提示复核');
  await page.getByLabel('启用模板文字检查', { exact: true }).uncheck();
  await page.getByRole('group', { name: '适用领域', exact: true }).getByLabel('民机', { exact: true }).check();
  assert.match(await page.locator('.rules-save-bar').innerText(), /6 项修改尚未保存/);
  await page.locator('#rule-note').fill('依据最新业务讨论调整交付检查');
  await page.getByRole('button', { name: '检查修改', exact: true }).click();
  await page.locator('.rules-change-preview').waitFor();
  assert.match(await page.locator('.rules-feedback.success').innerText(), /检查通过/);
  assert.equal(saves, 0);
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.locator('button[data-page="home"]').click();
  assert.equal(await page.locator('#management-rules').isVisible(), true);
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: /射频连接器分类/ }).click();
  assert.equal(await page.getByRole('heading', { name: '质量门禁', exact: true }).isVisible(), true);
  await page.getByRole('button', { name: '保存并生效', exact: true }).click();
  await page.getByText('规则已保存并生效，新建任务将使用当前版本。', { exact: true }).waitFor();
  assert.equal(saves, 1);
  assert.equal(current.enabled, false);
  assert.deepEqual(current.checks.keywords, ['适用时保留', '不适用请删除', '测试模板文字']);
  assert.equal(current.checks.threshold, 2);
  assert.equal(current.definitions[0].text, '新增业务说明');
  assert.deepEqual(current.domains, ['military', 'civil_aviation']);
  assert.equal(await page.getByRole('button', { name: '保存并生效', exact: true }).isDisabled(), true);

  await page.getByLabel('检查说明', { exact: true }).fill('保留冲突时的草稿');
  conflict = true;
  await page.getByRole('button', { name: '保存并生效', exact: true }).click();
  await page.getByRole('alert').waitFor();
  assert.match(await page.getByRole('alert').innerText(), /规则版本已更新/);
  assert.equal(await page.getByLabel('检查说明', { exact: true }).inputValue(), '保留冲突时的草稿');
  assert.equal(saves, 1);
  conflict = false;
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '放弃修改', exact: true }).click();
  assert.equal(await page.getByLabel('检查说明', { exact: true }).inputValue(), '新增业务说明');

  await page.locator('.rules-history>summary').click();
  await page.getByRole('button', { name: '恢复此版本', exact: true }).click();
  await page.getByLabel('恢复说明（选填）', { exact: true }).fill('恢复已验证的业务规则');
  await page.getByRole('button', { name: '确认恢复并生效', exact: true }).click();
  await page.getByText('历史规则已恢复并生效，已保留本次恢复记录。', { exact: true }).waitFor();
  assert.equal(restores, 1);
  assert.deepEqual(current, initial);
  assert.equal(history.length, 3);
  await page.locator('.rules-history>summary').click();
  assert.equal(await page.getByRole('button', { name: '恢复此版本', exact: true }).count(), 1, 'A→B→A must not offer restoring the previous A event into current A');

  canSave = false;
  await page.getByRole('button', { name: /射频连接器分类/ }).click();
  await page.getByRole('heading', { name: '射频连接器分类', exact: true }).waitFor();
  await page.getByLabel('检查说明', { exact: true }).fill('任务运行期间的编辑');
  assert.equal(await page.getByRole('button', { name: '保存并生效', exact: true }).isDisabled(), true);
  canSave = true;
  await page.getByRole('button', { name: '刷新运行状态', exact: true }).click();
  await page.waitForFunction(() => ![...document.querySelectorAll('button')].find((button) => button.textContent === '保存并生效').disabled);
  assert.equal(await page.getByLabel('检查说明', { exact: true }).inputValue(), '任务运行期间的编辑');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '放弃修改', exact: true }).click();

  if (process.env.SCREENSHOT_DIR) {
    await mkdir(process.env.SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'rules-editor-desktop.png'), fullPage: true });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  const sidebarToggle = page.locator('#sidebar .sidebar-toggle');
  if (await page.locator('#workspace-shell').evaluate((element) => element.classList.contains('sidebar-expanded'))) await sidebarToggle.click();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'mobile horizontal overflow');
  assert.equal(await page.getByLabel('检查说明', { exact: true }).isVisible(), true);
  if (process.env.SCREENSHOT_DIR) await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'rules-editor-mobile.png'), fullPage: true });

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator('button[data-page="home"]').click();
  failedDirectory = true;
  await page.locator('button[data-page="rules"]').click();
  await page.getByRole('alert').waitFor();
  assert.match(await page.getByRole('alert').innerText(), /规则服务暂时不可用/);
  failedDirectory = false;
  await page.getByRole('button', { name: '重新读取', exact: true }).click();
  await page.getByRole('heading', { name: '质量门禁', exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log('PASS: rules search, all field types, nested paths, validation preview, save, dirty navigation, version conflict, discard, restore, running-task lock, retry, responsive layout.');
} finally { await browser.close(); }
