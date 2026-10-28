import assert from 'node:assert/strict';
import test from 'node:test';
import { projectTabFromUrl, materialSectionFromUrl } from '../../src/features/rd/model/projectNavigation.ts';

test('existing project links open their corresponding business area', () => {
  for (const tab of ['overview', 'artifacts', 'results']) assert.equal(projectTabFromUrl(`?tab=${tab}`), 'results');
  for (const tab of ['tasks', 'flow']) assert.equal(projectTabFromUrl(`?tab=${tab}`), 'flow');
  for (const tab of ['requirements', 'members', 'history', 'materials']) assert.equal(projectTabFromUrl(`?tab=${tab}`), 'materials');
});

test('materials preserve legacy destination, explicit section and requirement anchors', () => {
  assert.equal(materialSectionFromUrl('?tab=members'), 'members');
  assert.equal(materialSectionFromUrl('?tab=history'), 'history');
  assert.equal(materialSectionFromUrl('?tab=materials&section=sources'), 'sources');
  assert.equal(materialSectionFromUrl('?tab=materials&section=members', '#requirement-r1'), 'requirements');
});

test('unknown URL values recover to an actionable project view', () => {
  assert.equal(projectTabFromUrl('?tab=unknown'), 'results');
  assert.equal(materialSectionFromUrl('?section=unknown'), 'requirements');
});
