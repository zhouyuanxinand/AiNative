/** Controlled engine values shared by the standalone and project-native forms. */
export const PROCESS_OPTIONS = [
  { value: '全新', label: '全新' },
  { value: '改型I', label: '改型I' },
  { value: '改型II', label: '改型II' },
  { value: '改型III', label: '改型III' },
];
export const COVER_PHASE_OPTIONS = [
  { value: '', label: '请选择 F / C / S / D' },
  ...['F', 'C', 'S', 'D'].map(value => ({ value, label: value })),
];
export const ORGANIZATION_OPTIONS = [
  { value: 'non_central_research', label: '非中央研究院产品' },
  { value: 'central_research', label: '中央研究院产品' },
];
export function nativeParameterIssues(parameters: Record<string, unknown>) {
  const issues: string[] = [];
  if (!PROCESS_OPTIONS.some(item => item.value === parameters.development_process)) issues.push('请选择受控研制流程分类');
  if (!COVER_PHASE_OPTIONS.some(item => item.value && item.value === parameters.cover_phase)) issues.push('请选择封面研制阶段 F / C / S / D');
  if (!ORGANIZATION_OPTIONS.some(item => item.value === parameters.organization_scope)) issues.push('请选择产品归属范围');
  if (typeof parameters.product_series !== 'string' || !parameters.product_series.trim()) issues.push('请填写产品系列');
  if (!parameters.product_type || !parameters.product_domain) issues.push('请选择产品类型与领域');
  if (parameters.use_llm !== true) issues.push('受控编制需要启用所选模型');
  return issues;
}
