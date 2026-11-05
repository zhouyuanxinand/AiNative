/** Same-origin fixtures only: no deployed identities, uploads, or external links are used. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const playwrightModule = process.env.PLAYWRIGHT_MODULE;
const { chromium } = await import(playwrightModule && /^[A-Z]:[\\/]/i.test(playwrightModule) ? pathToFileURL(playwrightModule).href : playwrightModule || 'playwright');
const browser = await chromium.launch({ headless: true, ignoreDefaultArgs: ['--hide-scrollbars'], executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5193';
const shotDir = process.env.SCREENSHOT_DIR;
if (shotDir) await mkdir(shotDir, { recursive: true });
const requests = [], errors = [], unexpected = [];
const member = { authenticated: true, user: { username: 'resource-editor', display_name: '资料管理员', userid: 'fixture-resource-editor' }, can_manage_admins: false };
const stamp = '2026-10-22T02:20:00Z';
const fileItem = (id, kind, title, filename, previewType) => ({ id, kind, title, source_type: 'file', source_url: null, filename,
  size_bytes: 2097152, media_type: previewType === 'video' ? 'video/webm' : previewType === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  created_at: stamp, updated_at: stamp, created_by: 'resource-editor', content_url: `/api/help-resources/${id}/content`,
  preview_type: previewType, preview_url: `/api/help-resources/${id}/${previewType === 'document' ? 'document' : 'content'}` });
const linkItem = (id, kind, title, sourceUrl) => ({ id, kind, title, source_type: 'link', source_url: sourceUrl, filename: null,
  size_bytes: null, media_type: null, created_at: stamp, updated_at: stamp, created_by: 'resource-editor', content_url: null,
  preview_type: 'link', preview_url: null });
const video = fileItem('video-fixture', 'video', '研制任务书生成操作演示', `研制任务书生成完整流程_${'归档文件名'.repeat(9)}.webm`, 'video');
const word = fileItem('word-fixture', 'manual', '平台使用手册（含操作步骤与图表）', '平台操作手册.docx', 'document');
const pdf = fileItem('pdf-fixture', 'manual', '操作速查表 PDF', '操作速查表.pdf', 'pdf');
const external = linkItem('link-fixture', 'manual', '培训资料与常见问题', `https://training.example.test/manual/${'long-reference-'.repeat(12)}?version=2026`);
let items = [video, word, pdf, external], sequence = 0;
let listMode = 'ready', uploadMode = 'ready', linkMode = 'ready', deleteMode = 'ready', documentMode = 'ready';
let listGate = null, uploadGate = null;
const paragraph = (id, text, heading_level = 0, images = []) => ({ id, kind: 'paragraph', text, heading_level, editable: false, can_delete: false, images });
const diagram = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="110" viewBox="0 0 640 110"><rect width="640" height="110" fill="#f5f5f7"/><g fill="#fff" stroke="#0071e3"><rect x="20" y="30" width="160" height="50" rx="8"/><rect x="240" y="30" width="160" height="50" rx="8"/><rect x="460" y="30" width="160" height="50" rx="8"/></g><g fill="#1d1d1f" font-size="16" text-anchor="middle" font-family="sans-serif"><text x="100" y="60">Upload</text><text x="320" y="60">Review</text><text x="540" y="60">Generate</text></g><path d="M190 55h38m-8-6 8 6-8 6M410 55h38m-8-6 8 6-8 6" fill="none" stroke="#0071e3" stroke-width="2"/></svg>`;
const projection = { document_id: 'help-manual-fixture', sha256: 'fixture-sha256', format: 'docx', view_mode: 'content', warnings: [], outline: [], sections: [], blocks: [
  paragraph('guide-heading', '生成任务书的三个步骤', 1),
  paragraph('guide-intro', '选择产品并上传需求文件，核对预检结果后生成任务书。'),
  { id: 'steps-table', kind: 'table', rows: [
    { cells: ['操作', '所需材料', '检查内容', '完成标志'].map((text, index) => ({ id: `head-${index}`, blocks: [paragraph(`head-p-${index}`, text)] })) },
    { cells: ['上传文件', '需求文件与产品规范', '文件格式与产品类型', '预检通过'].map((text, index) => ({ id: `value-${index}`, blocks: [paragraph(`value-p-${index}`, text)] })) },
  ] },
  paragraph('guide-diagram', '', 0, [{ id: 'steps-image', mime: 'image/svg+xml', available: true, alt: '操作步骤示意图', src: `data:image/svg+xml;base64,${Buffer.from(diagram).toString('base64')}` }]),
  ...Array.from({ length: 40 }, (_, index) => paragraph(`guide-detail-${index}`, `操作说明 ${index + 1}：核对需求文件、产品规范和生成结果中的表格及图片，确认后保存复核记录。`)),
  paragraph('guide-end', '操作手册结束：全部操作说明已展示。'),
] };

function pdfBytes() {
  const stream = 'BT /F1 20 Tf 40 760 Td (Taskbook Quick Guide) Tj 0 -36 Td /F1 12 Tf (1. Upload documents) Tj 0 -24 Td (2. Review requirements) Tj 0 -24 Td (3. Generate taskbook) Tj ET';
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`];
  let result = '%PDF-1.4\n'; const offsets = [0];
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(result)); result += `${index + 1} 0 obj\n${object}\nendobj\n`; });
  const start = Buffer.byteLength(result);
  result += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`;
  return Buffer.from(result);
}

async function choose(page, id, label) {
  await page.locator(`#${id}`).focus();
  await page.locator(`#${id}`).press('ArrowDown');
  await page.getByRole('listbox').getByRole('option', { name: label, exact: true }).click();
}
async function assertNoPageOverflow(page, label) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `${label}: root width fits viewport`);
  if (await page.locator('.help-page').count()) assert.equal(await page.locator('.help-page').evaluate(element => element.scrollWidth > element.clientWidth + 1), false, `${label}: help scroller has no horizontal overflow`);
}
async function shot(page, filename) {
  if (shotDir) await page.screenshot({ path: join(shotDir, filename), fullPage: true, animations: 'disabled' });
}

try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, timezoneId: 'America/New_York', reducedMotion: 'reduce' });
  context.on('page', page => { page.setDefaultTimeout(10000); page.on('pageerror', error => errors.push(error.message)); });
  const mediaPage = await context.newPage();
  const videoBytes = Buffer.from(await mediaPage.evaluate(async () => {
    const canvas = document.createElement('canvas'); canvas.width = 480; canvas.height = 270; document.body.appendChild(canvas);
    const paint = canvas.getContext('2d'); paint.fillStyle = '#f5f5f7'; paint.fillRect(0, 0, 480, 270);
    paint.fillStyle = '#0071e3'; paint.fillRect(32, 32, 416, 60); paint.fillStyle = '#1d1d1f'; paint.font = '24px sans-serif';
    paint.fillText('Taskbook operation demo', 40, 150);
    const stream = canvas.captureStream(0), track = stream.getVideoTracks()[0], recorder = new MediaRecorder(stream, { mimeType: 'video/webm' }), chunks = [];
    recorder.ondataavailable = event => chunks.push(event.data);
    const finished = new Promise(resolve => { recorder.onstop = resolve; });
    const started = new Promise(resolve => { recorder.onstart = resolve; }); recorder.start(); await started;
    for (let frame = 0; frame < 4; frame++) {
      paint.fillStyle = '#0071e3'; paint.fillRect(40 + frame * 40, 200, 32, 8);
      track.requestFrame();
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    recorder.stop(); await finished;
    stream.getTracks().forEach(track => track.stop());
    return Array.from(new Uint8Array(await new Blob(chunks, { type: 'video/webm' }).arrayBuffer()));
  }));
  assert.ok(videoBytes.length > 200, 'recorded media fixture contains video frames');
  await mediaPage.close();
  const pdfBody = pdfBytes();

  await context.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    if (!path.startsWith('/api/') && !path.startsWith('/admin/api/')) return route.continue();
    requests.push({ path, method: request.method(), headers: request.headers() });
    if (path === '/api/admin/session') return route.fulfill({ json: member });
    if (path === '/api/admin/members') return route.fulfill({ json: { items: [{ username: 'wangxue', created_at: stamp, created_by: 'system', is_owner: true }], can_manage_admins: false } });
    if (path === '/api/feedback-admin') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20,
      stats: { total: 0, good: 0, average: 0, poor: 0, good_rate: 0, open: 0, in_progress: 0, resolved: 0 } } });
    if (path === '/api/logs/requests') return route.fulfill({ json: { items: [], retention: 50, stats: { total: 0, running: 0, success: 0, failed: 0 } } });
    if (path === '/api/help-resources' || path === '/admin/api/help-resources') {
      if (listGate) await listGate;
      if (listMode === 'error') return route.fulfill({ status: 503, json: { error: '资料列表暂时不可用，请重试。' } });
      return route.fulfill({ json: { items: listMode === 'empty' ? [] : items.filter(item => item.kind === url.searchParams.get('kind')) } });
    }
    if (path === '/api/help-resources-admin/upload') {
      assert.equal(request.headers()['x-admin-action'], '1');
      const form = await new Request(request.url(), { method: 'POST', headers: request.headers(), body: request.postDataBuffer() }).formData();
      const file = form.get('file'); assert.ok(file && file.size > 0, 'multipart transports the original file');
      assert.equal(request.method(), 'POST');
      if (uploadGate) await uploadGate;
      if (uploadMode === 'error') return route.fulfill({ status: 503, json: { error: '上传保存失败，请重试。' } });
      const kind = form.get('kind'), previewType = kind === 'video' ? 'video' : file.name.endsWith('.pdf') ? 'pdf' : 'document';
      const item = { ...fileItem(`uploaded-${++sequence}`, kind, form.get('title'), file.name, previewType), size_bytes: file.size };
      items.unshift(item); return route.fulfill({ status: 201, json: { item } });
    }
    if (path === '/api/help-resources-admin/links') {
      assert.equal(request.headers()['x-admin-action'], '1'); assert.equal(request.method(), 'POST');
      if (linkMode === 'error') return route.fulfill({ status: 503, json: { error: '链接保存失败，请重试。' } });
      const body = request.postDataJSON(), item = linkItem(`created-link-${++sequence}`, body.kind, body.title, body.source_url);
      items.unshift(item); return route.fulfill({ status: 201, json: { item } });
    }
    if (path.startsWith('/api/help-resources-admin/')) {
      assert.equal(request.headers()['x-admin-action'], '1'); assert.equal(request.method(), 'DELETE');
      if (deleteMode === 'error') return route.fulfill({ status: 503, json: { error: '资料删除失败，请重试。' } });
      items = items.filter(item => item.id !== decodeURIComponent(path.split('/').at(-1)));
      return route.fulfill({ json: { ok: true } });
    }
    if (path.startsWith('/api/help-resources/') && path.endsWith('/document')) {
      if (documentMode === 'error') return route.fulfill({ status: 503, json: { error: '手册内容读取失败，请重试。' } });
      return route.fulfill({ json: projection });
    }
    if (path.startsWith('/api/help-resources/') && path.endsWith('/content')) {
      const item = items.find(entry => entry.id === path.split('/').at(-2));
      return route.fulfill({ contentType: item?.preview_type === 'video' ? 'video/webm' : 'application/pdf', body: item?.preview_type === 'video' ? videoBytes : pdfBody });
    }
    if (path === '/api/rd/session') return route.fulfill({ json: { authenticated: true } });
    if (path === '/api/rd/projects') return route.fulfill({ json: { projects: [] } });
    if (path === '/api/rd/catalog') return route.fulfill({ json: { stages: [], scenarios: [{ id: 'taskbook', title: '研制任务书生成', status: 'published' }], actions: [], workpackage_definitions: [] } });
    if (path === '/api/current-user') return route.fulfill({ json: { auth_enabled: true, authenticated: true, user: { userid: 'fixture-engineer', display_name: '测试工程师', name: '测试工程师', source: 'smartvision', verified: true } } });
    if (path === '/api/product_catalog') return route.fulfill({ json: { product_types: [{ value: 'rf_connector', label: '射频连接器', enabled: true,
      configured_enabled: true, integration_status: 'available', template_label: '射频连接器研制任务书', domains: [{ value: 'military', label: '军品' }] }] } });
    if (path === '/api/models') return route.fulfill({ json: { success: true, models: [{ model: '工程测试模型', id: 'fixture-model', provider: 'smartvision', vendor: '测试网关', configured: true }] } });
    if (path === '/api/llm/status') return route.fulfill({ json: { configured: true, provider: 'smartvision', model: '工程测试模型' } });
    if (path === '/api/history' || path === '/api/local_defaults') return route.fulfill({ json: [] });
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok', ready_for_generation: true } });
    unexpected.push(`${request.method()} ${path}`); return route.fulfill({ status: 404, json: { error: 'Unexpected fixture API' } });
  });

  // Chrome 104 ignores dynamic viewport units. Keep all other production CSS
  // and exercise actual wheel/keyboard scrolling, not programmatic positioning.
  for (const legacy of [true, false]) {
    const reader = await context.newPage();
    let removedViewportDeclarations = 0;
    if (legacy) await reader.route(/\/(?:assets\/[^/]+|helpResources)\.css(?:\?.*)?$/, async route => {
      const response = await route.fetch();
      const body = (await response.text()).replace(/(\.help-page\s*\{[^}]*?)height:\s*100dvh\s*;/g, (_match, prefix) => {
        removedViewportDeclarations++;
        return prefix;
      });
      await route.fulfill({ response, body });
    });
    for (const viewport of [{ width: 1366, height: 768 }, { width: 390, height: 844 }]) {
      const label = `manual-${legacy ? 'legacy' : 'modern'}-${viewport.width}`;
      await reader.setViewportSize(viewport);
      await reader.goto(`${base}/help/manual`);
      await reader.getByText('操作手册结束：全部操作说明已展示。', { exact: true }).waitFor({ state: 'attached' }).catch(async error => {
        console.error('Manual load diagnostics:', await reader.locator('body').innerText(), errors, unexpected);
        throw error;
      });
      if (legacy) assert.ok(removedViewportDeclarations > 0, `${label}: production help viewport declaration was removed`);
      const dimensions = await reader.locator('.help-page').evaluate(element => ({
        height: element.clientHeight, content: element.scrollHeight, viewport: innerHeight,
      }));
      assert.ok(dimensions.height <= dimensions.viewport && dimensions.content > dimensions.height,
        `${label}: long manual has a viewport-bounded scroller: ${JSON.stringify(dimensions)}`);
      await reader.mouse.move(viewport.width / 2, viewport.height / 2);
      await reader.mouse.wheel(0, 600);
      await reader.waitForFunction(() => document.querySelector('.help-page').scrollTop > 100);
      await reader.getByRole('link', { name: '返回平台', exact: true }).focus();
      await reader.keyboard.press('Control+End');
      await reader.waitForFunction(() => {
        const element = document.querySelector('.help-page');
        return element.scrollHeight - element.clientHeight - element.scrollTop < 2;
      });
      const end = await reader.getByText('操作手册结束：全部操作说明已展示。', { exact: true }).boundingBox();
      assert.ok(end.y >= 0 && end.y + end.height <= viewport.height, `${label}: final paragraph is reachable`);
      await assertNoPageOverflow(reader, label);
      await shot(reader, `${label}-bottom.png`);
      await reader.keyboard.press('Control+Home');
      await reader.waitForFunction(() => document.querySelector('.help-page').scrollTop === 0);
      if (viewport.width > 1000) {
        // The native scrollbar must also be reachable with the pointer.
        await reader.mouse.move(viewport.width - 8, 30);
        await reader.mouse.down();
        await reader.mouse.move(viewport.width - 8, viewport.height - 30, { steps: 8 });
        await reader.mouse.up();
        await reader.waitForFunction(() => document.querySelector('.help-page').scrollTop > 100);
        await reader.getByRole('link', { name: '返回平台', exact: true }).focus();
        await reader.keyboard.press('Control+Home');
      }
      await reader.getByRole('navigation', { name: '使用帮助', exact: true }).getByRole('link', { name: '操作视频', exact: true }).click();
      await reader.locator('video').waitFor();
      await assertNoPageOverflow(reader, `${label}: video sibling`);
    }
    await reader.close();
  }
  console.log('Long manual scroll passed: legacy viewport fallback, wheel, keyboard, final paragraph and video navigation.');

  const admin = await context.newPage();
  await admin.goto(`${base}/admin`);
  await admin.getByRole('heading', { name: '问题反馈管理', exact: true }).waitFor();
  const navigation = admin.getByRole('navigation', { name: '管理员导航', exact: true });
  let releaseList;
  listGate = new Promise(resolve => { releaseList = resolve; });
  await navigation.getByRole('link', { name: '操作资料上传', exact: true }).focus(); await admin.keyboard.press('Enter');
  await admin.getByText('正在读取资料列表…', { exact: true }).waitFor(); releaseList(); listGate = null;
  const resourceList = admin.locator('.admin-help-resource-list');
  await resourceList.getByRole('heading', { name: word.title, exact: true }).waitFor();
  assert.equal(new URL(admin.url()).searchParams.get('view'), 'resources');
  assert.equal(await navigation.getByRole('link', { name: '操作资料上传', exact: true }).getAttribute('aria-current'), 'page');
  assert.equal(await admin.getByRole('button', { name: '统一登录设置', exact: true }).count(), 0, 'ordinary member has no owner-only setting');
  assert.equal(await admin.getByRole('button', { name: '上传资料', exact: true }).isEnabled(), true, 'ordinary administrators can maintain resources');
  assert.match(await resourceList.innerText(), /10:20:00/, 'timestamps stay in Beijing time');
  assert.equal(new URL(await resourceList.getByRole('link', { name: `下载原文件：${word.title}`, exact: true }).getAttribute('href')).searchParams.get('download'), '1');

  await admin.getByRole('button', { name: '上传资料', exact: true }).click();
  await admin.getByRole('alert').filter({ hasText: '请填写资料标题' }).waitFor();
  assert.equal(requests.filter(request => request.method === 'POST').length, 0);
  const uploadedTitle = '完整生成流程培训视频';
  await admin.locator('#help-resource-title').fill(uploadedTitle);
  await admin.locator('#help-resource-file').setInputFiles({ name: 'unsupported.txt', mimeType: 'text/plain', buffer: Buffer.from('fixture') });
  await admin.getByRole('button', { name: '上传资料', exact: true }).click();
  await admin.getByRole('alert').filter({ hasText: '文件格式不支持' }).waitFor();
  assert.equal(requests.filter(request => request.method === 'POST').length, 0, 'unsupported file is rejected before upload');
  await admin.locator('#help-resource-file').setInputFiles({ name: '完整培训视频.webm', mimeType: 'video/webm', buffer: videoBytes });
  await navigation.getByRole('link', { name: '管理员名单', exact: true }).click();
  await admin.getByText('当前名单只读。仅 wangxue 可以添加或移除管理员。', { exact: true }).waitFor();
  await navigation.getByRole('link', { name: '操作资料上传', exact: true }).click();
  assert.equal(await admin.locator('#help-resource-title').inputValue(), uploadedTitle);
  assert.equal(await admin.locator('#help-resource-file').evaluate(input => input.files[0].name), '完整培训视频.webm', 'navigation retains the selected file');
  uploadMode = 'error'; let releaseUpload;
  uploadGate = new Promise(resolve => { releaseUpload = resolve; });
  await admin.getByRole('button', { name: '上传资料', exact: true }).click();
  await admin.getByRole('progressbar').waitFor();
  assert.equal(await admin.locator('#help-resource-title').isDisabled(), true);
  assert.equal(await admin.getByRole('button', { name: '正在上传…', exact: true }).isDisabled(), true);
  releaseUpload(); uploadGate = null;
  await admin.getByRole('alert').filter({ hasText: '上传保存失败' }).waitFor();
  assert.equal(await admin.locator('#help-resource-title').inputValue(), uploadedTitle);
  assert.equal(await admin.locator('#help-resource-file').evaluate(input => input.files.length), 1, 'failed upload retains original file');
  uploadMode = 'ready'; await admin.getByRole('button', { name: '上传资料', exact: true }).click();
  await resourceList.getByRole('heading', { name: uploadedTitle, exact: true }).waitFor();
  assert.equal(await admin.locator('#help-resource-title').inputValue(), '');
  assert.equal(await admin.locator('#help-resource-file').evaluate(input => input.files.length), 0);
  await choose(admin, 'help-resource-kind', '操作手册');
  await admin.locator('#help-resource-title').fill('纸面操作速查说明');
  await admin.locator('#help-resource-file').setInputFiles({ name: '纸面操作速查说明.pdf', mimeType: 'application/pdf', buffer: pdfBody });
  await admin.getByRole('button', { name: '上传资料', exact: true }).click();
  await resourceList.getByRole('heading', { name: '纸面操作速查说明', exact: true }).waitFor();

  await choose(admin, 'help-resource-source', '添加链接');
  const addedTitle = '团队培训补充链接', addedUrl = 'https://training.example.test/extra-guide';
  await admin.locator('#help-resource-title').fill(addedTitle); await admin.locator('#help-resource-url').fill('javascript:alert(1)');
  const postsBeforeInvalidUrl = requests.filter(request => request.path.endsWith('/links')).length;
  await admin.getByRole('button', { name: '保存链接', exact: true }).click();
  await admin.getByRole('alert').filter({ hasText: 'HTTP 或 HTTPS' }).waitFor();
  assert.equal(requests.filter(request => request.path.endsWith('/links')).length, postsBeforeInvalidUrl);
  await admin.locator('#help-resource-url').fill(addedUrl);
  await navigation.getByRole('link', { name: '运行日志', exact: true }).click();
  await navigation.getByRole('link', { name: '操作资料上传', exact: true }).click();
  assert.equal(await admin.locator('#help-resource-title').inputValue(), addedTitle); assert.equal(await admin.locator('#help-resource-url').inputValue(), addedUrl);
  linkMode = 'error'; await admin.getByRole('button', { name: '保存链接', exact: true }).click();
  await admin.getByRole('alert').filter({ hasText: '链接保存失败' }).waitFor();
  assert.equal(await admin.locator('#help-resource-url').inputValue(), addedUrl);
  linkMode = 'ready'; await admin.getByRole('button', { name: '保存链接', exact: true }).click();
  await resourceList.getByRole('heading', { name: addedTitle, exact: true }).waitFor();
  assert.equal(await resourceList.getByRole('link', { name: `查看链接：${addedTitle}`, exact: true }).getAttribute('href'), addedUrl);

  const help = await context.newPage();
  await help.goto(`${base}/help/manual`);
  const helpList = help.getByRole('navigation', { name: '已发布资料', exact: true });
  await helpList.getByRole('button', { name: `${addedTitle} 链接`, exact: true }).waitFor();
  await admin.getByRole('button', { name: `删除资料：${addedTitle}`, exact: true }).click();
  let confirmation = admin.getByRole('dialog', { name: '删除操作资料', exact: true });
  await confirmation.getByRole('button', { name: '取消', exact: true }).click();
  assert.equal(requests.filter(request => request.method === 'DELETE').length, 0, 'cancel never deletes');
  await admin.getByRole('button', { name: `删除资料：${addedTitle}`, exact: true }).click();
  deleteMode = 'error'; await confirmation.getByRole('button', { name: '确认删除', exact: true }).click();
  await confirmation.getByRole('alert').filter({ hasText: '资料删除失败' }).waitFor();
  deleteMode = 'ready'; await confirmation.getByRole('button', { name: '确认删除', exact: true }).click();
  await confirmation.waitFor({ state: 'hidden' });
  assert.equal(await resourceList.getByRole('heading', { name: addedTitle, exact: true }).count(), 0);
  await help.getByRole('button', { name: '刷新资料', exact: true }).click();
  await helpList.getByRole('button', { name: `${addedTitle} 链接`, exact: true }).waitFor({ state: 'hidden' });
  await helpList.getByRole('button', { name: `${word.title} DOCX`, exact: true }).waitFor();
  await help.getByRole('button', { name: '刷新资料', exact: true }).waitFor();
  assert.equal(await helpList.getByRole('button', { name: `${addedTitle} 链接`, exact: true }).count(), 0, 'deleted entry disappears after reader refresh');

  await choose(admin, 'help-resource-filter', '操作视频');
  assert.equal(await resourceList.getByRole('heading', { name: word.title, exact: true }).count(), 0);
  await choose(admin, 'help-resource-filter', '全部资料');
  listMode = 'empty'; await admin.getByRole('button', { name: '刷新列表', exact: true }).click();
  await admin.getByText('暂无操作资料', { exact: true }).waitFor();
  listMode = 'error'; await admin.getByRole('button', { name: '刷新列表', exact: true }).click();
  await admin.getByRole('alert').filter({ hasText: '资料列表暂时不可用' }).waitFor();
  listMode = 'ready'; await admin.getByRole('button', { name: '重试加载资料', exact: true }).click();
  await resourceList.getByRole('heading', { name: video.title, exact: true }).waitFor();
  console.log('Administrator fixtures passed: upload, links, drafts, permissions, deletion and recovery.');

  await help.bringToFront(); await help.goto(`${base}/help/video`);
  await help.getByRole('navigation', { name: '已发布资料', exact: true }).getByRole('button', { name: `${video.title} WEBM`, exact: true }).click();
  const player = help.locator('video'); await player.waitFor();
  assert.equal(await player.getAttribute('controls'), ''); assert.equal(await player.getAttribute('src'), video.preview_url);
  await player.evaluate(element => { element.muted = true; void element.play().catch(() => {}); });
  await help.waitForFunction(() => document.querySelector('video')?.readyState >= 1).catch(async error => {
    console.error('Video fixture diagnostics:', { bytes: videoBytes.length, contentRequests: requests.filter(request => request.path === video.preview_url),
      media: await player.evaluate(element => ({ ready: element.readyState, network: element.networkState, error: element.error?.message, src: element.currentSrc })) });
    throw error;
  });
  await player.evaluate(element => element.pause());
  assert.equal(await help.getByRole('alert').count(), 0, 'video fixture is playable');
  await help.getByRole('navigation', { name: '使用帮助', exact: true }).getByRole('link', { name: '操作手册', exact: true }).click();
  const pdfResponse = help.waitForResponse(response => new URL(response.url()).pathname === pdf.preview_url);
  await helpList.getByRole('button', { name: `${pdf.title} PDF`, exact: true }).click();
  const pdfFrame = help.getByTitle(pdf.title, { exact: true }); await pdfFrame.waitFor();
  assert.equal(await pdfFrame.getAttribute('src'), pdf.preview_url);
  assert.equal((await pdfResponse).headers()['content-type'], 'application/pdf', 'PDF iframe loads a real PDF response');
  documentMode = 'error'; await helpList.getByRole('button', { name: `${word.title} DOCX`, exact: true }).click();
  await help.getByRole('alert').filter({ hasText: '手册内容读取失败' }).waitFor();
  documentMode = 'ready'; await help.getByRole('button', { name: '重新加载手册', exact: true }).click();
  await help.getByRole('article', { name: '操作手册正文', exact: true }).waitFor();

  console.log('Reader media loaded: playable video, PDF and Word projection.');
  assert.equal(await help.getByRole('region', { name: '手册表格', exact: true }).getByRole('cell').count(), 8);
  await help.getByRole('img', { name: '操作步骤示意图', exact: true }).scrollIntoViewIfNeeded();
  await help.waitForFunction(() => document.querySelector('.help-document img')?.naturalWidth > 0);
  await helpList.getByRole('button', { name: `${external.title} 链接`, exact: true }).click();
  assert.equal(await help.getByRole('link', { name: '打开原链接', exact: true }).getAttribute('href'), external.source_url);
  listMode = 'empty'; await help.getByRole('button', { name: '刷新资料', exact: true }).click();
  await help.getByRole('heading', { name: '操作手册待发布', exact: true }).waitFor();
  listMode = 'error'; await help.getByRole('button', { name: '刷新资料', exact: true }).click();
  await help.getByRole('alert').filter({ hasText: '资料列表暂时不可用' }).waitFor();
  listMode = 'ready'; await help.getByRole('button', { name: '重新加载', exact: true }).click();
  await helpList.getByRole('button', { name: `${word.title} DOCX`, exact: true }).click();
  await help.getByRole('article', { name: '操作手册正文', exact: true }).waitFor();
  await help.getByRole('img', { name: '操作步骤示意图', exact: true }).scrollIntoViewIfNeeded();
  await help.waitForFunction(() => document.querySelector('.help-document img')?.naturalWidth > 0);

  // Capture the final stable state as one desktop/mobile/wide-screen batch.
  await choose(admin, 'help-resource-source', '上传原文件');
  await admin.evaluate(() => scrollTo(0, 0)); await assertNoPageOverflow(admin, 'admin desktop'); await shot(admin, 'admin-desktop.png');
  await admin.setViewportSize({ width: 390, height: 844 });
  await admin.getByRole('button', { name: '管理菜单', exact: false }).click();
  await navigation.getByRole('link', { name: '用户反馈', exact: true }).click();
  await admin.getByRole('button', { name: '管理菜单', exact: false }).click();
  await navigation.getByRole('link', { name: '操作资料上传', exact: true }).click();
  await resourceList.getByRole('heading', { name: video.title, exact: true }).waitFor();
  assert.equal(await navigation.isVisible(), false, 'mobile menu closes after selection');
  await admin.evaluate(() => scrollTo(0, 0)); await assertNoPageOverflow(admin, 'admin mobile'); await shot(admin, 'admin-mobile.png');
  await help.locator('.help-page').evaluate(element => { element.scrollTop = 0; });
  await assertNoPageOverflow(help, 'help desktop'); await shot(help, 'help-desktop.png');
  await help.setViewportSize({ width: 390, height: 844 });
  await assertNoPageOverflow(help, 'help mobile');
  assert.equal(await help.getByRole('region', { name: '手册表格', exact: true }).evaluate(element => element.scrollWidth > element.clientWidth), true, 'wide manual tables scroll inside their own region');
  await shot(help, 'help-mobile.png');
  await help.getByRole('img', { name: '操作步骤示意图', exact: true }).scrollIntoViewIfNeeded();
  await assertNoPageOverflow(help, 'help mobile document'); await shot(help, 'help-mobile-preview.png');
  const home = await context.newPage(); await home.setViewportSize({ width: 1990, height: 1080 }); await home.goto(`${base}/`);
  await home.locator('.rd-application-shell').waitFor();
  const homeLinks = home.locator('.rd-topbar-help');
  await homeLinks.getByRole('link', { name: '操作视频', exact: true }).waitFor();
  await home.getByRole('region', { name: '当前账号与设置', exact: true }).getByText('测试工程师', { exact: true }).waitFor();
  await home.getByRole('heading', { name: '我的工作', exact: true }).waitFor();
  await home.getByText('暂无项目记录', { exact: true }).waitFor();
  assert.equal(await homeLinks.getByRole('link', { name: '操作视频', exact: true }).getAttribute('href'), '/help/video');
  assert.equal(await homeLinks.getByRole('link', { name: '操作手册', exact: true }).getAttribute('href'), '/help/manual');
  await assertNoPageOverflow(home, 'user 1990'); await shot(home, 'user1990.png');
  for (const [label, path] of [['操作视频', '/help/video'], ['操作手册', '/help/manual']]) {
    await homeLinks.getByRole('link', { name: label, exact: true }).click();
    await home.getByRole('heading', { name: label, exact: true }).first().waitFor();
    assert.equal(new URL(home.url()).pathname, path, 'topbar help link opens the selected help page');
    await home.getByRole('link', { name: '返回平台', exact: true }).click();
    await home.locator('.rd-application-shell').waitFor();
    await home.getByRole('region', { name: '当前账号与设置', exact: true }).getByText('测试工程师', { exact: true }).waitFor();
  }
  assert.deepEqual(errors, [], 'no unhandled browser errors');
  assert.deepEqual(unexpected, [], 'all API traffic stayed inside explicit fixtures');
  console.log('Help resources browser passed: ordinary administrator CRUD, upload progress, link/file validation, error and navigation draft preservation, cancel/delete/retry, reader refresh, playable video, PDF, Word table/image projection, empty/error recovery, mobile and 1990px overflow checks.');
} finally { await browser.close(); }
