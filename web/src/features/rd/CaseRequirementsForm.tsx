import { PlatformButton } from '../../components/ui/PlatformButton';
import { Button, Table, type TableColumnsType } from 'antd';
import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { SourcePicker } from './CaseFields';
import { isCurrentSource } from './presentation';
import type { Requirement, ResearchCase } from './types';
import type { CommandRunner } from './WorkpackagePanel';

export function CaseRequirementsForm({ researchCase, busy, command, onOpenSources, onDirtyChange, onReviewClarification }: { researchCase: ResearchCase; busy: boolean; command: CommandRunner; onOpenSources: () => void; onDirtyChange: (dirty: boolean) => void; onReviewClarification?: (requirementId: string) => void }) {
  const [reqId, setReqId] = useState('');
  const editor = useRef<HTMLDetailsElement>(null);
  const [reqTitle, setReqTitle] = useState('');
  const [reqContent, setReqContent] = useState('');
  const [reqSources, setReqSources] = useState<string[]>([]);
  const [reqBase, setReqBase] = useState(JSON.stringify(['', '', []]));
  const [reqError, setReqError] = useState('');
  const [discardReq, setDiscardReq] = useState(false);
  const reqDirty = JSON.stringify([reqTitle, reqContent, reqSources]) !== reqBase;
  useLayoutEffect(() => { onDirtyChange(reqDirty); }, [reqDirty, onDirtyChange]);
  const isArchivedSource = (id: string) => { const source = researchCase.sources.find(item => item.id === id); return !source || !isCurrentSource(source, researchCase.source_selection); };
  const outdatedRequirements = researchCase.requirements.filter(requirement => requirement.source_ids.some(isArchivedSource));
  function saveRequirement(event: FormEvent) {
    event.preventDefault();
    if (!reqTitle.trim() || !reqContent.trim() || !reqSources.length || reqSources.some(isArchivedSource)) { setReqError('请填写需求标题、内容，并关联当前输入。历史技术资料或规范需先取消并更新关联。'); document.getElementById(!reqTitle.trim() ? 'rd-req-title' : 'rd-req-content')?.focus(); return; }
    setReqError('');
    void command('save_requirement', { ...(reqId ? { id: reqId } : {}), title: reqTitle, content: reqContent, source_ids: reqSources }, () => { setReqId(''); setReqTitle(''); setReqContent(''); setReqSources([]); setReqBase(JSON.stringify(['', '', []])); });
  }
  const clearRequirement = () => { setReqId(''); setReqTitle(''); setReqContent(''); setReqSources([]); setReqBase(JSON.stringify(['', '', []])); setDiscardReq(false); setReqError(''); };
  function editRequirement(requirement: Requirement) {
    if (editor.current) editor.current.open = true;
    requestAnimationFrame(() => document.getElementById('rd-req-title')?.focus());
    setReqId(requirement.id); setReqTitle(requirement.title); setReqContent(requirement.content); setReqSources(requirement.source_ids);
    setReqBase(JSON.stringify([requirement.title, requirement.content, requirement.source_ids])); setReqError('');
  }
  const columns: TableColumnsType<Requirement> = [
    { key: 'title', title: '指标', width: '25%', render: (_, item) => <><strong>{item.title}</strong>{item.source_ids.some(isArchivedSource) && <span className="rd-badge blocked">来源待更新</span>}</> },
    { key: 'content', title: '当前需求', width: '36%', render: (_, item) => <p className="rd-req-original">{item.content}</p> },
    { key: 'sources', title: '来源文件', width: '23%', render: (_, item) => <ul className="rd-req-files">{item.source_ids.map(id => {
      const source = researchCase.sources.find(record => record.id === id);
      return <li key={id}>{source ? source.name + ' · v' + source.version + (isArchivedSource(id) ? '（历史版本）' : '') : '来源记录缺失'}</li>;
    })}</ul> },
    { key: 'action', title: '办理', width: '16%', render: (_, item) => <div className="rd-req-actions">
      <Button type="link" size="small" disabled={busy || reqDirty} onClick={() => editRequirement(item)}>编辑需求</Button>
      {onReviewClarification && <Button type="link" size="small" disabled={busy} onClick={() => onReviewClarification(item.id)}>办理澄清</Button>}
    </div> },
  ];
  const requirementsPanel = <section className="rd-section">
    <div className="rd-section-head"><h3>需求记录</h3><span className="rd-badge">{researchCase.requirements.length} 条</span></div>
    {!!outdatedRequirements.length && <p className="rd-warning">{outdatedRequirements.length} 条需求仍关联历史版本。请通过“编辑需求”改为当前输入并保存，再重新确认需求阶段。</p>}
    <Table<Requirement> className="rd-requirement-list rd-req-table" dataSource={researchCase.requirements} columns={columns} rowKey="id" size="small" tableLayout="fixed" pagination={false}
      locale={{ emptyText: '尚未采用原文需求。先分析上传资料，核对识别结果后确认采用。' }} />
    {!researchCase.requirements.length && <PlatformButton type="button" className="rd-button" disabled={busy || reqDirty} onClick={onOpenSources}>分析资料并采用需求</PlatformButton>}
    <details className="rd-requirement-supplement" ref={editor}><summary>补充或修订需求记录</summary><form noValidate onSubmit={saveRequirement}><h4>{reqId ? '编辑需求记录' : '新增需求记录'}</h4><div className="rd-field"><label htmlFor="rd-req-title">需求标题</label><input id="rd-req-title" value={reqTitle} onChange={event => setReqTitle(event.target.value)} disabled={busy} aria-invalid={!!reqError && !reqTitle.trim()} aria-describedby={reqError ? 'rd-req-error' : undefined} /></div><div className="rd-field"><label htmlFor="rd-req-content">需求内容</label><textarea id="rd-req-content" className="resize-none" rows={5} value={reqContent} onChange={event => setReqContent(event.target.value)} disabled={busy} aria-invalid={!!reqError && !reqContent.trim()} aria-describedby={reqError ? 'rd-req-error' : undefined} /></div><SourcePicker sources={researchCase.sources} sourceSelection={researchCase.source_selection} value={reqSources} onChange={setReqSources} disabled={busy} />{reqError && <p id="rd-req-error" role="alert" className="rd-error">{reqError}</p>}<div className="rd-actions"><p className="rd-muted">{reqDirty ? '有未保存的需求填写。' : '实质修改需求或依据会回到资料输入，原确认与后续成果需重新核对。'}</p><div>{(reqId || reqDirty) && <PlatformButton className="rd-button" disabled={busy} type="button" onClick={() => reqDirty ? setDiscardReq(true) : clearRequirement()}>取消填写</PlatformButton>}<PlatformButton className="rd-button primary" disabled={busy || !reqDirty} type="submit">保存需求记录</PlatformButton></div></div></form></details></section>;

  return <>{requirementsPanel}
    {discardReq && <FeedbackConfirmDialog title="放弃未保存的需求填写" confirm="放弃填写" cancel="继续编辑" onCancel={() => setDiscardReq(false)} onConfirm={clearRequirement}><p>本次未保存的标题、正文和来源选择将清空。</p></FeedbackConfirmDialog>}
  </>;
}
