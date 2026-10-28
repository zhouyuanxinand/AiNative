import assert from 'node:assert/strict';
import test from 'node:test';
import { exampleWbsTemplate, parseWbsTemplate, WBS_TEMPLATE_MAX_BYTES } from '../../src/features/taskbook/model/wbsTemplate.ts';

const scope = { memberIds: ['author', 'reviewer'], requirementIds: ['requirement-one'] };
const complete = () => { const template = exampleWbsTemplate(); template.items[0] = { ...template.items[0], title: '连接器方案设计', assignee_id: 'author', reviewer_id: 'reviewer', acceptance_owner_id: 'reviewer', requirement_ids: ['requirement-one'], output_anchor: 'body-1', deliverable: '方案报告\n保留原文换行', acceptance: '人工核对适用要求', verification_method: '设计审查', planned_start: '2026-10-28', planned_end: '2026-11-02' }; return template; };
const parse = value => parseWbsTemplate(JSON.stringify(value), scope);

test('a design/verification template keeps dependencies and engineer text as an unsaved candidate', () => {
  const template = complete(), result = parse(template);
  assert.equal(result.length, 2);
  assert.equal(result[0].title, '连接器方案设计');
  assert.equal(result[0].deliverable, '方案报告\n保留原文换行');
  assert.deepEqual(result[1].predecessor_ids, [result[0].id]);
  assert.deepEqual(result[0].requirement_ids, ['requirement-one']);
  assert.equal(result[1].title, '', 'incomplete business fields remain visible for manual completion, not silently fabricated');
});

test('the downloadable example roundtrips as a blank draft without inventing project members or requirements', () => {
  const result = parseWbsTemplate('\uFEFF' + JSON.stringify(exampleWbsTemplate()), { memberIds: [], requirementIds: [] });
  assert.equal(result[0].assignee_id, '');
  assert.equal(result[0].output_anchor, '');
  assert.deepEqual(result[0].requirement_ids, []);
});

test('malformed JSON and wrong template shape explain how to correct the import', () => {
  assert.throws(() => parseWbsTemplate('{"items": [}', scope), /JSON 格式错误/);
  assert.throws(() => parse({ schema_version: 2, items: [] }), /schema_version: 1/);
  assert.throws(() => parse({ schema_version: 1, items: {} }), /条目数组/);
  assert.throws(() => parse({ schema_version: 1, items: [] }), /1 至 500/);
});

test('a bad later row rejects the entire candidate with field and row context', () => {
  const template = complete(); template.items[1].title = 42;
  assert.throws(() => parse(template), /条目 2：.*工作名称.*文本/);
  const wrongArray = complete(); wrongArray.items[0].requirement_ids = 'requirement-one';
  assert.throws(() => parse(wrongArray), /条目 1：.*关联需求.*数组/);
  const mixed = complete(); mixed.items[1].predecessor_ids = ['design-1', 17];
  assert.throws(() => parse(mixed), /条目 2：.*前置工作.*数组/);
  const unknown = complete(); unknown.items[0].assignee = 'author';
  assert.throws(() => parse(unknown), /不支持的字段“assignee”/);
});

test('foreign members and requirements cannot become invisible values in the project selectors', () => {
  const foreignMember = complete(); foreignMember.items[0].assignee_id = 'other-project-member';
  assert.throws(() => parse(foreignMember), /执行人.*不是本项目成员/);
  const foreignRequirement = complete(); foreignRequirement.items[0].requirement_ids = ['other-project-requirement'];
  assert.throws(() => parse(foreignRequirement), /不属于本任务采用的需求基线/);
});

test('duplicate IDs, dangling predecessors and invalid dates fail before any replacement is accepted', () => {
  const duplicate = complete(); duplicate.items[1].id = duplicate.items[0].id;
  assert.throws(() => parse(duplicate), /条目编号重复/);
  const missing = complete(); missing.items[1].predecessor_ids = ['missing-row'];
  assert.throws(() => parse(missing), /前置工作必须引用模板内的其他条目/);
  const invalidDate = complete(); invalidDate.items[0].planned_start = '2026-02-30';
  assert.throws(() => parse(invalidDate), /计划开始.*有效的.*日期/);
  const reversed = complete(); reversed.items[0].planned_end = '2026-10-27';
  assert.throws(() => parse(reversed), /计划结束不能早于计划开始/);
});

test('large files are rejected before JSON parsing', () => {
  assert.throws(() => parseWbsTemplate('x'.repeat(WBS_TEMPLATE_MAX_BYTES + 1), scope), /超过 2 MB/);
});
