/** Browser review behavior; intercepted synthetic task never changes a user's task. */
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const paragraph = (id, text, level = 0) => ({ id, kind: 'paragraph', text, heading_level: level, editable: true, can_delete: true, images: [] });
const outputBlocks = [paragraph('heading', '1 技术要求', 1), paragraph('requirement', '插入损耗不大于 0.5 dB。'),
  { id: 'table', kind: 'table', rows: [{ cells: [{ id: 'cell', blocks: [paragraph('cell-text', '工作温度：-40 ℃～85 ℃。')] }] }] },
  paragraph('pending', '可靠性要求：待补充。'), paragraph('unknown', '该段来源尚未确认。'),
  ...Array.from({ length: 25 }, (_, index) => paragraph(`extra-${index}`, `试验要求 ${index + 1}：保留原文图表与技术数据，不改变文档引用关系。`))];
const projection = blocks => ({ document_id: 'synthetic-doc', sha256: 'synthetic-hash', format: 'docx', view_mode: 'content', blocks,
  outline: [{ id: 'heading', text: '1 技术要求', level: 1 }], sections: [{ id: 'heading', title: '技术要求', level: 1, block_ids: blocks.map(item => item.id) }], warnings: [] });
const source = projection([paragraph('source-heading', '需求原文', 1), paragraph('source-evidence', '插入损耗不大于 0.5 dB。'),
  { id: 'source-table', kind: 'table', rows: [{ cells: [{ id: 'source-cell', blocks: [paragraph('source-cell-text', '工作温度：-40 ℃～85 ℃。')] }] }] },
  ...Array.from({ length: 30 }, (_, index) => paragraph(`source-extra-${index}`, `来源条款 ${index + 1}：环境试验与产品要求。`))]);
