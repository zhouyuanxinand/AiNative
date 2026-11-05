import { PlatformButton } from '../../components/ui/PlatformButton';
import { useEffect, useState, type FormEvent } from 'react';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { SourcePicker } from './CaseFields';
import { artifactUrl } from './api';
import { formatTime } from './presentation';
import type { Project, ResearchCase } from './types';
import type { CommandRunner } from './WorkpackagePanel';

export function CaseHandover({ kind, project, researchCase, busy, command, onDirtyChange }: { kind: 'delivery' | 'reuse'; project: Project; researchCase: ResearchCase; busy: boolean; command: CommandRunner; onDirtyChange: (dirty: boolean) => void }) {
  const [recipient, setRecipient] = useState('');
  const [receipt, setReceipt] = useState('');
  const [feedback, setFeedback] = useState('');
  const [outcome, setOutcome] = useState('');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [sources, setSources] = useState<string[]>([]);
  const [selectedArtifacts, setSelectedArtifacts] = useState<string[]>([]);
  const [validation, setValidation] = useState('');
  const dirty = !!recipient || !!receipt || !!feedback || !!outcome || !!title || !!content || !!sources.length || !!selectedArtifacts.length;
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  const direct = researchCase.product_route?.value === 'direct';
  const editable = researchCase.status !== 'completed' && researchCase.stage === (kind === 'delivery' ? 'delivery' : 'knowledge');
  const artifacts = researchCase.workpackages.flatMap(workpackage => workpackage.artifacts.map(artifact => ({ ...artifact, workpackage })));
  function save(event: FormEvent) {
    event.preventDefault();
    if (kind === 'delivery' && (!recipient.trim() || !receipt.trim() || !outcome || (direct ? !sources.length : !selectedArtifacts.length)) || kind === 'reuse' && (!title.trim() || !content.trim() || !sources.length && !selectedArtifacts.length)) { setValidation(kind === 'delivery' ? '请关联交付成果（成熟产品直接选用须关联上传的实际回执来源）、填写接收方与实际回执，并选择结果。' : '请填写候选名称和内容，并关联来源或成果。'); return; }
    setValidation('');
    const data = kind === 'delivery' ? { artifact_ids: selectedArtifacts, recipient, receipt, feedback, outcome, source_ids: sources } : { title, content, source_ids: sources, artifact_ids: selectedArtifacts };
    void command(kind === 'delivery' ? 'record_delivery' : 'prepare_reuse', data, () => { setRecipient(''); setReceipt(''); setFeedback(''); setOutcome(''); setTitle(''); setContent(''); setSources([]); setSelectedArtifacts([]); });
  }
  return <section className="rd-section"><div className="rd-section-head"><div><h3>{kind === 'delivery' ? '交付与反馈' : '准备知识复用候选'}</h3><p>{kind === 'delivery' ? '登记实际接收方、交付回执与反馈；这是人工登记，不是电子签名。' : '形成当前案例的复用候选；不会自动发布到 K-box 或共享知识库。'}</p></div></div>
    {direct && kind === 'delivery' && <p className="rd-notice">成熟产品直接选用：关联实际交付回执资料即可登记。本平台未接入库存、价格、预留或补货服务，请依据实际办理记录核对。</p>}<form noValidate onSubmit={save}>{kind === 'delivery' ? <><div className="rd-field"><label htmlFor="rd-delivery-recipient">实际接收方</label><input id="rd-delivery-recipient" value={recipient} onChange={event => setRecipient(event.target.value)} disabled={busy || !editable} /></div><div className="rd-field"><label htmlFor="rd-delivery-receipt">实际交付回执</label><textarea id="rd-delivery-receipt" className="resize-none" rows={3} value={receipt} onChange={event => setReceipt(event.target.value)} disabled={busy || !editable} /></div><div className="rd-field"><label htmlFor="rd-delivery-feedback">接收反馈</label><textarea id="rd-delivery-feedback" className="resize-none" rows={3} value={feedback} onChange={event => setFeedback(event.target.value)} disabled={busy || !editable} /></div><div className="rd-field"><label id="rd-delivery-outcome-label">登记结果</label><StyledSelect aria-labelledby="rd-delivery-outcome-label" value={outcome} onChange={setOutcome} disabled={busy || !editable} options={[{ value: '', label: '请选择实际结果' }, { value: 'accepted', label: '实际已接收' }, { value: 'revision_required', label: '反馈要求修订' }]} /></div></> : <><div className="rd-field"><label htmlFor="rd-reuse-title">候选名称</label><input id="rd-reuse-title" value={title} onChange={event => setTitle(event.target.value)} disabled={busy || !editable} /></div><div className="rd-field"><label htmlFor="rd-reuse-content">复用内容与适用范围</label><textarea id="rd-reuse-content" className="resize-none" rows={5} value={content} onChange={event => setContent(event.target.value)} disabled={busy || !editable} /></div></>}
      <SourcePicker sources={researchCase.sources} sourceSelection={researchCase.source_selection} value={sources} onChange={setSources} disabled={busy || !editable} label={kind === 'delivery' ? '回执与反馈来源' : '候选依据'} />
      <fieldset className="rd-source-picker" disabled={busy || !editable}><legend>{kind === 'delivery' ? '本次交付成果' : '关联固定成果'}</legend>{artifacts.map(artifact => <label key={`${artifact.workpackage.id}-${artifact.id}`}><input type="checkbox" checked={selectedArtifacts.includes(artifact.id)} onChange={event => setSelectedArtifacts(current => event.target.checked ? [...current, artifact.id] : current.filter(id => id !== artifact.id))} /><a href={artifactUrl(project.id, researchCase.id, artifact.workpackage.id, artifact.id)} target="_blank" rel="noreferrer">{artifact.name} ↗</a></label>)}{!artifacts.length && <p className="rd-muted">当前没有已登记成果。</p>}</fieldset>{validation && <p className="rd-error" role="alert">{validation}</p>}<div className="rd-actions"><p className="rd-muted">{kind === 'delivery' ? '服务端核验当前输入及成果版本，不以旧交付替代新输入的接收。' : '仅准备案例内候选，发布须经过实际知识治理。'}</p><PlatformButton type="submit" className="rd-button primary" disabled={busy || !editable || !dirty}>{kind === 'delivery' ? '登记交付反馈' : '保存复用候选'}</PlatformButton></div></form>
    <details className="rd-record-new"><summary>{kind === 'delivery' ? '查看交付登记历史' : '查看已准备候选'}</summary>{kind === 'delivery' ? (researchCase.deliveries ?? []).map(record => <article className="rd-evidence-record" key={record.id}><div><strong>{record.recipient}</strong><span className={`rd-badge ${record.input_revision !== researchCase.input_revision ? 'blocked' : record.outcome === 'accepted' ? 'completed' : 'blocked'}`}>{record.input_revision !== researchCase.input_revision ? '历史输入登记' : record.outcome === 'accepted' ? '人工登记已接收' : '要求修订'}</span></div><p className="rd-prewrap">{record.receipt}</p><p className="rd-prewrap">{record.feedback}</p><small>{record.actor} · {formatTime(record.created_at)} · 输入版 {record.input_revision} · 非电子签名</small></article>) : (researchCase.reuse_candidates ?? []).map(record => <article className="rd-evidence-record" key={record.id}><div><strong>{record.title}</strong><span className="rd-badge">案例内候选 · 未发布</span></div><p className="rd-prewrap">{record.content}</p><small>{record.actor} · {formatTime(record.created_at)} · 输入版 {record.input_revision}</small></article>)}</details>
  </section>;
}
