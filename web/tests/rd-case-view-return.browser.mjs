/** Same-case sidebar return regression. All HTTP data is isolated; no platform/model writes. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'runtime/rd-case-view-return-browser';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const stamp = '2026-11-05T02:00:00Z', actor = 'return-owner';
const workflow = { id: 'taskbook-generation', version: '1', template_id: 'taskbook-generation', template_version: '1', template_digest: 'return-fixed', digest: 'return-fixed', title: '研制任务书生成流程', category: 'project', status: 'published', publication_revision: 1,
  graph: { nodes: [{ id: 'input', title: '资料受理', role: '研发工程师', deliverables: [], position: { x: 0, y: 0 } }, { id: 'taskbook', title: '研制任务书生成', role: '研发工程师', deliverables: [], position: { x: 240, y: 0 }, workpackage_definition_id: 'taskbook' }], edges: [{ id: 'input-taskbook', source: 'input', target: 'taskbook' }] }, node_states: { input: 'pending', taskbook: 'pending' } };
const sources = ['tech', 'spec'].map(role => ({ id: role, role, name: role === 'tech' ? '返回链路技术要求.docx' : '返回链路产品规范.pdf', size: 2048, version: 1, sha256: role.repeat(16), created_at: stamp }));
const requirements = Array.from({ length: 12 }, (_, index) => ({ id: 'requirement-' + (index + 1), title: '压力要求 ' + (index + 1), content: '工作压力为 0.3 MPa。', source_ids: ['tech'], revision: 1, history: [], evidence: [{ source_id: 'tech', quote: '工作压力为 0.3 MPa。' }] }));
const analysis = { id: 'return-analysis', status: 'adopted', input_revision: 2, adopted_input_revision: 3, created_at: stamp, source_hashes: { tech: sources[0].sha256, spec: sources[1].sha256 }, model_selection: { provider: 'smartvision', name: 'azure/gpt-5.4', id: 'fixture-azure' }, context: {}, warnings: [], requirements: requirements.map(row => ({ ...row, requirement_id: row.id })) };
const researchCase = { id: 'return-case', title: '返回链路隔离流程', scenario_id: 'taskbook', stage: 'input', status: 'active', input_revision: 3,
  context: { product_type: 'liquid_cooling_pipeline', product_domain: 'military', product_series: 'YLZJ', organization_scope: 'non_central_research' }, sources, source_selection: { tech: 'tech', spec: 'spec' }, requirements, source_analysis: analysis, clarifications: [], comparisons: [], workpackages: [], decisions: [],
  product_route: null, composition_route: null, model_selection: { provider: '', name: '', id: '' }, workflow_templates: { project: workflow }, project_workflow_status: { status: 'pending', terminal_node_id: 'taskbook' },
  business_lifecycle: { policy_version: 'v2', rd_activation_state: 'not_started', review_mode: 'local_review', local_review_enabled: true, can_record_decision: true, can_confirm_requirements: true } };
const otherCase = { ...researchCase, id: 'return-other-case', title: '另一条独立流程', source_analysis: undefined, sources: [], source_selection: {}, requirements: [] };
const project = { id: 'return-project', title: '隔离返回测试项目', customer_name: '隔离客户', product_name: '液冷管路', owner_id: actor, members: [], events: [], version: 1, created_at: stamp, updated_at: stamp, cases: [researchCase, otherCase] };
const catalog = { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书', status: 'published' }], project_workflow_templates: [workflow], actions: [], workpackage_definitions: [] };
const checks = [], failures = [], unexpected = [], writes = [], pageErrors = [];
function check(condition, message) { if (condition) checks.push(message); else failures.push(message); }
async function settle(page) { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve))))); }

try {
  for (const surface of (process.env.TEST_CASE ? [process.env.TEST_CASE] : ['sources', 'requirements'])) {
    assert(['sources', 'requirements'].includes(surface), 'TEST_CASE must identify an existing editing surface');
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage(); page.setDefaultTimeout(15000);
    let sessionStatus = 200;
    page.on('pageerror', error => pageErrors.push(error.message));
    await page.route('**/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname;
      if (!path.startsWith('/api/')) return route.continue();
      if (!['GET', 'HEAD'].includes(request.method())) writes.push({ method: request.method(), path });
      if (request.method() === 'GET') {
        if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: false, authenticated: false, user: null } });
        if (path === '/api/rd/session') return route.fulfill({ status: sessionStatus, json: sessionStatus === 200 ? { actor_id: actor, local_mode: true } : { error: '会话服务暂不可用' } });
        if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [project] } });
        if (path === '/api/rd/projects/' + project.id) return route.fulfill({ json: project });
        if (path === '/api/rd/catalog') return route.fulfill({ json: catalog });
        if (path === '/api/rd/catalog/items') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 5, total_pages: 1 } });
        if (path === '/api/models') return route.fulfill({ json: { success: true, models: [{ provider: 'smartvision', name: 'azure/gpt-5.4', id: 'fixture-azure', vendor: '微软 Azure', configured: true }] } });
        if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [{ value: 'liquid_cooling_pipeline', label: '液冷产品-液冷管路', enabled: true, domains: [{ value: 'military', label: '军品' }] }] } });
        if (path === '/api/rd/assistant/weather') return route.fulfill({ json: { status: 'unavailable', location: '隔离测试', notice: '返回测试不读取天气。' } });
        if (path.endsWith('/assistant')) return route.fulfill({ json: { messages: [], suggestions: [], context: { stage: 'input', project_version: 1, input_revision: 3 } } });
      }
      unexpected.push({ method: request.method(), path });
      return route.fulfill({ status: 500, json: { error: '返回测试不允许此请求：' + path } });
    });
    const side = name => page.getByRole('navigation', { name: '当前业务流程视图', exact: true }).getByRole('button', { name, exact: true });
    await page.goto(`${base}/?rd_view=projects&project=${project.id}&case=${researchCase.id}&case_view=current&step=${surface}`);
    await page.locator('#rd-case-workarea').waitFor();
    await page.getByRole('navigation', { name: '办理步骤', exact: true }).locator('[aria-current="step"]').waitFor();
    let readDraft;
    if (surface === 'sources') {
      await page.locator('.rd-analysis-model-field .ant-select-selector').click();
      await page.getByRole('option', { name: '微软 Azure · azure/gpt-5.4', exact: true }).click();
      readDraft = () => page.locator('.rd-analysis-model-field .ant-select-selection-item').textContent();
    } else {
      await page.getByRole('textbox', { name: '压力要求 1 实际结果', exact: true }).fill('0.35 MPa，尚未提交');
      await page.getByText('补充或修订需求记录', { exact: true }).click();
      await page.getByRole('textbox', { name: '需求标题', exact: true }).fill('尚未提交的返回链路需求');
      await page.getByRole('textbox', { name: '需求内容', exact: true }).fill('保留此处未保存填写，返回时继续编辑。');
      readDraft = async () => JSON.stringify({ title: await page.getByRole('textbox', { name: '需求标题', exact: true, includeHidden: true }).inputValue(), actual: await page.getByRole('textbox', { name: '压力要求 1 实际结果', exact: true, includeHidden: true }).inputValue() });
    }
    await settle(page);
    // The source page is long enough to read below the model selector; the requirement form is near its end.
    await page.locator('.rd-application-shell').evaluate((element, target) => { element.scrollTop = target; }, surface === 'sources' ? 1100 : 1800);
    await settle(page);
    const before = await page.locator('.rd-application-shell').evaluate(element => ({ top: element.scrollTop, height: element.scrollHeight, viewport: element.clientHeight }));
    assert(before.top > 500, `${surface}: fixture must reproduce a scrolled editing workface`);
    const draftBefore = await readDraft();
    await page.screenshot({ path: join(output, `${surface}-before.png`) });
    await side('项目流程').click();
    await page.getByRole('region', { name: '项目固定流程', exact: true }).waitFor();
    await side('当前成果').click();
    await settle(page);
    const after = { step: new URL(page.url()).searchParams.get('step'), title: await page.locator('.rd-case-heading h1').innerText(), top: await page.locator('.rd-application-shell').evaluate(element => element.scrollTop), draft: await readDraft(), leaveDialogs: await page.getByRole('dialog', { name: '未保存的填写', exact: true }).count() };
    await page.screenshot({ path: join(output, `${surface}-sidebar-return.png`) });
    check(after.step === surface, `${surface}: sidebar 当前成果 restores the last editing subpage (actual=${after.step})`);
    check(Math.abs(after.top - before.top) <= 3, `${surface}: sidebar return restores the reading position (before=${before.top}, after=${after.top})`);
    check(after.draft === draftBefore, `${surface}: switching the same-case sidebar retains the unsaved draft`);
    check(after.leaveDialogs === 0, `${surface}: internal switching does not ask to discard the retained draft`);
    let explicitReturn = null;
    if (after.step !== surface) {
      await page.getByRole('button', { name: '返回办理', exact: true }).click();
      await page.getByRole('navigation', { name: '办理步骤', exact: true }).locator('[aria-current="step"]').waitFor();
      await settle(page);
      explicitReturn = { step: new URL(page.url()).searchParams.get('step'), top: await page.locator('.rd-application-shell').evaluate(element => element.scrollTop), draft: await readDraft() };
      check(explicitReturn.step === surface, `${surface}: 返回办理 already restores the correct subpage`);
      check(explicitReturn.draft === draftBefore, `${surface}: original draft is still present after explicitly returning`);
      check(Math.abs(explicitReturn.top - before.top) <= 3, `${surface}: 返回办理 restores the reading position (before=${before.top}, after=${explicitReturn.top})`);
      await page.screenshot({ path: join(output, `${surface}-explicit-return.png`) });
    }
    await writeFile(join(output, `${surface}-observed.json`), JSON.stringify({ surface, before, draftBefore, after, explicitReturn }, null, 2));
    if (after.step === surface) {
      for (const auxiliary of ['项目流程', '资料与依据', '项目流程']) {
        await side(auxiliary).click(); await settle(page);
        await side('当前成果').click(); await settle(page);
        assert.equal(new URL(page.url()).searchParams.get('step'), surface, `${surface}: repeated ${auxiliary} return preserves the editing subpage`);
        assert(Math.abs(await page.locator('.rd-application-shell').evaluate(element => element.scrollTop) - before.top) <= 3, `${surface}: repeated ${auxiliary} return preserves the reading position`);
        assert.equal(await readDraft(), draftBefore, `${surface}: repeated ${auxiliary} return retains the draft`);
      }
      const overview = page.getByRole('button', { name: '成果概览', exact: true });
      await overview.scrollIntoViewIfNeeded(); await settle(page);
      const explicitLeaveTop = await page.locator('.rd-application-shell').evaluate(element => element.scrollTop);
      await overview.click(); await settle(page);
      assert.equal(new URL(page.url()).searchParams.get('step'), 'current', 'explicit overview remains an overview');
      await page.goBack(); await settle(page);
      assert.equal(new URL(page.url()).searchParams.get('step'), surface, 'browser Back restores the explicit previous workface');
      assert(Math.abs(await page.locator('.rd-application-shell').evaluate(element => element.scrollTop) - explicitLeaveTop) <= 3, 'browser Back restores the editing position immediately before opening the overview');
      await page.goForward(); await settle(page);
      assert.equal(new URL(page.url()).searchParams.get('step'), 'current', 'browser Forward honors the explicit overview route');
      await page.getByRole('button', { name: '返回办理', exact: true }).click(); await settle(page);
      assert.equal(await readDraft(), draftBefore, 'explicit return preserves the original draft');
      assert(Math.abs(await page.locator('.rd-application-shell').evaluate(element => element.scrollTop) - explicitLeaveTop) <= 3, 'explicit return restores the last editing reading position');
      checks.push(`${surface}: repeated auxiliary switching, explicit overview and browser history preserve the intended workface, reading position and draft`);
    }
    if (surface === 'requirements') {
      const beforeSessionDraft = await readDraft();
      sessionStatus = 503;
      const failedRefresh = page.waitForResponse(response => new URL(response.url()).pathname === '/api/rd/session' && response.status() === 503);
      await page.evaluate(() => window.dispatchEvent(new Event('focus')));
      await (await failedRefresh).finished(); await settle(page);
      assert.equal(await page.locator('#rd-req-title').count(), 1, 'temporary session failure must not unmount the open new-requirement editor');
      assert.equal(await readDraft(), beforeSessionDraft, 'temporary session failure preserves both new-requirement and actual-value drafts');
      assert(await page.getByRole('textbox', { name: '需求标题', exact: true }).isDisabled(), 'unverified session temporarily disables editing without clearing fields');
      assert(await page.getByRole('button', { name: '保存需求记录', exact: true }).isDisabled(), 'unverified session cannot submit requirement changes');
      await page.getByRole('button', { name: '重新核验', exact: true }).waitFor();
      sessionStatus = 200;
      const recoveredRefresh = page.waitForResponse(response => new URL(response.url()).pathname === '/api/rd/session' && response.status() === 200);
      await page.getByRole('button', { name: '重新核验', exact: true }).click();
      await (await recoveredRefresh).finished(); await settle(page);
      assert.equal(await readDraft(), beforeSessionDraft, 'successful session recovery keeps both unsaved drafts intact');
      assert(await page.getByRole('textbox', { name: '需求标题', exact: true }).isEditable(), 'the same verified account can continue editing after recovery');
      assert.equal(await page.getByRole('button', { name: '重新核验', exact: true }).count(), 0, 'the temporary failure message clears after successful verification');
      checks.push('requirements: a focus-triggered session 503 retains both drafts, blocks submissions, and inline verification restores editing');
    }
    await page.goto(`${base}/?rd_view=projects&project=${project.id}&case=${otherCase.id}&case_view=current`);
    await page.waitForURL(url => url.searchParams.get('step') === 'sources'); await settle(page);
    assert.equal(await page.locator('.rd-case-heading h1').innerText(), '资料识别与项目信息', 'a different case opens its own initial workface');
    assert(await page.locator('.rd-application-shell').evaluate(element => element.scrollTop) < 500, 'a different case does not inherit the previous case reading position');
    assert.equal(await page.locator('.rd-current-files .rd-source-card').count(), 0, 'a different case does not inherit the previous files');
    assert.equal(await page.locator('.rd-analysis-model-field .ant-select-selection-item').innerText(), '使用平台默认模型', 'a different case does not inherit an unsaved model choice');
    checks.push(`${surface}: another case retains its own route, scroll position and source/model state`);
    await context.close();
  }
  assert.deepEqual(pageErrors, [], 'no browser runtime errors');
  assert.deepEqual(unexpected, [], 'the test must not silently reach unmocked endpoints');
  assert.deepEqual(writes, [], 'navigation must not issue business writes');
  assert.deepEqual(failures, [], 'sidebar navigation must preserve the editing subpage and reading position');
} finally {
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ checks, failures, unexpected, writes, pageErrors }, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ checks, screenshots: output }));
