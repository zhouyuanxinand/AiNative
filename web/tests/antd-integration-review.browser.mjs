/** Final read-only integration checks. Never submits a project or mutates admin data. */
import assert from 'node:assert/strict';
import { mkdir, unlink, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = resolve(process.env.SCREENSHOT_DIR || '../runtime/creation-modal-polish');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ignoreDefaultArgs: ['--hide-scrollbars'], executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(6000);
const writes = [], errors = [], receipt = {};
page.on('pageerror', error => errors.push(error.message));
await page.route('**/api/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname;
  if (!path.startsWith('/api/')) return route.continue();
  if (!['GET', 'HEAD'].includes(request.method())) {
    writes.push({ path, method: request.method() });
    return route.fulfill({ status: 405, json: { error: 'Read-only UI verification' } });
  }
  return route.continue();
});
async function outside(dialog) { const box = await dialog.boundingBox(); assert(box.x > 0); await page.mouse.click(box.x / 2, box.y + Math.min(70, box.height / 2)); }
async function screenshot(name) { await page.screenshot({ path: join(output, name + '.png'), animations: 'disabled' }); }
function textFieldGeometry(dialog) {
  return [...dialog.querySelectorAll('.rd-field')].map(field => {
    const input = field.querySelector(':scope>input:not([type=hidden]),:scope>textarea');
    if (!input) return null;
    const outer = field.getBoundingClientRect(), inner = input.getBoundingClientRect();
    return { id: input.id, fieldWidth: outer.width, inputWidth: inner.width, height: inner.height, display: getComputedStyle(field).display };
  }).filter(Boolean);
}
function creationGeometry(dialog) {
  const rect = element => {
    const box = element.getBoundingClientRect();
    return { left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width, height: box.height };
  };
  const body = dialog.querySelector('.rd-create-body'), footer = dialog.querySelector('.rd-create-footer');
  const style = getComputedStyle(body);
  return {
    dialog: rect(dialog), title: rect(dialog.querySelector('.feedback-dialog-title')), body: rect(body), footer: rect(footer),
    scrollTop: body.scrollTop, scrollHeight: body.scrollHeight, clientHeight: body.clientHeight,
    scrollbarWidth: style.scrollbarWidth, scrollbarColor: style.scrollbarColor, overflowY: style.overflowY,
    buttons: [...footer.querySelectorAll('button')].map(button => {
      const box = rect(button), hit = document.elementFromPoint((box.left + box.right) / 2, (box.top + box.bottom) / 2);
      return { ...box, label: button.textContent, reachable: !!hit && button.contains(hit) };
    }),
  };
}
function assertCreationBounds(geometry, viewport) {
  const inside = box => box.left >= 0 && box.right <= viewport.width && box.top >= 0 && box.bottom <= viewport.height;
  assert(inside(geometry.dialog), JSON.stringify({ viewport, geometry }));
  assert(inside(geometry.title) && inside(geometry.footer), JSON.stringify({ viewport, geometry }));
  assert(geometry.body.bottom <= geometry.footer.top + 1, JSON.stringify(geometry));
  assert.equal(geometry.buttons.length, 2);
  geometry.buttons.forEach(button => {
    assert(inside(button), JSON.stringify({ viewport, button }));
    assert(button.top >= geometry.footer.top && button.bottom <= geometry.footer.bottom, JSON.stringify({ footer: geometry.footer, button }));
    assert(button.reachable, JSON.stringify(button));
  });
  assert.equal(geometry.overflowY, 'auto');
  assert.notEqual(geometry.scrollbarWidth, 'none');
}
async function verifyCreationLayout(dialog, viewport, expanded) {
  const body = dialog.locator('.rd-create-body'), options = dialog.locator('.rd-create-options');
  await page.setViewportSize(viewport);
  if (await options.evaluate(element => element.open) !== expanded) await options.locator('summary').click();
  await body.evaluate(element => { element.scrollTop = 0; });
  const before = await dialog.evaluate(creationGeometry);
  assertCreationBounds(before, viewport);
  const name = `${viewport.width}x${viewport.height}-${expanded ? 'expanded' : 'collapsed'}`;
  await screenshot(`layout-${name}-top`);
  if (before.scrollHeight > before.clientHeight) {
    await body.hover();
    await page.mouse.wheel(0, 320);
    await page.waitForFunction(() => document.querySelector('.rd-create-body')?.scrollTop > 0);
  }
  await body.evaluate(element => { element.scrollTop = element.scrollHeight; });
  const after = await dialog.evaluate(creationGeometry);
  assertCreationBounds(after, viewport);
  for (const part of ['title', 'footer']) {
    assert(Math.abs(before[part].top - after[part].top) <= 1 && Math.abs(before[part].bottom - after[part].bottom) <= 1, JSON.stringify({ name, part, before: before[part], after: after[part] }));
  }
  assert(Math.abs(after.scrollHeight - after.clientHeight - after.scrollTop) <= 1, JSON.stringify(after));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await screenshot(`layout-${name}-bottom`);
  const result = { viewport, expanded, before, after };
  if (expanded) {
    await dialog.getByRole('combobox', { name: '产品归属范围', exact: true }).locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]').click();
    const popup = page.locator('.platform-select-popup:visible');
    await popup.waitFor({ state: 'visible' });
    await popup.getByRole('option', { name: '中央研究院产品', exact: true }).hover();
    await screenshot(`layout-${name}-select-open`);
    const menu = await popup.evaluate(element => {
      const rect = item => { const box = item.getBoundingClientRect(); return { left: box.left, right: box.right, top: box.top, bottom: box.bottom }; };
      return {
        box: rect(element),
        options: [...element.querySelectorAll('[role="option"]')].map(option => {
          const box = rect(option), hit = document.elementFromPoint((box.left + box.right) / 2, (box.top + box.bottom) / 2);
          return { ...box, text: option.textContent, reachable: !!hit && option.contains(hit) };
        }),
      };
    });
    assert(menu.box.left >= 0 && menu.box.right <= viewport.width && menu.box.top >= 0 && menu.box.bottom <= viewport.height, JSON.stringify({ viewport, menu }));
    assert(menu.options.length >= 2, JSON.stringify(menu));
    menu.options.forEach(option => {
      assert(option.left >= menu.box.left && option.right <= menu.box.right && option.top >= menu.box.top && option.bottom <= menu.box.bottom, JSON.stringify({ menu: menu.box, option }));
      assert(option.reachable, JSON.stringify(option));
    });
    result.menu = menu;
    await page.keyboard.press('Escape');
    await popup.waitFor({ state: 'hidden' });
    await dialog.waitFor({ state: 'visible' });
  }
  return result;
}
try {
  await page.goto(base);
  const open = page.getByRole('button', { name: '新建项目', exact: true });
  const dialog = page.getByRole('dialog', { name: '新建项目', exact: true });
  await open.click(); await dialog.waitFor();
  const desktop = await dialog.evaluate(textFieldGeometry);
  assert(desktop.length >= 4);
  desktop.forEach(item => { assert(Math.abs(item.fieldWidth - item.inputWidth) < 2, JSON.stringify(item)); assert(item.height >= 32, JSON.stringify(item)); assert.equal(item.display, 'flex'); });
  receipt.desktop = desktop;
  await screenshot('01-new-project-desktop');
  await outside(dialog); await dialog.waitFor({ state: 'hidden' });
  await open.click(); await dialog.getByLabel('项目名称', { exact: false }).fill('验收草稿，不创建项目');
  await outside(dialog);
  const discard = page.getByRole('dialog', { name: '关闭当前创建', exact: true }); await discard.waitFor();
  await screenshot('02-unsaved-protection');
  await discard.getByRole('button', { name: '继续填写', exact: true }).click(); await discard.waitFor({ state: 'hidden' });
  assert.equal(await dialog.getByLabel('项目名称', { exact: false }).inputValue(), '验收草稿，不创建项目');
  receipt.creationLayouts = [];
  for (const viewport of [{ width: 1366, height: 768 }, { width: 1440, height: 900 }, { width: 390, height: 640 }]) {
    for (const expanded of [false, true]) receipt.creationLayouts.push(await verifyCreationLayout(dialog, viewport, expanded));
  }
  await dialog.locator('.rd-create-options summary').click();
  await page.setViewportSize({ width: 390, height: 640 });
  const mobile = await dialog.evaluate(element => {
    const box = element.getBoundingClientRect(), body = element.querySelector('.rd-create-body');
    return { left: box.left, right: box.right, top: box.top, bottom: box.bottom, clientHeight: body.clientHeight, scrollHeight: body.scrollHeight };
  });
  assert(mobile.left >= 0 && mobile.right <= 390 && mobile.top >= 0 && mobile.bottom <= 640, JSON.stringify(mobile));
  const mobileFields = await dialog.evaluate(textFieldGeometry);
  mobileFields.forEach(item => assert(Math.abs(item.fieldWidth - item.inputWidth) < 2, JSON.stringify(item)));
  assert(mobile.scrollHeight > mobile.clientHeight, 'short mobile viewport provides a scrolling body');
  await dialog.getByRole('button', { name: '创建并开始', exact: true }).scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  receipt.mobile = { ...mobile, fields: mobileFields };
  await screenshot('03-new-project-mobile-scrolled');
  await outside(dialog); await discard.waitFor(); await discard.getByRole('button', { name: '关闭创建', exact: true }).click(); await dialog.waitFor({ state: 'hidden' });
  receipt.closeProtection = true;
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.route('**/api/admin/session', route => route.fulfill({ json: { authenticated: true, user: { username: 'wangxue', display_name: '验收管理员', userid: 'test-owner' }, can_manage_admins: true } }));
  await page.route('**/api/admin/members', route => route.fulfill({ json: { items: [{ username: 'review-user', is_owner: false, created_by: 'wangxue', created_at: '2026-11-03T00:00:00Z' }], can_manage_admins: true } }));
  await page.route('**/api/feedback-admin**', route => route.fulfill({ json: { items: [{ id: 7, version: 1, username: '测试人员', rating: 'average', status: 'open', comment: '只读验证', handling_note: '', created_at: '2026-11-03T00:00:00Z', updated_at: '2026-11-03T00:00:00Z', identity: {}, snapshot: { jid: 'read-only-fixture', parameters: {}, files: {} } }], total: 1, page: 1, page_size: 20, stats: { total: 1, good: 0, average: 1, poor: 0, good_rate: 0, open: 1, in_progress: 0, resolved: 0 } } }));
  await page.goto(base + '/admin');
  const removeFeedback = page.getByRole('button', { name: '删除反馈 7', exact: true }); await removeFeedback.waitFor();
  assert(await removeFeedback.evaluate(element => element.classList.contains('ant-btn-dangerous')));
  receipt.feedbackDanger = { class: await removeFeedback.getAttribute('class'), color: await removeFeedback.evaluate(element => getComputedStyle(element).color) };
  await screenshot('04-feedback-danger');
  await page.getByRole('link', { name: '管理员名单', exact: true }).click();
  const removeMember = page.getByRole('button', { name: '移除管理员 review-user', exact: true }); await removeMember.waitFor();
  assert(await removeMember.evaluate(element => element.classList.contains('ant-btn-dangerous')));
  receipt.memberDanger = { class: await removeMember.getAttribute('class'), color: await removeMember.evaluate(element => getComputedStyle(element).color) };
  await screenshot('05-member-danger');
  assert.deepEqual(writes, []); assert.deepEqual(errors, []);
  Object.assign(receipt, { passed: true, writes, errors });
  await unlink(join(output, 'failure.png')).catch(error => { if (error.code !== 'ENOENT') throw error; });
  await writeFile(join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt, null, 2));
} catch (error) {
  await screenshot('failure');
  Object.assign(receipt, { passed: false, writes, errors, failure: error.stack || String(error) });
  await writeFile(join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  console.error(JSON.stringify({ writes, errors }, null, 2));
  throw error;
}
finally { await browser.close(); }
