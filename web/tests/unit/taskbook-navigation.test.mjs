import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
import { taskbookView, taskbookProjectHref, taskbookReviewHref } from '../../src/features/taskbook/model/taskbookNavigation.ts';

const workspace = (patch = {}) => ({
  current_user_id: 'engineer', project: { id: 'p', owner_id: 'owner', role: 'engineer' },
  task: { id: 't', status: 'in_progress', assignee_id: 'engineer', reviewer_id: 'reviewer' },
  work_unit: { current_stage: 'ND13', input_package_id: undefined, selected_revision_id: undefined },
  reviews: [], releases: [], plan_releases: [], handoffs: [], change_impacts: [], wbs: null,
  ...patch,
});

test('valid view preserves explicit historical browsing; unknown view falls back to actual work', () => {
  for (const view of ['inputs', 'document', 'planning', 'review', 'handoff']) assert.equal(taskbookView(view, workspace()), view);
  assert.equal(taskbookView('unknown', workspace()), 'inputs');
  assert.equal(taskbookView('', workspace()), 'inputs');
});

test('pending independent reviewer enters the fixed review, while returned work opens document', () => {
  const pending = workspace({ current_user_id: 'reviewer', project: { owner_id: 'owner', role: 'reviewer' }, task: { status: 'in_review', assignee_id: 'engineer', reviewer_id: 'reviewer' }, reviews: [{ id: 'r', status: 'pending', reviewer_id: 'reviewer', submitter_id: 'engineer' }] });
  assert.equal(taskbookView(null, pending), 'review');
  assert.equal(taskbookView('document', pending), 'document');
  assert.equal(taskbookView(null, workspace({ task: { status: 'changes_requested' }, work_unit: { current_stage: 'ND15', selected_revision_id: 'revision-old' } })), 'document');
});

test('adopted document, WBS stage and fixed submission each enter their corresponding work surface', () => {
  assert.equal(taskbookView(null, workspace({ work_unit: { current_stage: 'ND13', selected_revision_id: 'rev' } })), 'document');
  assert.equal(taskbookView(null, workspace({ work_unit: { current_stage: 'ND14', selected_revision_id: 'rev' } })), 'planning');
  assert.equal(taskbookView(null, workspace({ work_unit: { current_stage: 'ND15', selected_revision_id: 'rev' }, wbs: { source_revision_id: 'rev', status: 'verified' } })), 'review');
  assert.equal(taskbookView(null, workspace({ work_unit: { current_stage: 'ND15', selected_revision_id: 'rev' }, wbs: { source_revision_id: 'old', status: 'verified' } })), 'planning');
});

test('approved publication, pending receipt and accepted handoffs enter publication and handoff', () => {
  const approved = workspace({ task: { status: 'done' }, work_unit: { current_stage: 'ND15', release_id: 'release' }, releases: [{ id: 'release' }] });
  assert.equal(taskbookView(null, approved), 'handoff');
  assert.equal(taskbookView(null, { ...approved, plan_releases: [{ id: 'plan', release_id: 'release' }], handoffs: [{ status: 'accepted', assignee_id: 'engineer' }] }), 'handoff');
  assert.equal(taskbookView(null, workspace({ handoffs: [{ status: 'pending', assignee_id: 'engineer' }] })), 'handoff');
  assert.equal(taskbookView(null, workspace({ current_user_id: 'owner', project: { owner_id: 'owner', role: 'owner' }, change_impacts: [{ status: 'pending' }] })), 'handoff');
});

test('reopening an approved package returns to current compilation, without using the old release as the current stage', () => {
  assert.equal(taskbookView(null, workspace({ work_unit: { current_stage: 'ND13', selected_revision_id: 'new-revision', release_id: 'old-release' }, releases: [{ id: 'old-release' }] })), 'document');
});

test('project returns and fixed-review links encode ownership and preserve exact record anchors', () => {
  assert.equal(taskbookProjectHref('p /一', 't ?二'), '/rd/p%20%2F%E4%B8%80?tab=flow#task-t%20%3F%E4%BA%8C');
  assert.equal(taskbookReviewHref('p/1', 't/2', 'r ?三'), '/rd/p%2F1/tasks/t%2F2?view=review#review-r%20%3F%E4%B8%89');
});

const rendered = await build({
  stdin: { contents: "import React from 'react'; import { renderToStaticMarkup } from 'react-dom/server'; import { RdArtifacts } from './src/features/rd/components/RdArtifacts'; export const render = context => renderToStaticMarkup(React.createElement(RdArtifacts, { context }));", resolveDir: process.cwd() },
  bundle: true, platform: 'node', format: 'esm', write: false, loader: { '.css': 'empty' },
  external: ['react', 'react-dom/server'],
  banner: { js: `import { createRequire } from 'node:module'; const require = createRequire(${JSON.stringify(import.meta.url)});` },
});
// Resolve React from the repository while loading the bundled component graph.
const { render } = await import(`data:text/javascript;base64,${Buffer.from(rendered.outputFiles[0].text.replaceAll('from "react"', `from ${JSON.stringify(import.meta.resolve('react'))}`).replaceAll('from "react-dom/server"', `from ${JSON.stringify(import.meta.resolve('react-dom/server'))}`).replaceAll('from "react/jsx-runtime"', `from ${JSON.stringify(import.meta.resolve('react/jsx-runtime'))}`)).toString('base64')}`);

