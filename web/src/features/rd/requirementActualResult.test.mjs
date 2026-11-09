import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(new URL('../../../package.json', import.meta.url));
const ts = require('typescript');
function load(name) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(`./${name}.ts`, import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(path => path.startsWith('./') ? load(path.slice(2)) : require(path), module, module.exports);
  return module.exports;
}
const { requirementActualResult: actual, requirementDisplayResult: display } = load('requirementActualResult');
const source = { id: 'tech', role: 'tech', name: '需求.docx', version: 1, sha256: 'tech-hash' };
const row = { id: 'r1', revision: 2, content: '24 V', source_ids: ['tech'], history: [] };
const fixture = () => ({ input_revision: 8, sources: [source], source_selection: { tech: 'tech' }, requirements: [structuredClone(row)], clarifications: [], business_lifecycle: { policy_version: 'v2' } });
function accepted() {
  const value = fixture();
  value.requirement_recommendations = { id: 'batch', status: 'current', input_revision: 8, source_hashes: { tech: 'tech-hash' }, items: [{ requirement_id: 'r1', requirement_revision: 1, status: 'matched', proposed_value: '24 V' }] };
  value.requirements[0].review = { decision: 'accept', actual_value: '24 V', requirement_revision: 2, recommendation_batch_id: 'batch' };
  return value;
}
function clarified() {
  const value = fixture();
  value.requirements[0].history = [{ revision: 2, clarification_id: 'clar-1' }];
  value.clarifications = [{ id: 'clar-1', requirement_id: 'r1', status: 'adopted', answer_source_ids: ['tech'], answer_source_snapshots: [source], adoption: { requirement_revision: 2, requirement_content: '24 V', input_revision: 7, source_hashes: { tech: 'tech-hash' } } }];
  return value;
}
test('source content and historic manual decisions never become an unconfirmed actual result', () => {
  const value = fixture(), before = structuredClone(value);
  assert.equal(actual(value, value.requirements[0]), null);
  assert.equal(display(value, value.requirements[0]), null);
  assert.deepEqual(value, before);
  for (const decision of ['manual', 'reject', 'accept']) {
    value.requirements[0].review = { decision, actual_value: '24 V', requirement_revision: 2, analysis_id: 'analysis-1' };
    assert.equal(actual(value, value.requirements[0]), null);
  }
});
test('only explicit matched acceptance of the current batch supplies the actual value', () => {
  const value = accepted();
  assert.deepEqual(actual(value, value.requirements[0]), { value: '24 V', kind: 'accepted' });
  for (const change of [v => { v.requirements[0].review.decision = 'reject'; }, v => { v.requirements[0].review.decision = 'manual'; }, v => { v.requirements[0].review.requirement_revision = 1; }, v => { v.requirements[0].content = '12 V'; }, v => { v.requirement_recommendations.items[0].status = 'difference'; }, v => { v.requirement_recommendations.id = 'new-batch'; }, v => { v.requirement_recommendations.status = 'stale'; }, v => { v.requirement_recommendations.input_revision = 7; }, v => { v.sources = [{ ...source, sha256: 'replacement' }]; }]) {
    const changed = accepted(); change(changed); assert.equal(actual(changed, changed.requirements[0]), null);
  }
});

