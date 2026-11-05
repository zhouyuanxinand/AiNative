import { summarizeCaseOutcome } from './caseOutcomeModel';
import { isCurrentSource, STAGES } from './presentation';
import { nextCaseAction, scenarioManifest, scenarioStage, type CaseSurface, type ScenarioManifest } from './scenarioManifest';
import type { ResearchCase, StageId } from './types';

export interface CaseJourneyStep {
  id: CaseSurface;
  title: string;
  target: CaseSurface;
  available: boolean;
  reason?: string;
}

const stageSteps: Record<StageId, CaseSurface> = {
  input: 'sources', requirements: 'requirements', selection: 'routes', planning: 'preparation',
  design: 'workpackages', verification: 'workpackages', delivery: 'delivery', knowledge: 'reuse',
};

function currentBinding(researchCase: ResearchCase) {
  const binding = researchCase.taskbook_binding;
  return !!binding && researchCase.input_revision !== undefined && binding.status === 'current'
    && !binding.invalidated_at && binding.input_revision === researchCase.input_revision;
}

function currentAdoptedAnalysis(researchCase: ResearchCase) {
  const analysis = researchCase.source_analysis;
  return analysis?.status === 'adopted' && researchCase.input_revision !== undefined
    && analysis.adopted_input_revision === researchCase.input_revision;
}

function isCompleted(researchCase: ResearchCase) {
  return researchCase.workflow_templates?.project
    ? researchCase.project_workflow_status?.status === 'completed'
    : researchCase.status === 'completed';
}

function activeStep(researchCase: ResearchCase): CaseSurface {
  if (isCompleted(researchCase)) return researchCase.workflow_templates?.project ? 'workpackages' : stageSteps[researchCase.stage];
  const execution = summarizeCaseOutcome(researchCase).execution.kind;
  if (['running', 'blocked', 'draft'].includes(execution)) return 'workpackages';
  if (researchCase.stage === 'input') {
    const sourceIds = new Set(researchCase.sources.filter(source => isCurrentSource(source, researchCase.source_selection)).map(source => source.id));
    const requirementsCurrent = researchCase.requirements.length > 0 && researchCase.requirements.every(item => item.source_ids.length > 0 && item.source_ids.every(id => sourceIds.has(id)));
    if (currentAdoptedAnalysis(researchCase) || requirementsCurrent) return 'requirements';
  }
  if (researchCase.stage === 'planning' && (researchCase.workflow_templates?.project || researchCase.business_lifecycle?.policy_version === 'v2') && currentBinding(researchCase)) return 'workpackages';
  return stageSteps[researchCase.stage];
}

/** The page being viewed and the pending business step can differ during review. */
export function caseStepForSurface(surface: CaseSurface, researchCase: ResearchCase): CaseSurface {
  if (surface === 'current') return activeStep(researchCase);
  if (surface !== 'decision') return surface;
  if (['input', 'requirements'].includes(researchCase.stage)) return 'requirements';
  if (researchCase.stage === 'selection') return 'routes';
  if (researchCase.stage === 'planning') return researchCase.business_lifecycle?.policy_version === 'v2' || researchCase.workflow_templates?.project ? 'workpackages' : 'preparation';
  return stageSteps[researchCase.stage];
}

