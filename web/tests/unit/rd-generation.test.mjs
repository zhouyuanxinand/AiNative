import assert from 'node:assert/strict';
import test from 'node:test';
import { readRdContext, setRdGenerationContext, prepareRdGeneration, completeRdGeneration, runningJobRecord, runningJobMatchesContext } from '../../src/features/taskbook/model/rdGeneration.ts';

const search = '?rd_project=project-1&rd_task=task-1';
const form = () => { const fd = new FormData(); fd.set('product_type', 'connector'); fd.set('tech', new File(['requirements'], '需求.docx', { lastModified: 1 })); return fd; };

test('resuming a job cannot mix projects, tasks or standalone generation', () => {
  const saved = runningJobRecord('job-a', search);
  assert.equal(runningJobMatchesContext(saved, search), true);
  assert.equal(runningJobMatchesContext(saved, '?rd_project=project-2&rd_task=task-1'), false);
  assert.equal(runningJobMatchesContext(saved, '?rd_project=project-1&rd_task=task-2'), false);
  assert.equal(runningJobMatchesContext(saved, ''), false);
  assert.equal(runningJobMatchesContext({ jid: 'legacy-job' }, search), false);
  assert.equal(runningJobMatchesContext({ jid: 'legacy-job' }, ''), true);
  assert.equal(runningJobMatchesContext(runningJobRecord('local', ''), search), false);
});

test('standalone generation remains unbound; incomplete project context is rejected', () => {
  assert.equal(readRdContext(''), null);
  assert.equal(prepareRdGeneration(form(), ''), undefined);
  assert.throws(() => readRdContext('?rd_project=project-1'), /不完整/);
});

test('project generation requires loaded matching context and explicit input confirmation', () => {
  setRdGenerationContext(null);
  assert.throws(() => prepareRdGeneration(form(), search), /读取/);
  setRdGenerationContext({ project_id: 'project-1', task_id: 'task-1', baseline_id: 'base-1', confirmed: false });
  assert.throws(() => prepareRdGeneration(form(), search), /核对/);
  setRdGenerationContext({ project_id: 'other', task_id: 'task-1', baseline_id: 'base-1', confirmed: true });
  assert.throws(() => prepareRdGeneration(form(), search), /不一致/);
});

test('an ambiguous retry reuses its request key; changed inputs or completed intent create a new key', () => {
  setRdGenerationContext({ project_id: 'project-1', task_id: 'task-1', baseline_id: 'base-1', confirmed: true });
  const first = form(); const key = prepareRdGeneration(first, search);
  assert.equal(first.get('rd_baseline_id'), 'base-1');
  assert.equal(first.get('rd_inputs_confirmed'), 'true');
  assert.equal(prepareRdGeneration(form(), search), key);
  const changed = form(); changed.set('product_type', 'chassis');
  assert.notEqual(prepareRdGeneration(changed, search), key);
  completeRdGeneration(key);
  assert.notEqual(prepareRdGeneration(form(), search), key);
});

test('generation works on intranet HTTP without secure-context randomUUID', () => {
  const original = globalThis.crypto.randomUUID;
  globalThis.crypto.randomUUID = undefined;
  try {
    setRdGenerationContext({ project_id: 'project-1', task_id: 'task-1', baseline_id: 'http-baseline', confirmed: true });
    const key = prepareRdGeneration(form(), search);
    assert.ok(key);
    assert.equal(prepareRdGeneration(form(), search), key);
  } finally { globalThis.crypto.randomUUID = original; }
});
