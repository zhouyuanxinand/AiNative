import type { ResearchCase, Workpackage } from './types';

export function packageUsesCurrentInput(workpackage: Workpackage, researchCase: ResearchCase) {
  return researchCase.input_revision !== undefined && workpackage.snapshot?.input_revision === researchCase.input_revision;
}

export function caseArtifactRecords(researchCase: ResearchCase) {
  return researchCase.workpackages.flatMap(workpackage => workpackage.artifacts.map(artifact => ({
    artifact, workpackage, current: packageUsesCurrentInput(workpackage, researchCase),
  })));
}

export function summarizeCaseOutcome(researchCase: ResearchCase) {
  const packages = researchCase.workpackages.filter(item => item.stage === researchCase.stage);
  const activePackages = packages.filter(item => item.status === 'draft' || packageUsesCurrentInput(item, researchCase));
  const blockedPackages = activePackages.filter(item => ['blocked', 'failed'].includes(item.status));
  const running = activePackages.filter(item => ['submitted', 'running'].includes(item.status));
  const completed = activePackages.filter(item => item.status === 'completed');
  const draft = activePackages.filter(item => item.status === 'draft');
  const execution = running.length ? { kind: 'running', label: `${running.length} 个工作包执行中` }
    : blockedPackages.length ? { kind: 'blocked', label: `${blockedPackages.length} 个工作包受阻或失败` }
      : draft.length ? { kind: 'draft', label: `${draft.length} 个工作包待提交` }
        : completed.length ? { kind: 'completed', label: `${completed.length} 个工作包已完成` }
          : { kind: 'unrecorded', label: '本阶段尚无当前执行记录' };
  const stageDecisions = researchCase.decisions.filter(item => item.kind !== 'route' && item.stage === researchCase.stage);
  const currentDecisions = stageDecisions.filter(item => !item.invalidated_at
    && (item.input_revision === undefined || item.input_revision === researchCase.input_revision));
  const decision = currentDecisions[currentDecisions.length - 1];
  const confirmation = decision ? { kind: decision.verdict ?? 'unrecorded', label: decision.verdict === 'approved' ? '已记录阶段通过' : '已记录阶段未通过' }
    : stageDecisions.length ? { kind: 'stale', label: '原决定待重新核对' }
      : { kind: 'unrecorded', label: '尚未记录阶段决定' };
  const checks = researchCase.workpackages.filter(item => item.status !== 'cancelled' && packageUsesCurrentInput(item, researchCase))
    .flatMap(item => item.nodes.filter(node => node.action_id === 'verify' && node.result));
  const check = checks[checks.length - 1];
  const verification = check?.status === 'completed' && check.result?.delivery_approved === true
    ? { kind: 'passed', label: '当前输入的自动核验通过' }
    : check ? { kind: 'blocked', label: '当前输入的自动核验未通过' }
      : { kind: 'unrecorded', label: '尚无当前输入的自动核验结果' };
  return { packages, activePackages, blockedPackages, execution, confirmation, verification };
}