let revisionIndex = 0;
const documents = { baseline: projection(structuredClone(outputBlocks)) };
const bundle = { jid: 'browser-review-fixture', title: '滤波连接器研制任务书 · 合成测试', selection: {},
  baseline_revision_id: 'baseline', current_revision_id: 'baseline', warnings: ['此任务为浏览器测试合成数据。'],
  assets: [{ id: 'tech', role: 'tech', label: '需求文件', name: '测试需求.docx', format: 'docx', available: true, url: '/synthetic-source.docx' },
    { id: 'template', role: 'template', label: '本次模板', name: '本次模板.doc', format: 'doc', available: true, url: '/synthetic-template.doc' },
    { id: 'spec', role: 'spec', label: '产品规范', name: '', format: 'docx', available: false, url: '' }],
  revisions: [{ id: 'baseline', parent_id: null, created_at: '2026-09-22T10:00:00+08:00', actor: '生成服务', reason: '原始生成件', sha256: 'baseline', annotations: [] }],
};
const errors = [];
let saves = 0; let checks = 0; let restores = 0; let conflictOnce = true;
let failInitial = true; let failSource = true; let legacyDocReads = 0;
function createRevision(parent, reason) {
  const id = `revision-${++revisionIndex}`;
  bundle.revisions.unshift({ id, parent_id: parent, created_at: `2026-09-22T10:0${revisionIndex}:00+08:00`, actor: '测试用户', reason, sha256: id, annotations: [] });
  bundle.current_revision_id = id; documents[id] = structuredClone(documents[parent]); return id;
}
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000); page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/review/**', async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    if (path === '/api/review/editor/status') return route.fulfill({ json: { configured: false, message: '未配置' } });
    if (path.endsWith('/document')) {
      if (url.searchParams.get('asset_id') === 'tech' && failSource) return route.fulfill({ status: 503, json: { detail: '来源文件读取暂时失败。' } });
      if (url.searchParams.get('asset_id') === 'template') legacyDocReads += 1;
      return route.fulfill({ json: url.searchParams.has('asset_id') ? source : documents[url.searchParams.get('revision_id')] });
    }
    if (path.endsWith('/links')) return route.fulfill({ json: { links: [
      { output_element_ids: ['requirement'], source_asset_id: 'tech', source_element_ids: ['source-evidence'], status: 'verified', label: '需求原文' },
      { output_element_ids: ['table'], source_asset_id: 'tech', source_element_ids: ['source-table'], status: 'verified', label: '需求指标表' },
      { output_element_ids: ['unknown'], source_asset_id: 'tech', source_element_ids: ['not-present'], status: 'candidate', label: '候选来源', reason: '原文定位不确定' },
    ], warnings: [] } });
    if (path.endsWith('/check')) {
      checks += 1; const id = path.split('/').at(-2); const result = { status: 'needs_review', checked_at: '2026-09-22T10:30:00+08:00', issues: [{ code: 'manual', message: '仍有待补充条款', severity: 'warning', element_id: 'pending' }], scope: 'revision_deterministic', delivery_approved: false };
      bundle.revisions.find(item => item.id === id).checks = result; return route.fulfill({ json: result });
    }
    if (path.endsWith('/annotations')) {
      const data = request.postDataJSON(); const revision = bundle.revisions.find(item => item.id === path.split('/').at(-2));
      revision.annotations = [data]; return route.fulfill({ json: { annotations: revision.annotations } });
    }
    if (path.endsWith('/restore')) {
      restores += 1; const id = path.split('/').at(-2); assert.equal(request.postDataJSON().expected_revision_id, bundle.current_revision_id);
      createRevision(id, '恢复历史内容'); return route.fulfill({ json: bundle });
    }
    if (path.endsWith('/revisions') && request.method() === 'POST') {
      saves += 1; const data = request.postDataJSON();
      if (conflictOnce) { conflictOnce = false; createRevision('baseline', '另一用户提交'); return route.fulfill({ status: 409, json: { detail: '当前修订已变化，请重新加载。' } }); }
      assert.equal(data.expected_revision_id, bundle.current_revision_id);
      const id = createRevision(bundle.current_revision_id, '正文修订');
      for (const operation of data.operations) {
        const visit = blocks => { for (let index = 0; index < blocks.length; index++) {
          const block = blocks[index];
          if (block.id === operation.element_id) {
            if (operation.op === 'replace_text') block.text = operation.text;
            if (operation.op === 'insert_paragraph') { blocks.splice(index + 1, 0, paragraph(`insert-${id}`, operation.text)); index += 1; }
            if (operation.op === 'delete_paragraph') { blocks.splice(index, 1); index -= 1; }
          } else if (block.kind === 'table') block.rows.forEach(row => row.cells.forEach(cell => visit(cell.blocks)));
        } }; visit(documents[id].blocks);
      }
      return route.fulfill({ json: bundle });
    }
    assert.equal(request.method(), 'GET');
    if (failInitial) return route.fulfill({ status: 503, json: { detail: '任务读取暂时失败。' } });
    return route.fulfill({ json: bundle });
  });
  await page.goto(`${base}/review/browser-review-fixture`);
  await page.getByRole('button', { name: '重新加载', exact: true }).waitFor(); failInitial = false;
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await page.getByRole('heading', { name: bundle.title, exact: true }).waitFor();
  await page.locator('#review-output-requirement').waitFor();
  await page.getByRole('button', { name: '重试读取来源', exact: true }).waitFor(); failSource = false;
  await page.getByRole('button', { name: '重试读取来源', exact: true }).click();
  await page.locator('#review-source-source-evidence').waitFor();
  assert.equal(await page.locator('.review-machine-status').textContent(), '机器检查：未检查', 'missing QA must not look approved');
  assert.equal(await page.getByRole('tab', { name: '版式编辑', exact: true }).count(), 0);
  await page.locator('#review-output-requirement').click();
  await page.locator('#review-source-source-evidence.is-linked').waitFor();
  assert.equal(await page.locator('#review-output-requirement.is-linked').count(), 1);
  await page.locator('#review-source-source-evidence').click();
  assert.equal(await page.locator('#review-output-requirement.is-selected').count(), 1);
  await page.locator('#review-output-cell-text').click();
  await page.locator('#review-source-source-table.is-linked').waitFor();
  await page.locator('#review-source-source-cell-text').click();
  assert.equal(await page.locator('#review-output-table.is-linked').count(), 1, 'table evidence resolves from cell paragraphs in both directions');
  await page.locator('#review-output-unknown').click();
  assert.equal(await page.locator('.review-paragraph.is-linked').count(), 0, 'candidate mapping must not be highlighted');
  await page.getByRole('tab', { name: '产品规范', exact: true }).click();
  await page.getByRole('heading', { name: '本次任务未留存该来源' }).waitFor();
  await page.getByRole('tab', { name: '本次模板', exact: true }).click();
  await page.locator('.review-source-panel .review-document').waitFor();
  assert.ok(legacyDocReads > 0, 'DOC source invokes server normalization instead of hiding content');
  await page.getByRole('tab', { name: '需求文件', exact: true }).click();
  await page.locator('#review-output-requirement').click();
  await page.getByLabel('核对备注', { exact: true }).fill('已与需求文件逐字核对。');
  await page.getByRole('button', { name: '标为已核对', exact: true }).click();
  await page.getByText('人工核对：已核对 1 处', { exact: true }).waitFor();
  assert.equal(await page.locator('.review-machine-status').textContent(), '机器检查：未检查');
  await page.getByRole('button', { name: '重新检查', exact: true }).click();
  await page.locator('.review-machine-status').filter({ hasText: '需人工核对' }).waitFor();
  assert.equal(checks, 1);
  await page.getByRole('tab', { name: '编辑正文', exact: true }).click();
  await page.getByLabel('编辑正文 requirement', { exact: true }).fill('插入损耗不大于 0.4 dB。');
  await page.getByRole('button', { name: '保存修订', exact: true }).click();
  await page.getByRole('button', { name: '加载最新版本', exact: true }).waitFor();
  assert.equal(await page.getByLabel('编辑正文 requirement', { exact: true }).inputValue(), '插入损耗不大于 0.4 dB。');
  await page.getByRole('button', { name: '加载最新版本', exact: true }).click();
  const confirm = page.getByRole('dialog', { name: '有未保存的修改' });
  await confirm.waitFor();
  const confirmBounds = await confirm.boundingBox();
  assert.ok(confirmBounds);
  await page.mouse.click(confirmBounds.x + 8, confirmBounds.y + 8);
  assert.equal(await confirm.isVisible(), true, 'blank padding inside a confirmation is not its backdrop');
  await page.mouse.click(confirmBounds.x - 12, confirmBounds.y + confirmBounds.height / 2);
  await confirm.waitFor({ state: 'hidden' });
  assert.equal(await page.getByLabel('编辑正文 requirement', { exact: true }).inputValue(), '插入损耗不大于 0.4 dB。', 'backdrop cancellation retains the unsaved review draft');
  await page.getByRole('button', { name: '加载最新版本', exact: true }).click();
  await confirm.getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(await page.getByLabel('编辑正文 requirement', { exact: true }).inputValue(), '插入损耗不大于 0.4 dB。');
  await page.getByRole('button', { name: '加载最新版本', exact: true }).click();
  await confirm.getByRole('button', { name: '放弃修改并继续', exact: true }).click();
  await page.locator('#review-output-requirement').waitFor();
  await page.getByRole('tab', { name: '编辑正文', exact: true }).click();
  await page.getByLabel('编辑正文 requirement', { exact: true }).fill('插入损耗不大于 0.4 dB。');
  await page.getByLabel('编辑正文 cell-text', { exact: true }).fill('工作温度：-55 ℃～85 ℃。');
  await page.locator('#review-output-unknown').getByRole('button', { name: '在下方加段落', exact: true }).click();
  await page.getByLabel('新增段落 unknown', { exact: true }).fill('新增经人工确认的补充条款。');
  assert.equal(await page.locator('#review-output-unknown').getByRole('button', { name: '在下方加段落', exact: true }).isDisabled(), true);
  await page.getByLabel('编辑正文 unknown', { exact: true }).fill('修改后的待核对条款。');
  await page.locator('#review-output-unknown').getByRole('button', { name: '删除此段', exact: true }).click();
  assert.equal(await page.getByLabel('新增段落 unknown', { exact: true }).count(), 0);
  await page.locator('#review-output-unknown').getByRole('button', { name: '撤销删除', exact: true }).click();
  assert.equal(await page.getByLabel('编辑正文 unknown', { exact: true }).inputValue(), '修改后的待核对条款。');
  assert.equal(await page.getByLabel('新增段落 unknown', { exact: true }).inputValue(), '新增经人工确认的补充条款。');
  await page.getByLabel('编辑正文 extra-0', { exact: true }).fill('删除段落的草稿不应提交。');
  await page.locator('#review-output-extra-0').getByRole('button', { name: '删除此段', exact: true }).click();
  await page.getByRole('button', { name: '撤销', exact: true }).click();
  assert.equal(await page.locator('#review-output-extra-0.is-deleted').count(), 0);
  assert.equal(await page.getByLabel('编辑正文 extra-0', { exact: true }).inputValue(), '删除段落的草稿不应提交。');
  await page.locator('#review-output-extra-0').getByRole('button', { name: '删除此段', exact: true }).click();
  await page.getByRole('button', { name: '保存修订', exact: true }).click();
  await page.getByRole('status').filter({ hasText: '已保存为新修订' }).waitFor();
  await page.getByLabel('编辑正文 requirement', { exact: true }).waitFor();
  assert.equal(await page.getByLabel('编辑正文 requirement', { exact: true }).inputValue(), '插入损耗不大于 0.4 dB。');
  assert.equal(await page.getByLabel('编辑正文 cell-text', { exact: true }).inputValue(), '工作温度：-55 ℃～85 ℃。');
  assert.equal(await page.locator('#review-output-extra-0').count(), 0);
  assert.equal(await page.locator('.review-machine-status').textContent(), '机器检查：未检查', 'new revision invalidates previous machine check');
  assert.equal(await page.getByRole('link', { name: '下载当前版本', exact: true }).getAttribute('href'), '/api/review/browser-review-fixture/revisions/revision-2/download');
  await page.getByRole('tab', { name: '修订历史', exact: true }).click();
  await page.locator('.review-history li').filter({ hasText: '生成原稿' }).getByRole('button', { name: '恢复此版本', exact: true }).click();
  await page.getByRole('dialog', { name: '恢复历史版本', exact: true }).getByRole('button', { name: '确认恢复', exact: true }).click();
  await page.locator('#review-output-requirement').waitFor();
  assert.equal(await page.locator('#review-output-requirement').innerText(), '插入损耗不大于 0.5 dB。');
  assert.equal(restores, 1); assert.equal(bundle.revisions.length, 4);
  const separator = page.getByRole('separator', { name: '调整左右文档宽度' });
  await separator.focus(); await page.keyboard.press('ArrowRight'); assert.equal(await separator.getAttribute('aria-valuenow'), '48');
  const sourceScroll = page.locator('.review-source-panel .review-document-scroll');
  const outputScroll = page.locator('.review-output-panel .review-document-scroll');
  await sourceScroll.evaluate(element => { element.scrollTop = 300; });
  assert.equal(await outputScroll.evaluate(element => element.scrollTop), 0, 'two documents scroll independently');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.locator('body').evaluate(element => element.scrollWidth > innerWidth), false);
  await page.getByRole('button', { name: '来源', exact: true }).click();
  assert.equal(await page.locator('.review-source-panel').isVisible(), true);
  assert.equal(await page.locator('.review-output-panel').isVisible(), false);
  await page.getByRole('button', { name: '目录', exact: true }).click();
  assert.equal(await page.locator('.review-outline').isVisible(), true);
  await page.getByRole('button', { name: '1 技术要求', exact: true }).click();
  assert.equal(await page.locator('.review-output-panel').isVisible(), true);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ passed: true, independentQAAndHumanReview: true, verifiedOnlyBidirectionalLinks: true,
    missingSource: true, loadAndSourceRetry: true, legacyDocNormalization: true, tableEvidenceNavigation: true, editParagraphAndTableCell: true, insertDeleteUndo: true, conflictPreservesDraft: true,
    confirmationBackdropPreservesDraft: true, versionRestorePreservesHistory: true, revisionDownload: true, independentScrolling: true, keyboardResize: true, narrowScreenSwitching: true, saves, checks, restores }));
} finally { await browser.close(); }
