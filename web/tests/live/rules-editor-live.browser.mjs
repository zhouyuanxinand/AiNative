/** Read-only smoke test plus non-writing validation. Never saves live rules. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(10000);
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
page.on('console', (message) => { if (message.type() === 'error' && /same key|unique.*key/.test(message.text())) errors.push(message.text()); });
await page.route('**/api/rules**', (route) => {
  if (route.request().method() !== 'GET' && !(route.request().method() === 'POST' && new URL(route.request().url()).pathname.endsWith('/validate'))) {
    errors.push(`Unexpected mutation ${route.request().method()}`);
    return route.abort();
  }
  return route.continue();
});

try {
  const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
  const response = await page.request.get(`${base}/api/rules`);
  assert.equal(response.ok(), true);
  const catalog = await response.json();
  assert.ok(catalog.items.length > 0);
  await page.goto(base);
  await page.locator('button[data-page="rules"]').click();
  await page.getByRole('heading', { name: catalog.items[0].title, exact: true }).waitFor();
  let totalFields = 0;
  const start = Date.now();
  for (const item of catalog.items) {
    const detailResponse = await page.request.get(`${base}/api/rules/${encodeURIComponent(item.id)}`);
    assert.equal(detailResponse.ok(), true);
    const detail = await detailResponse.json();
    assert.equal(typeof detail.revision, 'string');
    assert.ok(Array.isArray(detail.history));
    assert.equal(detail.fields.length, item.field_count);
    await page.locator('.rules-nav-item').filter({ hasText: item.title }).click();
    await page.getByRole('heading', { name: item.title, exact: true }).waitFor();
    assert.equal(await page.locator('.rule-field').count(), detail.fields.length, item.id);
    assert.equal(await page.getByRole('button', { name: '保存并生效', exact: true }).isDisabled(), true);
    assert.equal(await page.locator('.rules-feedback.error').count(), 0);
    totalFields += detail.fields.length;
  }
  const validationTarget = catalog.items.find((item) => item.id === 'failure_mode_policy');
  if (validationTarget) {
    const original = await (await page.request.get(`${base}/api/rules/failure_mode_policy`)).json();
    await page.locator('.rules-nav-item').filter({ hasText: validationTarget.title }).click();
    await page.getByRole('heading', { name: validationTarget.title, exact: true }).waitFor();
    const input = page.locator('.rule-field textarea').first();
    const originalValue = await input.inputValue();
    await input.fill(`${originalValue}（界面规则校验测试，不保存）`);
    await page.getByRole('button', { name: '检查修改', exact: true }).click();
    await page.locator('.rules-feedback.success').filter({ hasText: '检查通过' }).waitFor();
    assert.equal(await page.locator('.rules-change-preview').isVisible(), true);
    const after = await (await page.request.get(`${base}/api/rules/failure_mode_policy`)).json();
    assert.equal(after.revision, original.revision, 'validation must not save a revision');
    assert.deepEqual(after.data, original.data, 'validation must not change the active rule');
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: '放弃修改', exact: true }).click();
    assert.equal(await input.inputValue(), originalValue);
  }
  const target = catalog.items.find((item) => item.id === 'standard_applicability') || catalog.items[0];
  await page.locator('.rules-nav-item').filter({ hasText: target.title }).click();
  await page.getByRole('heading', { name: target.title, exact: true }).waitFor();
  await page.evaluate(() => { document.querySelector('.main').scrollTop = 0; });
  if (process.env.SCREENSHOT_DIR) {
    await mkdir(process.env.SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'rules-live-desktop.png'), fullPage: true });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  if (await page.locator('#workspace-shell').evaluate((element) => element.classList.contains('sidebar-expanded'))) await page.locator('#sidebar .sidebar-toggle').click();
  await page.evaluate(() => { document.querySelector('.main').scrollTop = 0; });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'mobile horizontal overflow');
  if (process.env.SCREENSHOT_DIR) await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'rules-live-mobile.png'), fullPage: true });
  assert.deepEqual(errors, []);
  console.log(`PASS: ${catalog.items.length} live rule groups / ${totalFields} editable fields rendered, ${Date.now() - start} ms; actual validation passed without saving; desktop/mobile checked.`);
} finally { await browser.close(); }
