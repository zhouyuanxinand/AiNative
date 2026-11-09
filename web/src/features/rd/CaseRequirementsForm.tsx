import { PlatformButton } from '../../components/ui/PlatformButton';
import { RequirementDecisionTable } from './RequirementDecisionTable';
import { ProjectProfileLinks } from './ProjectProfileLinks';
import { useLayoutEffect, useState, type FormEvent, type ReactNode } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { SourcePicker } from './CaseFields';
import { isCurrentSource } from './presentation';
import { requirementConfirmationBlockers } from './requirementConfirmation';
import type { Project, ResearchCase } from './types';
import type { CommandRunner } from './WorkpackagePanel';

export function CaseRequirementsForm({ project, actorId, researchCase, busy, command, onOpenSources, onDirtyChange, onReviewClarification, reviewAction }: { project: Project; actorId: string; researchCase: ResearchCase; busy: boolean; command: CommandRunner; onOpenSources: () => void; onDirtyChange: (dirty: boolean) => void; onReviewClarification?: (requirementId: string) => void; reviewAction?: ReactNode }) {
  const [reqTitle, setReqTitle] = useState('');
  const [reqContent, setReqContent] = useState('');
  const [reqSources, setReqSources] = useState<string[]>([]);
  const [reqBase, setReqBase] = useState(JSON.stringify(['', '', []]));
  const [reqError, setReqError] = useState('');
  const [discardReq, setDiscardReq] = useState(false);
  const reqDirty = JSON.stringify([reqTitle, reqContent, reqSources]) !== reqBase;
  const [rowDirty, setRowDirty] = useState(false);
  const readOnly = !actorId || researchCase.status === 'completed' || !['input', 'requirements'].includes(researchCase.stage) || !!researchCase.business_lifecycle?.current_requirement_baseline_id;
  useLayoutEffect(() => { onDirtyChange(!readOnly && (reqDirty || rowDirty)); }, [readOnly, reqDirty, rowDirty, onDirtyChange]);
  const isArchivedSource = (id: string) => { const source = researchCase.sources.find(item => item.id === id); return !source || !isCurrentSource(source, researchCase.source_selection); };
  const outdatedRequirements = researchCase.requirements.filter(requirement => requirement.source_ids.some(isArchivedSource));
  const confirmationBlockers = researchCase.business_lifecycle?.policy_version === 'v2' && !readOnly ? requirementConfirmationBlockers(researchCase) : [];
  function saveRequirement(event: FormEvent) {
    event.preventDefault();
    if (readOnly || busy || rowDirty) return;
    if (!reqTitle.trim() || !reqContent.trim() || !reqSources.length || reqSources.some(isArchivedSource)) { setReqError('请填写需求标题、内容，并关联当前输入。历史技术资料或规范需先取消并更新关联。'); document.getElementById(!reqTitle.trim() ? 'rd-req-title' : 'rd-req-content')?.focus(); return; }
    setReqError('');
    void command('save_requirement', { title: reqTitle, content: reqContent, source_ids: reqSources }, () => { setReqTitle(''); setReqContent(''); setReqSources([]); setReqBase(JSON.stringify(['', '', []])); });
  }
  const clearRequirement = () => { setReqTitle(''); setReqContent(''); setReqSources([]); setReqBase(JSON.stringify(['', '', []])); setDiscardReq(false); setReqError(''); };
  const requirementsPanel = <section className="rd-section">
    <div className="rd-section-head"><h3>用户确认与澄清</h3><ProjectProfileLinks project={project} researchCase={researchCase} /></div>
    {!!confirmationBlockers.length && <p className="rd-warning" role="status">暂不能确认需求：{confirmationBlockers[0].message}{confirmationBlockers.length > 1 && ` 另有 ${confirmationBlockers.length - 1} 项待处理。`}</p>}
    {!!outdatedRequirements.length && <p className="rd-warning">{outdatedRequirements.length} 条需求仍关联历史版本。请通过“编辑需求”改为当前输入并保存，再重新确认需求阶段。</p>}
    {readOnly && <p className="rd-muted">{actorId ? '此阶段已结束。以下为已保存的需求与决定。' : '尚未核实当前办理身份，只能查阅；若持续显示，请刷新页面。'}</p>}
    <RequirementDecisionTable project={project} researchCase={researchCase} actorId={actorId} busy={busy || reqDirty} readOnly={readOnly} onReviewClarification={onReviewClarification} onDirtyChange={setRowDirty} command={command} reviewAction={reviewAction} />
    {!researchCase.requirements.length && <PlatformButton type="button" className="rd-button" disabled={busy || reqDirty} onClick={onOpenSources}>分析资料并采用需求</PlatformButton>}
    {!readOnly && <details className="rd-requirement-supplement"><summary>新增需求记录</summary>
      <form noValidate onSubmit={saveRequirement}>
        <div className="rd-field"><label htmlFor="rd-req-title">需求标题</label><input id="rd-req-title" value={reqTitle} onChange={event => setReqTitle(event.target.value)} disabled={busy || rowDirty} aria-invalid={!!reqError && !reqTitle.trim()} aria-describedby={reqError ? 'rd-req-error' : undefined} /></div>
        <div className="rd-field"><label htmlFor="rd-req-content">需求内容</label><textarea id="rd-req-content" className="resize-none" rows={5} value={reqContent} onChange={event => setReqContent(event.target.value)} disabled={busy || rowDirty} aria-invalid={!!reqError && !reqContent.trim()} aria-describedby={reqError ? 'rd-req-error' : undefined} /></div>
        <SourcePicker sources={researchCase.sources} sourceSelection={researchCase.source_selection} value={reqSources} onChange={setReqSources} disabled={busy || rowDirty} />
        {reqError && <p id="rd-req-error" role="alert" className="rd-error">{reqError}</p>}
        <div className="rd-actions"><p className="rd-muted">新增后需重新核对需求。</p><div>
          {reqDirty && <PlatformButton className="rd-button" disabled={busy} type="button" onClick={() => setDiscardReq(true)}>取消填写</PlatformButton>}
          <PlatformButton className="rd-button primary" disabled={busy || rowDirty || !reqDirty} type="submit">保存需求记录</PlatformButton>
        </div></div>
      </form>
    </details>}</section>;

  return <>{requirementsPanel}
    {discardReq && <FeedbackConfirmDialog title="放弃未保存的需求填写" confirm="放弃填写" cancel="继续编辑" onCancel={() => setDiscardReq(false)} onConfirm={clearRequirement}><p>本次未保存的标题、正文和来源选择将清空。</p></FeedbackConfirmDialog>}
  </>;
}
