import { engineeringState } from './engineeringState';
import { CONTEXT_FIELDS, isCurrentSource, STAGES } from './presentation';
import { caseArtifactRecords, summarizeCaseOutcome } from './caseOutcomeModel';
import { requirementConfirmationBlockers } from './requirementConfirmation';
import type { ResearchCase, StageId } from './types';

export type CaseSurface = 'current' | 'preparation' | 'sources' | 'requirements' | 'routes' | 'workpackages' | 'delivery' | 'reuse' | 'decision';
export type OutcomeKind = 'sources' | 'requirements' | 'comparisons' | 'routes' | 'artifacts' | 'verification' | 'delivery' | 'reuse';
export interface ScenarioStage { title: string; guidance: string; outcomeTitle: string; outcome: OutcomeKind; edit: CaseSurface; editLabel: string; primaryArtifactKinds?: string[] }
export interface ScenarioManifest {
  id: string; title: string; parameterTitle: string; parameters: typeof CONTEXT_FIELDS;
  stages: Record<StageId, ScenarioStage>;
  surfaces: Array<{ id: Exclude<CaseSurface, 'current'>; label: string }>;
}

const taskbook: ScenarioManifest = {
  id: 'taskbook', title: '研制任务书编制', parameterTitle: '任务书场景参数', parameters: CONTEXT_FIELDS,
  stages: {
    input: { title: '资料输入与需求澄清', guidance: '上传需求与企业资料，分析原文并确认采用；资料未明确的参数由后续流程继续形成。', outcomeTitle: '输入资料包', outcome: 'sources', edit: 'sources', editLabel: '分析资料并确认采用' },
    requirements: { title: '需求确认', guidance: '核对有来源的需求，处理澄清答复并明确采用内容。', outcomeTitle: '当前需求清单', outcome: 'requirements', edit: 'requirements', editLabel: '核对需求与处理澄清' },
    selection: { title: '选型决策', guidance: '根据逐项比对，分别确定产品研制分类和任务书编制策略。', outcomeTitle: '选型与编制比对', outcome: 'comparisons', edit: 'routes', editLabel: '核对比对与两个决策项' },
    planning: { title: '采用研发流程与编制任务书', guidance: '继承已确认需求与选型差异，选择研发流程模板，固定任务书编制输入。', outcomeTitle: '研发流程与任务书准备', outcome: 'routes', edit: 'preparation', editLabel: '选择流程并固定任务书输入' },
    design: { title: '任务书编制', guidance: '拉取工作包，按需调整计划后确认提交；包内步骤自主执行。', outcomeTitle: '任务书编制成果', outcome: 'artifacts', edit: 'workpackages', editLabel: '编排与执行工作包', primaryArtifactKinds: ['taskbook', 'docx'] },
    verification: { title: '验证及审签', guidance: '查看固定成果及核验结果，业务确认以实际记录为准。', outcomeTitle: '成果与核验结果', outcome: 'verification', edit: 'workpackages', editLabel: '查看或发起成果核验', primaryArtifactKinds: ['taskbook', 'docx', 'verification'] },
    delivery: { title: '交付与反馈', guidance: '关联实际成果，登记接收凭据及反馈。', outcomeTitle: '交付与反馈记录', outcome: 'delivery', edit: 'delivery', editLabel: '登记交付与反馈' },
    knowledge: { title: '复用整理', guidance: '整理案例内可复用内容，或在阶段决定中记录不发布的依据。', outcomeTitle: '可复用内容候选', outcome: 'reuse', edit: 'reuse', editLabel: '整理复用候选' },
  },
  surfaces: [
    { id: 'sources', label: '资料识别与项目信息' }, { id: 'requirements', label: '需求与澄清' },
    { id: 'routes', label: '比对与决策' }, { id: 'preparation', label: '研发流程与任务书准备' }, { id: 'workpackages', label: '工作包编排与执行' },
    { id: 'delivery', label: '交付与反馈' }, { id: 'reuse', label: '复用候选' }, { id: 'decision', label: '本阶段业务确认' },
  ],
};

const scenarios: Record<string, ScenarioManifest> = { taskbook };
export function scenarioManifest(id: string): ScenarioManifest | undefined { return scenarios[id]; }

export function scenarioStage(researchCase: ResearchCase, manifest?: ScenarioManifest): ScenarioStage {
  if (researchCase.workflow_templates?.project && researchCase.stage === 'planning') return {
    title: '研制任务书生成', guidance: researchCase.project_workflow_status?.status === 'completed'
      ? '本次流程已完成，可查看任务书、质量报告及固定版本的执行记录。'
      : '沿用已选流程，固定当前需求与文档模板；提交工作包后完成编制和质量校验。',
    outcomeTitle: '研制任务书生成成果', outcome: 'artifacts', edit: researchCase.project_workflow_status?.status === 'completed' ? 'workpackages' : 'preparation', editLabel: researchCase.project_workflow_status?.status === 'completed' ? '查看任务书工作包' : '核对固定流程与任务书输入', primaryArtifactKinds: ['taskbook', 'docx'],
  };
  if (manifest?.id === 'taskbook' && researchCase.business_lifecycle?.policy_version === 'v2') {
    if (researchCase.business_lifecycle.rd_activation_state === 'historical_unverified') return { ...manifest.stages[researchCase.stage], title: '历史记录待核对', guidance: '原阶段与成果继续保留，不能推断已取得研发启动或任务书范围批准。请在项目空间新建业务流程，按当前政策重新确认后续办。', edit: 'sources', editLabel: '核对历史来源' };
    if (researchCase.stage === 'selection') return { ...manifest.stages.selection, title: '选型决定与研发启动', guidance: '核对固定选型报告并记录决定；改型与新研需再单独确认研发启动。' };
    if (researchCase.stage === 'planning') return { title: '研发策划与任务书', guidance: '采用流程并固定输入，在本阶段编排任务书工作包；完成质量核验后办理范围批准。', outcomeTitle: '策划任务书与范围核对', outcome: 'artifacts', edit: 'preparation', editLabel: '核对流程与任务书输入', primaryArtifactKinds: ['taskbook', 'docx'] };
    if (researchCase.stage === 'design') return { ...manifest.stages.design, title: '工程设计', guidance: '任务书范围已批准，按实际工程证据办理方案设计、详细设计与整合。', editLabel: '办理工程设计与查看工作包' };
  }
  return manifest?.stages[researchCase.stage] ?? {
    title: STAGES.find(stage => stage.id === researchCase.stage)?.title ?? researchCase.stage,
    guidance: '查看已登记成果和项目记录；此场景尚未配置原生工作面。', outcomeTitle: '已登记成果',
    outcome: 'artifacts', edit: 'workpackages', editLabel: '查看工作包记录',
  };
}

