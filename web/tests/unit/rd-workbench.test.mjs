import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';

const bundled = await build({ entryPoints: ['src/features/rd/model/rdWorkbench.ts'], bundle: true, platform: 'node', format: 'esm', write: false });
const { projectRole, roleLabel, projectJourney, workItems } = await import(`data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].text).toString('base64')}`);
const project = (role = 'owner') => ({ project: { id: 'project 1', name: '连接器研制', role, owner_id: 'owner', current_baseline_id: 'base' }, current_user_id: role, members: [], requirements: [], baselines: [], tasks: [], artifacts: [], reviews: [], events: [], generations: [] });
const task = (id, fields = {}) => ({ id, title: id, assignee_id: 'engineer', reviewer_id: 'reviewer', status: 'todo', baseline_id: 'base', ...fields });

test('owner can resume an unresolved or stale route even when no native task exists', () => {
  for (const stage of ['selection_pending', 'needs_revalidation']) {
    const d = project();
    d.journey = {route:'modification',route_label:'改型',stage,stage_label:'选型待核实',blockers:['适用性待核实']};
    const item=workItems([d],'owner').find(item=>item.kind==='selection');
    assert.ok(item, stage);
    assert.match(item.href, /tab=flow#route-decision$/);
  }
});

test('engineering work is assigned explicitly, not inferred from project data gaps', () => {
  const d=project('engineer');
  d.requirements=[{id:'r',title:'待澄清要求',required:true,clarification:'open',source:'',acceptance:''}];
  d.tasks=[task('other',{assignee_id:'another-engineer'})];
  assert.deepEqual(workItems([d],'engineer'),[]);
});

test('responsibility is independent of permission and journey never infers project completion from one task', () => {
  const d = project('viewer'); d.project.workbench_role = 'leadership'; d.tasks = [task('finished', { status: 'done' })];
  assert.equal(projectRole(d), 'viewer'); assert.equal(roleLabel('reviewer'), '独立评审');
  assert.equal(projectJourney(d).route, 'undecided'); assert.doesNotMatch(projectJourney(d).stage_label, /完成/);
  d.journey = { route: 'direct', route_label: '直接选用', stage: 'delivery', stage_label: '交接待确认', blockers: ['供应状态待核实'] };
  assert.deepEqual(projectJourney(d), d.journey);
  const historical = project(); historical.development_adoptions = [{ route: 'modified' }];
  assert.equal(projectJourney(historical).route, 'modification');
});
test('owner sees approved unpublished plan and unresolved impacts without execution assignments', () => {
  const d = project(); d.tasks = [task('native', { kind: 'taskbook', status: 'done' })];
  d.taskbook_releases = [{ id: 'release', task_id: 'native', revision_id: 'fixed', version: 1 }];
  d.taskbook_work_units = [{ task_id: 'native', release_id: 'release' }];
  d.change_impacts = [{ id: 'impact', task_id: 'native', status: 'pending' }];
  assert.ok(workItems([d], 'owner').some(i => i.kind === 'change_impact'));
  assert.ok(!workItems([d], 'owner').some(i => i.kind === 'publish_plan'), 'pending impact blocks publication');
  d.change_impacts = [];
  const publication = workItems([d], 'owner').find(i => i.kind === 'publish_plan');
  assert.equal(publication.href, '/rd/project%201/tasks/native?view=handoff');
  d.project_plan = { versions: [{ release_id: 'release' }], items: [], work_units: [] };
  assert.ok(!workItems([d], 'owner').some(i => i.kind === 'publish_plan'));
});
test('engineer accepts only current assigned handoff; reviewer opens exact native fixed review', () => {
  const d = project('engineer'); d.tasks = [task('child', { kind: 'plan_item', required_handoff_id: 'current' }), task('native', { kind: 'taskbook', status: 'in_review' })];
  d.handoffs = [{ id: 'old', task_id: 'child', assignee_id: 'engineer', status: 'superseded' }, { id: 'current', task_id: 'child', assignee_id: 'engineer', status: 'pending' }];
  assert.equal(workItems([d], 'engineer').filter(i => i.kind === 'accept_handoff').length, 1);
  assert.ok(!workItems([d], 'engineer').some(i => i.kind === 'execute_task' && i.id.includes('child')));
  d.reviews = [{ id: 'fixed-review', task_id: 'native', reviewer_id: 'reviewer', submitter_id: 'engineer', status: 'pending' }];
  assert.equal(workItems([d], 'reviewer').find(i => i.kind === 'review').href, '/rd/project%201/tasks/native?view=review');
});
test('legacy platform management labels cannot create project assignments', () => {
  for(const legacy of ['technical_lead','leadership','knowledge','operations']) {
    const d=project('viewer');d.project.workbench_role=legacy;
    d.requirements=[{id:'r',title:'待补要求',source:'',acceptance:'',required:true,clarification:'open'}];
    d.taskbook_runs=[{run_id:'failed',task_id:'native',status:'failed'}];
    assert.equal(projectRole(d),'viewer');
    assert.deepEqual(workItems([d],'viewer'),[]);
  }
});

test('cross-project work ids stay unique and generic task links preserve pager location', () => {
  const a = project('engineer'); a.tasks = Array.from({ length: 12 }, (_, i) => task(`t${i}`));
  const b = { ...a, project: { ...a.project, id: 'project2' } };
  const items = workItems([a, b], 'engineer'); assert.equal(new Set(items.map(i => i.id)).size, items.length);
  const href = items.find(i => i.projectId === a.project.id && i.title === '办理任务：t11').href;
  assert.equal(new URL(href, 'http://local').searchParams.get('rd_tasks_page'), '2');
});
test('server publication eligibility overrides legacy release inference', () => {
  const d = project(); d.tasks = [task('native', { kind: 'taskbook', status: 'done' })];
  d.taskbook_releases = [{ id: 'historic', task_id: 'native', revision_id: 'fixed', version: 1 }];
  d.project_plan = { versions: [], items: [], work_units: [], pending_releases: [] };
  assert.equal(workItems([d], 'owner').filter(i => i.kind === 'publish_plan').length, 0);
  d.project_plan.pending_releases = [{ task_id: 'native', release_id: 'current', source_revision_id: 'current-fixed' }];
  const publications = workItems([d], 'owner').filter(i => i.kind === 'publish_plan');
  assert.equal(publications.length, 1); assert.match(publications[0].id, /current$/);
});
test('a responsibility designation never grants publication, execution or approval permission', () => {
  const d = project('viewer'); d.project.workbench_role = 'owner';
  d.tasks = [task('assigned', { assignee_id: 'viewer' })];
  d.reviews = [{ id: 'pending', task_id: 'assigned', status: 'pending', reviewer_id: 'viewer', submitter_id: 'engineer' }];
  assert.deepEqual(workItems([d], 'viewer'), []);
  const owner = project();
  const selection = new URL(workItems([owner], 'owner').find(item => item.kind === 'selection').href, 'http://local');
  assert.equal(selection.searchParams.get('tab'), 'flow'); assert.equal(selection.hash, '#route-decision');
  owner.journey = { route: 'direct', route_label: '直接选用', stage: 'delivery_pending', stage_label: '待交接', blockers: [] };
  const delivery = new URL(workItems([owner], 'owner').find(item => item.kind === 'delivery').href, 'http://local');
  assert.equal(delivery.searchParams.get('tab'), 'flow'); assert.equal(delivery.hash, '#direct-delivery');
});
