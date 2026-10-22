/** Run against Vite with the existing Playwright installation, as the sibling browser tests do. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
const record = {
  id: 1, version: 1, created_at: '2026-10-15T01:20:00Z', updated_at: '2026-10-15T01:20:00Z',
  username: '质量工程师', rating: 'average', comment: '端子材料描述需要复核。\n希望保留原始参数。',
  status: 'open', handling_note: '',
  identity: { userid: 'oa-engineer-42', name: '原提交工程师', source: 'smartvision', verified: true },
  snapshot: { jid: 'feedback-job-1', job_status: 'done', parameters: { product_type: 'rf_connector',
    product_type_label: '射频连接器', product_series: 'J599', model_name: '工程模型', template_name: '连接器任务书模板.docx' },
    files: { tech: '技术要求.docx', spec: '产品规范.docx', output: '研制任务书.docx', report: '质量报告.html' },
    delivery_status: 'delivered', qa_ok: true, error: '' },
};
let current = structuredClone(record);
let items = [current];
let conflict = false;
const requests = [];

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.route('**/api/admin/session', route => route.fulfill({ json: { authenticated: true, user: { username: 'wangxue', display_name: '测试管理员', userid: 'owner-test' }, can_manage_admins: true } }));
  await page.route('**/api/feedback-admin**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push({ method: request.method(), url: url.toString(), body: request.postDataJSON() });
    if (request.method() === 'GET' && /\/\d+$/.test(url.pathname)) return route.fulfill({ json: { record: current } });
    if (request.method() === 'GET') return route.fulfill({ json: { items, total: items.length, page: 1, page_size: 20,
      stats: { total: items.length, good: 0, average: items.length, poor: 0, good_rate: 0, open: items.length, in_progress: 0, resolved: 0 } } });
    if (request.method() === 'PUT') {
      if (conflict) return route.fulfill({ status: 409, json: { error: '反馈已被其他人修改，请刷新后重试。' } });
      current = { ...current, ...request.postDataJSON(), version: current.version + 1 };
      items = [current];
      return route.fulfill({ json: { record: current } });
    }
    if (request.method() === 'DELETE') { items = []; return route.fulfill({ json: { ok: true } }); }
    if (request.method() === 'POST') {
      current = { ...current, ...request.postDataJSON(), id: 2,
        identity: { userid: '', name: request.postDataJSON().username, source: 'manual', verified: false } };
      items = [current];
      return route.fulfill({ json: { record: current } });
    }
  });
  await page.goto(`${base}/feedback`);
  await page.getByRole('heading', { name: '问题反馈管理', exact: true }).waitFor({ timeout: 5000 });
  await page.getByRole('table', { name: '生成效果反馈列表' }).waitFor();
  assert.match(await page.locator('.feedback-statistics').innerText(), /1/);
  await page.getByRole('table', { name: '生成效果反馈列表' }).getByText('平台账号：oa-engineer-42', { exact: true }).waitFor({ timeout: 3000 });
  if (process.env.SCREENSHOT_DIR) {
    await mkdir(process.env.SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'feedback-admin-desktop.png'), fullPage: true });
  }
  await page.getByRole('button', { name: '查看反馈 1', exact: true }).click();
  const detail = page.getByRole('dialog', { name: '反馈详情', exact: true });
  await detail.waitFor();
  await detail.getByText('希望保留原始参数。', { exact: false }).waitFor();
  assert.match(await detail.innerText(), /希望保留原始参数/);
  assert.match(await detail.innerText(), /技术要求\.docx/);
  const originalIdentity = detail.getByRole('region', { name: '提交时的身份', exact: true });
  assert.match(await originalIdentity.innerText(), /统一登录已验证/);
  assert.match(await originalIdentity.innerText(), /oa-engineer-42/);
  assert.match(await originalIdentity.innerText(), /原提交工程师/);
  await detail.getByRole('button', { name: '编辑反馈', exact: true }).click();
  assert.equal(await page.getByRole('region', { name: '提交时的身份', exact: true }).locator('input').count(), 0, 'original platform identity cannot be edited');
  await page.getByLabel('反馈用户名', { exact: false }).fill('管理员调整名称');
  await page.getByLabel('意见与建议', { exact: false }).fill('补充：连接器材料需与技术要求一致。');
  conflict = true;
  await page.getByRole('button', { name: '保存反馈', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '其他人修改' }).waitFor();
  assert.equal(await page.getByLabel('意见与建议', { exact: false }).inputValue(), '补充：连接器材料需与技术要求一致。');
  conflict = false;
  await page.getByRole('button', { name: '保存反馈', exact: true }).click();
  await page.getByRole('heading', { name: '反馈详情', exact: true }).waitFor();
  const put = requests.find(item => item.method === 'PUT');
  assert.equal(put.body.expected_version, 1);
  assert.equal(Object.hasOwn(put.body, 'identity'), false, 'editing a feedback label never posts platform identity');
  assert.equal(current.username, '管理员调整名称');
  assert.match(await page.getByRole('region', { name: '提交时的身份', exact: true }).innerText(), /原提交工程师/);
  await page.getByRole('button', { name: '关闭详情', exact: true }).click();
  await page.getByRole('button', { name: '删除反馈 1', exact: true }).click();
  assert.equal(requests.filter(item => item.method === 'DELETE').length, 0, 'delete waits for confirmation');
  await page.getByRole('dialog', { name: '删除反馈', exact: true }).getByRole('button', { name: '确认删除', exact: true }).click();
  await page.getByText('没有找到反馈记录。', { exact: true }).waitFor();
  assert.match(requests.find(item => item.method === 'DELETE').url, /expected_version=2/);
  await page.getByRole('button', { name: '新增反馈', exact: true }).click();
  await page.getByRole('button', { name: '保存反馈', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '请补全' }).waitFor();
  assert.equal(requests.filter(item => item.method === 'POST').length, 0);
  await page.getByLabel('关联任务 ID', { exact: false }).fill('feedback-job-1');
  await page.getByLabel('反馈用户名', { exact: false }).fill('试验工程师');
  await page.locator('#feedback-editor-rating').click();
  await page.getByRole('option', { name: '差', exact: true }).click();
  await page.getByLabel('意见与建议', { exact: false }).fill('复核件的条款编号需要调整。');
  await page.getByRole('button', { name: '保存反馈', exact: true }).click();
  await page.getByRole('heading', { name: '反馈详情', exact: true }).waitFor();
  assert.equal(requests.find(item => item.method === 'POST').body.jid, 'feedback-job-1');
  assert.equal(Object.hasOwn(requests.find(item => item.method === 'POST').body, 'identity'), false, 'admin creation cannot claim a verified identity');
  assert.match(await page.getByRole('region', { name: '提交时的身份', exact: true }).innerText(), /本地手填（未验证）/);
  await page.getByRole('button', { name: '关闭详情', exact: true }).click();
  current = { ...current, identity: {} }; items = [current];
  await page.getByLabel('关键词', { exact: true }).fill('条款');
  await page.locator('#feedback-rating-filter').click();
  await page.getByRole('option', { name: '差', exact: true }).click();
  await page.getByLabel('开始日期', { exact: true }).fill('2026-10-14');
  await page.getByLabel('结束日期', { exact: true }).fill('2026-10-15');
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await page.getByRole('table', { name: '生成效果反馈列表' }).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('rating'), 'poor');
  const filteredRequest = requests.filter(item => item.method === 'GET').at(-1);
  assert.equal(new URL(filteredRequest.url).searchParams.get('date_from'), '2026-10-14T00:00:00+08:00');
  assert.equal(new URL(filteredRequest.url).searchParams.get('date_to'), '2026-10-15T23:59:59.999999+08:00');
  await page.getByRole('table', { name: '生成效果反馈列表' }).getByText('历史未记录（未验证）', { exact: true }).waitFor();
  await page.getByRole('button', { name: '查看反馈 2', exact: true }).click();
  assert.match(await page.getByRole('region', { name: '提交时的身份', exact: true }).innerText(), /历史未记录（未验证）/);
  await page.getByRole('button', { name: '关闭详情', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'mobile page does not overflow');
  if (process.env.SCREENSHOT_DIR) {
    await mkdir(process.env.SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'feedback-admin-mobile.png'), fullPage: true });
  }
  await page.close();

  const generation = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  generation.on('pageerror', error => console.error('Generation page error:', error.message));
  const submissions = [];
  await generation.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/feedback') {
      const body = route.request().postDataJSON(); submissions.push(body);
      await new Promise(resolve => setTimeout(resolve, 120));
      if (submissions.length === 1) return route.fulfill({ status: 503, json: { error: '反馈服务暂不可用，请重试。' } });
      return route.fulfill({ json: { record: { ...record, id: submissions.length, username: body.username, rating: body.rating, comment: body.comment } } });
    }
    let response = {};
    if (path === '/api/current-user') response = { auth_enabled: false, authenticated: false, user: null };
    if (path === '/api/product_catalog') response = { product_types: [] };
    if (path === '/api/models') response = { success: true, models: [] };
    if (path === '/api/history' || path === '/api/local_defaults') response = [];
    if (path.startsWith('/api/indicator_review/')) response = { manual_review_required: [], comparison_decisions: [], indicator_clarifications: {} };
    return route.fulfill({ json: response });
  });
  await generation.addInitScript(() => { window.EventSource = class { constructor() { window.testEventSource = this; } close() {} }; });
  await generation.goto(`${base}/`);
  await generation.locator('#workspace-shell').waitFor({ timeout: 5000 }).catch(async error => {
    console.error('Public page URL:', generation.url());
    console.error('Public page text:', await generation.locator('body').innerText());
    throw error;
  });
  await generation.evaluate(() => window.dispatchEvent(new CustomEvent('taskbook:replay-started', { detail: { jid: 'feedback-job-1' } })));
  await generation.locator('#btn-cancel').waitFor();
  await generation.evaluate(() => window.testEventSource.onmessage({ data: JSON.stringify({ type: 'done', result: { meta: { product_type: '射频连接器', output_name: '任务书.docx' } } }) }));
  const feedback = generation.locator('#result-card .generation-feedback');
  await feedback.waitFor();
  const feedbackBox = await feedback.boundingBox();
  const downloadBox = await generation.locator('#btn-docx').boundingBox();
  assert.ok(feedbackBox.y + feedbackBox.height <= downloadBox.y, 'feedback is inside the result card above downloads');
  await feedback.getByRole('button', { name: '提交反馈', exact: true }).click();
  await feedback.getByRole('alert').waitFor();
  assert.equal(submissions.length, 0, 'missing username/rating never submitted');
  await feedback.getByLabel('反馈用户名', { exact: false }).fill('设计工程师');
  await feedback.getByLabel('好', { exact: true }).check();
  await feedback.getByLabel('意见与建议', { exact: false }).fill('章节完整，参数可追溯。');
  await feedback.getByRole('button', { name: '提交反馈', exact: true }).evaluate(button => { button.click(); button.click(); });
  await feedback.getByRole('alert').filter({ hasText: '暂不可用' }).waitFor();
  assert.equal(submissions.length, 1, 'rapid double click submits once');
  await feedback.getByRole('button', { name: '提交反馈', exact: true }).click();
  await feedback.getByText('反馈已提交', { exact: true }).waitFor();
  assert.equal(submissions.length, 2);
  assert.equal(submissions[0].request_id, submissions[1].request_id, 'retry preserves idempotency key');
  assert.deepEqual(Object.keys(submissions[0]).sort(), ['comment', 'jid', 'rating', 'request_id', 'username']);
  assert.equal(await generation.locator('#btn-docx').isEnabled(), true, 'feedback does not block downloads');
  if (process.env.SCREENSHOT_DIR) {
    await feedback.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'generation-feedback-receipt.png') });
    await generation.setViewportSize({ width: 390, height: 844 });
    if (await generation.locator('#workspace-shell.sidebar-expanded').count()) await generation.locator('#sidebar .sidebar-toggle').click();
    await feedback.getByRole('button', { name: '再写一条反馈', exact: true }).click();
    await feedback.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'generation-feedback-mobile.png') });
  }
  await generation.close();
  console.log('Feedback browser flow passed: CRUD, conflict preservation, filters, China dates, mobile, public validation and idempotent retry.');
} finally {
  await browser.close();
}
