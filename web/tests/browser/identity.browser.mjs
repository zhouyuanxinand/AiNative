/** Shared platform identity and feedback session recovery, using a simulated same-origin API. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
const user = { userid: 'engineer-1024', name: '梁工程师', display_name: '梁工程师', source: 'smartvision', verified: true };
const authenticated = current => ({ auth_enabled: true, authenticated: true, user: current });
const anonymous = { auth_enabled: true, authenticated: false, user: null, login_url: '/auth/login' };
const local = { auth_enabled: false, authenticated: false, user: null };
const errors = [];

async function open(initialIdentity, options = {}) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => errors.push(error.message));
  const state = { identity: initialIdentity, identityStatus: options.identityStatus || 200, posts: [], postStatus: 200, identityReads: 0 };
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/current-user') {
      state.identityReads += 1;
      if (options.identityGate) await options.identityGate;
      return route.fulfill({ status: state.identityStatus, json: state.identity });
    }
    if (path === '/api/feedback') {
      const body = request.postDataJSON();
      state.posts.push(body);
      await new Promise(resolve => setTimeout(resolve, 80));
      if (state.postStatus === 401) return route.fulfill({ status: 401, json: { error: '登录已过期，请重新登录。', auth_required: true, login_url: '/auth/login' } });
      if (state.postStatus === 503) return route.fulfill({ status: 503, json: { error: '反馈服务暂不可用，请重试。' } });
      return route.fulfill({ json: { record: { id: state.posts.length, username: state.identity.user?.display_name || body.username,
        rating: body.rating, comment: body.comment, status: 'open' } } });
    }
    let response = {};
    if (path === '/api/product_catalog') response = { product_types: [] };
    if (path === '/api/models') response = { success: true, models: [] };
    if (path === '/api/history' || path === '/api/local_defaults') response = [];
    if (path.startsWith('/api/indicator_review/')) response = { manual_review_required: [], comparison_decisions: [], indicator_clarifications: {} };
    return route.fulfill({ json: response });
  });
  await page.addInitScript(() => { window.EventSource = class { constructor() { window.testEventSource = this; } close() {} }; });
  await page.goto(`${base}/`);
  await page.locator('#workspace-shell').waitFor({ timeout: 8000 }).catch(async error => {
    console.error('Identity page errors:', errors, 'Body:', await page.locator('body').innerText());
    throw error;
  });
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('taskbook:replay-started', { detail: { jid: 'identity-job-1' } })));
  await page.locator('#btn-cancel').waitFor();
  await page.evaluate(() => window.testEventSource.onmessage({ data: JSON.stringify({ type: 'done', result: { meta: { product_type: '射频连接器', output_name: '任务书.docx' } } }) }));
  const feedback = page.locator('#result-card .generation-feedback');
  await feedback.waitFor();
  return { page, feedback, state };
}

try {
  const signed = await open(authenticated(user));
  await signed.page.locator('.sidebar-user-row').getByText(user.display_name, { exact: true }).waitFor({ timeout: 5000 });
  await signed.feedback.getByLabel('反馈用户名', { exact: false }).waitFor();
  assert.equal(await signed.feedback.getByLabel('反馈用户名', { exact: false }).inputValue(), user.display_name);
  assert.equal(await signed.feedback.getByLabel('反馈用户名', { exact: false }).isEditable(), false, 'platform name is read-only');
  assert.match(await signed.feedback.innerText(), new RegExp(user.userid));
  await signed.feedback.getByLabel('反馈用户名', { exact: false }).focus();
  await signed.page.keyboard.press('Tab');
  assert.equal(await signed.feedback.getByLabel('好', { exact: true }).evaluate(input => input === document.activeElement), true, 'keyboard reaches the rating after the read-only name');
  const feedbackBounds = await signed.feedback.boundingBox();
  const ratingBounds = await signed.feedback.getByLabel('差', { exact: true }).locator('..').boundingBox();
  assert.ok(ratingBounds.x + ratingBounds.width <= feedbackBounds.x + feedbackBounds.width, 'ratings fit inside the narrow desktop result panel');
  if (process.env.SCREENSHOT_DIR) {
    await mkdir(process.env.SCREENSHOT_DIR, { recursive: true });
    await signed.page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'identity-feedback-desktop.png'), fullPage: true });
  }
  const initialIdentityReads = signed.state.identityReads;
  await signed.feedback.getByLabel('好', { exact: true }).check();
  await signed.feedback.getByLabel('意见与建议', { exact: false }).fill('保留统一登录账号的反馈草稿。');
  signed.state.postStatus = 503;
  await signed.feedback.getByRole('button', { name: '提交反馈', exact: true }).evaluate(button => { button.click(); button.click(); });
  await signed.feedback.getByRole('alert').filter({ hasText: '暂不可用' }).waitFor();
  assert.equal(signed.state.posts.length, 1, 'double click submits once');
  signed.state.postStatus = 200;
  await signed.feedback.getByRole('button', { name: '提交反馈', exact: true }).click();
  await signed.feedback.getByText('反馈已提交', { exact: true }).waitFor();
  assert.equal(signed.state.posts[0].request_id, signed.state.posts[1].request_id, 'same-user retry keeps request ID');
  assert.deepEqual(Object.keys(signed.state.posts[0]).sort(), ['comment', 'jid', 'rating', 'request_id'], 'authenticated feedback does not send a claimed username');
  assert.equal(signed.state.identityReads, initialIdentityReads, 'rendering and submitting feedback reuse the sidebar identity');
  assert.equal(await signed.page.locator('#btn-docx').isEnabled(), true);
  await signed.page.close();

  const expired = await open(authenticated(user));
  await expired.feedback.getByLabel('反馈用户名', { exact: false }).waitFor();
  await expired.feedback.getByLabel('一般', { exact: true }).check();
  await expired.feedback.getByLabel('意见与建议', { exact: false }).fill('登录过期后仍应保留这条意见。');
  expired.state.postStatus = 401;
  await expired.feedback.getByRole('button', { name: '提交反馈', exact: true }).click();
  await expired.feedback.getByRole('link', { name: '前往统一登录', exact: true }).waitFor();
  assert.equal(await expired.feedback.getByRole('link', { name: '前往统一登录', exact: true }).getAttribute('href'), '/auth/login');
  assert.equal(await expired.feedback.getByLabel('意见与建议', { exact: false }).inputValue(), '登录过期后仍应保留这条意见。');
  assert.equal(await expired.feedback.getByLabel('一般', { exact: true }).isChecked(), true);
  assert.equal(await expired.feedback.getByRole('button', { name: '提交反馈', exact: true }).isDisabled(), true);
  assert.match(await expired.page.locator('.sidebar-user-row').innerText(), /未登录/);
  expired.state.postStatus = 200;
  await expired.feedback.getByRole('button', { name: '重新读取登录状态', exact: true }).click();
  await expired.feedback.getByLabel('反馈用户名', { exact: false }).waitFor();
  assert.equal(await expired.feedback.getByRole('alert').count(), 0, 'restored login clears the expired-session error');
  await expired.feedback.getByRole('button', { name: '提交反馈', exact: true }).click();
  await expired.feedback.getByText('反馈已提交', { exact: true }).waitFor();
  assert.equal(expired.state.posts[0].request_id, expired.state.posts[1].request_id, 'reauthentication as the same user preserves retry ID');
  await expired.feedback.getByRole('button', { name: '再写一条反馈', exact: true }).click();
  await expired.feedback.getByLabel('差', { exact: true }).check();
  await expired.feedback.getByLabel('意见与建议', { exact: false }).fill('账号切换草稿。');
  expired.state.postStatus = 401;
  await expired.feedback.getByRole('button', { name: '提交反馈', exact: true }).click();
  await expired.feedback.getByRole('link', { name: '前往统一登录', exact: true }).waitFor();
  expired.state.identity = authenticated({ ...user, userid: 'engineer-2048', display_name: '连接器事业部质量复核工程师'.repeat(6) });
  expired.state.postStatus = 200;
  await expired.feedback.getByRole('button', { name: '重新读取登录状态', exact: true }).click();
  await expired.feedback.getByText('登录账号已更换，请确认后再提交当前意见。', { exact: true }).waitFor();
  assert.equal(await expired.feedback.getByLabel('意见与建议', { exact: false }).inputValue(), '账号切换草稿。');
  await expired.page.setViewportSize({ width: 390, height: 844 });
  if (await expired.page.locator('#workspace-shell.sidebar-expanded').count()) await expired.page.locator('#sidebar .sidebar-toggle').click();
  assert.equal(await expired.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'long platform names do not overflow mobile');
  if (process.env.SCREENSHOT_DIR) {
    await mkdir(process.env.SCREENSHOT_DIR, { recursive: true });
    await expired.feedback.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'identity-feedback-mobile.png') });
  }
  await expired.feedback.getByRole('button', { name: '提交反馈', exact: true }).click();
  await expired.feedback.getByText('反馈已提交', { exact: true }).waitFor();
  assert.notEqual(expired.state.posts[2].request_id, expired.state.posts[3].request_id, 'changing user creates a new request ID');
  await expired.page.close();

  let releaseIdentity;
  const identityGate = new Promise(resolve => { releaseIdentity = resolve; });
  const loading = await open(authenticated(user), { identityGate });
  await loading.feedback.getByText('正在读取登录身份…', { exact: true }).waitFor();
  assert.equal(await loading.feedback.getByRole('button', { name: '提交反馈', exact: true }).isDisabled(), true);
  assert.equal(await loading.feedback.getByLabel('反馈用户名', { exact: false }).count(), 0, 'loading cannot fall back to a claimed username');
  releaseIdentity();
  await loading.feedback.getByLabel('反馈用户名', { exact: false }).waitFor();
  await loading.page.close();

  const missing = await open(anonymous);
  await missing.feedback.getByRole('link', { name: '前往统一登录', exact: true }).waitFor();
  assert.equal(await missing.feedback.getByLabel('反馈用户名', { exact: false }).count(), 0, 'unauthenticated platform mode cannot impersonate by typing');
  assert.equal(await missing.feedback.getByRole('button', { name: '提交反馈', exact: true }).isDisabled(), true);
  await missing.page.close();

  const unavailable = await open({ error: '统一登录服务暂不可用。' }, { identityStatus: 503 });
  await unavailable.feedback.getByRole('button', { name: '重试读取身份', exact: true }).waitFor();
  assert.equal(await unavailable.feedback.getByLabel('反馈用户名', { exact: false }).count(), 0, 'identity error cannot downgrade to local mode');
  assert.equal(await unavailable.feedback.getByRole('button', { name: '提交反馈', exact: true }).isDisabled(), true);
  assert.match(await unavailable.page.locator('.sidebar-user-row').innerText(), /身份读取失败/);
  unavailable.state.identityStatus = 200;
  unavailable.state.identity = local;
  await unavailable.feedback.getByRole('button', { name: '重试读取身份', exact: true }).click();
  await unavailable.feedback.getByLabel('反馈用户名', { exact: false }).waitFor();
  assert.equal(await unavailable.feedback.getByLabel('反馈用户名', { exact: false }).isEditable(), true);
  assert.match(await unavailable.page.locator('.sidebar-user-row').innerText(), /本地模式/);
  await unavailable.page.close();
  assert.deepEqual(errors, [], 'no runtime page errors');
  console.log('Identity browser flow passed: shared verified identity, loading/error/login states, preserved drafts, user-aware retries and narrow layout.');
} finally {
  await browser.close();
}
