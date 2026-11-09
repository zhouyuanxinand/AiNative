/** Runs the real requirements screen with isolated project/command fixtures. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const original = ['额定电压', '连接路数', '工作压力'];
const values = ['24 V', '8 路', '0.3 MPa'];
const recs = ['24 V 直流', '8 路独立回路'];
const basis = recs.map(value => ({ text: '补充适用条件', proposed_value: value, evidence: [{ source_id: 'spec', quote: value }] }));
const sources = ['tech', 'spec'].map((id, i) => ({ id, role: id, name: ['客户需求.docx','企业产品规范.docx'][i], version: 1, sha256: id, size: 16 }));
const items = original.map((title, i) => ({ id: 'req-' + i, title, content: values[i], source_ids: ['tech'], revision: 1 }));
const rc = { id: 'case', scenario_id: 'taskbook', title: '研制流程', stage: 'input', status: 'draft', context: {}, input_revision: 2,
  sources, requirements: items, product_route: null, composition_route: null, decisions: [], workpackages: [],
  clarifications:[{ id:'clar-pressure', requirement_id:'req-2', question:'请核实工作压力', answer:null, status:'open', input_revision:2, requirement_revision:1, revision:1, source_ids:['tech'], answer_source_ids:[], actor:'owner', created_at:'2026-11-05T02:00:00Z' }],
  source_selection: { tech:'tech', spec:'spec' }, source_analysis: { id:'analysis', input_revision:1, adopted_input_revision:2, status:'adopted',
    model_selection:{ provider:'fixture', id:'1', name:'test' }, context:{}, warnings:[], source_hashes:{ tech:'tech', spec:'spec' },
    requirements: items.map(row => ({ title:row.title, content:row.content, source_ids:['tech'], evidence:[{ source_id:'tech', quote:row.content }], requirement_id:row.id })) },
  requirement_recommendations: { id:'spec-batch', status:'current', input_revision:2, created_at:'2026-11-05T02:00:00Z',
    model_selection:{ provider:'fixture', id:'1', name:'test' }, source_hashes:{ tech:'tech', spec:'spec' }, warnings:[],
    items:items.map((row,i)=>({ requirement_id:row.id, requirement_revision:row.revision,
      ...(basis[i] ? { ...basis[i], status:'matched' } : { status:'not_found', text:'规范未找到对应指标', evidence:[] }) })) } };
const project = { id:'project', title:'需求复核验证', owner_id:'owner', members:['member'], version:1, cases:[rc], events:[] };
let actor = 'owner', fail = true;
const commands = [], faults = [];
try {
  const page = await browser.newPage({ viewport:{ width:1440, height:1000 } });
  page.setDefaultTimeout(20000);
  page.on('pageerror', err => faults.push(err.message));
  page.on('dialog', async dialog => { if (dialog.type() === 'beforeunload') await dialog.accept(); else await dialog.dismiss(); });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()).pathname;
    if (!url.startsWith('/api/')) return route.continue();
    if (url === '/api/current-user') return route.fulfill({ json:{ auth_enabled:false, authenticated:false, user:null } });
    if (url === '/api/rd/session') return route.fulfill({ json:{ actor_id:actor, local_mode:true } });
    if (url === '/api/rd/catalog') return route.fulfill({ json:{ stages:[], scenarios:[{ id:'taskbook', title:'研制任务书' }], actions:[], workpackage_definitions:[] } });
    if (url === '/api/rd/projects') return route.fulfill({ json:{ projects:[project] } });
    if (url === '/api/rd/projects/project') return route.fulfill({ json:project });
    if (url.endsWith('/evidence-locations') && route.request().method() === 'GET') return route.fulfill({ json:{ items:basis.flatMap((recommendation, index) => recommendation.evidence.map(evidence => ({ ...evidence, analysis_id:'spec-batch', status:'located', source_name:'企业产品规范.docx', source_version:1, locations:[{ id:'B00' + String(index + 1).padStart(2, '0'), label:'第 ' + (index + 1) + ' 段' }] }))) } });
    if (url === '/api/models') return route.fulfill({ json:{ success:true, models:[] } });
    if (url === '/api/product_catalog') return route.fulfill({ json:{ product_types:[] } });
    if (url.endsWith('/assistant')) return route.fulfill({ json:{ messages:[], suggestions:[], context:{ stage:rc.stage, project_version:project.version, input_revision:rc.input_revision } } });
    if (url.endsWith('/commands')) {
      const body = route.request().postDataJSON();
      assert.equal(body.expected_version,project.version);
      assert.equal(body.data.case_id,rc.id);
      commands.push(body);
      if (body.command === 'answer_clarification') {
        const record = rc.clarifications.find(item => item.id === body.data.clarification_id);
        assert(record); assert(body.data.answer.trim()); assert(body.data.source_ids.length);
        record.answer=body.data.answer; record.answer_source_ids=body.data.source_ids;
        record.answer_source_snapshots=sources.filter(source=>record.answer_source_ids.includes(source.id)).map(({id,role,name,version,sha256})=>({id,role,name,version,sha256}));
        record.status='answered'; record.input_revision=rc.input_revision; record.requirement_revision=items.find(item=>item.id===record.requirement_id).revision;
        record.answered_at='2026-11-06T02:00:00Z'; record.answered_by=actor; project.version++;
        return route.fulfill({ json:project });
      }
      if (body.command === 'adopt_clarification') {
        const record = rc.clarifications.find(item=>item.id===body.data.clarification_id);
        assert.equal(record.status,'answered'); assert(body.data.requirement_content.trim());
        const row=items.find(item=>item.id===record.requirement_id);
        row.content=body.data.requirement_content; row.revision++; rc.input_revision++; project.version++;
        row.history=[{revision:row.revision,clarification_id:record.id}];
        record.status='adopted'; record.adoption={requirement_content:row.content,requirement_revision:row.revision,input_revision:rc.input_revision,recommendation_batch_id:'spec-batch',source_hashes:{tech:'tech',spec:'spec'},actor,created_at:'2026-11-06T02:00:00Z'};
        rc.source_analysis.adopted_input_revision=rc.input_revision; rc.requirement_recommendations.input_revision=rc.input_revision;
        return route.fulfill({ json:project });
      }
      assert.equal(body.command,'review_requirement');
      const { decision, requirement_id, requirement_revision, case_id, analysis_id, recommendation_batch_id, actual_value, reason } = body.data;
      assert.equal(case_id,rc.id);
      assert.equal(analysis_id,'analysis');
      assert.equal(recommendation_batch_id,'spec-batch');
      const row = items.find(row => row.id === requirement_id);
      assert.equal(requirement_revision,row.revision);
      if (fail) { fail = false; return route.fulfill({ status:503, json:{ error:'需求保存暂不可用' } }); }
      assert(['accept','reject'].includes(decision)); assert.equal(actual_value,undefined);
      row.content = decision === 'accept' ? recs[items.indexOf(row)] : row.content;
      row.revision++; project.version++; rc.input_revision++; rc.source_analysis.adopted_input_revision = rc.input_revision;
      rc.requirement_recommendations.input_revision = rc.input_revision;
      row.review = { decision, actual_value:decision==='reject'?null:row.content, reason:reason || '', requirement_revision:row.revision, input_revision:rc.input_revision, analysis_id, recommendation_batch_id };
      return route.fulfill({ json:project });
    }
    return route.fulfill({ json:{} });
  });
  await page.goto((process.env.TEST_BASE_URL || 'http://127.0.0.1:18370') + '/?project=project&case=case&step=requirements');
  const table = page.locator('.rd-decision-table');
  await table.waitFor().catch(async err => { console.error('Rendered page:', await page.locator('body').innerText(), 'Errors:', faults); throw err; });
  const row = i => table.getByRole('row').filter({ has:page.locator('strong').filter({ hasText:original[i] }) });
  const actual = i => row(i).getByLabel(original[i] + ' 实际结果', { exact:true });
  for (const name of ['类别 / 指标','原始指标','AI 推荐','证据来源','操作','实际结果']) await table.getByRole('columnheader',{ name, exact:true }).waitFor();
  const recommendationSource = row(0).getByRole('button',{ name:'预览原文，定位 B0001', exact:true });
  await recommendationSource.waitFor();
  assert.equal(await recommendationSource.getAttribute('title'),'企业产品规范.docx · V1 · 第 1 段');
  assert.equal(await row(2).getByRole('button',{ name:'采纳', exact:true }).count(),0);
  for (let i=0;i<3;i++) assert.equal(await actual(i).innerText(),'--');
  const oldDraftKey='rd:requirement-draft:v1:'+JSON.stringify(['owner','owner',project.id,rc.id,items[2].id]);
  await page.evaluate(({key,value})=>localStorage.setItem(key,JSON.stringify({base:'historical-version',value,reason:'原浏览器草稿',rejecting:false})),{key:oldDraftKey,value:'人工核实为 0.4 MPa'});
  await page.reload(); await table.waitFor();
  await row(2).getByText('旧版草稿 · 不会应用').click();
  await row(2).getByText('人工核实为 0.4 MPa',{exact:true}).waitFor();
  assert.equal(await row(2).getByRole('button',{name:'保存实际结果'}).count(),0,'legacy drafts can only be viewed, copied or discarded');
  assert.equal(await row(2).locator('.ant-typography-copy').count(),1,'legacy text can be copied for clarification');
  const reviewTools = page.getByRole('region', { name:'筛选需求确认', exact:true });
  const search = reviewTools.getByRole('textbox', { name:'搜索需求确认', exact:true });
  await reviewTools.getByRole('button', { name:'待澄清（1）', exact:true }).click();
  assert.equal(await table.locator('tbody tr[data-row-key]').count(),1, 'clarification filter uses current requirement IDs');
  assert.equal(await row(2).count(),1);
  await reviewTools.getByRole('button', { name:'全部（3）', exact:true }).click();
  await search.fill('工作压力');
  assert.equal(await table.locator('tbody tr[data-row-key]').count(),1);
  assert.equal(await row(2).locator('.rd-req-metric > span').innerText(),'03', 'search retains original row number');
  await reviewTools.getByRole('button', { name:'填写草稿（1）', exact:true }).click();
  assert.equal(await actual(2).innerText(),'--');
  await search.fill('没有这项指标');
  await table.getByText('没有匹配的需求，请调整搜索或筛选。', { exact:true }).waitFor();
  await search.fill('');
  await reviewTools.getByRole('button', { name:'全部（3）', exact:true }).click();
  await row(2).getByText('旧版草稿 · 不会应用').click();
  await row(2).getByText('人工核实为 0.4 MPa',{exact:true}).waitFor();
  await reviewTools.getByRole('button', { name:'下一项待处理', exact:true }).click();
  assert.equal(await table.locator('tr[data-row-key="req-0"]').evaluate(el=>el===document.activeElement),true, 'next pending focuses the real row');
  if (process.env.SCREENSHOT_DIR) { await mkdir(process.env.SCREENSHOT_DIR,{ recursive:true }); await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'requirement-review-tools-desktop.png')}); }
  await search.fill('连接路数');
  await row(1).getByRole('button',{name:'不采纳',exact:true}).click();
  assert(await row(1).getByRole('button',{name:'确认不采纳',exact:true}).isDisabled());
  await row(1).getByLabel(original[1]+' 不采纳原因').fill('规格未要求独立回路');
  await row(1).getByRole('button',{name:'确认不采纳',exact:true}).click();
  await page.getByRole('alert').filter({ hasText:'需求保存暂不可用' }).first().waitFor();
  assert.equal(await row(1).getByLabel(original[1]+' 不采纳原因').inputValue(),'规格未要求独立回路');
  await page.reload();
  assert.equal(await row(1).getByLabel(original[1]+' 不采纳原因').inputValue(),'规格未要求独立回路');
  actor = 'member'; await page.reload();
  assert.equal(await row(1).getByLabel(original[1]+' 不采纳原因').count(),0,'another account does not see the owner rejection draft');
  assert.equal(await row(2).getByText('旧版草稿 · 不会应用').count(),0,'historical draft is account-isolated');
  actor = 'owner'; await page.reload();
  assert.equal(await row(1).getByLabel(original[1]+' 不采纳原因').inputValue(),'规格未要求独立回路');
  await row(0).getByRole('button',{ name:'采纳', exact:true }).click();
  await row(0).getByText('已采纳',{ exact:true }).waitFor();
  await reviewTools.getByRole('button', { name:'待决定（2）', exact:true }).waitFor();
  await reviewTools.getByRole('button', { name:'待决定（2）', exact:true }).click();
  assert.equal(await row(0).count(),0, 'reviewed items leave the pending filter');
  await reviewTools.getByRole('button', { name:'全部（3）', exact:true }).click();
  assert.equal(await actual(0).innerText(),recs[0]);
  assert.equal((await row(0).getByRole('cell').nth(1).innerText()).startsWith(values[0]),true);
  assert.equal(await row(1).getByLabel(original[1]+' 不采纳原因').inputValue(),'规格未要求独立回路','unrelated row update preserves rejection draft');
  await row(1).getByRole('button',{ name:'确认不采纳', exact:true }).click();
  await row(1).getByText('不采纳 · 待澄清',{exact:true}).waitFor();
  assert.equal(await actual(1).innerText(),'--');
  assert.equal(items[1].content,values[1],'rejection retains original content without treating it as adopted');
  await page.locator('.rd-record-new').getByLabel('需要澄清的问题').waitFor();
  await page.locator('.rd-record-new .ant-select-selection-item').filter({hasText:'连接路数 · v2'}).waitFor();
  rc.requirements[2].review={decision:'manual',actual_value:'历史填写0.4 MPa',reason:'旧记录',requirement_revision:1};
  rc.requirements[2].revision++; rc.input_revision++; rc.source_analysis.adopted_input_revision=rc.input_revision; project.version++;
  rc.requirement_recommendations.input_revision = rc.input_revision;
  rc.requirement_recommendations.items[2].requirement_revision = rc.requirements[2].revision;
  await page.reload();
  await row(2).getByText('旧版草稿 · 不会应用').waitFor();
  assert.equal(await actual(2).innerText(),'--');
  assert.equal(await row(2).getByRole('textbox').count(),0);
  await row(2).getByText('历史填写记录').click();
  await row(2).getByText('历史填写0.4 MPa',{exact:true}).waitFor();
  await row(2).getByRole('button',{ name:'放弃旧稿' }).click();
  const clarification=page.locator('[data-clarification-id="clar-pressure"]');
  await clarification.locator('summary').click();
  await clarification.getByLabel('澄清答复',{exact:true}).fill('此型号不含承压接口，工作压力不适用。');
  await clarification.getByRole('button',{name:'针对当前版本重新答复',exact:true}).click();
  await clarification.getByText('请填写答复并关联真实来源。',{exact:true}).waitFor();
  await clarification.getByRole('checkbox',{name:/客户需求.docx/}).check();
  await clarification.getByRole('button',{name:'针对当前版本重新答复',exact:true}).click();
  await clarification.getByLabel('采用后的完整需求正文',{exact:true}).waitFor();
  assert.equal(await actual(2).innerText(),'--','saving an answer is not adopting it');
  assert(await clarification.getByRole('button',{name:'核对并采用答复',exact:true}).isDisabled());
  await clarification.getByLabel('采用后的完整需求正文',{exact:true}).fill('工作压力不适用：此型号不含承压接口。');
  await clarification.getByRole('button',{name:'核对并采用答复',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'采用并重新确认',exact:true}).click();
  await row(2).getByText('澄清已采用',{exact:true}).waitFor();
  assert.equal(await actual(2).innerText(),'工作压力不适用：此型号不含承压接口。');
  assert.equal(await actual(0).innerText(),recs[0],'another row clarification does not invalidate a current accepted value');
  assert.equal(await actual(1).innerText(),'--','a rejected row still awaits its own clarification');
  if (process.env.SCREENSHOT_DIR) { await mkdir(process.env.SCREENSHOT_DIR,{ recursive:true }); await table.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'requirement-decisions.png')}); }
  await page.setViewportSize({ width:390,height:844 });
  assert.equal(await table.evaluate(el => el.scrollWidth <= el.clientWidth + 1),true, 'no overflow on narrow view');
  assert.equal(await reviewTools.evaluate(el => el.scrollWidth <= el.clientWidth + 1),true, 'review controls fit narrow view');
  if (process.env.SCREENSHOT_DIR) await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'requirement-review-tools-narrow.png')});
  rc.source_selection.tech='missing-current-source'; project.version++; await page.reload();
  await reviewTools.getByRole('button', {name:'来源待复核（3）',exact:true}).click();
  assert.equal(await table.locator('tbody tr[data-row-key]').count(),3);
  assert.equal(await actual(2).innerText(),'--','stale source cannot supply a current actual value');
  assert.equal(await row(2).getByRole('textbox').count(),0,'stale source remains read-only under its filter');
  rc.source_selection.tech='tech';
  rc.stage='selection'; await page.reload();
  await row(0).getByText('只读',{ exact:true }).waitFor();
  assert.equal(await table.locator('textarea').count(),0);
  assert.deepEqual(commands.map(call=>call.command==='review_requirement'?call.data.decision:call.command),['reject','accept','reject','answer_clarification','adopt_clarification']);
  assert.deepEqual(faults,[]);
  if (process.env.SCREENSHOT_DIR) await writeFile(path.join(process.env.SCREENSHOT_DIR,'receipt.json'),JSON.stringify({ passed:true, checks:['read-only results, explicit acceptance/rejection/clarification','failure + reload and personal rejection drafts','counted search/decision/draft/clarification/stale-source filters','stable row keys and numbers; filtered save targets original ID','next pending focuses actual row','historical drafts view/copy/discard, read-only and narrow controls'], fixtureCommands:commands.length,pageErrors:faults,realApiRequests:0 },null,2));
  console.log('PASS: evidence, explicit accept/reject/clarification, filtered commands + isolated drafts, counted filters, next pending, failure + reload, historical drafts, read-only and mobile layout');
} finally { await browser.close(); }