function originalAccepted() {
  const value = accepted();
  value.requirement_recommendations.items[0].status = 'needs_review';
  value.requirement_recommendations.items[0].proposed_value = '12 V';
  value.source_analysis = { id: 'analysis', status: 'adopted', adopted_input_revision: 8,
    source_hashes: { tech: 'tech-hash' }, requirements: [{ requirement_id: 'r1', content: '24 V', source_ids: ['tech'] }] };
  Object.assign(value.requirements[0].review, { analysis_id: 'analysis', actual_value_source: 'original' });
  return value;
}
function specificationMatched() {
  const value = fixture();
  value.sources.push({ ...source, id: 'spec', role: 'spec', name: '规范.docx', sha256: 'spec-hash' });
  value.source_selection.spec = 'spec';
  value.requirement_recommendations = { id: 'batch', status: 'current', input_revision: 8,
    source_hashes: { tech: 'tech-hash', spec: 'spec-hash' }, items: [{ requirement_id: 'r1', requirement_revision: 2,
      status: 'matched', proposed_value: '额定电压 24 V DC', evidence: [{ source_id: 'spec', quote: '额定电压 24 V DC' }] }] };
  return value;
}
test('a current matched specification automatically supplies its value without inventing an acceptance', () => {
  const value = specificationMatched(), before = structuredClone(value);
  assert.deepEqual(actual(value, value.requirements[0]), { value: '额定电压 24 V DC', kind: 'specification' });
  assert.deepEqual(value, before);
  assert.equal(value.requirements[0].content, '24 V');
  assert.equal(value.requirements[0].review, undefined);
});
test('automatic specification values require current row, sources, evidence and resolved proposal', () => {
  for (const change of [
    v => { v.requirement_recommendations.items[0].requirement_revision = 1; },
    v => { v.requirement_recommendations.status = 'stale'; },
    v => { v.requirement_recommendations.source_hashes.spec = 'old'; },
    v => { v.requirement_recommendations.items[0].proposed_value = '待确认'; },
    v => { v.requirement_recommendations.items[0].evidence = []; },
    v => { v.requirement_recommendations.items[0].evidence[0].source_id = 'tech'; },
    v => { v.requirement_recommendations.items[0].evidence[0].quote = ''; },
    v => { v.requirements[0].review = { decision: 'reject', recommendation_batch_id: 'batch', requirement_revision: 2 }; },
    v => { v.requirement_recommendations.items.push(structuredClone(v.requirement_recommendations.items[0])); },
  ]) {
    const value = specificationMatched(); change(value);
    assert.equal(actual(value, value.requirements[0]), null);
  }
});

test('a resolved specification fills an unknown original, and survives unified confirmation of sibling rows', () => {
  const value = specificationMatched(), requirement = value.requirements[0];
  requirement.content = '待澄清';
  assert.deepEqual(actual(value, requirement), { value: '额定电压 24 V DC', kind: 'specification' });
  requirement.content = '额定电压 24 V DC';
  requirement.revision = 3;
  requirement.specification_result = { actual_value_source: 'specification', actual_value: requirement.content,
    recommendation_batch_id: 'batch', source_requirement_revision: 2, requirement_revision: 3,
    source_hashes: { tech: 'tech-hash', spec: 'spec-hash' }, input_revision: 8 };
  value.input_revision = value.requirement_recommendations.input_revision = 10;
  assert.deepEqual(actual(value, requirement), { value: requirement.content, kind: 'specification' });
  requirement.specification_result.source_hashes.spec = 'replaced';
  assert.equal(actual(value, requirement), null);
});
test('an adopted clarification takes precedence over a matched specification suggestion', () => {
  const value = specificationMatched();
  value.requirements[0].history = [{ revision: 2, clarification_id: 'clar-1' }];
  value.clarifications = clarified().clarifications;
  Object.assign(value.clarifications[0].adoption, { recommendation_batch_id: 'batch', source_hashes: { tech: 'tech-hash', spec: 'spec-hash' } });
  assert.deepEqual(actual(value, value.requirements[0]), { value: '24 V', kind: 'clarified' });
});
test('explicit applicability acceptance uses the original indicator, not the model proposal', () => {
  const value = originalAccepted();
  assert.deepEqual(actual(value, value.requirements[0]), { value: '24 V', kind: 'accepted' });
  delete value.requirement_recommendations.items[0].proposed_value;
  assert.deepEqual(actual(value, value.requirements[0]), { value: '24 V', kind: 'accepted' });
});
test('applicability acceptance requires an explicit original decision and a current original snapshot', () => {
  for (const change of [
    v => { delete v.requirements[0].review; },
    v => { delete v.requirements[0].review.actual_value_source; },
    v => { v.requirements[0].review.decision = 'reject'; },
    v => { v.requirements[0].review.analysis_id = 'old-analysis'; },
    v => { v.requirements[0].review.requirement_revision = 1; },
    v => { v.requirements[0].content = v.requirements[0].review.actual_value = '12 V'; },
    v => { v.source_analysis.requirements = []; },
    v => { v.source_analysis.requirements[0].content = '待确认'; },
    v => { v.source_analysis.requirements[0].source_ids = ['archived']; },
    v => { v.source_analysis.status = 'stale'; },
    v => { v.source_analysis.adopted_input_revision = 7; },
    v => { v.source_analysis.source_hashes = {}; },
    v => { v.requirement_recommendations.status = 'stale'; },
  ]) {
    const value = originalAccepted(); change(value);
    assert.equal(actual(value, value.requirements[0]), null);
  }
});
test('clarification adoption is tied to row revision, content and adoption history, not unrelated input changes', () => {
  const value = clarified();
  assert.deepEqual(actual(value, value.requirements[0]), { value: '24 V', kind: 'clarified' });
  value.input_revision = 99;
  assert.deepEqual(actual(value, value.requirements[0]), { value: '24 V', kind: 'clarified' });
  for (const change of [v => { v.clarifications[0].status = 'answered'; }, v => { v.requirements[0].history = []; }, v => { v.requirements[0].revision++; }, v => { v.requirements[0].content = '12 V'; }, v => { v.clarifications[0].answer_source_snapshots = []; }, v => { v.clarifications[0].adoption.source_hashes = {}; }, v => { v.sources = [{ ...source, sha256: 'replacement' }]; }]) {
    const changed = clarified(); change(changed); assert.equal(actual(changed, changed.requirements[0]), null);
  }
  value.requirement_recommendations = accepted().requirement_recommendations;
  value.requirement_recommendations.input_revision = 99;
  assert.equal(actual(value, value.requirements[0]), null, 'a new spec batch must not reuse an older clarification');
  value.clarifications[0].adoption.recommendation_batch_id = 'batch';
  assert.equal(actual(value, value.requirements[0]).kind, 'clarified');
});
test('fixed historical baseline values remain visible but are not a new unconfirmed decision', () => {
  const value = fixture();
  value.requirements[0].review = { decision: 'manual', actual_value: '24 V', requirement_revision: 2 };
  value.business_lifecycle.current_requirement_baseline_id = 'baseline';
  value.requirement_baselines = [{ id: 'baseline', status: 'current', input_revision: 8, items: structuredClone(value.requirements), source_refs: [source] }];
  assert.equal(actual(value, value.requirements[0]), null);
  assert.deepEqual(display(value, value.requirements[0]), { value: '24 V', kind: 'baseline' });
  value.requirement_baselines[0].invalidated_at = '2026-11-06';
  assert.equal(display(value, value.requirements[0]), null);
});

