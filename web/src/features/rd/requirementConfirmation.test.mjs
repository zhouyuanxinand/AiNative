import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(new URL('../../../package.json', import.meta.url));
const ts = require('typescript');
function load(name) {
  const source = readFileSync(new URL(`./${name}.ts`, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(path => path.startsWith('./') ? load(path.slice(2)) : require(path), module, module.exports);
  return module.exports;
}
const { requirementConfirmationBlockers: blockers } = load('requirementConfirmation');
const requirement = { id: 'temperature', title: '环境温度', content: '5°C～42°C', revision: 2, source_ids: ['tech'] };
const source = role => ({ id: role, role, name: `${role}.txt`, sha256: `${role}-hash`, version: 1 });
const fixture = extra => ({
  id: 'case', stage: 'requirements', input_revision: 52, sources: [source('tech'), source('spec')],
  source_selection: { tech: 'tech', spec: 'spec' }, requirements: [structuredClone(requirement)], clarifications: [], ...extra,
});
const batch = extra => ({
  id: 'batch-1', status: 'current', input_revision: 52, source_hashes: { tech: 'tech-hash', spec: 'spec-hash' },
  items: [{ requirement_id: requirement.id, requirement_revision: 2, status: 'difference', text: '请核实适用工况' }], ...extra,
});
const review = extra => ({ recommendation_batch_id: 'batch-1', requirement_revision: 2, decision: 'manual', actual_value: requirement.content, ...extra });
const analysis = extra => ({ id: 'analysis-1', status: 'adopted', requirements: [{ ...requirement, requirement_id: requirement.id, recommendation: { proposed_value: '42°C' } }], ...extra });

test('plain source-backed requirements do not require invented review decisions', () => {
  assert.deepEqual(blockers(fixture()), []);
  assert.deepEqual(blockers(fixture({ source_selection: undefined })), [], 'one file per role is the legacy active-source default');
  assert.match(blockers(fixture({ requirements: [] }))[0].message, /采用有来源的需求/);
});

test('missing or historical evidence and ambiguous primary sources block confirmation', () => {
  for (const ids of [[], ['missing'], ['old-tech']]) {
    const result = blockers(fixture({ requirements: [{ ...requirement, source_ids: ids }] }));
    assert.equal(result[0].requirementId, requirement.id);
    assert.match(result[0].message, /当前来源/);
  }
  const ambiguous = fixture({ source_selection: {}, sources: [source('tech'), { ...source('tech'), id: 'other-tech' }, source('spec')] });
  assert(blockers(ambiguous).some(item => /明确选择/.test(item.message)));
});

test('required clarifications must be explicitly adopted, not merely answered', () => {
  for (const status of ['open', 'answered']) {
    const result = blockers(fixture({ clarifications: [{ requirement_id: requirement.id, required: true, status }] }));
    assert.equal(result[0].requirementId, requirement.id);
    assert.match(result[0].message, /必需澄清尚未采用/);
  }
  assert.deepEqual(blockers(fixture({ clarifications: [{ requirement_id: requirement.id, required: true, status: 'adopted' }] })), []);
});

test('legacy actionable suggestions need a valid actual result, not merely a recorded decision', () => {
  for (const status of ['matched', 'difference', 'needs_review']) {
    const value = fixture({ source_analysis: analysis({ adopted_input_revision: 52,
      source_hashes: { tech: 'tech-hash', spec: 'spec-hash' } }), requirement_recommendations: batch({ items: [{
      requirement_id: requirement.id, requirement_revision: 1, status, proposed_value: requirement.content,
      evidence: [{ source_id: 'spec', quote: requirement.content }],
    }] }) });
    assert.match(blockers(value)[0].message, /规范建议尚未处理/);
    for (const decision of ['reject', 'manual']) {
      value.requirements[0].review = review({ decision });
      assert.match(blockers(value)[0].message, /规范建议尚未处理/, `${decision} is not an actual result`);
    }
    const accepted = { decision: 'accept', ...(status === 'needs_review' ? { actual_value_source: 'original', analysis_id: 'analysis-1' } : {}) };
    value.requirements[0].review = review(accepted);
    if (status === 'difference') assert.match(blockers(value)[0].message, /规范建议尚未处理/);
    else assert.deepEqual(blockers(value), []);
    value.requirements[0].review = review({ ...accepted, requirement_revision: 1 });
    assert.match(blockers(value)[0].message, /尚未处理/);
    value.requirements[0].review = review({ ...accepted, recommendation_batch_id: 'older-batch' });
    assert.match(blockers(value)[0].message, /尚未处理/);
  }
  assert.deepEqual(blockers(fixture({ requirement_recommendations: batch({ status: 'stale', items: [{ requirement_id: requirement.id, status: 'not_found' }] }) })), []);
});

test('clarification adoption resolves a suggestion only for its current batch and requirement revision', () => {
  const adoption = { recommendation_batch_id: 'batch-1', requirement_revision: 2, requirement_content: requirement.content };
  const value = fixture({ requirement_recommendations: batch(), requirements: [{ ...requirement,
    history: [{ revision: 2, clarification_id: 'clarification-1' }] }], clarifications: [{ id: 'clarification-1',
    requirement_id: requirement.id, required: true, status: 'adopted', adoption,
    answer_source_ids: ['spec'], answer_source_snapshots: [source('spec')],
  }] });
  assert.deepEqual(blockers(value), []);
  adoption.recommendation_batch_id = 'older-batch';
  assert.match(blockers(value)[0].message, /规范建议尚未处理/);
  adoption.recommendation_batch_id = 'batch-1'; adoption.requirement_revision = 1;
  assert.match(blockers(value)[0].message, /规范建议尚未处理/);
});

test('stale batch, input revision, replaced sources, and new sources cannot reuse decisions', () => {
  for (const changed of [{ status: 'stale' }, { input_revision: 51 }, { source_hashes: { tech: 'old-hash', spec: 'spec-hash' } }, { source_hashes: { tech: 'tech-hash' } }]) {
    const value = fixture({ requirements: [{ ...requirement, review: review() }], requirement_recommendations: batch(changed) });
    assert.match(blockers(value)[0].message, /批次或来源已变化/);
  }
  const value = fixture({ requirements: [{ ...requirement, review: review() }], requirement_recommendations: batch(), sources: [source('tech'), source('spec'), source('reference')] });
  assert.match(blockers(value)[0].message, /批次或来源已变化/);
});

test('source analysis suggestions never create specification decisions or confirmation blockers', () => {
  const value = fixture({ source_analysis: analysis() });
  value.source_analysis.requirements[0].recommendation.evidence = [{ source_id: 'tech', quote: requirement.content }];
  const before = structuredClone(value);
  assert.deepEqual(blockers(value), [], 'self-cited extraction hints are not specification suggestions');
  assert.deepEqual(value, before, 'reading blockers must preserve historical data');
  value.requirements[0].review = review({ analysis_id: 'analysis-1' });
  assert.deepEqual(blockers(value), []);
  value.requirements[0].review.analysis_id = 'older-analysis';
  assert.deepEqual(blockers(value), []);
  value.source_analysis.status = 'stale';
  assert.deepEqual(blockers(value), [], 'source validity is checked independently of obsolete enhancement hints');
  value.source_analysis.requirements[0].status = 'rejected';
  assert.deepEqual(blockers(value), [], 'rejected suggestions do not require a decision');
});

test('historical extraction hints do not leak into the current requirement confirmation stage', () => {
  const adoptedWithSuggestion = analysis({ adopted_at: '2026-11-05T08:00:00Z' });
  for (const current of [analysis({ id: 'new-analysis', status: 'proposed', requirements: [] }), undefined]) {
    const value = fixture({ source_analysis: current, source_analysis_history: [adoptedWithSuggestion] });
    const before = structuredClone(value);
    assert.deepEqual(blockers(value), []);
    assert.deepEqual(value, before);
  }
});

test('only specification batches own suggestion review gates, independently of analysis history', () => {
  const oldSuggestion = analysis({ adopted_at: '2026-11-05T08:00:00Z' });
  const adoptedWithoutSuggestion = analysis({ id: 'new-adopted', requirements: [], adopted_at: '2026-11-05T09:00:00Z' });
  const current = analysis({ id: 'proposal', status: 'proposed', requirements: [] });
  assert.deepEqual(blockers(fixture({ source_analysis: current, source_analysis_history: [oldSuggestion, adoptedWithoutSuggestion] })), []);
  assert.deepEqual(blockers(fixture({ source_analysis: adoptedWithoutSuggestion, source_analysis_history: [oldSuggestion] })), [], 'current adopted analysis owns its own review gate');
  const rejected = analysis({ status: 'proposed' });
  rejected.requirements[0].status = 'rejected';
  assert.deepEqual(blockers(fixture({ source_analysis: current, source_analysis_history: [rejected] })), []);
  const value = fixture({ source_analysis: oldSuggestion, source_analysis_history: [oldSuggestion], requirement_recommendations: batch(),
    requirements: [{ ...requirement, review: review({ recommendation_batch_id: undefined, analysis_id: oldSuggestion.id }) }] });
  assert.match(blockers(value)[0].message, /规范建议尚未处理/, 'legacy decisions cannot satisfy a new specification batch');
  value.requirements[0].review = review();
  assert.match(blockers(value)[0].message, /规范建议尚未处理/, 'a manual decision cannot supply an adopted result');
  value.requirement_recommendations.items[0] = { requirement_id: requirement.id, requirement_revision: 1,
    status: 'matched', proposed_value: requirement.content, evidence: [{ source_id: 'spec', quote: requirement.content }] };
  value.requirements[0].review = review({ decision: 'accept' });
  assert.deepEqual(blockers(value), []);
});

test('empty or standalone placeholders block, but factual text mentioning clarification remains valid', () => {
  for (const content of ['', '  ', '待澄清', '防水等级：待澄清。', '防水等级: 待补充；', '待确认（客户未反馈）', '防水等级：待澄清 (客户未反馈)。', '【人工填写】']) {
    const result = blockers(fixture({ requirements: [{ ...requirement, content }] }));
    assert.equal(result[0].requirementId, requirement.id);
    assert.match(result[0].message, /明确采用值/);
  }
  for (const content of ['防水等级：IP67，待澄清事项采用单独记录管理。', '待机功耗：2 W', '等待时间：5 秒']) {
    assert.deepEqual(blockers(fixture({ requirements: [{ ...requirement, content }] })), []);
  }
});

test('conflicted or rejected requirements cannot be fixed into the baseline', () => {
  for (const status of ['conflict', 'rejected']) assert.match(blockers(fixture({ requirements: [{ ...requirement, status }] }))[0].message, /冲突或拒绝/);
});

test('v2 requires every actual result to be explicitly accepted or adopted through clarification', () => {
  const value = fixture({ business_lifecycle: { policy_version: 'v2' } });
  assert.match(blockers(value)[0].message, /明确采用|实际结果/);
  value.requirement_recommendations = batch({ items: [{ requirement_id: requirement.id, requirement_revision: 2, status: 'not_found' }] });
  assert.match(blockers(value)[0].message, /明确采用|实际结果/);
  for (const decision of ['manual', 'reject']) {
    value.requirements[0].review = review({ decision });
    assert(blockers(value).length, `${decision} is not an adopted result`);
  }
  value.requirement_recommendations.items[0] = { requirement_id: requirement.id, requirement_revision: 1, status: 'matched', proposed_value: requirement.content };
  value.requirements[0].review = review({ decision: 'accept' });
  assert.deepEqual(blockers(value), []);
  value.requirements.push({ ...requirement, id: 'other', title: '工作压力', review: undefined });
  assert.equal(blockers(value)[0].requirementId, 'other', 'accepting one row cannot resolve another');
});

test('current matched specification indicators can be confirmed together without per-row acceptance', () => {
  const value = fixture({ business_lifecycle: { policy_version: 'v2' }, requirement_recommendations: batch({ items: [{
    requirement_id: requirement.id, requirement_revision: 2, status: 'matched', proposed_value: '5°C～45°C',
    evidence: [{ source_id: 'spec', quote: '5°C～45°C' }],
  }] }) });
  const before = structuredClone(value);
  assert.deepEqual(blockers(value), []);
  assert.deepEqual(value, before, 'displaying readiness must not fabricate an individual acceptance');
  value.requirements[0].content = '待澄清';
  assert.deepEqual(blockers(value), [], 'a valid specification result can complete a missing original value');
  value.requirement_recommendations.items[0].evidence = [];
  assert(blockers(value).length, 'a bare matched label is not evidence');
});

test('legacy matched specification results are automatic, but explicit rejection still blocks', () => {
  const value = fixture({ requirement_recommendations: batch({ items: [{
    requirement_id: requirement.id, requirement_revision: 2, status: 'matched', proposed_value: '5°C～45°C',
    evidence: [{ source_id: 'spec', quote: '5°C～45°C' }],
  }] }) });
  assert.deepEqual(blockers(value), []);
  value.requirements[0].content = '待澄清';
  assert.deepEqual(blockers(value), [], 'the current specification can resolve an unknown original');
  value.requirements[0].content = requirement.content;
  value.requirements[0].review = review({ decision: 'reject' });
  assert.match(blockers(value)[0].message, /规范建议尚未处理/, 'rejecting a match leaves no actual result');
});

test('applicability needs explicit original acceptance before unified confirmation', () => {
  const value = fixture({ business_lifecycle: { policy_version: 'v2' }, source_analysis: analysis({
    adopted_input_revision: 52, source_hashes: { tech: 'tech-hash', spec: 'spec-hash' },
  }), requirement_recommendations: batch({ items: [{ requirement_id: requirement.id, requirement_revision: 1,
    status: 'needs_review', proposed_value: '其他工况的值' }] }) });
  assert(blockers(value).length);
  value.requirements[0].review = review({ decision: 'accept', actual_value_source: 'original', analysis_id: 'analysis-1' });
  assert.deepEqual(blockers(value), []);
  value.requirements[0].content = value.requirements[0].review.actual_value = '其他工况的值';
  assert(blockers(value).length, 'the model proposal must not substitute for the accepted original');
});
