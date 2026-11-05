/** Persistent conversation UX against an in-memory transport; never writes live conversations. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
let actor = 'actor-a', serial = 0, failClose = false, failMessage = false, holdMessage = null, holdIdentity = null;
const accounts = new Map(), requests = [], errors = [], receipts = new Map();
const stamp = '2026-11-04T12:00:00Z';
function account() { if (!accounts.has(actor)) accounts.set(actor, { active: null, conversations: [] }); return accounts.get(actor); }
function summary(item) { const { messages, draft, ...rest } = item; return { ...rest, message_count: messages.length }; }
function detail(item, before = Infinity) { const messages = item.messages.filter(message => message.seq < before).slice(-40); const first = messages[0]?.seq; const hasMore = item.messages.some(message => message.seq < first); return { ...summary(item), draft: item.draft, messages, has_more: hasMore, next_before: hasMore ? first : null }; }
function makeConversation(source) {
  const id = `session-${++serial}`;
  return { id, title: source ? `续聊 · ${source.title}` : '新对话', created_at: stamp, updated_at: stamp, source_id: source?.id || null,
    version: 1, draft: '', messages: (source?.messages || []).map((message, index) => ({ ...message, id: `${id}-message-${index + 1}`, seq: index + 1 })) };
}
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method();
    const state = account();
    if (path === '/api/rd/session') { if (holdIdentity) await holdIdentity; return route.fulfill({ json: { actor_id: actor, local_mode: false } }); }
    if (path === '/api/rd/assistant/weather') return route.fulfill({ json: { status: 'unavailable', location: '洛阳 · 涧西区', message: '测试天气暂不可用' } });
    if (!path.startsWith('/api/rd/assistant/conversations')) return route.fulfill({ status: 404, json: { detail: 'fixture route missing' } });
    const body = method === 'POST' ? request.postDataJSON() : null;
    const key = request.headers()['idempotency-key'];
    requests.push({ path, method, body, key, actor, before: url.searchParams.get('before') });
    if (method === 'POST') assert(key, 'every mutation has an idempotency key');
    const receiptKey = `${actor}:${key}`;
    if (method === 'POST' && receipts.has(receiptKey)) return route.fulfill({ json: receipts.get(receiptKey) });
    const reply = value => { if (method === 'POST') receipts.set(receiptKey, structuredClone(value)); return route.fulfill({ json: value }); };
    if (path === '/api/rd/assistant/conversations') {
      if (method === 'GET') {
        const currentPage = Number(url.searchParams.get('page') || 1);
        return reply({ items: state.conversations.slice((currentPage - 1) * 20, currentPage * 20).map(summary), total: state.conversations.length, page: currentPage, page_size: 20, active_id: state.active });
      }
      const source = state.conversations.find(item => item.id === body.source_id);
      const item = makeConversation(source); state.conversations.unshift(item); state.active = item.id;
      return reply(detail(item));
    }
    const [, id, action] = path.match(/\/conversations\/([^/]+)(?:\/(messages|close))?$/) || [];
    const item = state.conversations.find(entry => entry.id === id);
    if (!item) return route.fulfill({ status: 404, json: { detail: '对话不存在' } });
    if (method === 'GET') return reply(detail(item, url.searchParams.has('before') ? Number(url.searchParams.get('before')) : Infinity));
    if (body.expected_version !== item.version || state.active !== item.id) return route.fulfill({ status: 409, json: { detail: '对话版本已变化，请重新读取。' } });
    if (action === 'close') {
      if (failClose) { failClose = false; return route.fulfill({ status: 503, json: { detail: '测试关闭未保存，请重试。' } }); }
      item.draft = body.choice === 'keep' ? body.draft : ''; item.version += 1;
      if (body.choice === 'end') state.active = null;
      return reply({ active_id: state.active });
    }
    if (failMessage) { failMessage = false; return route.fulfill({ status: 503, json: { detail: '测试回复失败，请重试。' } }); }
    if (holdMessage) await holdMessage;
    if (!item.messages.length) item.title = body.message.slice(0, 50);
    for (const [role, content] of [['user', body.message], ['assistant', `已收到：${body.message}。之前有 ${item.messages.length} 条消息。`]]) {
      const seq = item.messages.length + 1;
      item.messages.push({ id: `${id}-message-${seq}`, seq, role, content, created_at: stamp,
        ...(role === 'assistant' ? { mode: 'model', actions: [{ id: 'start_task', label: '开始任务' }, { id: 'open_projects', label: '查看项目' }] } : {}) });
    }
    item.version += 1; item.draft = ''; return reply(detail(item));
  });
  await page.goto(`${base}/tests/fixtures/xiaohang-companion.html`);
  const launcher = page.getByRole('button', { name: '打开小航助手', exact: true });
  const panel = page.getByRole('dialog', { name: '小航助手', exact: true });
  const input = panel.getByRole('textbox', { name: '问问小航', exact: true });
  const close = panel.getByRole('button', { name: '收起小航助手', exact: true });
  const confirm = page.getByRole('dialog', { name: '收起还是结束本次对话？', exact: true });
  async function open(expectedDraft = '') { await launcher.click(); await input.waitFor(); await page.waitForFunction(expected => { const field = document.querySelector('.rd-welcome-composer textarea'); return field && !field.disabled && field.value === expected; }, expectedDraft); }
  async function ask(text) { await input.fill(text); await panel.getByRole('button', { name: '发送给小航', exact: true }).click(); await panel.getByText(`已收到：${text}。`, { exact: false }).waitFor(); }
  await open();
  await ask('第一段对话');
  const firstId = account().active;
  assert.equal(await panel.getByRole('button', { name: '开始任务', exact: true }).count(), 0);
  assert.equal(await panel.getByRole('button', { name: '查看项目', exact: true }).count(), 0);
  const firstSend = requests.find(item => item.path.endsWith('/messages'));
  assert.deepEqual(Object.keys(firstSend.body).sort(), ['expected_version', 'message'], 'history is supplied by the server');
  await input.fill('未发送的草稿');
  await close.click(); await confirm.waitFor();
  await confirm.getByRole('button', { name: '继续聊天', exact: true }).click();
  assert.equal(await input.inputValue(), '未发送的草稿');
  await page.getByRole('button', { name: '页面操作', exact: true }).click();
  await confirm.waitFor();
  failClose = true;
  await confirm.getByRole('button', { name: '保留并收起', exact: true }).click();
  await confirm.getByRole('alert').filter({ hasText: '测试关闭未保存' }).waitFor();
  assert(await panel.isVisible()); assert.equal(await input.inputValue(), '未发送的草稿');
  await confirm.getByRole('button', { name: '保留并收起', exact: true }).click();
  await panel.waitFor({ state: 'hidden' });
  const keeps = requests.filter(item => item.path.endsWith('/close'));
  assert.equal(keeps[0].key, keeps[1].key, 'failed close reuses its mutation key');
  assert.equal(account().conversations.find(item => item.id === firstId).draft, '未发送的草稿');
  await open('未发送的草稿'); assert.equal(await input.inputValue(), '未发送的草稿');
  await panel.getByText('已收到：第一段对话。', { exact: false }).waitFor();
  await page.keyboard.press('Escape'); await confirm.waitFor();
  if (output) await page.screenshot({ path: join(output, 'conversation-close-desktop.png'), animations: 'disabled' });
  await confirm.getByRole('button', { name: '结束并退出', exact: true }).click();
  await panel.waitFor({ state: 'hidden' });
  assert.equal(account().active, null); assert.equal(account().conversations.find(item => item.id === firstId).messages.length, 2);
  await open(); assert.equal(await input.inputValue(), ''); assert.equal(await panel.locator('.rd-welcome-message').count(), 0);
  await ask('第二段对话'); assert.notEqual(account().active, firstId);
  await input.fill('切换前的草稿');
  await panel.getByRole('button', { name: '历史记录', exact: true }).click();
  const mutationCount = requests.filter(item => item.method === 'POST').length;
  await panel.locator('.rd-chat-history-list').getByRole('button', { name: /第一段对话/ }).click();
  assert.equal(requests.filter(item => item.method === 'POST').length, mutationCount, 'preview never mutates the active session');
  const original = structuredClone(account().conversations.find(item => item.id === firstId));
  await panel.getByRole('button', { name: '基于此记录新对话', exact: true }).click();
  const discard = page.getByRole('dialog', { name: '另开新对话？', exact: true });
  await discard.getByRole('button', { name: '继续编辑', exact: true }).click();
  assert.equal(requests.filter(item => item.method === 'POST').length, mutationCount);
  await panel.getByRole('button', { name: '基于此记录新对话', exact: true }).click();
  await discard.getByRole('button', { name: '放弃草稿并新建', exact: true }).click();
  await input.waitFor(); await page.waitForFunction(() => !document.querySelector('.rd-welcome-composer textarea')?.disabled);
  assert.equal(account().conversations[0].source_id, firstId); assert.equal(await input.inputValue(), '');
  await ask('接着聊');
  assert.equal(account().conversations[0].messages.length, 4);
  assert.deepEqual(account().conversations.find(item => item.id === firstId), original, 'fork and follow-up leave the source record unchanged');
  for (let index = 0; index < 19; index++) {
    const item = makeConversation(); item.title = `历史样本 ${index}`;
    if (index === 18) item.messages = Array.from({ length: 44 }, (_, i) => ({ id: `${item.id}-${i + 1}`, seq: i + 1, role: i % 2 ? 'assistant' : 'user', content: `分页消息 ${i + 1}`, created_at: stamp }));
    account().conversations.push(item);
  }
  await panel.getByRole('button', { name: '历史记录', exact: true }).click();
  await panel.getByRole('button', { name: '下一页', exact: true }).click();
  await panel.locator('.rd-chat-history-list').getByRole('button', { name: /历史样本 18/ }).click();
  await panel.getByText('分页消息 5', { exact: true }).waitFor();
  assert.equal(await panel.locator('.rd-welcome-message').count(), 40);
  await panel.getByRole('button', { name: '查看更早消息', exact: true }).click();
  await panel.getByText('分页消息 1', { exact: true }).waitFor();
  assert.equal(await panel.locator('.rd-welcome-message').count(), 44);
  await page.setViewportSize({ width: 390, height: 844 });
  assert(await panel.evaluate(element => element.scrollWidth <= element.clientWidth + 1));
  if (output) await page.screenshot({ path: join(output, 'conversation-history-mobile.png'), animations: 'disabled' });
  await panel.getByRole('button', { name: '返回当前对话', exact: true }).click();
  await input.fill('账号 A 未发送内容');
  let releaseIdentity; holdIdentity = new Promise(resolve => { releaseIdentity = resolve; });
  actor = 'actor-b';
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await panel.getByText('正在核对对话', { exact: true }).waitFor();
  assert.equal(await panel.locator('.rd-chat-toolbar > span').getAttribute('title'), null, 'identity recheck hides old conversation titles');
  assert.equal(await input.inputValue(), '');
  holdIdentity = null; releaseIdentity();
  await panel.getByRole('heading', { name: '你好，我是小航', exact: true }).waitFor();
  assert.equal(await input.inputValue(), ''); assert.equal(await panel.locator('.rd-welcome-message').count(), 0);
  failMessage = true;
  await input.fill('账号 B 重试问题');
  await panel.getByRole('button', { name: '发送给小航', exact: true }).click();
  await panel.getByRole('alert').filter({ hasText: '测试回复失败' }).waitFor();
  await panel.getByRole('button', { name: '重试发送', exact: true }).click();
  await panel.getByText('已收到：账号 B 重试问题。', { exact: false }).waitFor();
  const sends = requests.filter(item => item.actor === actor && item.path.endsWith('/messages'));
  assert.equal(sends[0].key, sends[1].key, 'failed send reuses its mutation key');
  account().conversations[0].version += 1;
  await input.fill('冲突后仍要发送的问题');
  await panel.getByRole('button', { name: '发送给小航', exact: true }).click();
  await panel.getByRole('alert').filter({ hasText: '版本已变化' }).waitFor();
  await panel.getByRole('button', { name: '重新读取对话', exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('.rd-welcome-composer textarea')?.disabled);
  assert.equal(await input.inputValue(), '冲突后仍要发送的问题');
  await panel.getByRole('button', { name: '发送给小航', exact: true }).click();
  await panel.getByText('已收到：冲突后仍要发送的问题。', { exact: false }).waitFor();
  let release; holdMessage = new Promise(resolve => { release = resolve; });
  await input.fill('正在处理的问题');
  await panel.getByRole('button', { name: '发送给小航', exact: true }).click();
  await panel.getByText('小航正在整理回复…', { exact: false }).waitFor();
  assert(await close.isDisabled());
  await page.getByRole('button', { name: '页面操作', exact: true }).click();
  assert.equal(await confirm.count(), 0, 'pending response cannot end the session');
  holdMessage = null; release();
  await panel.getByText('已收到：正在处理的问题。', { exact: false }).waitFor();
  await input.fill('刷新后恢复的草稿');
  account().conversations[0].version += 1;
  await close.click(); await confirm.waitFor();
  await confirm.getByRole('button', { name: '保留并收起', exact: true }).click();
  await confirm.getByRole('alert').filter({ hasText: '版本已变化' }).waitFor();
  await confirm.getByRole('button', { name: '重新读取对话', exact: true }).click();
  await confirm.getByRole('alert').waitFor({ state: 'hidden' });
  await page.waitForFunction(() => !document.querySelector('.rd-welcome-composer textarea')?.disabled);
  assert.equal(await input.inputValue(), '刷新后恢复的草稿');
  if (output) await page.screenshot({ path: join(output, 'conversation-close-mobile.png'), animations: 'disabled' });
  await confirm.getByRole('button', { name: '保留并收起', exact: true }).click();
  await panel.waitFor({ state: 'hidden' });
  await page.reload(); await open('刷新后恢复的草稿');
  assert.equal(await input.inputValue(), '刷新后恢复的草稿');
  await panel.getByText('已收到：正在处理的问题。', { exact: false }).waitFor();
  assert.equal(await page.evaluate(() => [...Object.values(localStorage), ...Object.values(sessionStorage)].some(value => /第一段对话|账号 B|刷新后恢复的草稿/.test(value))), false);
  assert.deepEqual(errors, []);
  console.log('PASS conversation sessions: keep/end/reopen/reload, close failure and stable retry keys, readonly history/fork/source preservation, directory/message pagination, actor isolation, version conflict draft recovery, pending guards and mobile.');
} finally { await browser.close(); }