test('legacy clarification adoption cannot reuse inactive requirement or answer sources', () => {
  for (const replace of ['requirement', 'answer']) {
    const value = clarified();
    const reference = { id: 'ref', role: 'reference', name: '答复.docx', version: 1, sha256: 'ref-hash' };
    value.sources.push(reference);
    delete value.clarifications[0].adoption.source_hashes;
    if (replace === 'requirement') {
      value.clarifications[0].answer_source_ids = ['ref'];
      value.clarifications[0].answer_source_snapshots = [reference];
    } else value.requirements[0].source_ids = ['ref'];
    value.sources.push({ ...source, id: 'new-tech' });
    value.source_selection.tech = 'new-tech';
    assert.equal(actual(value, value.requirements[0]), null, replace + ' must use current sources');
  }
});

test('a current batch cannot revive acceptance of a row whose original source is inactive', () => {
  const value = accepted();
  value.sources.push({ ...source, id: 'new-tech' });
  value.source_selection.tech = 'new-tech';
  value.requirement_recommendations.source_hashes = { 'new-tech': 'tech-hash' };
  assert.equal(actual(value, value.requirements[0]), null);
});

test('an acceptance or clarification cannot turn an empty value or placeholder into an actual result', () => {
  for (const content of ['', '  ', '--', '待澄清', '防水等级：待澄清。', '【人工填写】']) {
    const value = accepted();
    value.requirements[0].content = content;
    value.requirements[0].review.actual_value = content;
    value.requirement_recommendations.items[0].proposed_value = content;
    assert.equal(actual(value, value.requirements[0]), null);
    const clarification = clarified();
    clarification.requirements[0].content = content;
    clarification.clarifications[0].adoption.requirement_content = content;
    assert.equal(actual(clarification, clarification.requirements[0]), null);
  }
});
