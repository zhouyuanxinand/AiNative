/** P2A governance UI: isolated API fixtures, no real projects, grants or model calls. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const errors = [], requests = [], writes = [];
let access = { application_id: 'rd-platform-local', can_edit_resources: false, can_publish_resources: false, can_manage_application_grants: false, local_bootstrap: false };
let denyManagement = false, failSave = '', failGrant = false, grantStatus = 'revoked', latestVersion = 1, publicationStatus = 'published', resourceRetired = false;
let holdNextDetail = false, holdNextWrite = false, releaseDetail, releaseWrite, onDetailHeld, onWriteHeld;
const resources = Array.from({ length: 12 }, (_, index) => ({ id: `resource-${index + 1}`, kind: 'skill', name: `本地能力 ${index + 1}`, description: '固定版本资源摘要', version: 1, status: 'published', available_versions: [1], executable: false }));
const resourceDetail = (id, version) => ({ ...resources.find(item => item.id === id), version: version === 'latest' ? latestVersion : Number(version), head_version: latestVersion, status: publicationStatus, resource_retired: resourceRetired, available_versions: [1, 4], configuration: { private_marker: 'management-only-configuration' }, publication_revision: 2, state_revision: 2, control_revision: 6, grant: { status: grantStatus, revision: 3 } });
const catalog = { stages: [], scenarios: [], actions: Array.from({ length: 7 }, (_, index) => ({ id: `action-${index}`, title: `本地动作 ${index}`, version: '1' })), workpackage_definitions: [{ id: 'wp', version: '1', title: '任务书工作包', nodes: [{ id: 'n1', action_id: 'action-0', action_version: '1', depends_on: [], required: true }] }] };
function paginate(items, url) {
  assert.equal(url.searchParams.get('page_size'), '5');
  const page = Number(url.searchParams.get('page') || 1), q = url.searchParams.get('q') || '';
  const filtered = items.filter(item => JSON.stringify(item).includes(q));
  return { items: filtered.slice((page - 1) * 5, page * 5), total: filtered.length, page, page_size: 5, total_pages: Math.ceil(filtered.length / 5) };
}
async function setup(page) {
  page.setDefaultTimeout(15000); page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    if (!path.startsWith('/api/')) return route.continue();
    requests.push({ path, search: url.search, method: request.method() });
    if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
    if (path === '/api/rd/session') return route.fulfill({ json: { ok: true } });
    if (path === '/api/rd/workspace/session') return route.fulfill({ json: access });
    if (path === '/api/rd/catalog') return route.fulfill({ json: catalog });
    if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [] } });
    if (path === '/api/rd/workspace/resources' && request.method() === 'POST') {
      const body = request.postDataJSON(); writes.push({ body, key: request.headers()['idempotency-key'] });
      assert(request.headers()['idempotency-key']);
      if (['publish', 'retire'].includes(body.operation)) assert.equal(body.expected_control_revision, 6);
      if (failSave) { const fail = failSave; failSave = ''; return route.fulfill({ status: fail === 'conflict' ? 409 : 503, json: { error: fail === 'conflict' ? '资源内容已有新版本' : '保存结果尚未确认，请重试' } }); }
      if (holdNextWrite) { holdNextWrite = false; await new Promise(resolve => { releaseWrite = resolve; onWriteHeld?.(); }); }
      if (body.operation === 'publish') { publicationStatus = 'published'; resourceRetired = false; }
      if (body.operation === 'retire') { publicationStatus = 'retired'; resourceRetired = true; }
      return route.fulfill({ json: resourceDetail(body.id, body.version || body.expected_version || 1) });
    }
    if (path === '/api/rd/workspace/grants') {
      const body = request.postDataJSON(); writes.push({ body, key: request.headers()['idempotency-key'] });
      assert.equal(body.expected_revision, 3); assert(!('application_id' in body));
      if (failGrant) { failGrant = false; return route.fulfill({ status: 503, json: { error: '授权结果尚未确认，请重试' } }); }
      grantStatus = body.operation === 'grant' ? 'granted' : 'revoked';
      return route.fulfill({ json: { status: grantStatus, revision: 3 } });
    }
    if (path === '/api/rd/workspace/resources') {
      if (denyManagement) return route.fulfill({ status: 403, json: { error: '资源治理权限已撤销' } });
      const result = paginate(resources, url); return route.fulfill({ json: { ...result, resources: result.items } });
    }
    if (path.startsWith('/api/rd/workspace/resources/')) {
      if (denyManagement) return route.fulfill({ status: 403, json: { error: '资源治理权限已撤销' } });
      const [id, version] = path.split('/').slice(-2);
      const snapshot = resourceDetail(id, version);
      if (holdNextDetail && version === 'latest') { holdNextDetail = false; await new Promise(resolve => { releaseDetail = resolve; onDetailHeld?.(); }); }
      return route.fulfill({ json: snapshot });
    }
    if (path === '/api/rd/catalog/resources') {
      const q = url.searchParams.get('q');
      if (q === '旧') await new Promise(resolve => setTimeout(resolve, 700));
      if (q === '失败') return route.fulfill({ status: 503, json: { error: '目录暂不可用' } });
      return route.fulfill({ json: paginate(resources, url) });
    }
    if (path.startsWith('/api/rd/catalog/resources/')) return route.fulfill({ json: resources.find(item => item.id === path.split('/').at(-2)) });
    if (path === '/api/rd/catalog/items') {
      const category = url.searchParams.get('category');
      const items = category === 'actions' ? catalog.actions : category === 'workpackages' ? catalog.workpackage_definitions : category === 'research' ? [{ id: 'research', version: '1', title: '研发路径', nodes: ['taskbook'], status: 'published' }] : [{ product_type_id: 'test', product_domain_id: 'test', product_type: '受控文档模板', product_domain: '测试', filename: 'template.docx', version: '1' }];
      return route.fulfill({ json: paginate(items, url) });
    }
    return route.fulfill({ json: {} });
  });
}
const snap = async (page, name) => { if (output) await page.screenshot({ path: join(output, name), fullPage: false }); };
try {
  const reader = await browser.newPage({ viewport: { width: 1440, height: 950 } }); await setup(reader);
  await reader.goto(`${base}/?rd_view=workspace&workspace_page=2&workspace_item=resource-7&workspace_version=1`);
  await reader.getByRole('heading', { name: '当前应用获准目录', exact: true }).waitFor().catch(async error => { console.error({ url: reader.url(), body: await reader.locator('body').innerText(), requests, errors }); throw error; });
  await reader.getByRole('heading', { name: '本地能力 7 · v1', exact: true }).waitFor();
  assert.equal(await reader.locator('.rd-resource-list > article').count(), 5);
  assert.equal(requests.filter(item => item.path === '/api/rd/workspace/resources').length, 0);
  assert.equal(await reader.getByText('查看资源配置', { exact: true }).count(), 0);
  assert.equal(await reader.locator('#rd-resource-configuration').count(), 0);
  await snap(reader, '01-readonly-desktop.png');
  const search = reader.getByLabel('搜索资源', { exact: true });
  const before = requests.filter(item => item.path === '/api/rd/catalog/resources').length;
  await search.dispatchEvent('compositionstart'); await search.fill('本地能力'); await reader.waitForTimeout(400);
  assert.equal(requests.filter(item => item.path === '/api/rd/catalog/resources').length, before, 'IME does not send partial query');
  await search.dispatchEvent('compositionend', { data: '本地能力' });
  await reader.waitForURL(/workspace_q=/); await reader.waitForTimeout(100);
  assert.equal(new URL(reader.url()).searchParams.get('workspace_page'), '1');
  await search.fill('旧'); await reader.waitForTimeout(350); await search.fill('本地能力'); await reader.waitForTimeout(1100);
  assert.equal(await reader.locator('.rd-resource-list > article').count(), 5, 'late response cannot replace newer query');
  await search.fill('失败'); await reader.waitForTimeout(450); await reader.getByRole('alert').filter({ hasText: '目录暂不可用' }).waitFor();
  await reader.getByRole('button', { name: '清空资源搜索' }).click();
  await reader.getByRole('button', { name: '下一页', exact: true }).click();
  assert.equal(new URL(reader.url()).searchParams.get('workspace_page'), '2');
  await reader.setViewportSize({ width: 390, height: 520 });
  await reader.getByRole('button', { name: '下一页', exact: true }).scrollIntoViewIfNeeded();
  assert.equal(await reader.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  await snap(reader, '02-readonly-mobile-short.png'); await reader.close();

  access = { ...access, can_manage_application_grants: true };
  const granter = await browser.newPage({ viewport: { width: 1440, height: 950 } }); await setup(granter);
  await granter.goto(`${base}/?rd_view=workspace&workspace_item=resource-1&workspace_version=1`);
  await granter.getByRole('button', { name: '授予应用', exact: true }).waitFor();
  assert.equal(await granter.getByRole('button', { name: '发布版本', exact: true }).count(), 0);
  assert.equal(await granter.locator('#rd-resource-name').count(), 0);
  await granter.getByText('查看资源配置', { exact: true }).click(); await snap(granter, '03-granter-surface.png');
  failGrant = true;
  await granter.getByRole('button', { name: '授予应用', exact: true }).click();
  const grantDialog = granter.getByRole('dialog');
  await grantDialog.getByRole('button', { name: '授予应用', exact: true }).click();
  await grantDialog.getByText('授权结果尚未确认，请重试', { exact: true }).waitFor();
  const firstGrant = writes.at(-1);
  await grantDialog.getByRole('button', { name: '授予应用', exact: true }).click(); await grantDialog.waitFor({ state: 'hidden' });
  assert.equal(writes.at(-1).key, firstGrant.key); assert.deepEqual(writes.at(-1).body, firstGrant.body);
  await granter.getByRole('button', { name: '撤销授权', exact: true }).click();
  await granter.getByRole('dialog').getByRole('button', { name: '撤销授权', exact: true }).click();
  await granter.getByRole('dialog').waitFor({ state: 'hidden' });
  assert.equal(writes.at(-1).body.operation, 'revoke');
  resourceRetired = true;
  await granter.getByRole('button', { name: '刷新资源', exact: true }).click();
  await granter.getByText('资源整体状态：已停用，所有版本暂停 · 控制修订 6', { exact: true }).waitFor();
  assert.equal(await granter.getByRole('button', { name: '授予应用', exact: true }).isDisabled(), true, 'whole-resource retirement blocks granting even when fixed version is published');
  resourceRetired = false;
  await granter.close();

  access = { ...access, can_manage_application_grants: false, can_edit_resources: true, can_publish_resources: true };
  const publisher = await browser.newPage({ viewport: { width: 1440, height: 950 } }); await setup(publisher);
  await publisher.goto(`${base}/?rd_view=workspace&workspace_item=resource-1&workspace_version=1`);
  await publisher.getByRole('button', { name: '编辑资源', exact: true }).waitFor();
  await publisher.setViewportSize({ width: 390, height: 520 });
  await publisher.getByRole('heading', { name: '本地 Workspace', exact: true }).scrollIntoViewIfNeeded();
  await snap(publisher, '07-publisher-mobile-header.png');
  await publisher.setViewportSize({ width: 1440, height: 950 });
  await publisher.getByRole('button', { name: '编辑资源', exact: true }).click();
  assert.equal(await publisher.getByRole('button', { name: '授予应用', exact: true }).count(), 0);
  await publisher.getByLabel('资源名称', { exact: true }).fill('我的保留草稿'); failSave = 'conflict'; latestVersion = 4;
  await publisher.getByRole('button', { name: '保存资源', exact: true }).click();
  await publisher.getByRole('button', { name: '读取最新版本并保留填写', exact: true }).click();
  await publisher.getByText('已读取目标最新修订，当前填写保留。请核对后重新操作。', { exact: true }).waitFor();
  assert.equal(await publisher.getByLabel('资源名称', { exact: true }).inputValue(), '我的保留草稿');
  assert(requests.some(item => item.path === '/api/rd/workspace/resources/resource-1/latest'));
  failSave = 'network'; await publisher.getByRole('button', { name: '保存资源', exact: true }).click();
  await publisher.getByRole('alert').filter({ hasText: '保存结果尚未确认' }).waitFor();
  const firstSave = writes.at(-1); assert.equal(firstSave.body.expected_version, 4);
  await publisher.getByRole('button', { name: '保存资源', exact: true }).click();
  await publisher.getByText('草稿已保存；发布与应用授权需分别办理。', { exact: true }).waitFor();
  assert.equal(writes.at(-1).key, firstSave.key);
  await publisher.getByRole('button', { name: '停用资源', exact: true }).click();
  await publisher.getByRole('dialog').getByRole('button', { name: '停用资源', exact: true }).click();
  await publisher.getByRole('dialog').waitFor({ state: 'hidden' });
  assert.equal(writes.at(-1).body.expected_state_revision, 2); assert(!('configuration' in writes.at(-1).body));
  failSave = 'conflict';
  await publisher.getByRole('button', { name: '恢复发布', exact: true }).click();
  await publisher.getByRole('dialog').getByRole('button', { name: '恢复发布', exact: true }).click();
  await publisher.getByRole('button', { name: '读取最新版本并保留填写', exact: true }).click();
  await publisher.getByText('已读取目标最新修订，当前填写保留。请核对后重新操作。', { exact: true }).waitFor();
  assert(requests.some(item => item.path === '/api/rd/workspace/resources/resource-1/4'));
  await publisher.getByRole('button', { name: '恢复发布', exact: true }).click();
  await publisher.getByRole('dialog').getByRole('button', { name: '恢复发布', exact: true }).click();
  await publisher.getByRole('dialog').waitFor({ state: 'hidden' });
  assert.equal(writes.at(-1).body.operation, 'publish'); assert.equal(writes.at(-1).body.version, 4); assert.equal(writes.at(-1).body.expected_version, 4);
  assert(!('configuration' in writes.at(-1).body));
  await publisher.getByLabel('查看固定版本', { exact: true }).click();
  await publisher.getByRole('option', { name: '固定版本 v1', exact: true }).click();
  await publisher.getByRole('heading', { name: '本地能力 1 · v1', exact: true }).waitFor();
  await publisher.getByRole('button', { name: '停用资源', exact: true }).click();
  await publisher.getByRole('dialog').getByRole('button', { name: '停用资源', exact: true }).click();
  await publisher.getByRole('dialog').waitFor({ state: 'hidden' });
  assert.equal(writes.at(-1).body.version, 1); assert.equal(writes.at(-1).body.expected_version, 4, 'historical status command carries latest head CAS');
  publicationStatus = 'published';
  await publisher.getByRole('button', { name: '刷新资源', exact: true }).click();
  await publisher.getByRole('button', { name: '恢复发布', exact: true }).waitFor();
  assert.equal(await publisher.getByRole('button', { name: '恢复发布', exact: true }).isEnabled(), true);
  await publisher.getByText('资源整体状态：已停用，所有版本暂停 · 控制修订 6', { exact: true }).waitFor();
  await publisher.getByRole('button', { name: '恢复发布', exact: true }).click();
  await publisher.getByRole('dialog').getByText(/将解除资源整体停用/).waitFor();
  await publisher.getByRole('dialog').getByRole('button', { name: '恢复发布', exact: true }).click();
  await publisher.getByRole('dialog').waitFor({ state: 'hidden' });
  await publisher.getByText('资源整体状态：未整体停用 · 控制修订 6', { exact: true }).waitFor();
  await publisher.setViewportSize({ width: 390, height: 520 });
  await publisher.getByLabel('资源名称', { exact: true }).fill('窄屏保存按钮可达验证');
  await publisher.getByLabel('资源配置（JSON）', { exact: true }).fill('[]');
  await publisher.getByRole('button', { name: '保存资源', exact: true }).scrollIntoViewIfNeeded();
  await publisher.getByRole('button', { name: '保存资源', exact: true }).click();
  await publisher.getByRole('alert').filter({ hasText: '资源配置必须是 JSON 对象' }).waitFor();
  assert.equal(await publisher.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  await publisher.getByRole('button', { name: '保存资源', exact: true }).scrollIntoViewIfNeeded();
  await snap(publisher, '06-publisher-mobile-short.png');
  await publisher.getByRole('button', { name: '清空填写', exact: true }).click();
  await publisher.getByRole('dialog').getByRole('button', { name: '放弃填写', exact: true }).click();
  await publisher.setViewportSize({ width: 1440, height: 950 });
  await publisher.locator('.rd-resource-detail').scrollIntoViewIfNeeded();
  await snap(publisher, '04-publisher-desktop.png');
  denyManagement = true; await publisher.getByRole('button', { name: '刷新资源', exact: true }).click();
  await publisher.getByRole('alert').filter({ hasText: '资源治理权限已撤销' }).waitFor();
  assert.equal(await publisher.locator('.rd-resource-list > article').count(), 0);
  assert.equal(await publisher.locator('#rd-resource-configuration').count(), 0);
  assert.equal(await publisher.getByText('management-only-configuration', { exact: false }).count(), 0);
  await publisher.close();

  // An explicit 403 invalidates already-in-flight fixed/head reads and mutation receipts.
  for (const race of ['refresh', 'mutation']) {
    denyManagement = false;
    const raced = await browser.newPage({ viewport: { width: 1440, height: 950 } }); await setup(raced);
    await raced.goto(`${base}/?rd_view=workspace&workspace_item=resource-1&workspace_version=1`);
    await raced.getByRole('button', { name: '编辑资源', exact: true }).click();
    await raced.getByLabel('资源名称', { exact: true }).fill(`并发撤权-${race}`);
    let ready;
    if (race === 'refresh') {
      failSave = 'conflict';
      await raced.getByRole('button', { name: '保存资源', exact: true }).click();
      const held = new Promise(resolve => { onDetailHeld = resolve; }); holdNextDetail = true;
      await raced.getByRole('button', { name: '读取最新版本并保留填写', exact: true }).click(); ready = held;
    } else {
      const held = new Promise(resolve => { onWriteHeld = resolve; }); holdNextWrite = true;
      await raced.getByRole('button', { name: '保存资源', exact: true }).click(); ready = held;
    }
    await ready;
    denyManagement = true;
    await raced.getByLabel('搜索资源', { exact: true }).fill('触发服务端撤权');
    await raced.getByRole('alert').filter({ hasText: '资源治理权限已撤销' }).waitFor();
    const readsBeforeRelease = requests.filter(item => item.path === '/api/rd/workspace/session').length;
    if (race === 'refresh') releaseDetail(); else releaseWrite();
    await raced.waitForTimeout(250);
    assert.equal(await raced.locator('.rd-resource-detail').count(), 0, `${race}: late receipt cannot restore detail`);
    assert.equal(await raced.locator('#rd-resource-configuration').count(), 0, `${race}: late receipt cannot restore configuration`);
    assert.equal(requests.filter(item => item.path === '/api/rd/workspace/session').length, readsBeforeRelease, `${race}: late receipt cannot trigger privileged refresh`);
    assert.equal(await raced.getByText('已读取目标最新修订，当前填写保留。请核对后重新操作。', { exact: true }).count(), 0);
    await raced.close();
  }

  access = { ...access, can_edit_resources: false, can_publish_resources: false }; denyManagement = false;
  const flow = await browser.newPage({ viewport: { width: 1440, height: 950 } }); await setup(flow);
  await flow.goto(`${base}/?rd_view=flows&flow_tab=resources&flow_page=2`);
  await flow.locator('.rd-flow-resource-card').first().waitFor(); assert.equal(await flow.locator('.rd-flow-resource-card').count(), 5);
  await flow.getByRole('tab', { name: '动作模板', exact: true }).click();
  await flow.getByRole('heading', { name: '本地动作 0', exact: true }).waitFor(); assert.equal(await flow.locator('.rd-flow-resource-card').count(), 5);
  await flow.getByRole('button', { name: '下一页', exact: true }).click();
  await flow.getByRole('heading', { name: '本地动作 5', exact: true }).waitFor(); assert.equal(await flow.locator('.rd-flow-resource-card').count(), 2);
  assert.equal(new URL(flow.url()).searchParams.get('flow_page'), '2'); await flow.reload();
  await flow.getByRole('heading', { name: '本地动作 5', exact: true }).waitFor();
  await flow.getByRole('tab', { name: '流程模板', exact: true }).click();
  await flow.getByRole('region', { name: '工作包节点预览', exact: true }).waitFor();
  await flow.getByRole('button', { name: /任务书工作包/ }).click(); assert.equal(new URL(flow.url()).searchParams.get('flow_item'), 'wp@1');
  await flow.getByRole('button', { name: '研发流程', exact: true }).click();
  await flow.getByRole('region', { name: '研发路径预览', exact: true }).waitFor();
  await flow.getByRole('tab', { name: '报告模板', exact: true }).click();
  await flow.getByRole('link', { name: '下载当前模板 ↗' }).waitFor();
  assert(requests.some(item => item.path === '/api/rd/catalog/items' && item.search.includes('category=reports')));
  await flow.setViewportSize({ width: 390, height: 520 });
  await flow.getByRole('button', { name: '下一页', exact: true }).scrollIntoViewIfNeeded();
  assert.equal(await flow.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  await snap(flow, '05-flow-mobile-short.png');
  assert.deepEqual(errors, []); console.log('P2A workspace and directory browser checks passed');
} finally { await browser.close(); }