function artifactContext({ native = true, actor = 'engineer', status = 'in_progress', impacts = [] } = {}) {
  return { disabled: false, run: async () => {}, detail: {
    current_user_id: actor, project: { id: 'p', role: actor === 'reviewer' ? 'reviewer' : 'engineer', owner_id: 'owner', current_baseline_id: native ? 'unrelated-new' : 'fixed' },
    members: [], baselines: [], change_impacts: impacts,
    tasks: [{ id: 't', title: '固定任务书', kind: native ? 'taskbook' : undefined, baseline_id: 'fixed', status, assignee_id: 'engineer', reviewer_id: 'reviewer' }],
    artifacts: [{ id: 'a', task_id: 't', baseline_id: 'fixed', jid: 'j', source_revision_id: 'revision-fixed', filename: 'fixed.docx', sha256: 'sha', author_id: 'engineer', quality_status: 'passed', status: 'draft' }],
    reviews: status === 'in_review' ? [{ id: 'r', task_id: 't', artifact_id: 'a', baseline_id: 'fixed', reviewer_id: 'reviewer', submitter_id: 'engineer', status: 'pending' }] : [],
  } };
}

test('native artifacts use fixed-package navigation across unrelated baselines and explicit impacts', () => {
  globalThis.location = new URL('http://localhost/rd/p?tab=results');
  const html = render(artifactContext());
  assert.match(html, /查看任务书固定包/);
  assert.match(html, /固定输入版本/);
  assert.doesNotMatch(html, />提交审签</);
  assert.doesNotMatch(html, /采用新基线后须重新生成/);
  const impacted = render(artifactContext({ impacts: [{ task_id: 't', status: 'pending' }] }));
  assert.match(impacted, /固定输入待复核/);
  assert.match(impacted, /view=review/);
});

test('native pending review routes to its exact fixed record; generic approvals retain their actions', () => {
  const native = render(artifactContext({ actor: 'reviewer', status: 'in_review' }));
  assert.match(native, /view=review#review-r/);
  assert.match(native, /进入任务书工程审签/);
  assert.doesNotMatch(native, />批准固定成果</);
  assert.match(render(artifactContext({ native: false, actor: 'reviewer', status: 'in_review' })), />批准固定成果</);
  assert.match(render(artifactContext({ native: false })), />提交审签</);
});

test('recompiled native releases keep prior approved artifacts historical even after input validity is restored', () => {
  const context = artifactContext({ status: 'done' }), detail = context.detail;
  const old = { ...detail.artifacts[0], id: 'a-b1', baseline_id: 'B1', source_revision_id: 'revision-b1', status: 'approved' };
  const current = { ...old, id: 'a-b2', baseline_id: 'B2', source_revision_id: 'revision-b2', filename: 'current.docx' };
  detail.project.current_baseline_id = 'B2'; detail.tasks[0].baseline_id = 'B2';
  detail.artifacts = [old, current];
  detail.change_impacts = [{ task_id: 't', status: 'resolved' }];
  detail.reviews = [old, current].map((artifact, index) => ({ id: `r-${index + 1}`, task_id: 't', artifact_id: artifact.id, baseline_id: artifact.baseline_id, reviewer_id: 'reviewer', submitter_id: 'engineer', status: 'approved' }));
  detail.taskbook_work_units = [{ task_id: 't', release_id: 'release-b2', selected_revision_id: 'revision-b2' }];
  detail.taskbook_releases = [old, current].map((artifact, index) => ({ id: `release-b${index + 1}`, task_id: 't', artifact_id: artifact.id, revision_id: artifact.source_revision_id, version: index + 1 }));
  const html = render(context);
  const oldRecord = html.match(/<article[^>]*id="artifact-a-b1"[\s\S]*?<\/article>/)?.[0];
  const currentRecord = html.match(/<article[^>]*id="artifact-a-b2"[\s\S]*?<\/article>/)?.[0];
  assert.ok(oldRecord); assert.ok(currentRecord);
  assert.match(oldRecord, /历史固定输入版本/);
  assert.match(oldRecord, />下载历史批准版</);
  assert.doesNotMatch(oldRecord, />下载批准版</);
  assert.match(currentRecord, /当前固定输入版本/);
  assert.match(currentRecord, />下载批准版</);
  // A fresh adoption of the same document revision must still select its exact release artifact.
  detail.artifacts[0].source_revision_id = 'revision-b2';
  detail.taskbook_releases[0].revision_id = 'revision-b2';
  const sameRevisionOld = render(context).match(/<article[^>]*id="artifact-a-b1"[\s\S]*?<\/article>/)?.[0];
  assert.match(sameRevisionOld, /历史固定输入版本/);
  assert.match(sameRevisionOld, />下载历史批准版</);
});
