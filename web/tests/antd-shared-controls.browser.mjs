/** Real shared controls, isolated React state. No business API reads or writes. */
import assert from 'node:assert/strict';
import { mkdir, unlink, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = resolve(process.env.SCREENSHOT_DIR || '../docs/rd-platform/verification/screenshots/2026-11-03-ant-design/shared-controls');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const errors = [], apiRequests = [], checks = [];
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, hasTouch: true });
page.setDefaultTimeout(6000);
page.on('pageerror', error => errors.push(error.message));
async function outside(dialog, button = 'left') {
  const box = await dialog.boundingBox();
  assert(box && box.x > 1, 'a visible backdrop remains available');
  await page.mouse.click(box.x / 2, box.y + Math.min(box.height / 2, 120), { button });
}
async function clickSelect(combo) { await combo.locator('xpath=ancestor::div[contains(@class, "ant-select-selector")]').click(); }
async function snap(name) { await page.screenshot({ path: join(output, name + '.png'), animations: 'disabled' }); }
try {
  await page.route('**/api/**', route => {
    if (!new URL(route.request().url()).pathname.startsWith('/api/')) return route.continue();
    apiRequests.push(route.request().url());
    return route.fulfill({ status: 500, json: { error: 'Shared control fixture forbids business APIs' } });
  });
  await page.route('**/__antd-controls-fixture', route => route.fulfill({ contentType: 'text/html', body: '<html lang="zh-CN"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>共享控件验收</title></head><body><main id="fixture"></main></body></html>' }));
  await page.goto(base + '/__antd-controls-fixture');
  await page.evaluate(async () => {
    const refresh = await import('/@react-refresh'); refresh.default.injectIntoGlobalHook(window); window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => type => type; window.__vite_plugin_react_preamble_installed__ = true;
    const React = (await import('/node_modules/.vite/deps/react.js')).default;
    const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
    const { StyledSelect } = await import('/src/components/ui/StyledSelect.tsx');
    const { FeedbackDialog, FeedbackConfirmDialog } = await import('/src/components/feedback/FeedbackDialog.tsx');
    const { PlatformTheme } = await import('/src/components/ui/PlatformTheme.tsx');
    for (const path of ['/src/styles.css', '/src/feedback.css', '/src/features/rd/rd.css']) await import(path);
    const h = React.createElement;
    const options = [{ value: 'alpha', label: '资料受理' }, { value: 'locked', label: '已停用能力', disabled: true }, { value: 'beta', label: '成果复核', title: '已发布的成果复核能力' }];
    function App() {
      const [value, setValue] = React.useState('alpha'), [disabled, setDisabled] = React.useState(false), [grouped, setGrouped] = React.useState(false), [many, setMany] = React.useState(false);
      const [open, setOpen] = React.useState(false), [confirm, setConfirm] = React.useState(false), [pending, setPending] = React.useState(false);
      const [native, setNative] = React.useState(false), [nativeConfirm, setNativeConfirm] = React.useState(false);
      const host = React.useRef(null);
      React.useEffect(() => { if (native) host.current.showModal(); }, [native]);
      window.sharedControls = { value, setValue, setDisabled, setGrouped, setMany, setPending, setOpen };
      const select = label => h(StyledSelect, { id: label === '业务能力' ? 'capability' : undefined, name: 'capability', 'aria-label': label, 'aria-describedby': 'select-help', required: true, invalid: value === 'unknown', value, disabled, onChange: setValue, options: many ? Array.from({ length: 45 }, (_, i) => ({ value: 'item-' + i, label: '固定能力 ' + (i + 1) })) : grouped ? [{ label: '已发布能力', options }] : options });
      return h('div', { className: 'rd-shell', style: { display: 'block', padding: '24px', minHeight: '100vh' } },
        h('h1', null, '共享控件验收'), h('p', { id: 'select-help' }, '隔离测试，不修改业务数据。'),
        h('form', { id: 'select-form', style: { maxWidth: 480 } }, select('业务能力')),
        h('div', { style: { display: 'flex', gap: 16, marginTop: 24 } },
          h('button', { id: 'open-parent', className: 'rd-button', onClick: () => setOpen(true) }, '打开资料弹窗'),
          h('button', { id: 'open-native', className: 'rd-button', onClick: () => setNative(true) }, '打开现有设置弹窗')),
        open && h(FeedbackDialog, { title: '资料设置', onCancel: () => setOpen(false) },
          h('label', null, '草稿名称', h('input', { defaultValue: '尚未提交资料' })), select('弹窗业务能力'),
          h('button', { id: 'open-child', className: 'feedback-button', onClick: () => setConfirm(true) }, '关闭并确认'),
          h('div', null, ...Array.from({ length: 24 }, (_, i) => h('p', { key: i, style: { padding: '14px 0', borderBottom: '1px solid #e4e8ef' } }, `资料条目 ${i + 1} · 已登记内容，滚动后可继续查看。`))), h('p', { id: 'dialog-last' }, '资料最后一项'),
          confirm && h(FeedbackConfirmDialog, { title: '确认放弃草稿', confirm: '放弃草稿', danger: true, pending, error: '示例错误，取消后仍保留草稿。', onCancel: () => setConfirm(false), onConfirm: () => { setConfirm(false); setOpen(false); } }, '关闭后将放弃本次修改。')),
        native && h('dialog', { ref: host, style: { width: 'min(650px,calc(100vw - 32px))', padding: 24, margin: 'auto' }, onCancel: event => { event.preventDefault(); setNative(false); } },
          h('h2', null, '现有设置'), select('现有设置业务能力'),
          h('button', { className: 'feedback-button', onClick: () => setNativeConfirm(true) }, '设置内确认'),
          nativeConfirm && h(FeedbackConfirmDialog, { title: '设置内确认', confirm: '确认设置', onCancel: () => setNativeConfirm(false), onConfirm: () => setNativeConfirm(false) }, '原生设置窗口中的确认')));
    }
    createRoot(document.getElementById('fixture')).render(h(React.StrictMode, null, h(PlatformTheme, null, h(App))));
  });
  const select = page.getByRole('combobox', { name: '业务能力', exact: true });
  await select.waitFor();
  assert.equal(await page.locator('#select-form select').count(), 0, 'no hidden native select drives the control');
  assert.equal(await select.getAttribute('aria-required'), 'true');
  assert.equal(await select.getAttribute('aria-describedby'), 'select-help');
  await select.focus(); await page.keyboard.press('ArrowDown');
  await page.getByRole('listbox').waitFor();
  await page.waitForFunction(() => document.getElementById(document.querySelector('#capability')?.getAttribute('aria-activedescendant') || '')?.textContent?.includes('资料受理'));
  await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter');
  await page.waitForFunction(() => window.sharedControls.value === 'beta');
  assert.equal(await page.evaluate(() => new FormData(document.querySelector('#select-form')).get('capability')), 'beta');
  await clickSelect(select); await page.getByRole('option', { name: '资料受理', exact: true }).click();
  await page.waitForFunction(() => window.sharedControls.value === 'alpha');
  await page.evaluate(() => window.sharedControls.setDisabled(true));
  await page.waitForFunction(() => document.querySelector('#capability')?.disabled);
  assert(await select.isDisabled());
  await page.evaluate(() => { window.sharedControls.setDisabled(false); window.sharedControls.setGrouped(true); });
  await clickSelect(select); await page.getByText('已发布能力', { exact: true }).waitFor();
  assert.equal(await page.getByRole('option', { name: '已停用能力', exact: true }).getAttribute('aria-disabled'), 'true');
  await page.getByRole('option', { name: '成果复核', exact: true }).click();
  await page.evaluate(() => window.sharedControls.setValue('unknown'));
  await page.waitForFunction(() => document.querySelector('#capability')?.getAttribute('aria-invalid') === 'true');
  assert.match(await page.locator('#select-form').innerText(), /unknown/, 'unknown fixed values remain visible until explicitly changed');
  await page.evaluate(() => window.sharedControls.setMany(true));
  await clickSelect(select);
  await page.getByRole('option', { name: '固定能力 43', exact: true }).click();
  await page.waitForFunction(() => window.sharedControls.value === 'item-42');
  await page.evaluate(() => { window.sharedControls.setMany(false); window.sharedControls.setValue('alpha'); });
  checks.push('真实 Select：键盘跳过禁用项、选择、分组、必填与错误语义、未知值、表单值、长选项滚动');
  await snap('01-select');

  await page.locator('#open-parent').click();
  const parent = page.getByRole('dialog', { name: '资料设置', exact: true });
  await parent.waitFor();
  await page.waitForFunction(() => document.activeElement?.closest('[role="dialog"]')?.getAttribute('aria-labelledby'));
  await parent.getByLabel('草稿名称').fill('保持未保存输入');
  await parent.getByRole('heading', { name: '资料设置', exact: true }).click({ trial: true });
  const box = await parent.boundingBox();
  await page.mouse.click(box.x + 15, box.y + 15);
  assert(await parent.isVisible(), 'dialog interior whitespace does not dismiss');
  await page.mouse.move(box.x + 15, box.y + 15); await page.mouse.down(); await page.mouse.move(box.x / 2, box.y + 40); await page.mouse.up();
  assert(await parent.isVisible(), 'inside-to-mask drag does not dismiss');
  await outside(parent, 'right');
  assert(await parent.isVisible(), 'right click does not dismiss');
  const modalSelect = parent.getByRole('combobox', { name: '弹窗业务能力', exact: true });
  await clickSelect(modalSelect); await page.getByRole('option', { name: '资料受理', exact: true }).waitFor();
  await page.keyboard.press('Escape');
  assert(await parent.isVisible(), 'first Escape closes only the select popup');
  await page.getByRole('listbox').waitFor({ state: 'hidden' });
  await parent.locator('#open-child').click();
  const child = page.getByRole('dialog', { name: '确认放弃草稿', exact: true });
  await child.waitFor();
  for (let i = 0; i < 8; i++) { await page.keyboard.press('Tab'); assert(await child.evaluate(e => e.contains(document.activeElement)), 'Tab remains in the top dialog'); }
  await outside(child); await child.waitFor({ state: 'hidden' });
  assert(await parent.isVisible(), 'nested mask closes only the top dialog');
  assert.equal(await parent.getByLabel('草稿名称').inputValue(), '保持未保存输入');
  await page.waitForFunction(() => document.activeElement?.id === 'open-child');
  await page.keyboard.press('Escape'); await parent.waitFor({ state: 'hidden' });
  await page.waitForFunction(() => document.activeElement?.id === 'open-parent');
  checks.push('真实 Modal：内部空白、拖动和右键不误关；嵌套遮罩、Escape、焦点锁定及回退');

  await page.locator('#open-parent').click(); await parent.waitFor(); await parent.locator('#open-child').click(); await child.waitFor();
  await page.evaluate(() => window.sharedControls.setPending(true));
  await child.getByRole('button', { name: '正在处理…', exact: true }).waitFor();
  assert(await child.getByRole('button', { name: '取消', exact: true }).isDisabled());
  await outside(child); await page.keyboard.press('Escape'); assert(await child.isVisible(), 'pending confirmation does not dismiss');
  await page.evaluate(() => window.sharedControls.setPending(false));
  await child.getByRole('alert').waitFor();
  await child.getByRole('button', { name: '取消', exact: true }).click(); await child.waitFor({ state: 'hidden' });
  await clickSelect(parent.getByRole('combobox', { name: '弹窗业务能力', exact: true }));
  await page.getByRole('option', { name: '成果复核', exact: true }).click();
  assert(await parent.isVisible());
  await parent.locator('#dialog-last').scrollIntoViewIfNeeded();
  await snap('02-modal-scroll');
  await page.keyboard.press('Escape'); await parent.waitFor({ state: 'hidden' });
  checks.push('忙碌确认不能误关闭；错误保留；弹窗内选择、内容滚动');

  await page.locator('#open-native').click();
  const native = page.locator('dialog[open]');
  await native.waitFor(); await clickSelect(native.getByRole('combobox', { name: '现有设置业务能力', exact: true }));
  await page.getByRole('option', { name: '资料受理', exact: true }).click();
  await native.getByRole('button', { name: '设置内确认', exact: true }).click();
  const nativeChild = page.getByRole('dialog', { name: '设置内确认', exact: true });
  await nativeChild.waitFor();
  await nativeChild.getByRole('button', { name: '取消', exact: true }).click(); await nativeChild.waitFor({ state: 'hidden' });
  assert(await native.isVisible(), 'native parent remains visible');
  await page.keyboard.press('Escape'); await native.waitFor({ state: 'hidden' });
  checks.push('现有原生设置窗口中的 Select 和嵌套 Modal 可见、可点击');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#open-parent').click(); await parent.waitFor();
  await clickSelect(parent.getByRole('combobox', { name: '弹窗业务能力', exact: true }));
  const popup = page.getByRole('listbox'); await popup.waitFor();
  const popupBox = await popup.boundingBox(), parentBox = await parent.boundingBox();
  assert(popupBox.x >= 0 && popupBox.x + popupBox.width <= 390, 'dropdown stays within 390px');
  assert(parentBox.x >= 0 && parentBox.x + parentBox.width <= 390, 'modal stays within 390px');
  await page.getByRole('option', { name: '成果复核', exact: true }).click();
  await parent.locator('#dialog-last').scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await snap('03-modal-mobile');
  await outside(parent); await parent.waitFor({ state: 'hidden' });
  checks.push('390px 弹窗、下拉与长内容均可访问且页面无横向溢出');
  assert.deepEqual(apiRequests, []); assert.deepEqual(errors, []);
  await unlink(join(output, 'failure.png')).catch(error => { if (error.code !== 'ENOENT') throw error; });
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ passed: true, checks, apiRequests, errors }, null, 2));
  console.log(JSON.stringify({ passed: true, checks }, null, 2));
} catch (error) {
  await page.screenshot({ path: join(output, 'failure.png') }).catch(() => {});
  console.error(JSON.stringify({ checks, errors, error: String(error) }, null, 2));
  throw error;
} finally { await browser.close(); }
