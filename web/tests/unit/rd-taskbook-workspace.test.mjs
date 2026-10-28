import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
import { PROCESS_OPTIONS, COVER_PHASE_OPTIONS, nativeParameterIssues } from '../../src/features/taskbook/model/taskbookOptions.ts';
import { displayedNativeRun, nextNativeRunView } from '../../src/features/taskbook/model/nativeRuns.ts';
import { inputPackageMatchesForm } from '../../src/features/taskbook/model/taskbookInputs.ts';
import { taskInputApplicability } from '../../src/features/rd/model/rdTaskApplicability.ts';

const bundled = await build({ entryPoints: ['src/features/taskbook/api/workspace.ts'], bundle: true, platform: 'node', format: 'esm', write: false });
const api = await import(`data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].text).toString('base64')}`);
globalThis.window = globalThis;

test('unrelated new project baselines keep native fixed inputs usable; targeted impacts require source review', () => {
  const taskbook = { id: 'native-parent', kind: 'taskbook', baseline_id: 'adopted-old', status: 'in_progress' };
  const downstream = { id: 'native-child', kind: 'plan_item', source_task_id: 'native-parent', baseline_id: 'adopted-old', status: 'todo' };
  assert.deepEqual(taskInputApplicability(downstream, 'unrelated-new'), { native: true, current: true, reviewTaskId: 'native-parent' });
  assert.equal(taskInputApplicability(taskbook, 'unrelated-new').current, true);
  const otherImpact = { task_id: 'other-parent', status: 'pending', downstream_task_ids: ['other-child'] };
  assert.equal(taskInputApplicability(downstream, 'unrelated-new', [otherImpact]).current, true);
  const pending = { task_id: 'native-parent', status: 'pending', downstream_task_ids: ['native-child'] };
  assert.equal(taskInputApplicability(downstream, 'adopted-old', [pending]).current, false);
  assert.equal(taskInputApplicability(taskbook, 'adopted-old', [pending]).current, false);
  assert.equal(taskInputApplicability(downstream, 'unrelated-new', [{ ...pending, status: 'resolved' }]).current, true);
  assert.equal(taskInputApplicability({ ...downstream, status: 'needs_revalidation' }, 'adopted-old').current, false);
  const generic = { id: 'generic', baseline_id: 'adopted-old', status: 'todo' };
  assert.equal(taskInputApplicability(generic, 'unrelated-new').current, false);
  assert.equal(taskInputApplicability(generic, 'adopted-old').current, true);
  assert.equal(taskInputApplicability(generic, 'adopted-old').reviewTaskId, undefined);
});

test('a freshly confirmed package matches sorted-key persistence without a page reload', () => {
  const form = { source_refs: [{ source_id: 'tech', version: 2 }, { source_id: 'spec', version: 1 }], parameters: { product_type: 'filter_connector', product_domain: 'military', development_process: '改型I', use_llm: true, template_edit_plan: { operations: [{ operation: 'rename', target_slot: 'section-a', new_title: '新标题' }] } }, model_selection: { provider: 'oa', name: 'chosen', id: 'model-a' } };
  const sorted = value => Array.isArray(value) ? value.map(sorted) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])])) : value;
  const stored = JSON.parse(JSON.stringify(sorted({ source_refs: form.source_refs.map(ref => ({ ...ref, name: '固定原件' })), raw_parameters: form.parameters, model_selection: form.model_selection })));
  assert.equal(inputPackageMatchesForm(stored, form), true);
  assert.equal(inputPackageMatchesForm(stored, { ...form, model_selection: { ...form.model_selection, id: 'different' } }), false);
  assert.equal(inputPackageMatchesForm(stored, { ...form, source_refs: [...form.source_refs].reverse() }), false, 'source order is not rewritten');
  assert.equal(inputPackageMatchesForm(stored, { ...form, parameters: { ...form.parameters, template_edit_plan: { operations: [...form.parameters.template_edit_plan.operations, { operation: 'delete', target_slot: 'section-b' }] } } }), false);
});

test('native engine parameters use the existing controlled processes and phases', () => {
  assert.deepEqual(PROCESS_OPTIONS.map(item => item.value), ['全新', '改型I', '改型II', '改型III']);
  assert.deepEqual(COVER_PHASE_OPTIONS.filter(item => item.value).map(item => item.value), ['F', 'C', 'S', 'D']);
  const valid = { product_type: 'filter_connector', product_domain: 'military', development_process: '改型I', product_series: 'J599', organization_scope: 'non_central_research', cover_phase: 'F', use_llm: true };
  assert.deepEqual(nativeParameterIssues(valid), []);
  assert.match(nativeParameterIssues({ ...valid, development_process: '改型' }).join(), /受控研制/);
  assert.match(nativeParameterIssues({ ...valid, use_llm: false }).join(), /启用所选模型/);
  assert.match(nativeParameterIssues({ ...valid, cover_phase: 'unknown' }).join(), /封面研制阶段/);
});

