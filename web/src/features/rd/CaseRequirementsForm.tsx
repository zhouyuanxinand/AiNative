import { useEffect, useRef, useState, type FormEvent } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { SourcePicker } from './CaseFields';
import { isCurrentSource } from './presentation';
import type { ResearchCase } from './types';
import type { CommandRunner } from './WorkpackagePanel';

export function CaseRequirementsForm({ researchCase, busy, command, onOpenSources, onDirtyChange }: { researchCase: ResearchCase; busy: boolean; command: CommandRunner; onOpenSources: () => void; onDirtyChange: (dirty: boolean) => void }) {
  const [reqId, setReqId] = useState('');
  const editor = useRef<HTMLDetailsElement>(null);
  const [reqTitle, setReqTitle] = useState('');
  const [reqContent, setReqContent] = useState('');
  const [reqSources, setReqSources] = useState<string[]>([]);
  const [reqBase, setReqBase] = useState(JSON.stringify(['', '', []]));
  const [reqError, setReqError] = useState('');
  const [discardReq, setDiscardReq] = useState(false);
  const reqDirty = JSON.stringify([reqTitle, reqContent, reqSources]) !== reqBase;
  useEffect(() => { onDirtyChange(reqDirty); }, [reqDirty, onDirtyChange]);
  const isArchivedSource = (id: string) => { const source = researchCase.sources.find(item => item.id === id); return !source || !isCurrentSource(source, researchCase.source_selection); };
  const outdatedRequirements = researchCase.requirements.filter(requirement => requirement.source_ids.some(isArchivedSource));
  function saveRequirement(event: FormEvent) {
    event.preventDefault();
    if (!reqTitle.trim() || !reqContent.trim() || !reqSources.length || reqSources.some(isArchivedSource)) { setReqError('请填写需求标题、内容，并关联当前输入。历史技术资料或规范需先取消并更新关联。'); document.getElementById(!reqTitle.trim() ? 'rd-req-title' : 'rd-req-content')?.focus(); return; }
    setReqError('');
    void command('save_requirement', { ...(reqId ? { id: reqId } : {}), title: reqTitle, content: reqContent, source_ids: reqSources }, () => { setReqId(''); setReqTitle(''); setReqContent(''); setReqSources([]); setReqBase(JSON.stringify(['', '', []])); });
  }
  const clearRequirement = () => { setReqId(''); setReqTitle(''); setReqContent(''); setReqSources([]); setReqBase(JSON.stringify(['', '', []])); setDiscardReq(false); setReqError(''); };
  const requirementsPanel = <section className="rd-section"><div className="rd-section-head"><div><span className="rd-eyebrow">需求主账</span><h3>需求记录</h3><p>保留需求正文与来源关联，作为实际需求确认的依据。</p></div><span className="rd-badge">{researchCase.requirements.length} 条</span></div>{!!outdatedRequirements.length && <p className="rd-warning">{outdatedRequirements.length} 条需求仍关联历史版本。请通过“编辑需求”改为当前输入并保存，再重新确认需求阶段。</p>}<div className="rd-requirement-list">{researchCase.requirements.map(requirement => <article key={requirement.id}><div className="rd-section-head"><div><h4>{requirement.title}</h4>{requirement.source_ids.some(isArchivedSource) && <span className="rd-badge blocked">来源待更新</span>}</div><button className="rd-button compact" disabled={busy || reqDirty} onClick={() => { if (editor.current) editor.current.open = true; requestAnimationFrame(() => document.getElementById('rd-req-title')?.focus()); setReqId(requirement.id); setReqTitle(requirement.title); setReqContent(requirement.content); setReqSources(requirement.source_ids); setReqBase(JSON.stringify([requirement.title, requirement.content, requirement.source_ids])); }}>编辑需求</button></div><p className="rd-prewrap">{requirement.content}</p><p className="rd-muted">来源：{requirement.source_ids.map(id => (() => { const source = researchCase.sources.find(item => item.id === id); return source ? `${source.name} · v${source.version}${isCurrentSource(source, researchCase.source_selection) ? '' : '（历史版本）'}` : id; })()).join('、')}</p></article>)}{!researchCase.requirements.length && <p className="rd-empty-inline">尚未采用原文需求。先分析上传资料，核对识别结果后确认采用。</p>}</div><button type="button" className="rd-button" disabled={busy || reqDirty} onClick={onOpenSources}>查看资料识别与采用</button><details className="rd-requirement-supplement" ref={editor}><summary>补充或修订需求记录</summary><form noValidate onSubmit={saveRequirement}><h4>{reqId ? '编辑需求记录' : '新增需求记录'}</h4><div className="rd-field"><label htmlFor="rd-req-title">需求标题</label><input id="rd-req-title" value={reqTitle} onChange={event => setReqTitle(event.target.value)} disabled={busy} aria-invalid={!!reqError && !reqTitle.trim()} aria-describedby={reqError ? 'rd-req-error' : undefined} /></div><div className="rd-field"><label htmlFor="rd-req-content">需求内容</label><textarea id="rd-req-content" className="resize-none" rows={5} value={reqContent} onChange={event => setReqContent(event.target.value)} disabled={busy} aria-invalid={!!reqError && !reqContent.trim()} aria-describedby={reqError ? 'rd-req-error' : undefined} /></div><SourcePicker sources={researchCase.sources} sourceSelection={researchCase.source_selection} value={reqSources} onChange={setReqSources} disabled={busy} />{reqError && <p id="rd-req-error" role="alert" className="rd-error">{reqError}</p>}<div className="rd-actions"><p className="rd-muted">{reqDirty ? '有未保存的需求填写。' : '实质修改需求或依据会回到资料输入，原确认与后续成果需重新核对。'}</p><div>{(reqId || reqDirty) && <button className="rd-button" disabled={busy} type="button" onClick={() => reqDirty ? setDiscardReq(true) : clearRequirement()}>取消填写</button>}<button className="rd-button primary" disabled={busy || !reqDirty} type="submit">保存需求记录</button></div></div></form></details></section>;

  return <>{requirementsPanel}
    {discardReq && <FeedbackConfirmDialog title="放弃未保存的需求填写" confirm="放弃填写" cancel="继续编辑" onCancel={() => setDiscardReq(false)} onConfirm={clearRequirement}><p>本次未保存的标题、正文和来源选择将清空。</p></FeedbackConfirmDialog>}
  </>;
}