export function caseJourney(researchCase: ResearchCase, manifest?: ScenarioManifest): {
  steps: CaseJourneyStep[];
  active: CaseSurface;
  next: { target: CaseSurface; label: string } | null;
  completed: boolean;
} {
  const reached = (stage: StageId) => STAGES.findIndex(item => item.id === researchCase.stage) >= STAGES.findIndex(item => item.id === stage);
  const hasRequirements = !!(researchCase.requirements.length || researchCase.clarifications?.length
    || researchCase.source_analysis?.adopted_input_revision !== undefined);
  const hasRoutes = !!(researchCase.product_route || researchCase.composition_route || researchCase.comparisons?.length
    || researchCase.business_lifecycle?.current_requirement_baseline_id
    || researchCase.review_bundles?.some(item => item.kind === 'selection')
    || researchCase.decisions.some(item => item.kind === 'selection'));
  const hasPreparation = !!(researchCase.taskbook_binding || researchCase.taskbook_binding_history?.length || researchCase.rd_activations?.length);
  const hasExecution = !!(researchCase.workpackages.length || researchCase.flow_drafts?.length || researchCase.execution_candidates?.length
    || researchCase.engineering_records?.length || researchCase.review_bundles?.some(item => item.kind === 'taskbook_scope'));
  const v2 = researchCase.business_lifecycle?.policy_version === 'v2' || !!researchCase.workflow_templates?.project;
  const entries: Array<{ id: CaseSurface; title: string; available: boolean; reason: string }> = [
    { id: 'sources', title: '资料识别', available: true, reason: '' },
    { id: 'requirements', title: '需求确认', available: reached('requirements') || currentAdoptedAnalysis(researchCase) || hasRequirements, reason: '请先分析资料并确认采用，或形成需求记录。' },
    { id: 'routes', title: '选型与启动', available: reached('selection') || hasRoutes, reason: '请先确认当前需求。' },
    { id: 'preparation', title: '编制准备', available: reached('planning') || hasPreparation, reason: v2 ? '请先完成选型决定和研发启动。' : '请先完成选型阶段确认。' },
    { id: 'workpackages', title: '编排与生成', available: reached('design') || hasExecution || v2 && researchCase.stage === 'planning' && currentBinding(researchCase), reason: v2 ? '请先固定当前任务书输入。' : '请先通过编制准备阶段确认。' },
  ];
  if (!researchCase.workflow_templates?.project) entries.push(
    { id: 'delivery', title: '交付与反馈', available: reached('delivery') || !!researchCase.deliveries?.length, reason: '请先完成当前阶段并确认交付条件。' },
    { id: 'reuse', title: '复用整理', available: reached('knowledge') || !!(researchCase.reuse_candidates?.length || researchCase.reuse_disposition), reason: '请先完成交付与反馈。' },
  );
  const completed = isCompleted(researchCase);
  return {
    steps: entries.map(({ id, title, available, reason }) => ({ id, title, target: id, available, ...(!available ? { reason } : {}) })),
    active: activeStep(researchCase),
    next: completed ? null : nextCaseAction(researchCase, manifest),
    completed,
  };
}

/** Destinations only follow a successful server response; they never execute the next action. */
export function successfulCaseDestination(command: string, data: Record<string, unknown>, before: ResearchCase, after: ResearchCase): CaseSurface | null {
  if (before.id !== after.id || data.case_id !== undefined && data.case_id !== after.id || data.verdict === 'rejected') return null;
  if (command === 'adopt_source_analysis') return currentAdoptedAnalysis(after) && after.source_analysis?.id === data.analysis_id ? 'requirements' : null;
  if (command === 'confirm_requirements') return after.stage === 'selection' && after.business_lifecycle?.current_requirement_baseline_id ? 'routes' : null;
  if (command === 'authorize_rd_start') return after.stage === 'planning' && after.business_lifecycle?.rd_activation_state === 'active' && after.business_lifecycle.current_activation_id ? 'preparation' : null;
  if (command === 'adopt_taskbook_flow') return after.stage === 'planning' && currentBinding(after)
    && (after.workflow_templates?.project || after.business_lifecycle?.policy_version === 'v2') ? 'workpackages' : null;
  if (data.verdict !== 'approved') return null;
  if (command === 'record_selection_decision') return before.stage === 'selection' && after.stage === 'delivery' && after.product_route?.value === 'direct' ? 'delivery' : null;
  if (command === 'record_taskbook_scope_decision') return before.stage === 'planning' && after.stage === 'design' ? 'workpackages' : null;
  if (command !== 'advance_stage' && command !== 'confirm_engineering_stage') return null;
  if (after.status === 'completed' && before.status !== 'completed') return 'current';
  return after.stage !== before.stage ? scenarioStage(after, scenarioManifest(after.scenario_id)).edit : null;
}