export function nextCaseAction(researchCase: ResearchCase, manifest?: ScenarioManifest): { target: CaseSurface; label: string } | null {
  if (researchCase.workflow_templates?.project && researchCase.project_workflow_status?.status === 'completed') return null;
  if (!manifest || researchCase.status === 'completed' || researchCase.business_lifecycle?.rd_activation_state === 'historical_unverified' && researchCase.business_lifecycle.policy_version === 'v2') return null;
  const stage = scenarioStage(researchCase, manifest);
  const state = summarizeCaseOutcome(researchCase);
  if (state.execution.kind === 'running') return { target: 'workpackages', label: '查看执行进展' };
  if (state.blockedPackages.length) return { target: 'workpackages', label: '查看阻塞与证据缺口' };
  if (state.execution.kind === 'draft') return { target: 'workpackages', label: '检查计划并确认提交' };
  const sources = researchCase.sources.filter(source => isCurrentSource(source, researchCase.source_selection));
  const currentSourceIds = new Set(sources.map(source => source.id));
  const hasRequirements = researchCase.requirements.length > 0 && researchCase.requirements.every(item => item.source_ids.length > 0 && item.source_ids.every(id => currentSourceIds.has(id)));
  const requiredClarifications = researchCase.clarifications?.some(item => item.required && (item.status !== 'adopted' || !!item.invalidated_at));
  const hasDeliverable = caseArtifactRecords(researchCase).some(item => item.current && item.workpackage.status === 'completed' && ['docx', 'taskbook'].includes(item.artifact.kind ?? ''));
  const analysis = researchCase.source_analysis;
  const adoptedAnalysis = analysis?.status === 'adopted' && analysis.adopted_input_revision === researchCase.input_revision;
  if (researchCase.business_lifecycle?.policy_version === 'v2') {
    if (['input', 'requirements'].includes(researchCase.stage)) return !requirementConfirmationBlockers(researchCase).length
      ? { target: 'decision', label: '确认需求并进入选型' } : { target: hasRequirements ? 'requirements' : 'sources', label: hasRequirements ? '处理需求与关键澄清' : '分析资料并确认采用' };
    if (researchCase.stage === 'selection') return researchCase.product_route && researchCase.composition_route
      ? { target: 'decision', label: researchCase.business_lifecycle.current_selection_decision_id ? '办理研发启动' : '核对选型报告与决定' }
      : { target: 'routes', label: '核对逐项证据与选型路线' };
    if (researchCase.stage === 'planning') {
      const binding = researchCase.taskbook_binding;
      if (!binding || binding.status !== 'current' || binding.invalidated_at || binding.input_revision !== researchCase.input_revision) return { target: 'preparation', label: '采用流程并固定任务书输入' };
      if (researchCase.workflow_templates?.project) return { target: 'workpackages', label: hasDeliverable ? '查看生成成果与执行记录' : '编排与执行任务书工作包' };
      return hasDeliverable && state.verification.kind === 'passed' ? { target: 'decision', label: '核对并批准任务书范围' } : { target: 'workpackages', label: '编排与执行任务书工作包' };
    }
  }
  const ready = researchCase.stage === 'input' ? ['tech', 'spec'].every(role => sources.some(source => source.role === role)) && (adoptedAnalysis || !analysis && hasRequirements)
    : researchCase.stage === 'requirements' ? hasRequirements && !requiredClarifications
      : researchCase.stage === 'planning' ? researchCase.product_route?.value === 'direct' || !!researchCase.taskbook_binding && researchCase.taskbook_binding.status === 'current' && !researchCase.taskbook_binding.invalidated_at && researchCase.taskbook_binding.input_revision === researchCase.input_revision
      : researchCase.stage === 'selection' ? !!researchCase.product_route && !!researchCase.composition_route
        : ['design', 'verification'].includes(researchCase.stage) ? hasDeliverable && state.verification.kind === 'passed' && (researchCase.stage !== 'design' || engineeringState(researchCase).complete)
          : researchCase.stage === 'delivery' ? researchCase.deliveries?.some(item => item.input_revision === researchCase.input_revision && item.outcome === 'accepted')
            : researchCase.reuse_candidates?.some(item => item.input_revision === researchCase.input_revision) || !!researchCase.reuse_disposition;
  return ready ? { target: 'decision', label: '核对并记录阶段决定' } : { target: stage.edit, label: stage.editLabel };
}
