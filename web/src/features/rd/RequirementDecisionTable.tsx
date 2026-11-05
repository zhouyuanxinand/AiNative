import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Button, Input, Table, Tag, type TableColumnsType } from 'antd';
import { RequirementEvidence } from './RequirementEvidence';
import { ProjectProfileLinks } from './ProjectProfileLinks';
import { isCurrentSource } from './presentation';
import { isCurrentClarification } from './clarificationReview';
import { RequirementReviewTools } from './RequirementReviewTools';
import type { Project, Requirement, ResearchCase, SourceEvidence } from './types';
import type { CommandRunner } from './WorkpackagePanel';
import './requirementDecisions.css';

interface Props {
  project: Project; researchCase: ResearchCase; actorId: string; readOnly: boolean; busy: boolean;
  command: CommandRunner; onEdit: (item: Requirement) => void; onReviewClarification?: (id: string) => void;
  onDirtyChange: (value: boolean) => void;
}
interface Draft { base: string; value: string; reason: string; rejecting: boolean }
type Choice = 'accept' | 'reject' | 'manual';
const choices = { accept: '已采纳', reject: '不采纳', manual: '人工填写' };
const revision = (item: Requirement) => item.revision ?? item.version ?? 1;

export function RequirementDecisionTable({ project, researchCase: rc, actorId, command, busy, readOnly, onEdit, onReviewClarification, onDirtyChange }: Props) {
  const analysis = rc.source_analysis;
  const sourceById = useMemo(() => new Map(rc.sources.map(source => [source.id, source])), [rc.sources]);
  const originals = useMemo(() => new Map(analysis?.requirements.flatMap(candidate => candidate.requirement_id ? [[candidate.requirement_id, candidate] as const] : [])), [analysis]);
  const currentAnalysis = analysis?.status === 'adopted' && analysis.adopted_input_revision === rc.input_revision;
  const sourceVersion = JSON.stringify(rc.sources.filter(s => isCurrentSource(s, rc.source_selection)).map(s => [s.id, s.version, s.sha256]).sort((a, b) => String(a[0]).localeCompare(String(b[0]))));
  const base = (row: Requirement) => JSON.stringify([analysis?.id ?? null, analysis?.status ?? null, sourceVersion, revision(row)]);
  const draftKey = (id: string) => 'rd:requirement-draft:v1:' + JSON.stringify([actorId, project.owner_id === actorId ? 'owner' : 'member', project.id, rc.id, id]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() => {
    const result: Record<string, Draft> = {};
    if (actorId) for (const row of rc.requirements) {
      try {
        const raw = localStorage.getItem(draftKey(row.id));
        if (!raw) continue;
        const saved = JSON.parse(raw);
        if (saved && typeof saved.base === 'string' && typeof saved.value === 'string' && typeof saved.reason === 'string' && typeof saved.rejecting === 'boolean') result[row.id] = saved;
      } catch { /* An unreadable entry is not a valid draft. */ }
    }
    return result;
  });
  const [storageError, setStorageError] = useState(false);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const table = useRef<HTMLDivElement>(null);
  const liveDraft = (item: Requirement) => drafts[item.id]?.base === base(item) ? drafts[item.id] : undefined;
  const reviewed = (row: Requirement) => row.review?.requirement_revision === revision(row) && (!row.review.analysis_id || row.review.analysis_id === analysis?.id);
  const staleSource = (row: Requirement) => originals.has(row.id) && !currentAnalysis || row.source_ids.some(id => !sourceById.has(id) || !isCurrentSource(sourceById.get(id)!, rc.source_selection));
  const currentClarifications = (row: Requirement) => (rc.clarifications ?? []).filter(record => record.requirement_id === row.id && record.status !== 'adopted' && isCurrentClarification(record, rc.input_revision, revision(row)));
  const matches = (row: Requirement, key: string) => key === 'pending' ? !reviewed(row) : key === 'draft' ? !!drafts[row.id] : key === 'stale' ? staleSource(row) : key === 'clarification' ? !!currentClarifications(row).length : true;
  const term = query.trim().toLocaleLowerCase();
  const searched = rc.requirements.filter(row => !term || [row.title, row.content, drafts[row.id]?.value, drafts[row.id]?.reason,
    originals.get(row.id)?.content, originals.get(row.id)?.recommendation?.text, originals.get(row.id)?.recommendation?.proposed_value,
    ...(originals.get(row.id)?.evidence ?? []).map(item => item.quote), ...(originals.get(row.id)?.recommendation?.evidence ?? []).map(item => item.quote),
    ...(rc.clarifications ?? []).filter(record => record.requirement_id === row.id).flatMap(record => [record.question, record.answer]),
  ].some(value => value?.toLocaleLowerCase().includes(term)));
  const filtered = searched.filter(row => matches(row, filter));
  const pending = filtered.filter(row => !reviewed(row));
  const filters = [{ key: 'all', label: '全部' }, { key: 'pending', label: '待决定' }, { key: 'draft', label: '填写草稿' }, { key: 'stale', label: '来源待复核' }, { key: 'clarification', label: '待澄清' }]
    .map(item => ({ ...item, count: searched.filter(row => matches(row, item.key)).length }));
  function focusRow(id: string) {
    const row = Array.from(table.current?.querySelectorAll<HTMLTableRowElement>('tr[data-row-key]') ?? []).find(item => item.dataset.rowKey === id);
    row?.scrollIntoView({ block: 'nearest' }); row?.focus({ preventScroll: true });
  }
  const dirty = !readOnly && rc.requirements.some(item => !!liveDraft(item));
  useLayoutEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  function put(id: string, draft?: Draft) {
    setDrafts(previous => { const next = { ...previous }; if (draft) next[id] = draft; else delete next[id]; return next; });
    try {
      if (draft) localStorage.setItem(draftKey(id), JSON.stringify(draft)); else localStorage.removeItem(draftKey(id));
      setStorageError(false);
    } catch { setStorageError(true); }
  }
  function edit(row: Requirement, fields: Partial<Draft>) {
    const next = { base: base(row), value: row.content, reason: '', rejecting: false, ...liveDraft(row), ...fields };
    put(row.id, next.value === row.content && !next.rejecting ? undefined : next);
  }
  function submit(item: Requirement, decision: Choice) {
    if (busy || readOnly || !actorId) return;
    const draft = liveDraft(item);
    void command('review_requirement', {
      requirement_id: item.id, requirement_revision: revision(item), decision,
      ...(currentAnalysis ? { analysis_id: analysis!.id } : {}),
      ...(decision === 'manual' ? { actual_value: draft?.value.trim(), ...(draft?.value.trim() === '不适用' ? { reason: draft.reason.trim() } : {}) } : {}),
      ...(decision === 'reject' ? { reason: draft?.reason.trim() } : {}),
    }, () => put(item.id));
  }
  function evidence(items: SourceEvidence[]) {
    return <RequirementEvidence project={project} researchCase={rc} evidence={items} analysisId={analysis?.id ?? null} />;
  }
  const columns: TableColumnsType<Requirement> = [
    { key: 'metric', title: '类别 / 指标', width: '14%', render: (_, row) => <div className="rd-req-metric"><span>{String(rc.requirements.indexOf(row) + 1).padStart(2, '0')}</span><strong>{originals.get(row.id)?.title ?? row.title}</strong></div> },
    { key: 'original', title: '原始指标', width: '18%', render: (_, row) => {
      const original = originals.get(row.id);
      return original ? <><p className="rd-req-original">{original.content}</p>{!!original.evidence.length && <details className="rd-req-source"><summary>查看原文</summary>{evidence(original.evidence)}</details>}</> :
        <span className="rd-req-muted">未关联原文</span>;
    } },
    { key: 'recommend', title: 'AI 推荐', width: '16%', render: (_, row) => {
      const rec = originals.get(row.id)?.recommendation;
      return rec ? <><p className="rd-req-original">{rec.text}</p><small className="rd-review-hint">建议指标：{rec.proposed_value}</small></> : <span className="rd-req-muted">暂无有据建议</span>;
    } },
    { key: 'evidence', title: '证据来源', width: '14%', render: (_, row) => {
      const rec = originals.get(row.id)?.recommendation;
      return rec?.evidence.length ? evidence(rec.evidence) : <span className="rd-req-muted" aria-label="没有建议来源">—</span>;
    } },
    { key: 'action', title: '操作', width: '16%', render: (_, row) => {
      const rec = originals.get(row.id)?.recommendation;
      const archived = row.source_ids.some(id => !sourceById.has(id) || !isCurrentSource(sourceById.get(id)!, rc.source_selection));
      const draft = liveDraft(row);
      const disableSuggestion = busy || !currentAnalysis || archived || !!drafts[row.id];
      const currentChoice = row.review?.analysis_id === analysis?.id && row.review?.requirement_revision === revision(row) ? row.review?.decision : undefined;
      if (readOnly) return <span className="rd-req-muted">只读</span>;
      return <div className="rd-review-actions">
        {rec && <div><Button size="small" disabled={disableSuggestion || currentChoice === 'accept'} onClick={() => submit(row, 'accept')}>采纳</Button>
          <Button size="small" disabled={disableSuggestion || currentChoice === 'reject'} onClick={() => edit(row, { rejecting: true })}>不采纳</Button></div>}
        {draft?.rejecting && <div className="rd-review-reason"><Input.TextArea aria-label={row.title + ' 不采纳原因'} autoSize={{ minRows: 2, maxRows: 5 }} value={draft.reason} disabled={busy} onChange={event => edit(row, { reason: event.target.value })} placeholder="说明不采纳的原因" />
          <Button size="small" disabled={busy || !currentAnalysis || archived || !draft.reason.trim()} onClick={() => submit(row, 'reject')}>确认不采纳</Button></div>}
        <div className="rd-req-actions"><Button type="link" size="small" disabled={busy || !!drafts[row.id]} onClick={() => onEdit(row)}>编辑需求</Button>
          {onReviewClarification && <Button type="link" size="small" disabled={busy} onClick={() => onReviewClarification(row.id)}>办理澄清</Button>}</div>
      </div>;
    } },
    { key: 'actual', title: '实际结果', width: '22%', render: (_, row) => {
      const draft = liveDraft(row), staleDraft = drafts[row.id] && !draft;
      const needsReason = !!draft && !draft.rejecting && draft.value.trim() === '不适用';
      const staleAnalysis = originals.has(row.id) && !currentAnalysis;
      const reviewed = row.review?.requirement_revision === revision(row) && (!row.review.analysis_id || row.review.analysis_id === analysis?.id);
      const archived = row.source_ids.some(id => !sourceById.has(id) || !isCurrentSource(sourceById.get(id)!, rc.source_selection));
      return <div className="rd-review-actual">
        {readOnly ? <p className="rd-req-original">{row.content}</p> : <Input.TextArea aria-label={row.title + ' 实际结果'} value={draft?.value ?? row.content} autoSize={{ minRows: 2, maxRows: 6 }} disabled={busy || archived || staleAnalysis || staleDraft || draft?.rejecting} onChange={event => edit(row, { value: event.target.value })} />}
        {needsReason && !readOnly && <Input.TextArea aria-label={row.title + ' 不适用原因'} autoSize={{ minRows: 2, maxRows: 5 }} disabled={busy || archived || staleAnalysis} placeholder="说明不适用的原因（必填）" value={draft.reason} onChange={event => edit(row, { reason: event.target.value })} />}
        {reviewed && <div><Tag>{choices[row.review!.decision]}</Tag>{row.review!.reason && <small className="rd-review-hint">{row.review!.reason}</small>}</div>}
        {archived && <small className="rd-review-hint">来源待更新</small>}
        {staleDraft && <details className="rd-review-old-draft"><summary>旧版草稿 · 不会应用</summary><p>{drafts[row.id].value}</p><small>{drafts[row.id].reason}</small></details>}
        {draft && !draft.rejecting && !readOnly && <Button type="primary" size="small" disabled={busy || archived || staleAnalysis || !draft.value.trim() || (needsReason && !draft.reason.trim())} onClick={() => submit(row, 'manual')}>保存实际结果</Button>}
        {drafts[row.id] && !readOnly && <Button size="small" type="link" disabled={busy} onClick={() => put(row.id)}>放弃{staleDraft ? '旧稿' : '草稿'}</Button>}
      </div>;
    } },
  ];
  return <><div className="rd-review-profile-toolbar"><ProjectProfileLinks project={project} researchCase={rc} /></div>{!!originals.size && !currentAnalysis && !readOnly && <p className="rd-warning" role="status">来源或分析版本已变化，请在“资料识别”重新核对并采用。旧分析中的建议暂不可办理。</p>}
    {storageError && <p className="rd-warning" role="status">浏览器未能更新本地草稿。当前填写仍在此页，请在离开前保存实际结果。</p>}
    <RequirementReviewTools label="筛选需求确认" searchLabel="搜索需求确认" query={query} onQueryChange={value => { setQuery(value); setFocusedId(null); }} filters={filters} activeFilter={filter}
      onFilterChange={value => { setFilter(value); setFocusedId(null); }} nextDisabled={!pending.length} onNext={() => {
        const index = pending.findIndex(row => row.id === focusedId), id = pending[(index + 1) % pending.length].id;
        setFocusedId(id); focusRow(id);
      }} />
    <p className="rd-review-result-count" role="status">显示 {filtered.length} / {rc.requirements.length} 项；筛选不会丢弃填写草稿。</p>
    <div ref={table}><Table<Requirement> className="rd-requirement-list rd-req-table rd-decision-table" dataSource={filtered} columns={columns} rowKey="id" size="small" tableLayout="fixed" pagination={false}
      onRow={row => ({ tabIndex: -1, className: row.id === focusedId ? 'rd-review-current-row' : '' })}
      locale={{ emptyText: rc.requirements.length ? '没有匹配的需求，请调整搜索或筛选。' : '尚未采用原文需求。先分析上传资料，核对识别结果后确认采用。' }} /></div></>;
}
