import type { BusinessWorkflowTemplate } from './types';

/** Describe configuration changes without treating coordinates as execution logic. */
export function workflowTemplateDiff(before: BusinessWorkflowTemplate, after: BusinessWorkflowTemplate, resourceNames: Record<string, string> = {}) {
  const changes: Array<{ kind: string; title: string; before?: string; after?: string }> = [];
  const text = (value: unknown): string => {
    if (value == null) return '未设置';
    if (Array.isArray(value)) return value.join('、') || '未设置';
    if (typeof value === 'object') {
      const fields = value as Record<string, unknown>;
      if ('resource_id' in fields) return `${resourceNames[String(fields.resource_id)] || fields.resource_id} · V${fields.resource_version}`;
      if ('x' in fields && 'y' in fields) return `位置 (${fields.x}, ${fields.y})`;
    }
    return value === 'taskbook' ? '任务书装配与校验' : value === 'input_check' ? '资料一致性检查' : String(value);
  };
  if (before.title !== after.title) changes.push({ kind: '名称', title: '流程名称', before: before.title, after: after.title });
  if (before.product_route !== after.product_route) changes.push({ kind: '条件', title: '适用研发路线', before: before.product_route === 'new' ? '全新研发' : before.product_route === 'modification' ? '改型研发' : '选型', after: after.product_route === 'new' ? '全新研发' : after.product_route === 'modification' ? '改型研发' : '选型' });
  for (const node of before.graph.nodes) if (!after.graph.nodes.some(item => item.id === node.id)) changes.push({ kind: '删除节点', title: node.title || node.id });
  const fields = { title: '名称', role: '负责角色', deliverables: '交付物', action_resource: '动作能力', workpackage_definition_id: '工作包', gate: '业务关口' } as const;
  for (const node of after.graph.nodes) {
    const old = before.graph.nodes.find(item => item.id === node.id);
    if (!old) { changes.push({ kind: '新增节点', title: node.title || node.id }); continue; }
    for (const [field, label] of Object.entries(fields)) {
      const key = field as keyof typeof fields;
      if (JSON.stringify(old[key]) !== JSON.stringify(node[key])) changes.push({ kind: '修改属性', title: `${node.title || node.id} · ${label}`, before: text(old[key]), after: text(node[key]) });
    }
    if (JSON.stringify(old.position) !== JSON.stringify(node.position)) changes.push({ kind: '仅布局', title: node.title || node.id, before: text(old.position), after: text(node.position) });
  }
  for (const [from, to, kind] of [[before, after, '删除依赖'], [after, before, '新增依赖']] as const) {
    for (const edge of from.graph.edges) if (!to.graph.edges.some(item => item.source === edge.source && item.target === edge.target)) changes.push({ kind, title: `${from.graph.nodes.find(node => node.id === edge.source)?.title || edge.source} → ${from.graph.nodes.find(node => node.id === edge.target)?.title || edge.target}` });
  }
  return changes;
}
