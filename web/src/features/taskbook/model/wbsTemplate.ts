import type { NativeWbsItem } from '../api/workspace';

export const WBS_TEMPLATE_MAX_BYTES = 2 * 1024 * 1024;
const textFields = ['id', 'title', 'kind', 'assignee_id', 'reviewer_id', 'output_anchor', 'deliverable', 'acceptance', 'acceptance_owner_id', 'verification_method'] as const;
const arrayFields = ['requirement_ids', 'predecessor_ids'] as const;
const dateFields = ['planned_start', 'planned_end'] as const;
const labels: Record<string, string> = { id: '条目编号', title: '工作名称', kind: '条目用途', assignee_id: '执行人', reviewer_id: '独立审核人', output_anchor: '任务书位置', deliverable: '交付物', acceptance: '验收判据', acceptance_owner_id: '接受责任人', verification_method: '验证方法', requirement_ids: '关联需求', predecessor_ids: '前置工作', planned_start: '计划开始', planned_end: '计划结束' };
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
export interface WbsImportScope { memberIds: string[]; requirementIds: string[] }

/** Parse into a separate candidate; the caller decides when to replace its unsaved draft. */
export function parseWbsTemplate(text: string, scope: WbsImportScope): NativeWbsItem[] {
  if (new TextEncoder().encode(text).byteLength > WBS_TEMPLATE_MAX_BYTES) throw new Error('模板超过 2 MB，请缩减条目后重试。');
  let document: unknown;
  try { document = JSON.parse(text.replace(/^\uFEFF/, '')); } catch { throw new Error('JSON 格式错误，请检查引号、逗号和括号，或重新下载示例模板。'); }
  if (!object(document) || document.schema_version !== 1 || !Array.isArray(document.items)) throw new Error('模板须包含 schema_version: 1 和 items 条目数组，请按示例文件整理。');
  if (!document.items.length || document.items.length > 500) throw new Error('模板须包含 1 至 500 个工作条目。');
  const allowed = new Set<string>([...textFields, ...arrayFields, ...dateFields]);
  const items = document.items.map((value: unknown, index: number) => {
    const fail = (message: string): never => { throw new Error(`条目 ${index + 1}：${message}`); };
    if (!object(value)) return fail('必须是包含工作字段的对象。');
    const unknown = Object.keys(value).find(key => !allowed.has(key));
    if (unknown) return fail(`存在不支持的字段“${unknown}”，请按示例字段填写。`);
    for (const field of textFields) if (typeof value[field] !== 'string') fail(`“${labels[field]}”必须是文本，不能缺省或填写为数组、数字。`);
    if (!String(value.id).trim() || value.id !== String(value.id).trim()) fail('条目编号须为非空文本，且不能以空格开头或结尾。');
    if (!['design', 'verification', 'work'].includes(String(value.kind))) fail('条目用途只能是 design、verification 或 work。');
    for (const field of arrayFields) {
      const refs = value[field];
      if (!Array.isArray(refs) || refs.some(ref => typeof ref !== 'string' || !ref.trim() || ref !== ref.trim())) fail(`“${labels[field]}”必须是编号文本数组；未填写时使用 []。`);
      if (new Set(refs as string[]).size !== (refs as string[]).length) fail(`“${labels[field]}”不能包含重复编号。`);
    }
    for (const field of ['assignee_id', 'reviewer_id', 'acceptance_owner_id']) if (value[field] && !scope.memberIds.includes(String(value[field]))) fail(`“${labels[field]}”不是本项目成员；可留空，导入后在面板中重新选择。`);
    if ((value.requirement_ids as string[]).some(id => !scope.requirementIds.includes(id))) fail('关联需求不属于本任务采用的需求基线；可使用 []，导入后按需求名称选择。');
    for (const field of dateFields) {
      const date = value[field];
      if (date !== undefined && typeof date !== 'string') fail(`“${labels[field]}”必须是 YYYY-MM-DD 文本或空文本。`);
      if (date && (!/^\d{4}-\d{2}-\d{2}$/.test(String(date)) || !Number.isFinite(Date.parse(String(date))) || new Date(String(date)).toISOString().slice(0, 10) !== date)) fail(`“${labels[field]}”不是有效的 YYYY-MM-DD 日期。`);
    }
    if (value.planned_start && value.planned_end && String(value.planned_start) > String(value.planned_end)) fail('计划结束不能早于计划开始。');
    return value as unknown as NativeWbsItem;
  });
  const ids = new Set(items.map(item => item.id));
  if (ids.size !== items.length) throw new Error('模板中的条目编号重复，请为每个条目使用独立编号。');
  for (const [index, item] of items.entries()) if (item.predecessor_ids.some(id => !ids.has(id) || id === item.id)) throw new Error(`条目 ${index + 1}：前置工作必须引用模板内的其他条目。`);
  return items;
}

/** Blank business fields deliberately require the engineer's review before server save. */
export function exampleWbsTemplate() {
  const item = (id: string, kind: string, predecessor_ids: string[]): NativeWbsItem => ({ id, title: '', kind, assignee_id: '', reviewer_id: '', requirement_ids: [], output_anchor: '', deliverable: '', acceptance: '', acceptance_owner_id: '', verification_method: '', predecessor_ids, planned_start: '', planned_end: '' });
  return { schema_version: 1, items: [item('design-1', 'design', []), item('verification-1', 'verification', ['design-1'])] };
}
