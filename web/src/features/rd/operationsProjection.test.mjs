import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
const ts = createRequire(new URL('../../../package.json', import.meta.url))('typescript');
const { outputText } = ts.transpileModule(await readFile(new URL('./operationsProjection.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const { projectOperations, EMPTY_OPERATIONS_FILTERS, operationTimestamp, operationEndTimestamp } = await import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
const now = new Date('2026-11-03T04:00:00Z');
const filters = overrides => ({ ...EMPTY_OPERATIONS_FILTERS, ...overrides });
const wp = (id, status = 'draft', extra = {}) => ({ id, title: id, status, nodes: [], artifacts: [], obligations: [], blocked_reasons: [], ...extra });
const researchCase = (id, packages = [], extra = {}) => ({ id, title: id, stage: 'planning', input_revision: 3, requirements: [], sources: [], workpackages: packages, ...extra });
const project = (id, cases = [], extra = {}) => ({ id, title: id, owner_id: 'owner-a', cases, ...extra });
const projectAt = (value, select = filters()) => projectOperations(value, select, now);

test('empty records preserve complete zero counts, null denominators and fourteen Shanghai dates', () => {
  const value = projectAt([]);
  for (const [key, number] of Object.entries(value.metrics)) assert.equal(number, ['completionRate', 'adoptionRate'].includes(key) ? null : 0, key);
  assert.equal(value.trend.length, 14); assert.equal(value.trend[0].day, '2026-10-21'); assert.equal(value.trend.at(-1).day, '2026-11-03');
  assert(value.trend.every(row => row.planned === 0 && row.completed === 0)); assert.equal(value.packages.length, 0);
});

test('counts actual execution states, percentages, registered evidence and retains unknown statuses', () => {
  const packages = [wp('ok', 'completed', { nodes: [{ status: 'completed' }, { status: 'running' }], artifacts: [{ id: 'doc' }], obligations: [{ id: 'historical' }] }), wp('draft'), wp('busy', 'running'), wp('stop', 'blocked'), wp('error', 'failed'), wp('cancel', 'cancelled'), wp('future', 'awaiting_external')];
  const value = projectAt([project('p', [researchCase('c', packages, { requirements: [{ id: 'r' }], sources: [{ id: 's' }], reuse_candidates: [{ id: 'k' }] })])]);
  assert.equal(value.metrics.packageCount, 7); assert.equal(value.metrics.openCount, 5); assert.equal(value.metrics.completionRate, 25);
  assert.equal(value.metrics.attentionCount, 2); assert.equal(value.metrics.requirementsCount, 1); assert.equal(value.metrics.sourceCount, 1);
  assert.equal(value.metrics.artifactCount, 1); assert.equal(value.metrics.obligationCount, 1); assert.equal(value.metrics.reuseCandidateCount, 1);
  assert.equal(value.metrics.nodeCount, 2); assert.equal(value.metrics.completedNodeCount, 1);
  assert.equal(value.statusCounts.find(row => row.id === 'awaiting_external').count, 1);
  assert.equal(value.issues.some(row => row.workpackage.id === 'ok'), false, 'historical obligations in completed work do not create new blocking issues');
});

test('hierarchical query, stage, status and owner filter every aggregate from the same matched subtree', () => {
  const input = [project('项目甲', [researchCase('需求澄清', [wp('检查'), wp('任务书', 'completed')]), researchCase('方案', [wp('任务书二', 'running')], { stage: 'design' })]), project('项目乙', [researchCase('案例乙', [wp('任务书三', 'running')])], { owner_id: 'owner-b' })];
  assert.equal(projectAt(input, filters({ query: '项目甲' })).metrics.packageCount, 3, 'parent match includes eligible descendants');
  assert.equal(projectAt(input, filters({ query: '需求澄清' })).metrics.packageCount, 2, 'case match includes its own packages');
  const filtered = projectAt(input, filters({ query: '任务书', owner: 'owner-a', stage: 'planning', status: 'completed' }));
  assert.equal(filtered.metrics.projectCount, 1); assert.equal(filtered.metrics.caseCount, 1); assert.equal(filtered.metrics.packageCount, 1);
  assert.equal(filtered.projects[0].packages[0].workpackage.id, '任务书'); assert.equal(filtered.metrics.completionRate, 100);
  assert.equal(filtered.stageCounts.find(row => row.id === 'design').count, 0);
  assert.equal(projectAt(input, filters({ query: '不存在' })).metrics.projectCount, 0);
});

test('unstarted projects and cases remain in all-status scope but cannot match an execution status', () => {
  const input = [project('无案例'), project('无包', [researchCase('刚建项')])];
  assert.equal(projectAt(input).metrics.projectCount, 2); assert.equal(projectAt(input).metrics.caseCount, 1);
  assert.equal(projectAt(input, filters({ status: 'running' })).metrics.projectCount, 0);
  assert.equal(projectAt(input, filters({ stage: 'planning' })).metrics.projectCount, 1);
});

test('overdue and seven-day deadlines use Shanghai calendar dates and exclude completed/cancelled', () => {
  const packages = [wp('past', 'running', { planned_end: '2026-11-02' }), wp('today', 'draft', { planned_end: '2026-11-03' }), wp('six-days-later', 'submitted', { planned_end: '2026-11-09' }), wp('seven-days-later', 'running', { planned_end: '2026-11-10' }), wp('done', 'completed', { planned_end: '2026-10-01' }), wp('cancelled', 'cancelled', { planned_end: '2026-10-01' })];
  const value = projectAt([project('p', [researchCase('c', packages)])]);
  assert.equal(value.metrics.overdueCount, 1); assert.equal(value.metrics.dueSoonCount, 2);
  assert.equal(value.packages.find(row => row.workpackage.id === 'six-days-later').dueSoon, true);
  assert.equal(value.packages.find(row => row.workpackage.id === 'seven-days-later').dueSoon, false);
  assert.equal(value.packages.find(row => row.workpackage.id === 'done').overdue, false);
  const boundary = projectOperations([project('p', [researchCase('c', [wp('midnight', 'running', { planned_end: '2026-11-02' })])])], filters(), new Date('2026-11-02T16:00:00Z'));
  assert.equal(boundary.metrics.overdueCount, 1); assert.equal(boundary.trend.at(-1).day, '2026-11-03');
});

test('missing, impossible and reversed dates remain unknown; valid fallback timestamps are retained', () => {
  const packages = [wp('missing'), wp('bad', 'failed', { planned_end: '2026-02-30', started_at: '2026-11-03T02:00:00Z', ended_at: '2026-11-03T01:00:00Z' }), wp('reverse', 'draft', { planned_start: '2026-11-05', planned_end: '2026-11-04' }), wp('valid', 'completed', { started_at: '2026-11-03T01:00:00Z', completed_at: 'not-a-time', ended_at: '2026-11-03T02:00:00Z' }), wp('invalid-clock', 'completed', { completed_at: '2026-11-02T24:00:00Z' })];
  const value = projectAt([project('p', [researchCase('c', packages)])]);
  assert.equal(value.metrics.missingDueCount, 5); assert.equal(value.metrics.overdueCount, 0);
  assert.equal(value.packages.find(row => row.workpackage.id === 'bad').durationMs, null);
  assert.equal(value.packages.find(row => row.workpackage.id === 'valid').durationMs, 3_600_000);
  assert.equal(value.trend.at(-1).completed, 1); assert.equal(value.trendSamples.missingCompletedDate, 1);
});

test('trend counts actual planned deadlines and completed end days only in the fourteen-day window', () => {
  const packages = [wp('yesterday', 'completed', { planned_end: '2026-11-02', completed_at: '2026-11-02T15:59:59Z' }), wp('today', 'completed', { planned_end: '2026-11-03', completed_at: '2026-11-02T16:00:00Z' }), wp('old', 'completed', { planned_end: '2026-10-20', completed_at: '2026-10-20T00:00:00Z' }), wp('blocked', 'blocked', { ended_at: '2026-11-03T00:00:00Z' }), wp('no-end', 'completed')];
  const value = projectAt([project('p', [researchCase('c', packages)])]);
  assert.deepEqual(value.trendSamples, { planned: 2, completed: 2, missingCompletedDate: 1 });
  assert.deepEqual(value.trend.find(row => row.day === '2026-11-02'), { day: '2026-11-02', planned: 1, completed: 1 });
  assert.deepEqual(value.trend.at(-1), { day: '2026-11-03', planned: 1, completed: 1 });
});

test('adoption requires current project evidence, counts each project once and rejects catalog or stale data', () => {
  const adoption = { id: 'receipt', template_id: 'template', template_version: '2', template_digest: 'fixed', input_revision: 3 };
  const binding = { id: 'binding', status: 'current', input_revision: 3, workflow: { id: 'workflow', version: '1' } };
  const input = [project('adopted', [researchCase('a', [], { workflow_templates: { research: adoption } }), researchCase('b', [], { taskbook_binding: binding })]), project('not-adopted', [researchCase('c', [], { workflow_templates: { research: { id: 'catalog', version: '1', status: 'published' } } }), researchCase('d', [], { workflow_templates: { research: { ...adoption, input_revision: 2 } } }), researchCase('e', [], { taskbook_binding: { ...binding, invalidated_at: '2026-11-01T00:00:00Z' } })])];
  const value = projectAt(input);
  assert.equal(value.metrics.adoptedCaseCount, 2); assert.equal(value.metrics.adoptedProjectCount, 1); assert.equal(value.metrics.adoptionRate, 50);
  assert.equal(projectAt(input, filters({ query: 'not-adopted' })).metrics.adoptionRate, 0);
});

test('issue priority is failed, blocked, overdue then registered reasons; projections never mutate source data', () => {
  const packages = [wp('late', 'draft', { planned_end: '2026-11-01' }), wp('reason', 'running', { blocked_reasons: [{ message: '需核查' }, { reason: '需补资料' }, { unrelated: 'not user text' }] }), wp('blocked', 'blocked'), wp('failed', 'failed')];
  const input = [project('p', [researchCase('c', packages)])], original = structuredClone(input);
  const value = projectAt(input); assert.deepEqual(value.issues.map(row => row.workpackage.id), ['failed', 'blocked', 'late', 'reason']);
  assert.deepEqual(value.issues[3].reasons, ['需核查', '需补资料']); assert.deepEqual(input, original);
  projectAt(input, filters({ status: 'completed' })); assert.deepEqual(input, original);
});

test('project table prioritizes attention, overdue and stable project identity without reordering input', () => {
  const input = [project('z-empty'), project('b-blocked', [researchCase('b', [wp('b', 'blocked')])]), project('a-overdue', [researchCase('a', [wp('a', 'running', { planned_end: '2026-11-01' })])]), project('most', [researchCase('c', [wp('c', 'failed'), wp('d', 'blocked')])]), project('a-empty')];
  const originalOrder = input.map(row => row.id);
  assert.deepEqual(projectAt(input).projects.map(row => row.project.id), ['most', 'a-overdue', 'b-blocked', 'a-empty', 'z-empty']);
  assert.deepEqual(input.map(row => row.id), originalOrder);
});

test('display timestamps share the same valid completed/end selection as execution spans and trends', () => {
  const completed = wp('completed', 'completed', { started_at: '2026-11-03T09:00:00+08:00', completed_at: '2026-11-03T10:00:00+08:00', ended_at: 'not-a-time' });
  const fallback = wp('fallback', 'completed', { started_at: '2026-11-03T01:00:00Z', completed_at: '2026-02-30T10:00:00Z', ended_at: '2026-11-03T02:00:00Z' });
  const value = projectAt([project('p', [researchCase('c', [completed, fallback])])]);
  assert.equal(operationTimestamp(completed.started_at), '2026-11-03T01:00:00.000Z');
  assert.equal(operationTimestamp('2026-02-30T01:00:00Z'), undefined);
  assert.equal(operationEndTimestamp(completed), '2026-11-03T02:00:00.000Z');
  assert.equal(operationEndTimestamp(fallback), '2026-11-03T02:00:00.000Z');
  assert.equal(operationEndTimestamp(wp('unknown')), undefined);
  for (const row of value.packages) assert.equal(Date.parse(operationEndTimestamp(row.workpackage)) - Date.parse(operationTimestamp(row.workpackage.started_at)), row.durationMs);
  assert.equal(value.trend.at(-1).completed, 2);
});
