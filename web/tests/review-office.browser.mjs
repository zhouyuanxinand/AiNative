/** Synthetic ONLYOFFICE bridge verifies save acknowledgement and session lifetime. */
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
const bundle = { jid: 'office-browser-fixture', title: '版式编辑保存测试', selection: {}, baseline_revision_id: 'baseline', current_revision_id: 'baseline', assets: [], warnings: [],
  revisions: [{ id: 'baseline', created_at: '2026-09-22T10:00:00+08:00', sha256: 'baseline', annotations: [] }] };
const projection = { document_id: 'synthetic', sha256: 'synthetic', format: 'docx', view_mode: 'content', blocks: [{ id: 'p', kind: 'paragraph', text: '测试正文', heading_level: 1, editable: true, can_delete: true, images: [] }], outline: [{ id: 'p', text: '测试正文', level: 1 }], sections: [], warnings: [] };
let sessionState = { status: 'opened', revision_id: 'baseline' };
let saves = 0; let opens = 0; let polls = 0;
const errors = [];
const saveRevision = (id, request) => {
  bundle.revisions.push({ id, created_at: '2026-09-22T10:10:00+08:00', sha256: id, annotations: [] }); bundle.current_revision_id = id;
  sessionState = { status: 'saved', revision_id: id, saved_at: Date.now() / 1000, saved_request_id: request };
};
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }); page.setDefaultTimeout(12000);
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    window.__officeTest = { created: 0, destroyed: 0, events: null };
    window.DocsAPI = { DocEditor: class {
      constructor(id, config) {
        window.__officeTest.created += 1; window.__officeTest.events = config.events;
        const host = document.getElementById(id); host.innerHTML = '<textarea aria-label="合成版式正文">测试正文</textarea>';
        setTimeout(() => config.events.onDocumentReady(), 10);
      }
      destroyEditor() { window.__officeTest.destroyed += 1; }
    } };
  });
  await page.route('**/api/review/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/editor/status')) return route.fulfill({ json: { configured: true, script_url: '/synthetic-office.js', message: '已配置' } });
    if (path.endsWith('/editor') && route.request().method() === 'POST') { opens += 1; return route.fulfill({ json: { session_id: 'test-session', script_url: '/synthetic-office.js', config: {} } }); }
    if (path.endsWith('/editor/test-session/save')) { saves += 1; return route.fulfill({ json: { status: 'pending', save_request_id: `save-${saves}`, message: '正在等待文档服务回传。' } }); }
    if (path.endsWith('/editor/test-session')) { polls += 1; return route.fulfill({ json: sessionState }); }
    if (path.endsWith('/document')) return route.fulfill({ json: projection });
    if (path.endsWith('/links')) return route.fulfill({ json: { links: [], warnings: [] } });
    return route.fulfill({ json: bundle });
  });
  await page.goto(`${base}/review/office-browser-fixture`);
  await page.locator('#review-output-p').waitFor();
  await page.getByRole('tab', { name: '版式编辑', exact: true }).click();
  const save = page.getByRole('button', { name: '保存版式修改', exact: true }); await save.waitFor();
  await page.getByText('可在文档中修改版式，保存后等待服务端确认。', { exact: true }).waitFor();
  await page.evaluate(() => window.__officeTest.events.onDocumentStateChange({ data: true }));
  assert.equal(await save.isDisabled(), true, 'must wait until edits have synced to document service');
  await page.evaluate(() => window.__officeTest.events.onDocumentStateChange({ data: false }));
  assert.equal(await save.isDisabled(), false);
  await page.getByRole('tab', { name: '对照审阅', exact: true }).click();
  await page.getByRole('dialog', { name: '有未保存的修改' }).getByRole('button', { name: '继续编辑', exact: true }).click();
  await page.locator('.review-outline').getByRole('button', { name: '测试正文', exact: true }).click();
  await page.getByRole('dialog', { name: '有未保存的修改' }).getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(await page.evaluate(() => window.__officeTest.destroyed), 0, 'chapter navigation must preserve unsaved office session');
  saveRevision('unsolicited-version', 'different-request');
  await page.waitForFunction(() => document.querySelector('#review-revision').value === 'unsolicited-version');
  assert.equal(await page.locator('.review-save-state').textContent(), '有修改未保存', 'automatic callbacks must not clear platform dirty state');
  assert.equal(await page.evaluate(() => window.__officeTest.created), 1, 'callback must not destroy and recreate editor');
  await save.click();
  await page.locator('.review-office-saving').waitFor();
  assert.equal(await page.locator('.review-office-surface').evaluate(element => element.inert), true, 'editor must freeze while explicit save is in flight');
  await page.locator('.review-outline').getByRole('button', { name: '测试正文', exact: true }).click();
  assert.equal(await page.evaluate(() => window.__officeTest.destroyed), 0, 'chapter navigation must not unmount pending save');
  assert.equal(await page.locator('.review-office-saving').isVisible(), true);
  const oldPolls = polls;
  await page.waitForResponse(response => response.url().endsWith('/editor/test-session') && response.status() === 200);
  assert.ok(polls > oldPolls);
  assert.equal(await page.locator('.review-office-saving').isVisible(), true, 'an unrelated saved callback is not this save acknowledgement');
  await page.evaluate(() => window.__officeTest.events.onDocumentStateChange({ data: true }));
  saveRevision('first-explicit-version', 'save-1');
  await page.locator('.review-office-saving').waitFor({ state: 'detached' });
  assert.equal(await page.locator('.review-save-state').textContent(), '有修改未保存', 'a later edit event remains dirty after older save acknowledgement');
  assert.equal(await page.evaluate(() => window.__officeTest.created), 1);
  await page.evaluate(() => window.__officeTest.events.onDocumentStateChange({ data: false }));
  await save.click();
  await page.locator('.review-office-saving').waitFor();
  saveRevision('second-explicit-version', 'save-2');
  await page.locator('.review-office-saving').waitFor({ state: 'detached' });
  await page.getByText('所有修改已保存', { exact: true }).waitFor();
  assert.equal(await page.evaluate(() => window.__officeTest.created), 1);
  assert.equal(await page.evaluate(() => window.__officeTest.destroyed), 0);
  assert.equal(opens, 1); assert.equal(saves, 2);
  await page.getByRole('tab', { name: '对照审阅', exact: true }).click();
  await page.locator('#review-output-p').waitFor();
  assert.equal(await page.evaluate(() => window.__officeTest.destroyed), 1);
  assert.equal(await page.getByRole('dialog').count(), 0);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ passed: true, waitForDocumentReadyAndSync: true, persistentEditorSession: true,
    explicitSaveFreezesEditor: true, requestTokenAcknowledgement: true, lateEditsRemainDirty: true, leaveGuard: true, opens, saves }));
} finally { await browser.close(); }
