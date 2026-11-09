/** Exercises the real table against isolated APIs; never updates project data on the server. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const sources = [
  { id:'tech', role:'tech', name:'客户技术要求.docx', version:1, sha256:'tech', size:16 },
  { id:'spec', role:'spec', name:'企业产品规范.docx', version:1, sha256:'spec', size:16 },
];
const names = ['额定电压','连接路数','工作压力','耐腐蚀','盐雾试验','工作温度','耐久性','连接方式'];
const items = names.map((title,index) => ({ id:'req-' + index, title, content:index ? '原文指标 ' + index : '24 V', source_ids:['tech'], revision:1 }));
const rc = {
  id:'case', scenario_id:'taskbook', title:'行内编辑验证流程', stage:'input', status:'draft', context:{}, input_revision:2,
  sources, source_selection:{ tech:'tech', spec:'spec' }, requirements:items,
  product_route:null, composition_route:null, decisions:[], workpackages:[], clarifications:[],
  source_analysis:{
    id:'analysis', input_revision:1, adopted_input_revision:2, status:'adopted', context:{}, warnings:[], source_hashes:{ tech:'tech', spec:'spec' },
    model_selection:{ provider:'fixture', id:'1', name:'test' },
    requirements:items.map(row => ({ requirement_id:row.id, title:row.title, content:row.content, source_ids:['tech'], evidence:[{ source_id:'tech', quote:row.content }] })),
  },
  requirement_recommendations:{
    id:'spec-batch', input_revision:2, status:'current', created_at:'2026-11-06T02:00:00Z', warnings:[], source_hashes:{ tech:'tech', spec:'spec' },
    model_selection:{ provider:'fixture', id:'1', name:'test' },
    items:items.map((row,index) => ({ requirement_id:row.id, requirement_revision:1, status:index === 0 ? 'not_found' : index === 2 ? 'difference' : index === 3 ? 'needs_review' : 'matched', text:'请核对适用条件', proposed_value:row.content + '（规范）', evidence:index === 0 ? [] : [{ source_id:'spec', quote:row.content + '（规范）' }] })),
  },
};
const project = { id:'project', title:'表格内需求修订验证', owner_id:'owner', members:[], version:1, cases:[rc], events:[] };
const commands = [], faults = [];
let failNextSave = true;

try {
  const page = await browser.newPage({ viewport:{ width:1440, height:1000 } });
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => faults.push(error.message));
  page.on('dialog', async dialog => { if (dialog.type() === 'beforeunload') await dialog.accept(); else await dialog.dismiss(); });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()).pathname;
    if (!url.startsWith('/api/')) return route.continue();
    if (url === '/api/current-user') return route.fulfill({ json:{ auth_enabled:false, authenticated:false, user:null } });
    if (url === '/api/rd/session') return route.fulfill({ json:{ actor_id:'owner', local_mode:true } });
    if (url === '/api/rd/catalog') return route.fulfill({ json:{ stages:[], scenarios:[{ id:'taskbook', title:'研制任务书' }], actions:[], workpackage_definitions:[] } });
    if (url === '/api/rd/projects') return route.fulfill({ json:{ projects:[project] } });
    if (url === '/api/rd/projects/project') return route.fulfill({ json:project });
    if (url.endsWith('/evidence-locations')) return route.fulfill({ json:{ items:[] } });
    if (url === '/api/models') return route.fulfill({ json:{ success:true, models:[] } });
    if (url === '/api/product_catalog') return route.fulfill({ json:{ product_types:[] } });
    if (url.endsWith('/assistant')) return route.fulfill({ json:{ messages:[], suggestions:[], context:{ stage:rc.stage, project_version:project.version, input_revision:rc.input_revision } } });
    if (url.endsWith('/commands')) {
      const body = route.request().postDataJSON();
      assert.equal(body.expected_version,project.version);
      assert.equal(body.data.case_id,rc.id);
      assert.equal(body.command,'save_requirement');
      commands.push(body);
      if (failNextSave) {
        failNextSave = false;
        return route.fulfill({ status:503, json:{ error:'需求保存暂不可用，请重试' } });
      }
      const row = rc.requirements.find(item => item.id === body.data.id);
      assert(row);
      assert(body.data.title.trim()); assert(body.data.content.trim());
      assert(body.data.source_ids.length);
      assert(body.data.source_ids.every(id => sources.some(source => source.id === id)));
      const previous = { revision:row.revision, title:row.title, content:row.content, source_ids:[...row.source_ids] };
      row.title=body.data.title; row.content=body.data.content; row.source_ids=[...body.data.source_ids]; row.revision++;
      row.history=[...(row.history || []), previous, { revision:row.revision, title:row.title, content:row.content, source_ids:[...row.source_ids], actor:'owner' }];
      delete row.review;
      project.version++; rc.input_revision++; rc.stage='input';
      // Ordinary edits invalidate analysis and downstream specification results; they do not adopt a value.
      rc.source_analysis.status='stale'; rc.requirement_recommendations.status='stale';
      return route.fulfill({ json:project });
    }
    return route.fulfill({ json:{} });
  });
  await page.goto((process.env.TEST_BASE_URL || 'http://127.0.0.1:18370') + '/?project=project&case=case&step=requirements');
  const table = page.locator('.rd-decision-table');
  await table.waitFor();
  const row = index => table.locator('tr[data-row-key="req-' + index + '"]');
  const actual = index => row(index).locator('.rd-review-actual > p');
  const editing = table.locator('tr.rd-requirement-editing');
  const cancel = async () => {
    await editing.getByRole('button',{ name:'取消', exact:true }).click();
    const discard = page.getByRole('dialog').getByRole('button',{ name:'放弃填写', exact:true });
    if (await discard.isVisible()) await discard.click();
    await editing.waitFor({ state:'hidden' });
  };
  assert.equal(await actual(0).innerText(),'--');
  await row(0).scrollIntoViewIfNeeded();
  const before = await row(0).boundingBox();
  await row(0).getByRole('button',{ name:'编辑需求', exact:true }).click();
  await editing.getByLabel('需求标题',{ exact:true }).waitFor();
  assert.equal(await editing.getAttribute('data-row-key'),'req-0');
  assert.equal(await editing.getByLabel('需求标题',{ exact:true }).inputValue(),'额定电压');
  assert.equal(await editing.getByLabel('需求内容',{ exact:true }).inputValue(),'24 V');
  const after = await editing.boundingBox();
  assert(before && after && after.y >= 0 && after.y < 1000 && Math.abs(after.y - before.y) < 160,'opening edit keeps the current row in view instead of focusing the bottom form');
  assert.equal(await page.getByRole('heading',{ name:'编辑需求记录', exact:true }).count(),0,'there is no second edit form at the bottom');
  await editing.getByLabel('需求内容',{ exact:true }).fill('取消时应保留原指标');
  assert(await row(2).getByRole('button',{ name:'编辑需求', exact:true }).isDisabled(),'one active editor prevents replacement by another editable row');
  assert.equal(await row(1).getByRole('button',{ name:'编辑需求', exact:true }).count(),0,'matched rows only support clarification');
  assert.equal(await row(1).getByRole('button',{ name:'采纳', exact:true }).count(),0,'matched rows are confirmed together without per-row adoption');
  assert(await row(3).getByRole('button',{ name:'采纳', exact:true }).isDisabled(),'editing cannot adopt another result');
  assert(await row(1).getByRole('button',{ name:'办理澄清', exact:true }).isDisabled(),'editing cannot open clarification with an unsaved draft');
  const side = name => page.getByRole('navigation',{ name:'当前业务流程视图', exact:true }).getByRole('button',{ name, exact:true });
  await side('项目流程').click();
  await page.locator('.rd-case-heading h1').filter({ hasText:/^项目流程$/ }).waitFor();
  assert.equal(await editing.isVisible(),false,'the table is hidden on the process view');
  await side('当前成果').click();
  await editing.getByLabel('需求内容',{ exact:true }).waitFor();
  assert.equal(await editing.getAttribute('data-row-key'),'req-0','returning to current results keeps the same editing row selected');
  assert.equal(await editing.getByLabel('需求内容',{ exact:true }).inputValue(),'取消时应保留原指标','same-case process switching preserves the row draft');
  assert.equal(await page.getByRole('dialog',{ name:'未保存的填写', exact:true }).count(),0,'a retained same-case draft does not trigger a discard dialog');
  assert.equal(commands.length,0,'view switching does not save the row');
  const search = page.getByRole('region',{ name:'筛选需求确认', exact:true }).getByRole('textbox',{ name:'搜索需求确认', exact:true });
  await search.fill('不存在的需求搜索词');
  await editing.getByLabel('需求内容',{ exact:true }).waitFor();
  assert.equal(await editing.getAttribute('data-row-key'),'req-0','an unmatched search keeps the selected editor mounted');
  assert.equal(await editing.getByLabel('需求内容',{ exact:true }).inputValue(),'取消时应保留原指标','searching never resets the row draft');
  assert.equal(await table.locator('tbody tr[data-row-key]').count(),1,'only the active unmatched row remains pinned');
  await search.fill('');
  await cancel();
  assert.equal(commands.length,0,'cancel never saves a requirement');
  assert.equal(items[0].content,'24 V');
  assert.equal(await actual(0).innerText(),'--');

  await row(0).getByRole('button',{ name:'编辑需求', exact:true }).click();
  await editing.getByLabel('需求标题',{ exact:true }).fill('额定直流电压');
  await editing.getByLabel('需求内容',{ exact:true }).fill('24 V DC，待核实接口适用条件');
  await editing.getByText('关联来源',{ exact:true }).click();
  await editing.getByRole('checkbox',{ name:/企业产品规范.docx/ }).check();
  const beforeSave = await editing.boundingBox();
  await editing.getByRole('button',{ name:'保存', exact:true }).click();
  await editing.getByRole('alert').waitFor();
  const afterFailure = await editing.boundingBox();
  assert(beforeSave && afterFailure && afterFailure.y >= 0 && afterFailure.y < 1000 && Math.abs(afterFailure.y - beforeSave.y) < 160,'a failed row save keeps the active editor in view');
  assert.equal(await editing.getByLabel('需求标题',{ exact:true }).inputValue(),'额定直流电压');
  assert.equal(await editing.getByLabel('需求内容',{ exact:true }).inputValue(),'24 V DC，待核实接口适用条件','failed save retains the current row draft');
  assert(await editing.getByRole('checkbox',{ name:/企业产品规范.docx/ }).isChecked(),'failed save retains the source choices');
  assert.equal(await actual(0).innerText(),'--');
  if (process.env.SCREENSHOT_DIR) {
    await mkdir(process.env.SCREENSHOT_DIR,{ recursive:true });
    await page.screenshot({ path:path.join(process.env.SCREENSHOT_DIR,'requirement-inline-edit-desktop.png') });
  }
  await editing.getByRole('button',{ name:'保存', exact:true }).click();
  await editing.waitFor({ state:'hidden' });
  assert.equal(commands.length,2);
  assert.deepEqual(commands[0].data,commands[1].data,'retry sends the same complete requirement change');
  assert.deepEqual(commands[1].data,{ case_id:'case', id:'req-0', title:'额定直流电压', content:'24 V DC，待核实接口适用条件', source_ids:['tech','spec'] });
  assert.equal(items[0].revision,2);
  assert.equal(rc.input_revision,3);
  assert.equal(rc.source_analysis.status,'stale');
  assert.equal(rc.requirement_recommendations.status,'stale');
  await row(0).getByText('额定直流电压',{ exact:true }).waitFor();
  await row(0).getByText('24 V DC，待核实接口适用条件',{ exact:true }).waitFor();
  await row(0).getByText('查看原始指标',{ exact:true }).click();
  await row(0).locator('details .rd-req-original').filter({ hasText:/^24 V$/ }).waitFor();
  assert.equal(rc.source_analysis.requirements[0].content,'24 V','the immutable original remains available after revision');
  assert.equal(await actual(0).innerText(),'--','editing a requirement does not adopt a recommendation or clarification');

  await row(0).getByRole('button',{ name:'编辑需求', exact:true }).click();
  await editing.getByLabel('需求内容',{ exact:true }).waitFor();
  await page.setViewportSize({ width:390, height:844 });
  await editing.scrollIntoViewIfNeeded();
  assert.equal(await table.evaluate(element => element.scrollWidth <= element.clientWidth + 1),true,'table does not overflow on a narrow viewport');
  assert.equal(await editing.evaluate(element => element.scrollWidth <= element.clientWidth + 1),true,'row inputs and source controls fit a narrow viewport');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),true,'the page has no horizontal overflow');
  if (process.env.SCREENSHOT_DIR) await page.screenshot({ path:path.join(process.env.SCREENSHOT_DIR,'requirement-inline-edit-narrow.png') });
  await cancel();
  rc.stage='selection'; project.version++;
  await page.reload();
  await row(0).getByText('只读',{ exact:true }).waitFor();
  assert.equal(await table.getByRole('button',{ name:'编辑需求', exact:true }).count(),0);
  assert.equal(await table.getByLabel('需求标题',{ exact:true }).count(),0);
  assert.equal(await table.getByLabel('需求内容',{ exact:true }).count(),0);
  assert.equal(commands.length,2,'readonly and cancel paths send no additional commands');
  assert.deepEqual(faults,[]);
  if (process.env.SCREENSHOT_DIR) await writeFile(path.join(process.env.SCREENSHOT_DIR,'inline-edit-receipt.json'),JSON.stringify({
    passed:true, checks:['edit remains in the selected row','same-case process return preserves the row editor and draft','search keeps an unmatched active editor pinned','cancel without request','dirty edit locks competing actions','failed save preserves draft and sources','retry uses unchanged save_requirement contract','edit invalidates source/spec analysis without adopting an actual result','original snapshot remains visible','readonly stage','390px layout'], fixtureCommands:commands.length, pageErrors:faults, realApiRequests:0,
  },null,2));
  console.log('PASS: inline editing, cancel, failure and retry, source choices, original retention, actual result boundary, readonly, and narrow layout');
} finally { await browser.close(); }
