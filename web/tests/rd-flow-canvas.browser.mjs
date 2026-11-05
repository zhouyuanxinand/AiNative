/** Real shared canvas components with isolated graph state. No production writes. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'file:///C:/Users/周园鑫/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18370';
const output = process.env.SCREENSHOT_DIR;
if (output) await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
// Intranet HTTP origins do not expose the secure-context UUID API.
await page.addInitScript(() => Object.defineProperty(window.crypto, 'randomUUID', { value: undefined, configurable: true }));
page.setDefaultTimeout(8000);
const errors = [], writes = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
page.on('request', request => { if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) writes.push(request.method()); });
await page.route('**/__flow-canvas-fixture', route => route.fulfill({ contentType: 'text/html', body: '<html lang="zh-CN"><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>流程配置画布交互验收</title></head><body><div id="fixture"></div></body></html>' }));
async function choose(root, label, option) { await root.getByRole('button', { name: new RegExp('^' + label) }).click(); await page.getByRole('option', { name: option, exact: true }).click(); }
const snap = async name => { if (output) await page.screenshot({ path: join(output, name) }); };
const graph = () => page.evaluate(() => window.canvasState.graph);
const position = async id => (await graph()).nodes.find(node => node.id === id).position;
try {
  await page.goto(base + '/__flow-canvas-fixture');
  assert.equal(await page.evaluate(() => typeof window.crypto.randomUUID), 'undefined');
  await page.evaluate(async () => {
    const refresh = await import('/@react-refresh'); refresh.default.injectIntoGlobalHook(window); window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => type => type; window.__vite_plugin_react_preamble_installed__ = true;
    const React = (await import('/node_modules/.vite/deps/react.js')).default;
    const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
    const { FlowGraphEditor } = await import('/src/features/rd/FlowGraphEditor.tsx');
    const { TeamConfiguration } = await import('/src/features/rd/TeamConfiguration.tsx');
    const { draftReducer } = await import('/src/features/rd/flowDraftReducer.ts');
    for (const file of ['/src/styles.css', '/src/features/rd/rd.css', '/src/features/rd/rdApplicationShell.css']) await import(file);
    const initial = { nodes: [
      { id: 'input', title: '资料受理', role: '研发工程师', deliverables: ['受理记录'], position: { x: 24, y: 24 } },
      { id: 'custom', title: '资料一致性检查', role: '研发工程师', deliverables: ['检查记录'], action_resource: { resource_id: 'consistency-team', resource_version: 1 }, workpackage_definition_id: 'input_check', position: { x: 294, y: 24 } },
      { id: 'selection_decision', title: '选型决定', role: '项目负责人', gate: 'selection', deliverables: ['选型记录'], position: { x: 564, y: 24 } },
      { id: 'extra', title: '补充资料复核', role: '研发工程师', deliverables: [], position: { x: 1100, y: 600 } },
    ], edges: [{ id: 'first', source: 'input', target: 'custom' }, { id: 'last', source: 'custom', target: 'selection_decision' }] };
    function App() {
      const [state, dispatch] = React.useReducer(draftReducer, { graph: initial, operations: [], past: [], future: [] });
      const [readOnly, setReadOnly] = React.useState(false);
      const [config, setConfig] = React.useState({ members: [{ resource_id: 'consistency', resource_version: 1 }], inputs: [], outputs: [], execution_graph: { nodes: [{ id: 'team-step', title: '内部一致性检查', role: '检查能力', resource_id: 'consistency', resource_version: 1, position: { x: 24, y: 24 } }], edges: [] } });
      window.canvasState = state; window.workspaceConfig = config;
      return React.createElement('div', { className: 'rd-shell rd-application-shell', style: { display: 'block' } }, React.createElement('main', { className: 'rd-page-content', style: { padding: '24px' } },
        React.createElement('section', { 'aria-label': '模板画布测试' }, React.createElement('h1', null, '流程模板配置'), React.createElement('p', null, '独立组件验收 · 不修改项目或模板数据'),
          React.createElement('div', { className: 'rd-designer-toolbar' }, React.createElement('button', { className: 'rd-button', disabled: !state.past.length, onClick: () => dispatch({ type: 'undo' }) }, '撤销'), React.createElement('button', { className: 'rd-button', disabled: !state.future.length, onClick: () => dispatch({ type: 'redo' }) }, '重做'), React.createElement('button', { className: 'rd-button', onClick: () => setReadOnly(value => !value) }, readOnly ? '切换可编辑' : '切换只读')),
          React.createElement(FlowGraphEditor, { graph: state.graph, choices: [{ id: 'consistency-team', version: 1, title: '资料一致性检查', kind: 'resource' }], business: true, businessCategory: 'selection', readOnly, onChange: operations => dispatch({ type: 'apply', operations }) })),
        React.createElement('section', { 'aria-label': '资源内部图测试' }, React.createElement(TeamConfiguration, { configuration: config, onChange: setConfig, resources: [{ id: 'consistency', name: '一致性检查', kind: 'skill', version: 1 }] }))));
    }
    createRoot(document.getElementById('fixture')).render(React.createElement(App));
  });
  const root = page.getByRole('region', { name: '模板画布测试', exact: true });
  const editor = root.locator('.rd-graph-editor');
  await editor.locator('.rd-graph-node').first().waitFor();
  assert.equal(await editor.getByText('查找节点与连线（辅助）', { exact: true }).count(), 0);
  const protectedDelete = editor.getByRole('button', { name: '删除节点', exact: true });
  assert.equal(await protectedDelete.isDisabled(), true);
  assert.equal(await protectedDelete.getAttribute('title'), '必需节点不能删除');
  await editor.getByRole('button', { name: '资料一致性检查，选择节点', exact: true }).dblclick();
  await editor.getByLabel('交付物（每行一项）', { exact: true }).fill('检查结果\n问题清单');
  assert.deepEqual((await graph()).nodes.find(node => node.id === 'custom').deliverables, ['检查结果', '问题清单']);
  await choose(editor, '办理动作', '普通业务办理节点');
  assert.equal('action_resource' in (await graph()).nodes.find(node => node.id === 'custom'), false);
  assert.equal('workpackage_definition_id' in (await graph()).nodes.find(node => node.id === 'custom'), false);
  await root.getByRole('button', { name: '撤销', exact: true }).click();
  assert.equal((await graph()).nodes.find(node => node.id === 'custom').action_resource.resource_id, 'consistency-team');
  await root.getByRole('button', { name: '重做', exact: true }).click();
  checks.push('multiline deliverables and undoable explicit action unbinding');
  const custom = editor.getByRole('button', { name: '资料一致性检查，选择节点', exact: true });
  await editor.getByRole('button', { name: '关闭节点属性', exact: true }).click();
  await custom.scrollIntoViewIfNeeded();
  let box = await custom.boundingBox(), before = await position('custom');
  await page.mouse.move(box.x + 80, box.y + 40); await page.mouse.down(); await page.mouse.move(box.x + 140, box.y + 90, { steps: 5 }); await page.mouse.up();
  assert.deepEqual(await position('custom'), { x: before.x + 60, y: before.y + 50 });
  await root.getByRole('button', { name: '撤销', exact: true }).click(); assert.deepEqual(await position('custom'), before);
  await root.getByRole('button', { name: '重做', exact: true }).click();
  box = await custom.boundingBox(); before = await position('custom');
  await page.mouse.move(box.x + 80, box.y + 40); await page.mouse.down(); await page.mouse.move(box.x + 145, box.y + 100, { steps: 5 }); await page.keyboard.press('Escape'); await page.mouse.up();
  assert.deepEqual(await position('custom'), before);
  await custom.focus(); await page.keyboard.press('Alt+ArrowRight'); assert.equal((await position('custom')).x, before.x + 10);
  checks.push('pointer drag commits once, undo redo, Escape cancels, Alt arrow works');
  await editor.getByRole('button', { name: '缩小画布', exact: true }).click();
  await custom.scrollIntoViewIfNeeded();
  box = await custom.boundingBox(); before = await position('custom');
  await page.mouse.move(box.x + 60, box.y + 30); await page.mouse.down(); await page.mouse.move(box.x + 111, box.y + 64, { steps: 5 }); await page.mouse.up();
  assert(Math.abs((await position('custom')).x - before.x - 60) <= 1);
  assert(Math.abs((await position('custom')).y - before.y - 40) <= 1);
  const viewport = editor.getByLabel('流程节点画布', { exact: true });
  await viewport.evaluate(el => el.scrollTo(0, 0));
  const pane = await viewport.boundingBox();
  await page.mouse.move(pane.x + 180, pane.y + 250); await page.mouse.down(); await page.mouse.move(pane.x + 80, pane.y + 150, { steps: 5 }); await page.mouse.up();
  assert(await viewport.evaluate(el => el.scrollTop > 50));
  await editor.getByRole('button', { name: '适应', exact: true }).click();
  checks.push('zoom-aware dragging, blank canvas pan and fit');
  await editor.getByRole('button', { name: '从补充资料复核连线', exact: true }).click();
  await page.keyboard.press('Escape');
  assert.equal((await graph()).edges.length, 2);
  await editor.getByRole('button', { name: '从补充资料复核连线', exact: true }).click();
  await editor.getByRole('button', { name: '选型决定，选择节点', exact: true }).click();
  assert((await graph()).edges.some(edge => edge.source === 'extra' && edge.target === 'selection_decision'));
  assert.match((await graph()).edges.find(edge => edge.source === 'extra').id, /^e-rd-/);
  await editor.getByRole('button', { name: '从选型决定连线', exact: true }).click();
  await editor.getByRole('button', { name: '资料受理，选择节点', exact: true }).click();
  await editor.getByText('这条连线会形成循环。请调整先后关系后再连接。', { exact: true }).waitFor();
  assert.equal((await graph()).edges.length, 3); await page.keyboard.press('Escape');
  const prior = await graph(); await editor.getByRole('button', { name: '自动排列', exact: true }).click();
  assert.deepEqual((await graph()).edges, prior.edges);
  await root.getByRole('button', { name: '撤销', exact: true }).click(); assert.deepEqual(await graph(), prior);
  await root.getByRole('button', { name: '重做', exact: true }).click();
  checks.push('click-to-connect, Escape cancels connection, cycle rejection, undoable arrangement');
  await editor.getByRole('button', { name: '新增节点', exact: true }).click();
  await editor.getByRole('button', { name: '添加节点', exact: true }).click();
  await editor.getByLabel('节点标题', { exact: true }).fill('新增复核事项');
  await editor.getByRole('button', { name: '关闭节点属性', exact: true }).click();
  await editor.getByRole('button', { name: '复制节点', exact: true }).click();
  await editor.getByRole('button', { name: '编辑节点', exact: true }).click();
  assert.equal(await editor.getByLabel('节点标题', { exact: true }).inputValue(), '新增复核事项（副本）');
  const createdNodes = (await graph()).nodes.filter(node => node.title.startsWith('新增复核事项'));
  assert.equal(createdNodes.length, 2);
  for (const node of createdNodes) assert.match(node.id, /^n-rd-/);
  assert.notEqual(createdNodes[0].id, createdNodes[1].id);
  checks.push('intranet HTTP without crypto.randomUUID supports add, copy and connect with unique prefixed IDs');
  const beforeDelete = await graph();
  await editor.getByRole('button', { name: '关闭节点属性', exact: true }).click();
  await editor.getByRole('button', { name: '删除节点', exact: true }).click(); assert.equal((await graph()).nodes.length, 5);
  await root.getByRole('button', { name: '撤销', exact: true }).click(); assert.deepEqual(await graph(), beforeDelete);
  checks.push('add, rename, copy, remove and restore nodes with incident edges');
  await editor.getByRole('button', { name: '适应', exact: true }).click();
  await editor.getByRole('button', { name: '编辑节点', exact: true }).click();
  await editor.scrollIntoViewIfNeeded(); await snap('01-configuration-canvas-desktop.png');
  assert.equal(await editor.getByLabel('X 坐标', { exact: true }).isVisible(), false);
  await editor.locator('.rd-graph-advanced > summary').click(); assert.equal(await editor.getByLabel('X 坐标', { exact: true }).isVisible(), true);
  await editor.locator('.rd-graph-advanced > summary').click();
  await root.getByRole('button', { name: '切换只读', exact: true }).click();
  const readonly = await graph();
  await custom.focus(); await page.keyboard.press('Alt+ArrowRight'); assert.deepEqual(await graph(), readonly);
  assert.equal(await editor.getByLabel('节点标题', { exact: true }).isDisabled(), true);
  assert.equal(await editor.getByRole('button', { name: '新增节点', exact: true }).count(), 0);
  await root.getByRole('button', { name: '切换可编辑', exact: true }).click();
  checks.push('advanced metadata disclosure and readonly version protections');
  const workspace = page.getByRole('region', { name: '资源内部图测试', exact: true });
  await workspace.getByRole('button', { name: '内部一致性检查，选择节点', exact: true }).dblclick();
  await workspace.getByLabel('节点标题', { exact: true }).fill('共享内部图改名');
  await workspace.getByLabel('交付物（每行一项）', { exact: true }).fill('报告一\n报告二');
  assert.equal(await page.evaluate(() => window.workspaceConfig.execution_graph.nodes[0].title), '共享内部图改名');
  assert.deepEqual(await page.evaluate(() => window.workspaceConfig.execution_graph.nodes[0].deliverables), ['报告一', '报告二']);
  assert.equal((await graph()).nodes[0].title, '资料受理');
  await workspace.scrollIntoViewIfNeeded(); await snap('02-shared-workspace-editor.png');
  checks.push('Workspace shared instance keeps isolated IDs, edits and multiline output');
  await page.setViewportSize({ width: 390, height: 760 });
  await editor.getByRole('button', { name: '关闭节点属性', exact: true }).click();
  await editor.getByRole('button', { name: '适应', exact: true }).click();
  await editor.scrollIntoViewIfNeeded(); await snap('03-canvas-narrow.png');
  assert(await page.locator('.rd-application-shell').evaluate(el => el.scrollWidth <= el.clientWidth + 2));
  await custom.focus(); await page.keyboard.press('Enter');
  await snap('04-node-menu-narrow.png');
  await editor.getByRole('button', { name: '编辑节点', exact: true }).focus(); await page.keyboard.press('Enter');
  assert((await page.evaluate(() => document.activeElement?.textContent)).startsWith('节点属性'));
  await snap('05-node-properties-narrow.png');
  checks.push('390px page bounds, direct node actions and keyboard property navigation');
  assert.deepEqual(errors, []); assert.deepEqual(writes, []);
  const result = { passed: true, componentFixture: true, productionWrites: false, randomUUIDAvailable: false, checks, errors, writes };
  if (output) await writeFile(join(output, 'canvas-receipt.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
} catch(error) { console.log((await page.locator('body').innerText()).slice(0,6000)); throw error; } finally { await browser.close(); }


