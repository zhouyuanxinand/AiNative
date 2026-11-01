import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(new URL('../../../package.json', import.meta.url));
const ts = require('typescript');
const source = await readFile(new URL('./caseOutcomeModel.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } });
const { summarizeCaseOutcome, caseArtifactRecords, latestTaskbookPackage } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const researchCase = overrides => ({ id: 'case', stage: 'design', status: 'active', input_revision: 2, decisions: [], workpackages: [], ...overrides });
const workpackage = overrides => ({ id: 'package', stage: 'design', title: '装配与核验', status: 'completed', nodes: [], artifacts: [{ id: 'document', name: '任务书.docx', kind: 'docx' }], snapshot: { input_revision: 2 }, obligations: [], blocked_reasons: [], ...overrides });

test('v2 scope review follows submission order, and an in-flight taskbook prevents selecting an older completion', () => {
  const a = workpackage({ id: 'a', definition_id: 'taskbook', definition_version: '2', stage: 'planning', snapshot: { input_revision: 2, submitted_at: '2026-11-01T02:00:00Z' } });
  const b = workpackage({ ...a, id: 'b', snapshot: { input_revision: 2, submitted_at: '2026-11-01T01:00:00Z' } });
  const data = researchCase({ stage: 'planning', workpackages: [a, b] });
  assert.equal(latestTaskbookPackage(data)?.id, 'a');
  a.status = 'running';
  assert.equal(latestTaskbookPackage(data)?.status, 'running');
});

test('execution completion and successful automated checks do not become business approval', () => {
  const state = summarizeCaseOutcome(researchCase({ workpackages: [workpackage({ nodes: [{ action_id: 'verify', status: 'completed', result: { delivery_approved: true } }] })] }));
  assert.equal(state.execution.kind, 'completed');
  assert.equal(state.confirmation.kind, 'unrecorded');
  assert.equal(state.verification.kind, 'passed');
});

test('changed inputs keep original artifacts readable but no longer present them as current evidence', () => {
  const data = researchCase({ input_revision: 3, workpackages: [workpackage({})], decisions: [{ kind: 'stage', stage: 'design', verdict: 'approved', input_revision: 2, invalidated_at: '2026-10-30T00:00:00Z' }] });
  const records = caseArtifactRecords(data);
  assert.equal(records.length, 1);
  assert.equal(records[0].current, false);
  assert.equal(summarizeCaseOutcome(data).confirmation.kind, 'stale');
  assert.equal(summarizeCaseOutcome(data).verification.kind, 'unrecorded');
});

test('current blocked execution stays distinct from earlier completed runs and unknown legacy inputs', () => {
  const data = researchCase({ workpackages: [workpackage({}), workpackage({ id: 'blocked', status: 'blocked', artifacts: [], obligations: [{ id: 'missing-proof' }], blocked_reasons: ['缺少来源'] }), workpackage({ id: 'legacy', stage: 'input', snapshot: undefined })] });
  const state = summarizeCaseOutcome(data);
  assert.equal(state.execution.kind, 'blocked');
  assert.equal(state.blockedPackages.length, 1);
  assert.equal(state.confirmation.kind, 'unrecorded');
  assert.equal(caseArtifactRecords(data).find(row => row.workpackage.id === 'legacy').current, false);
});

test('a cancelled package cannot supply an active automatic verification result', () => {
  const data = researchCase({ workpackages: [workpackage({ status: 'cancelled', nodes: [{ action_id: 'verify', status: 'completed', result: { delivery_approved: true } }] })] });
  assert.equal(summarizeCaseOutcome(data).verification.kind, 'unrecorded');
});