test('a second runtime attempt is shown without adopting it or losing unsaved document edits', () => {
  const runs = [{ run_id: 'attempt-new', status: 'running' }, { run_id: 'attempt-old', status: 'done' }];
  assert.equal(displayedNativeRun(runs, '', 'attempt-old').run_id, 'attempt-old');
  assert.equal(displayedNativeRun(runs, '', undefined).run_id, 'attempt-new');
  assert.equal(nextNativeRunView(runs, 'attempt-old', 'attempt-old', false), 'attempt-new');
  assert.equal(nextNativeRunView(runs, 'attempt-old', 'attempt-old', true), 'attempt-old');
  assert.equal(displayedNativeRun(runs, 'attempt-new', 'attempt-old').run_id, 'attempt-new');
  assert.equal(nextNativeRunView(runs, 'attempt-old', 'attempt-new', false), 'attempt-old', 'explicit historical browsing remains stable');
  assert.deepEqual(runs.map(run => run.run_id), ['attempt-new', 'attempt-old']);
});

test('native task route and API path preserve exact project/task ownership', () => {
  assert.equal(api.nativeTaskHref('project /一', 'task ?二'), '/rd/project%20%2F%E4%B8%80/tasks/task%20%3F%E4%BA%8C');
  assert.equal(api.taskbookPath('p/1', 't/2'), '/api/rd/projects/p%2F1/tasks/t%2F2/taskbook');
  const key = api.nativeContextKey('p1', 't1', 'author', 'engineer');
  assert.notEqual(key, api.nativeContextKey('p2', 't1', 'author', 'engineer'));
  assert.notEqual(key, api.nativeContextKey('p1', 't2', 'author', 'engineer'));
  assert.notEqual(key, api.nativeContextKey('p1', 't1', 'reviewer', 'engineer'));
  assert.notEqual(key, api.nativeContextKey('p1', 't1', 'author', 'viewer'));
});

test('a native run submits a fixed package and explicit project version with a reusable request key', async () => {
  const calls = [], original = globalThis.fetch;
  globalThis.fetch = async (url, init) => { calls.push({ url, init }); return new Response(JSON.stringify({ run: { run_id: 'run-1', jid: 'engine-1', package_id: 'pack-fixed' }, project_version: 8 }), { status: 200 }); };
  try {
    const body = Object.freeze({ package_id: 'pack-fixed', expected_version: 7 });
    await api.taskbookMutation('p', 't', 'runs', body, 'same-attempt');
    await api.taskbookMutation('p', 't', 'runs', body, 'same-attempt');
    assert.equal(calls[0].url, '/api/rd/projects/p/tasks/t/taskbook/runs');
    assert.deepEqual(JSON.parse(calls[0].init.body), { package_id: 'pack-fixed', expected_version: 7 });
    assert.equal(calls[0].init.headers['Idempotency-Key'], calls[1].init.headers['Idempotency-Key']);
    assert.equal(calls[0].init.credentials, 'same-origin');
    assert.equal(calls[0].init.cache, 'no-store');
    assert.ok(!calls[0].init.body.includes('jid'));
  } finally { globalThis.fetch = original; }
});

test('draft conflict retains pending ReviewStore operations and uses an independent revision', async () => {
  const original = globalThis.fetch;
  const local = { expected_draft_revision: 3, input_package_id: 'pack-fixed', form: { parameters: { product_type: 'connector' }, model_selection: { provider: 'oa', name: 'chosen', id: 'model-a' }, source_refs: [{ source_id: 'tech', version: 2 }] }, pending_operations: [{ op: 'replace_text', element_id: 'p12', text: '尚未提交的正文', revision_id: 'revision-1' }] };
  const before = structuredClone(local);
  let captured;
  globalThis.fetch = async (url, init) => { captured = { url, init }; return new Response(JSON.stringify({ detail: '草稿已有更新，请保留本地编辑并比较后重试' }), { status: 409 }); };
  try {
    await assert.rejects(api.saveTaskbookDraft('p', 't', local), error => error.status === 409 && /保留本地编辑/.test(error.message));
    assert.deepEqual(local, before);
    assert.equal(captured.init.method, 'PUT');
    assert.equal(JSON.parse(captured.init.body).expected_draft_revision, 3);
    assert.equal('expected_version' in JSON.parse(captured.init.body), false);
    assert.deepEqual(JSON.parse(captured.init.body).pending_operations, before.pending_operations);
  } finally { globalThis.fetch = original; }
});

test('restoring a package draft cannot ask for another package or silently substitute a model', async () => {
  const original = globalThis.fetch; let captured;
  const draft = { draft_revision: 4, input_package_id: 'pack ?二', form: { model_selection: { provider: 'oa', name: 'unavailable-model', id: 'chosen-id' }, parameters: {}, source_refs: [] }, pending_operations: [] };
  globalThis.fetch = async url => { captured = url; return new Response(JSON.stringify(draft)); };
  try {
    const restored = await api.getTaskbookDraft('p/1', 't/2', 'pack ?二');
    const params = new URL(captured, 'http://local').searchParams;
    assert.equal(params.get('input_package_id'), 'pack ?二');
    assert.deepEqual(restored.form.model_selection, draft.form.model_selection);
    assert.equal(restored.input_package_id, 'pack ?二');
  } finally { globalThis.fetch = original; }
});

test('authentication and network failures remain distinguishable for save protection', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: '仅当前任务执行人可以办理任务书' }), { status: 403 });
    await assert.rejects(api.getTaskbookWorkspace('p', 't'), error => error.status === 403 && /执行人/.test(error.message));
    globalThis.fetch = async () => { throw new TypeError('offline'); };
    await assert.rejects(api.getTaskbookWorkspace('p', 't'), error => error.status === 0 && /原表单重试/.test(error.message));
  } finally { globalThis.fetch = original; }
});
