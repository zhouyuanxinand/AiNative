import assert from 'node:assert/strict';
import test from 'node:test';
import { projectHref } from '../../src/features/rd/model/projectLinks.ts';

const records = prefix => Array.from({ length: 23 }, (_, index) => ({ id: `${prefix}${index + 1}` }));
const detail = { project: { id: 'project 1' }, requirements: records('r'), tasks: records('t'), artifacts: records('a'), reviews: records('v') };
const query = href => new URL(href, 'http://localhost').searchParams;

test('cross-project requirement and task links reveal records beyond the first page', () => {
  assert.equal(query(projectHref(detail, 'requirements', 'requirement-r21')).get('rd_requirements_page'), '3');
  const task = projectHref(detail, 'tasks', 'task-t11');
  assert.equal(query(task).get('rd_tasks_page'), '2');
  assert.equal(query(task).get('tab'), 'flow');
  assert.equal(new URL(task, 'http://localhost').hash, '#task-t11');
});

test('cross-project links use the three owning project areas', () => {
  assert.equal(query(projectHref(detail, 'requirements', 'requirement-r1')).get('tab'), 'materials');
  assert.equal(query(projectHref(detail, 'artifacts', 'artifact-a1')).get('tab'), 'results');
  assert.equal(query(projectHref(detail, 'members')).get('section'), 'members');
});

test('fixed artifacts and review links follow the newest-first project ordering', () => {
  assert.equal(query(projectHref(detail, 'artifacts', 'artifact-a1')).get('rd_artifacts_page'), '3');
  assert.equal(query(projectHref(detail, 'artifacts', 'artifact-a23')).get('rd_artifacts_page'), '1');
  assert.equal(query(projectHref(detail, 'artifacts', 'review-v11')).get('rd_reviews_page'), '2');
  assert.equal(query(projectHref(detail, 'artifacts', 'review-v1')).get('rd_reviews_page'), '3');
});

test('native tasks and their global approval entries open the same task workspace', () => {
  const native = { ...detail, tasks: [{ id: 'native-task', kind: 'taskbook' }], reviews: [{ id: 'native-review', task_id: 'native-task' }] };
  assert.equal(projectHref(native, 'tasks', 'task-native-task'), '/rd/project%201/tasks/native-task');
  assert.equal(projectHref(native, 'artifacts', 'review-native-review'), '/rd/project%201/tasks/native-task?view=review');
});
