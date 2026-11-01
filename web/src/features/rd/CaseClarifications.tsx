import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { SourcePicker } from './CaseFields';
import { formatTime } from './presentation';
import type { Clarification, ResearchCase } from './types';
import type { CommandRunner } from './WorkpackagePanel';

function ClarificationItem({ record, researchCase, busy, error, command, onDirtyChange }: { record: Clarification; researchCase: ResearchCase; busy: boolean; error: string; command: CommandRunner; onDirtyChange: (id: string, dirty: boolean) => void }) {
  const [answer, setAnswer] = useState('');
  const [sources, setSources] = useState<string[]>([]);
  const [content, setContent] = useState('');
  const [validation, setValidation] = useState('');
  const [confirm, setConfirm] = useState(false);
  const current = !record.invalidated_at && record.input_revision === researchCase.input_revision;
  const editable = record.status !== 'adopted' && ['input', 'requirements'].includes(researchCase.stage);
  useEffect(() => { onDirtyChange(record.id, !!answer || !!sources.length || !!content); }, [record.id, answer, sources, content, onDirtyChange]);
  function saveAnswer(event: FormEvent) {
    event.preventDefault();
    if (!answer.trim() || !sources.length) { setValidation('请填写答复并关联真实来源。'); document.getElementById(`rd-clar-answer-${record.id}`)?.focus(); return; }
    setValidation(''); void command('answer_clarification', { clarification_id: record.id, answer, source_ids: sources }, () => { setAnswer(''); setSources([]); setContent(''); });
  }
  return <details className="rd-record-item"><summary><span>{researchCase.requirements.find(item => item.id === record.requirement_id)?.title ?? record.requirement_id}<small>{record.question}</small></span><span className={`rd-badge ${!current ? 'blocked' : record.status === 'adopted' ? 'completed' : 'draft'}`}>{!current ? record.status === 'adopted' ? '历史采用记录' : '需重新答复' : { open: '待答复', answered: '待采用', adopted: '已采用' }[record.status]}</span></summary><div><p className="rd-muted">需求版 {record.requirement_revision} · 输入版 {record.input_revision} · {formatTime(record.created_at)}</p>{record.answer && <div className="rd-record-answer"><strong>已保存答复</strong><p className="rd-prewrap">{record.answer}</p><small>{record.answered_by} · {formatTime(record.answered_at ?? undefined)}</small></div>}{record.adoption && <p className="rd-notice">已采用至需求修订 {record.adoption.requirement_revision}，采用与原答复分别保留。</p>}
      {editable && <><form noValidate onSubmit={saveAnswer}><div className="rd-field"><label htmlFor={`rd-clar-answer-${record.id}`}>澄清答复</label><textarea className="resize-none" id={`rd-clar-answer-${record.id}`} rows={3} value={answer} onChange={event => setAnswer(event.target.value)} disabled={busy} /></div><SourcePicker sources={researchCase.sources} sourceSelection={researchCase.source_selection} value={sources} onChange={setSources} disabled={busy} label="答复来源" /><button className="rd-button" disabled={busy || !answer.trim()} type="submit">{current ? '保存澄清答复' : '针对当前版本重新答复'}</button></form>{current && record.status === 'answered' && <div className="rd-record-adoption"><div className="rd-field"><label htmlFor={`rd-clar-adopt-${record.id}`}>采用后的完整需求正文</label><textarea className="resize-none" id={`rd-clar-adopt-${record.id}`} rows={4} value={content} onChange={event => setContent(event.target.value)} disabled={busy} placeholder="核对已保存答复后，明确填写拟采用的完整需求" /></div><button type="button" className="rd-button primary" disabled={busy || !content.trim()} onClick={() => setConfirm(true)}>核对并采用答复</button></div>}</>}{validation && <p className="rd-error" role="alert">{validation}</p>}
      {confirm && <FeedbackConfirmDialog title="采用澄清答复并修订需求" confirm="采用并重新确认" pending={busy} error={error} onCancel={() => setConfirm(false)} onConfirm={() => void command('adopt_clarification', { clarification_id: record.id, requirement_content: content }, () => { setContent(''); setAnswer(''); setSources([]); setConfirm(false); })}><p>将保存当前填写的完整需求，形成新修订。实质修改会使原输入决定失效并返回资料输入，原需求、答复和采用历史保留。</p></FeedbackConfirmDialog>}
    </div></details>;
}

export function CaseClarifications({ researchCase, busy, error, command, onDirtyChange }: { researchCase: ResearchCase; busy: boolean; error: string; command: CommandRunner; onDirtyChange: (dirty: boolean) => void }) {
  const [requirement, setRequirement] = useState('');
  const [question, setQuestion] = useState('');
  const [sources, setSources] = useState<string[]>([]);
  const [validation, setValidation] = useState('');
  const [recordDirty, setRecordDirty] = useState<Record<string, boolean>>({});
  const setChildDirty = useCallback((id: string, dirty: boolean) => setRecordDirty(current => current[id] === dirty ? current : { ...current, [id]: dirty }), []);
  const editable = ['input', 'requirements'].includes(researchCase.stage) && researchCase.status !== 'completed';
  useEffect(() => { onDirtyChange(!!requirement || !!question || !!sources.length || Object.values(recordDirty).some(Boolean)); }, [requirement, question, sources, recordDirty, onDirtyChange]);
  function create(event: FormEvent) { event.preventDefault(); if (!requirement || !question.trim() || !sources.length) { setValidation('请选择需求、填写澄清问题，并关联依据。'); document.getElementById(!requirement ? 'rd-clar-requirement' : 'rd-clar-question')?.focus(); return; } setValidation(''); void command('open_clarification', { requirement_id: requirement, question, source_ids: sources }, () => { setRequirement(''); setQuestion(''); setSources([]); }); }
  return <section className="rd-section"><div className="rd-section-head"><div><h3>需求澄清</h3><p>问题、实际答复与明确采用分别保存。必需澄清未闭合时保留阻断。</p></div></div>{(researchCase.clarifications ?? []).map(record => <ClarificationItem key={record.id} record={record} researchCase={researchCase} busy={busy} error={error} command={command} onDirtyChange={setChildDirty} />)}<details className="rd-record-new"><summary>提出澄清问题</summary><form noValidate onSubmit={create}><div className="rd-field"><label id="rd-clar-requirement-label">对应需求</label><StyledSelect id="rd-clar-requirement" aria-labelledby="rd-clar-requirement-label" value={requirement} options={[{ value: '', label: '选择当前需求' }, ...researchCase.requirements.map(item => ({ value: item.id, label: `${item.title} · v${item.revision ?? 1}` }))]} onChange={setRequirement} disabled={busy || !editable} /></div><div className="rd-field"><label htmlFor="rd-clar-question">需要澄清的问题</label><textarea id="rd-clar-question" rows={3} className="resize-none" value={question} onChange={event => setQuestion(event.target.value)} disabled={busy || !editable} /></div><SourcePicker sources={researchCase.sources} sourceSelection={researchCase.source_selection} value={sources} onChange={setSources} disabled={busy || !editable} />{validation && <p className="rd-error" role="alert">{validation}</p>}<button type="submit" className="rd-button primary" disabled={busy || !editable}>保存澄清问题</button>{!editable && <p className="rd-muted">当前阶段只读；在资料澄清或需求确认阶段提出问题。</p>}</form></details></section>;
}
