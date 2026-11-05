/** Batch upload interactions use isolated API fixtures, never real project/model writes. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const stamp = '2026-11-04T00:00:00Z';
const originalSources = ['tech', 'spec'].map(role => ({ id: `old-${role}`, role, name: `原${role === 'tech' ? '需求' : '规范'}.txt`, size: 16, sha256: role, version: 1, created_at: stamp }));
const base = () => ({ id: 'batch-project', title: '批量资料验证', version: 7, owner_id: 'fixture', members: [], events: [], cases: [{
  id: 'batch-case', title: '批量资料流程', scenario_id: 'taskbook', stage: 'input', status: 'active', input_revision: 1,
  sources: structuredClone(originalSources), source_selection: { tech: 'old-tech', spec: 'old-spec' },
  context: {}, context_provenance: {}, model_selection: { provider: '', name: '', id: '' }, requirements: [], clarifications: [],
  product_route: null, composition_route: null, decisions: [], workpackages: [],
}] });
let project = base(), uploadMode = 'reject', holdClassification = true, releaseClassification;
const requests = [], errors = [], unexpected = [], checks = [];

function multipart(request) {
  const body = request.postData();
  const value = name => body.match(new RegExp(`name="${name}"\\r\\n\\r\\n([\\s\\S]*?)\\r\\n--`))?.[1];
  return { key: request.headers()['idempotency-key'], version: Number(value('expected_version')), manifest: JSON.parse(value('manifest')) };
}

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
    if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [] } });
    if (path === '/api/models') return route.fulfill({ json: { success: true, models: [] } });
    if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'batch-owner', local_mode: true } });
    if (path === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书' }], actions: [], workpackage_definitions: [] } });
    if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [project] } });
    if (path === '/api/rd/projects/batch-project') return route.fulfill({ json: project });
    if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: project.cases[0].stage, project_version: project.version, input_revision: project.cases[0].input_revision } } });
    if (path.endsWith('/sources/classify')) {
      const body = request.postDataJSON();
      assert.equal(body.use_model, true);
      if (holdClassification) await new Promise(resolve => { releaseClassification = resolve; });
      return route.fulfill({ json: { items: body.files.map(file => ({ id: file.id, role: file.name.includes('规范') ? 'spec' : 'tech', reason: '隔离文件名建议', method: 'filename' })), warnings: [] } });
    }
    if (path.endsWith('/sources/batch')) {
      const call = multipart(request); requests.push(call);
      if (uploadMode === 'reject') return route.fulfill({ status: 422, json: { error: '请核对批次分类后重试' } });
      if (uploadMode === 'uncertain') {
        assert.equal(call.version, project.version);
        project.version += 1; project.cases[0].input_revision += 1;
        call.manifest.forEach((item, index) => {
          const role = item.primary ? item.role : 'reference';
          const source = { id: `new-${index}`, client_id: item.id, role, document_category: item.role, name: item.name, size: 24, sha256: item.id, version: 1, created_at: stamp };
          project.cases[0].sources.push(source);
          if (item.primary) project.cases[0].source_selection[role] = source.id;
        });
        return route.abort('connectionreset');
      }
      return route.fulfill({ json: project });
    }
    if (request.method() !== 'GET') unexpected.push({ method: request.method(), path });
    return route.fulfill({ json: {} });
  });
  const openSources = async () => {
    await page.goto(`${process.env.TEST_BASE_URL || 'http://127.0.0.1:18370'}/?project=batch-project&case=batch-case`);
    await page.getByRole('navigation', { name: '办理步骤', exact: true }).getByRole('button', { name: '资料识别', exact: true }).click().catch(async error => {
      console.error(JSON.stringify({ errors, body: await page.locator('body').innerText(), html: (await page.content()).slice(0, 3000) })); throw error;
    });
    await page.getByRole('heading', { name: '添加编制资料', exact: true }).waitFor();
  };
  const group = name => page.getByRole('region', { name: `${name}分组`, exact: true });
  const card = name => page.getByRole('article', { name: `待上传文件：${name}`, exact: true });
  const chooseRole = async (name, role) => {
    const control = page.getByRole('combobox', { name: `调整“${name}”用途`, exact: true });
    await control.focus();
    await control.press('ArrowDown');
    await page.getByRole('option', { name: role, exact: true }).click();
  };
  const upload = () => page.getByRole('button', { name: '上传 3 份资料', exact: true });
  await openSources();
  const classifyStarted = page.waitForRequest(request => new URL(request.url()).pathname.endsWith('/sources/classify'));
  await page.locator('#rd-source-file').setInputFiles([
    { name: 'ABC-123技术要求.txt', mimeType: 'text/plain', buffer: Buffer.from('technical input') },
    { name: '补充需求.txt', mimeType: 'text/plain', buffer: Buffer.from('supplemental input') },
    { name: 'scan.pdf', mimeType: 'application/pdf', buffer: Buffer.from('manual category') },
  ]);
  await classifyStarted;
  await chooseRole('scan.pdf', '产品规范');
  releaseClassification();
  await card('ABC-123技术要求.txt').getByText('隔离文件名建议', { exact: true }).waitFor();
  assert.equal(await group('产品规范').getByRole('article').count(), 1, 'late automatic classification cannot overwrite a manual category');
  assert(await group('需求文件').getByRole('radio', { name: '保留当前主文件：原需求.txt', exact: true }).isChecked());
  assert(await group('产品规范').getByRole('radio', { name: '保留当前主文件：原规范.txt', exact: true }).isChecked());
  assert(await page.getByRole('button', { name: '分析上传资料', exact: true }).isDisabled());
  checks.push('multi-file queue, late manual override, existing primary preservation and analysis block');

  const drag = await page.evaluateHandle(() => new DataTransfer());
  await card('补充需求.txt').dispatchEvent('dragstart', { dataTransfer: drag });
  await group('补充资料').dispatchEvent('drop', { dataTransfer: drag });
  assert.equal(await group('补充资料').getByRole('article').count(), 1);
  await chooseRole('补充需求.txt', '需求文件');
  assert.equal(await group('需求文件').getByRole('article').count(), 2);
  await card('ABC-123技术要求.txt').getByRole('radio', { name: '作为主文件', exact: true }).check();
  await upload().click();
  const confirmation = page.getByRole('dialog', { name: '更新编制资料', exact: true });
  await confirmation.waitFor();
  await confirmation.getByRole('button', { name: '取消', exact: true }).click();
  assert.equal(requests.length, 0);
  assert.equal(await page.getByRole('article', { name: /^待上传文件：/ }).count(), 3);
  checks.push('drag/drop and dropdown parity, explicit primary replacement and cancel retention');

  await upload().click();
  await confirmation.getByRole('button', { name: '上传并重新确认', exact: true }).click();
  await page.locator('.rd-batch-upload').getByRole('alert').filter({ hasText: '请核对批次分类后重试' }).waitFor();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].manifest.filter(item => item.primary).length, 1);
  assert(!(await page.getByRole('combobox', { name: '调整“补充需求.txt”用途', exact: true }).isDisabled()));
  checks.push('known rejection preserves an editable queue without silently adopting supplements');

  await chooseRole('补充需求.txt', '补充资料');
  uploadMode = 'uncertain';
  await upload().click();
  await confirmation.getByRole('button', { name: '上传并重新确认', exact: true }).click();
  const retry = page.getByRole('button', { name: '重试核对上传', exact: true });
  await retry.waitFor();
  assert(await page.locator('#rd-source-file').isDisabled());
  assert(await page.getByRole('combobox', { name: '调整“ABC-123技术要求.txt”用途', exact: true }).isDisabled());
  assert(await page.getByRole('button', { name: '清空待上传', exact: true }).isDisabled());
  assert.notEqual(requests[0].key, requests[1].key, 'an edited known-failure retry starts a new request identity');
  uploadMode = 'replay';
  await retry.click();
  await page.getByRole('heading', { name: '添加编制资料', exact: true }).waitFor();
  await page.waitForFunction(() => document.querySelectorAll('.rd-batch-file').length === 0);
  assert.equal(requests.length, 3);
  assert.equal(requests[2].key, requests[1].key);
  assert.equal(requests[2].version, requests[1].version);
  assert.deepEqual(requests[2].manifest, requests[1].manifest);
  assert.equal(project.cases[0].sources.length, 5);
  assert(!(await page.getByRole('button', { name: '分析上传资料', exact: true }).isDisabled()));
  await page.locator('.rd-source-history summary').click();
  assert.equal(await page.getByRole('button', { name: /^删除资料“/ }).count(), 5);
  checks.push('unknown outcome freezes exact request and retries the same key/version without duplicates');

  holdClassification = false;
  const longName = 'ABC-123' + '超长需求文件名称'.repeat(6) + '.txt';
  await page.locator('#rd-source-file').setInputFiles({ name: longName, mimeType: 'text/plain', buffer: Buffer.from('long filename') });
  await card(longName).getByText('隔离文件名建议', { exact: true }).waitFor();
  if (output) await page.screenshot({ path: join(output, 'batch-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await card(longName).scrollIntoViewIfNeeded();
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'mobile layout has no horizontal overflow');
  assert(await page.getByRole('combobox', { name: `调整“${longName}”用途`, exact: true }).isVisible());
  if (output) await page.screenshot({ path: join(output, 'batch-mobile.png'), fullPage: true });
  checks.push('long names and manual controls remain usable at 390px');
  assert.deepEqual(unexpected, []);
  assert.deepEqual(errors, []);
  if (output) await writeFile(join(output, 'batch-checks.json'), JSON.stringify({ checks, requests, errors, unexpected }, null, 2));
  console.log(JSON.stringify({ checks, requestCount: requests.length, errors, unexpected }, null, 2));
} finally { await browser.close(); }
