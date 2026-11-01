import type { EngineeringRecord, ResearchCase } from './types';
export const ENGINEERING_NODES = [{ id: 'scheme', title: '方案设计', output: '方案报告、配置与BOM、差异处理依据' }, { id: 'detail', title: '详细设计', output: '专业图纸与规格、接口核对、设计验证记录' }, { id: 'integration', title: '方案整合', output: '受控配置、整合报告与待办闭环依据' }] as const;
export function engineeringState(researchCase: ResearchCase) {
  const binding = researchCase.taskbook_binding;
  const bindingCurrent = !!binding && binding.status === 'current' && !binding.invalidated_at && binding.input_revision === researchCase.input_revision;
  const nodes = ENGINEERING_NODES.filter(node => binding?.workflow?.nodes.includes(node.id));
  const latest = nodes.map(node => (researchCase.engineering_records ?? []).filter(record => record.node_id === node.id && record.binding_id === binding?.id && record.input_revision === researchCase.input_revision).slice(-1)[0]);
  const records: Array<EngineeringRecord | undefined> = [];
  nodes.forEach((_, index) => {
    const record = latest[index];
    const prerequisites = records.slice(0, index);
    const expected = prerequisites.map(prior => prior?.id);
    const actual = record?.prerequisite_record_ids;
    const matches = !!actual && actual.length === expected.length && actual.every((id, i) => id === expected[i]);
    records.push(bindingCurrent && record && prerequisites.every(prior => prior?.verdict === 'approved') && matches ? record : undefined);
  });
  return { bindingCurrent, nodes, latest, records, complete: bindingCurrent && nodes.length > 0 && records.every(record => record?.verdict === 'approved') };
}
