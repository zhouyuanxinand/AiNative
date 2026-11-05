/** Direct manipulation acceptance against the real canvas, with isolated React state.
 * All API requests are blocked; no production projects/templates are written.
 */
import assert from 'node:assert/strict';
import { mkdir, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'file:///C:/Users/周园鑫/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR || 'docs/rd-platform/verification/screenshots/2026-11-03-workflow-templates/direct-canvas';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const checks = [], failures = [], errors = [], apiRequests = [];
const initial = { nodes: [
  { id: 'input', title: '资料受理', role: '研发工程师', required: true, deliverables: ['受理记录'], position: { x: 40, y: 40 } },
  { id: 'custom', title: '资料一致性检查', role: '质量工程师', deliverables: ['检查记录'], position: { x: 340, y: 40 } },
  { id: 'selection_decision', title: '选型决定', role: '项目负责人', gate: 'selection', required: true, deliverables: ['选型记录'], position: { x: 640, y: 40 } },
  { id: 'extra', title: '补充资料复核', role: '研发工程师', deliverables: [], position: { x: 340, y: 240 } },
  { id: 'far', title: '远端节点', role: '研发工程师', deliverables: [], position: { x: 1350, y: 700 } },
], edges: [{ id: 'first', source: 'input', target: 'custom' }, { id: 'last', source: 'custom', target: 'selection_decision' }] };
async function mount(page, { graph = initial, readOnly = false } = {}) {
  page.setDefaultTimeout(6000);
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => Object.defineProperty(window.crypto, 'randomUUID', { value: undefined, configurable: true }));
  await page.route('**/api/**', route => {
    if (!new URL(route.request().url()).pathname.startsWith('/api/')) return route.continue();
    apiRequests.push({ url: route.request().url(), method: route.request().method() });
    return route.fulfill({ status: 500, json: { error: 'Direct canvas fixture blocks production APIs' } });
  });
  await page.route('**/__direct-canvas-fixture', route => route.fulfill({ contentType: 'text/html', body: '<html lang="zh-CN"><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>直接画布交互验收</title></head><body><div id="fixture"></div></body></html>' }));
  await page.goto(base + '/__direct-canvas-fixture');
  await page.evaluate(async ({ graph, initialReadOnly }) => {
    const refresh = await import('/@react-refresh'); refresh.default.injectIntoGlobalHook(window); window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => type => type; window.__vite_plugin_react_preamble_installed__ = true;
    const React = (await import('/node_modules/.vite/deps/react.js')).default;
    const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
    const { FlowGraphEditor } = await import('/src/features/rd/FlowGraphEditor.tsx');
    const { draftReducer } = await import('/src/features/rd/flowDraftReducer.ts');
    const { PlatformTheme } = await import('/src/components/ui/PlatformTheme.tsx');
    for (const file of ['/src/styles.css', '/src/features/rd/rd.css', '/src/features/rd/rdApplicationShell.css']) await import(file);
    function App() {
      const [state, dispatch] = React.useReducer(draftReducer, { graph, operations: [], past: [], future: [] });
      const [readOnly, setReadOnly] = React.useState(initialReadOnly), [disabled, setDisabled] = React.useState(false), [key, setKey] = React.useState(0);
      window.directCanvas = { state, reset(next) { dispatch({ type: 'reset', graph: next }); setKey(value => value + 1); }, replaceGraph(next) { dispatch({ type: 'reset', graph: next }); }, setReadOnly, setDisabled };
      return React.createElement('div', { className: 'rd-shell rd-application-shell', style: { display: 'block' } }, React.createElement('main', { className: 'rd-page-content', style: { padding: '24px' } },
        React.createElement('h1', null, '流程模板 · 直接画布操作'), React.createElement('p', null, '隔离组件验收，不修改真实业务数据'),
        React.createElement('div', { className: 'rd-designer-toolbar' }, React.createElement('button', { className: 'rd-button', disabled: !state.past.length, onClick: () => dispatch({ type: 'undo' }) }, '撤销'), React.createElement('button', { className: 'rd-button', disabled: !state.future.length, onClick: () => dispatch({ type: 'redo' }) }, '重做')),
        React.createElement(FlowGraphEditor, { key, graph: state.graph, choices: [{ id: 'consistency-team', version: 1, title: '资料一致性检查', kind: 'resource' }], business: true, businessCategory: 'selection', readOnly, disabled, onChange: operations => dispatch({ type: 'apply', operations }) })));
    }
    createRoot(document.getElementById('fixture')).render(React.createElement(PlatformTheme, null, React.createElement(App)));
  }, { graph, initialReadOnly: readOnly });
  await page.locator('.rd-graph-node').first().waitFor();
  await page.evaluate(() => document.fonts.ready);
}
const graph = page => page.evaluate(() => window.directCanvas.state.graph);
const node = (page, id) => page.locator(`.rd-graph-node[data-flow-node="${id}"]`);
const toolbar = page => page.getByRole('toolbar', { name: '节点操作', exact: true });
const inspector = page => page.getByRole('region', { name: '节点属性', exact: true });
const snap = (page, name) => page.screenshot({ path: join(output, name + '.png'), animations: 'disabled' });
const reset = async (page, value) => { await page.evaluate(next => window.directCanvas.reset(next), value); await page.waitForFunction(value => JSON.stringify(window.directCanvas.state.graph) === JSON.stringify(value), value); };
const drag = async (page, element, dx, dy, beforeRelease) => { await element.scrollIntoViewIfNeeded(); const box = await element.boundingBox(); const p = { x: box.x + box.width / 2, y: box.y + box.height / 2 }; await page.mouse.move(p.x, p.y); await page.mouse.down(); await page.mouse.move(p.x + dx, p.y + dy, { steps: 8 }); if (beforeRelease) await beforeRelease(); await page.mouse.up(); };
async function clickEdge(page, label) {
  const edge = page.getByRole('button', { name: label, exact: true });
  // Use a real stroke point rather than its rectangular bounding box (L-shaped edges).
  const p = await edge.evaluate(el => { const point = el.getPointAtLength(el.getTotalLength() * .5); const value = new DOMPoint(point.x, point.y).matrixTransform(el.getScreenCTM()); return { x: value.x, y: value.y }; });
  await page.mouse.click(p.x, p.y);
  assert.equal(await edge.getAttribute('aria-pressed'), 'true');
}
function arrowIntoTarget(d, rect) {
  const values = [...d.matchAll(/[ML](-?[\d.]+),(-?[\d.]+)/g)].map(m => ({ x: Number(m[1]), y: Number(m[2]) }));
  const end = values.at(-1), prev = values.at(-2), near = (a, b) => Math.abs(a - b) < 1;
  assert(end && prev && (end.x === prev.x || end.y === prev.y), 'orthogonal final segment');
  if (near(end.x, rect.x) && end.y > rect.y && end.y < rect.y + 108) { assert(prev.x < end.x, 'left edge points inward'); return 'left'; }
  if (near(end.x, rect.x + 210) && end.y > rect.y && end.y < rect.y + 108) { assert(prev.x > end.x, 'right edge points inward'); return 'right'; }
  if (near(end.y, rect.y) && end.x > rect.x && end.x < rect.x + 210) { assert(prev.y < end.y, 'top edge points inward'); return 'top'; }
  if (near(end.y, rect.y + 108) && end.x > rect.x && end.x < rect.x + 210) { assert(prev.y > end.y, 'bottom edge points inward'); return 'bottom'; }
  assert.fail('arrow tip must terminate on target border: ' + d);
}
async function allNodesVisible(page) {
  await page.waitForFunction(() => {
    const canvas = document.querySelector('.rd-graph-scroll');
    if (!canvas) return false;
    const box = canvas.getBoundingClientRect(), left = box.left + canvas.clientLeft, top = box.top + canvas.clientTop;
    return [...canvas.querySelectorAll('.rd-graph-node')].every(node => { const r = node.getBoundingClientRect(); return r.width > 0 && r.left >= left - 1 && r.top >= top - 1 && r.right <= left + canvas.clientWidth + 1 && r.bottom <= top + canvas.clientHeight + 1; });
  });
}
const scale = page => page.locator('.rd-graph-plane').evaluate(el => new DOMMatrixReadOnly(getComputedStyle(el).transform).a);
async function check(name, action, fixture) {
  if (process.env.TEST_CASE && !name.includes(process.env.TEST_CASE)) return;
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try { await mount(page, fixture); await action(page); checks.push(name); console.log('PASS', name); }
  catch (error) { failures.push({ name, message: error.message }); await snap(page, 'failure-' + failures.length); await writeFile(join(output, 'failure-' + failures.length + '.json'), JSON.stringify({ name, message: error.message, graph: await graph(page), text: await page.locator('body').innerText() }, null, 2)); console.error('FAIL', name, error.message); }
  finally { await page.close(); }
}
try {
  await check('readonly fixed view-node control remains at the stage corner across selection zoom scroll pan and mobile', async page => {
    const view = page.getByRole('button', { name: '查看节点', exact: true });
    const canvas = page.getByLabel('流程节点画布', { exact: true });
    const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    async function fixedCorner() {
      assert.equal(await view.count(), 1, 'readonly has exactly one persistent view-node button');
      const bounds = await toolbar(page).evaluate(element => {
        const tool = element.getBoundingClientRect(), stage = element.closest('.rd-canvas-stage').getBoundingClientRect();
        return { x: tool.left - stage.left, y: tool.top - stage.top, right: tool.right, viewport: innerWidth };
      });
      assert(Math.abs(bounds.x - 12) < 1 && Math.abs(bounds.y - 12) < 1, `view toolbar stays 12px from stage top-left, got ${bounds.x},${bounds.y}`);
      assert(bounds.right <= bounds.viewport + 1, 'view toolbar remains within the viewport');
    }
    const unchanged = await graph(page);
    await allNodesVisible(page); await fixedCorner();
    for (const id of ['custom', 'extra']) {
      await node(page, id).click(); await fixedCorner();
      assert.equal(await view.isEnabled(), true); assert.equal(await view.getAttribute('aria-expanded'), 'false');
      await view.click(); await inspector(page).waitFor();
      assert.equal(await inspector(page).getByLabel('节点标题', { exact: true }).inputValue(), initial.nodes.find(item => item.id === id).title, 'view opens the currently selected node');
      assert.equal(await inspector(page).getByLabel('节点标题', { exact: true }).isDisabled(), true);
      assert.equal(await view.getAttribute('aria-expanded'), 'true'); await fixedCorner();
      await page.getByRole('button', { name: '关闭节点属性', exact: true }).click();
      assert.equal(await view.getAttribute('aria-expanded'), 'false');
    }
    const originalScale = await scale(page);
    for (let index = 0; index < 4; index++) await page.getByRole('button', { name: '放大画布', exact: true }).click();
    await settle(); assert(await scale(page) > originalScale); await fixedCorner();
    await canvas.evaluate(element => element.scrollTo(120, 100)); await settle();
    assert(await canvas.evaluate(element => element.scrollLeft > 0 && element.scrollTop > 0), 'exercise horizontal and vertical canvas scrolling');
    await fixedCorner();
    const start = await canvas.evaluate(element => {
      const box = element.getBoundingClientRect();
      for (const offset of [60, 110, 160]) {
        const x = box.right - offset, y = box.bottom - 70;
        if (!document.elementFromPoint(x, y)?.closest('button,[role="button"]')) return { x, y, left: element.scrollLeft, top: element.scrollTop };
      }
      return null;
    });
    assert(start, 'fixture supplies a blank canvas point for real pointer panning');
    await page.mouse.move(start.x, start.y); await page.mouse.down(); await page.mouse.move(start.x - 45, start.y - 35, { steps: 5 });
    await fixedCorner(); await page.mouse.up(); await settle();
    assert(await canvas.evaluate((element, before) => element.scrollLeft > before.left && element.scrollTop > before.top, start), 'pointer panning changes the viewport');
    await fixedCorner();
    await page.getByRole('button', { name: '适应', exact: true }).click(); await allNodesVisible(page);
    await clickEdge(page, '选择连线 资料受理 → 资料一致性检查');
    assert.equal(await view.isDisabled(), true, 'selecting an edge disables node inspection without removing its fixed button'); await fixedCorner();
    await node(page, 'input').click(); assert.equal(await view.isEnabled(), true);
    await page.setViewportSize({ width: 390, height: 760 }); await allNodesVisible(page); await fixedCorner();
    assert.equal(await view.isVisible(), true); await view.click(); await inspector(page).waitFor();
    assert.equal(await inspector(page).getByLabel('节点标题', { exact: true }).inputValue(), '资料受理');
    await page.getByRole('button', { name: '关闭节点属性', exact: true }).click(); await snap(page, '12-readonly-fixed-view-mobile');
    assert.deepEqual(await graph(page), unchanged, 'readonly inspection and viewport manipulation never change the graph');
    await reset(page, { nodes: [], edges: [] }); await fixedCorner();
    assert.equal(await view.isDisabled(), true, 'an empty graph keeps the fixed inspection control disabled');
  }, { readOnly: true });
  await check('direct node selection, protected delete, add, edit, copy, delete and undo', async page => {
    assert.equal(await page.getByText('查找节点与连线（辅助）', { exact: true }).count(), 0);
    assert.equal(await inspector(page).count(), 0, 'properties do not occupy permanent sidebar');
    await node(page, 'input').click(); assert.equal(await toolbar(page).getByRole('button', { name: '删除节点', exact: true }).isDisabled(), true);
    const original = await graph(page); await node(page, 'input').focus(); await page.keyboard.press('Delete'); assert.deepEqual(await graph(page), original);
    await toolbar(page).getByRole('button', { name: '在画布新增节点', exact: true }).click();
    await page.getByRole('region', { name: '新增画布节点', exact: true }).getByRole('button', { name: '添加节点', exact: true }).click();
    await inspector(page).waitFor(); await inspector(page).getByLabel('节点标题', { exact: true }).fill('检查设计输入');
    await inspector(page).getByLabel('负责角色', { exact: true }).fill('产品工程师');
    await inspector(page).getByLabel('交付物（每行一项）', { exact: true }).fill('检查记录\n输入清单');
    const added = (await graph(page)).nodes.find(n => n.title === '检查设计输入'); assert(added); assert.match(added.id, /^n-rd-/);
    assert.deepEqual(added.deliverables, ['检查记录', '输入清单']);
    await snap(page, '01-direct-add-and-properties');
    await page.getByRole('button', { name: '关闭节点属性', exact: true }).click();
    await toolbar(page).getByRole('button', { name: '复制节点', exact: true }).click();
    const copy = (await graph(page)).nodes.find(n => n.title === '检查设计输入（副本）'); assert(copy && copy.id !== added.id);
    assert.equal(Object.hasOwn(copy, 'required'), false, 'business copies must omit unsupported required metadata');
    const beforeDelete = await graph(page); await toolbar(page).getByRole('button', { name: '删除节点', exact: true }).click();
    assert(!(await graph(page)).nodes.some(n => n.id === copy.id));
    assert(!(await graph(page)).edges.some(e => e.source === copy.id || e.target === copy.id));
    await page.getByRole('button', { name: '撤销', exact: true }).click(); assert.deepEqual(await graph(page), beforeDelete);
    await node(page, 'selection_decision').click(); await toolbar(page).getByRole('button', { name: '复制节点', exact: true }).click();
    const gateCopy = (await graph(page)).nodes.find(n => n.title === '选型决定（副本）'); assert(gateCopy && !gateCopy.gate && !gateCopy.required);
    assert.equal(Object.hasOwn(gateCopy, 'required'), false, 'copying a required business gate removes the field, not just its value');
    assert.equal(await toolbar(page).getByRole('button', { name: '删除节点', exact: true }).isEnabled(), true);
    await toolbar(page).getByRole('button', { name: '删除节点', exact: true }).click();
  });
  await check('port drag and click connect, stroke selection, delete undo, cycle and Escape cancellation', async page => {
    const before = await graph(page);
    const from = await page.getByRole('button', { name: '从资料一致性检查连线', exact: true }).boundingBox(); const to = await node(page, 'extra').boundingBox();
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2); await page.mouse.down(); await page.mouse.move(to.x + 80, to.y + 45, { steps: 8 });
    assert.equal(await page.locator('.rd-canvas-link-preview').count(), 1);
    await page.mouse.up(); assert((await graph(page)).edges.some(e => e.source === 'custom' && e.target === 'extra'));
    assert.deepEqual((await graph(page)).nodes, before.nodes, 'connecting never moves nodes');
    await clickEdge(page, '选择连线 资料一致性检查 → 补充资料复核');
    await snap(page, '02-select-and-delete-dependency');
    const linked = await graph(page); await page.getByRole('button', { name: '删除连线', exact: true }).click();
    assert.equal((await graph(page)).edges.length, 2); await page.getByRole('button', { name: '撤销', exact: true }).click(); assert.deepEqual(await graph(page), linked);
    await page.getByRole('button', { name: '从补充资料复核连线', exact: true }).click(); await node(page, 'selection_decision').click();
    assert((await graph(page)).edges.some(e => e.source === 'extra' && e.target === 'selection_decision'));
    const connected = await graph(page); await page.getByRole('button', { name: '从选型决定连线', exact: true }).click(); await node(page, 'input').click();
    await page.getByText('这条连线会形成循环。请调整先后关系后再连接。', { exact: true }).waitFor(); assert.deepEqual(await graph(page), connected); await page.keyboard.press('Escape');
    await page.getByRole('button', { name: '从资料受理连线', exact: true }).click(); await page.keyboard.press('Escape'); await node(page, 'extra').click(); assert.deepEqual(await graph(page), connected);
  });
  await check('moving nodes reroutes arrows into target on all four sides, including drag preview', async page => {
    const source = { id: 'a', title: '起点', position: { x: 350, y: 200 } }, target = { id: 'b', title: '终点', position: { x: 650, y: 200 } };
    const two = { nodes: [source, target], edges: [{ id: 'ab', source: 'a', target: 'b' }] };
    const destinations = [{ x: 700, y: 200, side: 'left' }, { x: 30, y: 200, side: 'right' }, { x: 350, y: 20, side: 'bottom' }, { x: 350, y: 350, side: 'top' }];
    for (const destination of destinations) {
      await reset(page, two);
      await drag(page, node(page, 'b'), destination.x - target.position.x, destination.y - target.position.y, async () => {
        const moving = await node(page, 'b').evaluate(el => ({ x: parseFloat(el.style.left), y: parseFloat(el.style.top) }));
        assert.deepEqual(moving, { x: destination.x, y: destination.y });
        const path = await page.locator('.rd-canvas-edge').getAttribute('d'); assert.equal(arrowIntoTarget(path, moving), destination.side);
        assert.deepEqual((await graph(page)).nodes[1].position, target.position, 'preview does not write a revision');
      });
      assert.deepEqual((await graph(page)).nodes[1].position, { x: destination.x, y: destination.y });
      assert.equal(await page.evaluate(() => window.directCanvas.state.past.length), 1, 'one drag is one undo entry');
      assert.equal(arrowIntoTarget(await page.locator('.rd-canvas-edge').getAttribute('d'), destination), destination.side);
      if (destination.side === 'bottom') await snap(page, '03-upward-arrow-after-node-move');
    }
  });
  await check('zoom and existing scroll preserve drag distance and connection targets; Escape cancels', async page => {
    await page.setViewportSize({ width: 1000, height: 900 });
    const moved = structuredClone(initial); moved.nodes.find(n => n.id === 'custom').position = { x: 900, y: 500 }; moved.nodes.find(n => n.id === 'extra').position = { x: 1180, y: 500 };
    await reset(page, moved); await page.getByRole('button', { name: '缩小画布', exact: true }).click();
    // Zoom restores the viewport center on the next frame; set the scroll fixture after it settles.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const canvas = page.getByLabel('流程节点画布', { exact: true }); await canvas.evaluate(el => el.scrollTo(380, 320));
    assert(await canvas.evaluate(el => el.scrollLeft > 0 && el.scrollTop > 0), 'exercise both existing scroll offsets');
    const before = (await graph(page)).nodes.find(n => n.id === 'custom').position;
    await drag(page, node(page, 'custom'), 51, 34); const after = (await graph(page)).nodes.find(n => n.id === 'custom').position;
    assert(Math.abs(after.x - before.x - 60) <= 1 && Math.abs(after.y - before.y - 40) <= 1);
    await drag(page, node(page, 'custom'), -34, 34, () => page.keyboard.press('Escape')); assert.deepEqual((await graph(page)).nodes.find(n => n.id === 'custom').position, after);
    const from = await page.getByRole('button', { name: '从资料一致性检查连线', exact: true }).boundingBox(), to = await node(page, 'extra').boundingBox();
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2); await page.mouse.down(); await page.mouse.move(to.x + 50, to.y + 30, { steps: 8 }); await page.mouse.up();
    assert((await graph(page)).edges.some(e => e.source === 'custom' && e.target === 'extra'));
    await snap(page, '04-scrolled-zoomed-canvas');
  });
  await check('readonly and disabled protect direct icons, keyboard and properties', async page => {
    await node(page, 'custom').dblclick(); await inspector(page).waitFor();
    await page.evaluate(() => window.directCanvas.setReadOnly(true));
    assert.equal(await inspector(page).getByLabel('节点标题', { exact: true }).isDisabled(), true);
    await page.getByRole('button', { name: '关闭节点属性', exact: true }).click();
    const before = await graph(page); await node(page, 'custom').focus(); await page.keyboard.press('Delete'); await page.keyboard.press('Alt+ArrowRight'); await drag(page, node(page, 'custom'), 40, 20); assert.deepEqual(await graph(page), before);
    assert.equal(await page.getByRole('button', { name: '新增节点', exact: true }).count(), 0); assert.equal(await page.locator('.rd-canvas-port').count(), 0);
    await page.evaluate(() => { window.directCanvas.setReadOnly(false); window.directCanvas.setDisabled(true); }); await node(page, 'custom').click();
    assert.equal(await toolbar(page).getByRole('button', { name: '复制节点', exact: true }).isDisabled(), true); assert.equal(await toolbar(page).getByRole('button', { name: '删除节点', exact: true }).isDisabled(), true);
    await node(page, 'custom').focus(); await page.keyboard.press('Delete'); await page.keyboard.press('Alt+ArrowRight'); assert.deepEqual(await graph(page), before);
    await snap(page, '05-disabled-canvas-protection');
  });
  await check('390px direct toolbar and scrollable properties stay inside the viewport', async page => {
    await page.setViewportSize({ width: 390, height: 760 }); await page.getByRole('button', { name: '适应', exact: true }).click();
    const port = await page.getByRole('button', { name: '从资料一致性检查连线', exact: true }).boundingBox(); assert(port.width >= 19 && port.height >= 19, 'connection handles remain usable at fit zoom');
    await node(page, 'custom').click();
    const tools = await toolbar(page).boundingBox(); assert(tools.x >= 0 && tools.x + tools.width <= 391);
    await toolbar(page).getByRole('button', { name: '编辑节点', exact: true }).click();
    const panel = await inspector(page).boundingBox(); assert(panel.x >= 0 && panel.x + panel.width <= 391);
    assert(await inspector(page).evaluate(el => el.scrollHeight > el.clientHeight));
    await inspector(page).getByLabel('节点标题', { exact: true }).fill('窄屏编辑节点');
    assert((await graph(page)).nodes.some(n => n.title === '窄屏编辑节点'));
    await snap(page, '06-narrow-canvas-properties');
    await page.keyboard.press('Escape'); assert.equal(await inspector(page).count(), 0);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  });
  const wide = { nodes: Array.from({ length: 7 }, (_, index) => ({ id: `wide-${index}`, title: `固定流程阶段 ${index + 1}`, role: '研发工程师', position: { x: 24 + index * 470, y: 40 }, deliverables: [] })), edges: Array.from({ length: 6 }, (_, index) => ({ id: `wide-edge-${index}`, source: `wide-${index}`, target: `wide-${index + 1}` })) };
  await check('readonly fits every node initially, on resize and fixed-graph change while manual zoom persists', async page => {
    const unchanged = structuredClone(wide);
    await allNodesVisible(page);
    assert.deepEqual(await graph(page), unchanged, 'initial fit does not rewrite saved positions');
    assert.equal(await page.evaluate(() => window.directCanvas.state.past.length), 0);
    await snap(page, '07-readonly-all-seven-nodes-desktop');
    const fitScale = await scale(page);
    await page.getByRole('button', { name: '放大画布', exact: true }).click();
    await page.waitForFunction(prior => new DOMMatrixReadOnly(getComputedStyle(document.querySelector('.rd-graph-plane')).transform).a > prior, fitScale);
    const userScale = await scale(page);
    const canvas = page.getByLabel('流程节点画布', { exact: true });
    await canvas.evaluate(el => el.scrollTo(120, 0));
    await page.waitForFunction(() => document.querySelector('.rd-graph-scroll').scrollLeft > 0);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await scale(page), userScale, 'scroll/ResizeObserver must not undo manual zoom');
    assert.deepEqual(await graph(page), unchanged);
    await page.setViewportSize({ width: 390, height: 760 });
    await allNodesVisible(page);
    assert((await scale(page)) < .25, 'a narrow readonly canvas can fit below the editing minimum zoom');
    await snap(page, '08-readonly-all-seven-nodes-narrow');
    const tall = structuredClone(wide); tall.nodes.forEach((node, index) => { node.position = { x: 24 + index % 2 * 500, y: 40 + index * 280 }; });
    await page.evaluate(next => window.directCanvas.replaceGraph(next), tall);
    await page.waitForFunction(() => window.directCanvas.state.graph.nodes[6].position.y === 1720);
    await allNodesVisible(page);
    assert.deepEqual(await graph(page), tall, 'changing a fixed graph refits without mutating coordinates');
    await snap(page, '09-readonly-replacement-fixed-graph');
    await page.evaluate(() => window.directCanvas.setReadOnly(false));
    await page.waitForFunction(() => new DOMMatrixReadOnly(getComputedStyle(document.querySelector('.rd-graph-plane')).transform).a === 1);
    assert.deepEqual(await graph(page), tall, 'editing restores 100% view, not different saved positions');
  }, { graph: wide, readOnly: true });
  const single = { nodes: [{ id: 'offset-single', title: '单项资料一致性检查', role: '质量工程师', position: { x: 1100, y: 600 }, deliverables: [] }], edges: [] };
  await check('readonly offset single node stays centered at 100% without empty scrollable space', async page => {
    const centered = async () => page.waitForFunction(() => {
      const canvas = document.querySelector('.rd-graph-scroll'), node = canvas?.querySelector('.rd-graph-node');
      if (!canvas || !node) return false;
      const bounds = canvas.getBoundingClientRect(), box = node.getBoundingClientRect();
      return Math.abs(box.left + box.width / 2 - bounds.left - canvas.clientLeft - canvas.clientWidth / 2) < 2 && Math.abs(box.top + box.height / 2 - bounds.top - canvas.clientTop - canvas.clientHeight / 2) < 2;
    });
    await allNodesVisible(page); await centered();
    assert.equal(await scale(page), 1, 'fit uses real content bounds rather than offset or empty canvas minimum');
    const canvas = page.getByLabel('流程节点画布', { exact: true });
    assert(await canvas.evaluate(el => el.scrollWidth <= el.clientWidth + 1 && el.scrollHeight <= el.clientHeight + 1), 'single-node view has no giant offscreen blank area');
    assert.deepEqual(await graph(page), single);
    assert.equal(await page.evaluate(() => window.directCanvas.state.past.length), 0);
    await snap(page, '10-readonly-offset-single-node-centered');
    await page.setViewportSize({ width: 390, height: 760 }); await allNodesVisible(page); await centered();
    assert.equal(await scale(page), 1, 'single-node narrow view remains readable at 100%');
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    assert(await canvas.evaluate(el => el.scrollWidth <= el.clientWidth + 1 && el.scrollHeight <= el.clientHeight + 1));
    await snap(page, '11-readonly-single-node-narrow');
  }, { graph: single, readOnly: true });
  const receipt = { passed: checks.length > 0 && failures.length === 0 && errors.length === 0 && apiRequests.length === 0, checks, failures, errors, apiRequests, mode: 'isolated real React canvas', actualBusinessWrites: 0 };
  await writeFile(join(output, 'direct-canvas-receipt.json'), JSON.stringify(receipt, null, 2)); console.log(JSON.stringify(receipt)); assert(receipt.passed);
  for (let index = 1; index <= checks.length; index++) for (const extension of ['png', 'json']) await unlink(join(output, `failure-${index}.${extension}`)).catch(error => { if (error.code !== 'ENOENT') throw error; });
} finally { await browser.close(); }
