import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Alert, Button, Input, Table, Tag, Typography, type InputRef, type TableColumnsType } from 'antd';
import { SourcePicker } from './CaseFields';
import { useRequirementInlineEdit } from './useRequirementInlineEdit';
import { RequirementEvidence } from './RequirementEvidence';
import { isCurrentSource } from './presentation';
import { isCurrentClarification } from './clarificationReview';
import { isCurrentSpecificationBatch, originalRequirementValue, requirementActualResult, requirementDisplayResult } from './requirementActualResult';
import { RequirementReviewTools } from './RequirementReviewTools';
import type { Project, Requirement, ResearchCase, SourceEvidence } from './types';
import type { CommandRunner } from './WorkpackagePanel';
import './requirementDecisions.css';

interface Props {
  project: Project; researchCase: ResearchCase; actorId: string; readOnly: boolean; busy: boolean;
  command: CommandRunner; onReviewClarification?: (id: string) => void;
  onDirtyChange: (value: boolean) => void;
  reviewAction?: ReactNode;
}
interface Draft { base: string; value: string; reason: string; rejecting: boolean }
type Choice = 'accept' | 'reject';
const revision = (item: Requirement) => item.revision ?? item.version ?? 1;

export function RequirementDecisionTable({ project, researchCase: rc, actorId, command, busy, readOnly, onReviewClarification, onDirtyChange, reviewAction }: Props) {
  const inline = useRequirementInlineEdit(rc, command, busy || readOnly);
  const titleInput = useRef<InputRef>(null);
  useLayoutEffect(() => { if (inline.draft) titleInput.current?.focus({ preventScroll: true }); }, [inline.draft?.id]);
  const editing = (row: Requirement) => inline.draft?.id === row.id && !readOnly;
  const editLock = !!inline.draft;
  const analysis = rc.source_analysis;
  const sourceById = useMemo(() => new Map(rc.sources.map(source => [source.id, source])), [rc.sources]);
  const originals = useMemo(() => new Map(analysis?.requirements.flatMap(candidate => candidate.requirement_id ? [[candidate.requirement_id, candidate] as const] : [])), [analysis]);
  const currentAnalysis = analysis?.status === 'adopted' && analysis.adopted_input_revision === rc.input_revision;
  const batch = rc.requirement_recommendations;
  const suggestions = useMemo(() => new Map(batch?.items.map(item => [item.requirement_id, item])), [batch]);
  const currentBatch = isCurrentSpecificationBatch(rc);
  const clarified = (row: Requirement) => requirementActualResult(rc, row)?.kind === 'clarified';
  const batchRowCurrent = (row: Requirement) => currentBatch && (suggestions.get(row.id)?.requirement_revision === revision(row)
    || row.review?.recommendation_batch_id === batch?.id && row.review?.requirement_revision === revision(row)
    || !!requirementActualResult(rc, row));
  // Extraction may contain historical hints, but only a specification review batch supplies suggestions.
  const recommendation = (row: Requirement) => suggestions.get(row.id);
  const canAccept = (row: Requirement) => recommendation(row)?.status === 'needs_review' && originalRequirementValue(rc, row) !== null;
  const hasSuggestion = (row: Requirement) => !!recommendation(row) && recommendation(row)?.status !== 'not_found';
  const [recommending, setRecommending] = useState(false);
  const [recommendationFailed, setRecommendationFailed] = useState(false);
  const recommendationLock = useRef(false);
  const primarySpec = rc.sources.find(source => source.role === 'spec' && isCurrentSource(source, rc.source_selection));
  const sourceVersion = JSON.stringify(rc.sources.filter(s => isCurrentSource(s, rc.source_selection)).map(s => [s.id, s.version, s.sha256]).sort((a, b) => String(a[0]).localeCompare(String(b[0]))));
  const base = (row: Requirement) => JSON.stringify([analysis?.id ?? null, analysis?.status ?? null, sourceVersion, revision(row), ...(batch ? [batch.id] : [])]);
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
  const liveDraft = (item: Requirement) => drafts[item.id]?.base === base(item)
    && drafts[item.id].rejecting && !!batch && hasSuggestion(item) ? drafts[item.id] : undefined;
  const reviewed = (row: Requirement) => !!requirementDisplayResult(rc, row);
  const staleSource = (row: Requirement) => originals.has(row.id) && !currentAnalysis || row.source_ids.some(id => !sourceById.has(id) || !isCurrentSource(sourceById.get(id)!, rc.source_selection));
  const currentClarifications = (row: Requirement) => (rc.clarifications ?? []).filter(record => record.requirement_id === row.id && record.status !== 'adopted' && isCurrentClarification(record, rc.input_revision, revision(row)));
  const matches = (row: Requirement, key: string) => key === 'pending' ? !reviewed(row) : key === 'draft' ? !!drafts[row.id] || editing(row) && inline.dirty : key === 'stale' ? staleSource(row) : key === 'clarification' ? !!currentClarifications(row).length : true;
  const term = query.trim().toLocaleLowerCase();
  const searched = rc.requirements.filter(row => !term || [row.title, row.content, drafts[row.id]?.value, drafts[row.id]?.reason,
    originals.get(row.id)?.content, recommendation(row)?.text, recommendation(row)?.proposed_value,
    ...(originals.get(row.id)?.evidence ?? []).map(item => item.quote), ...(recommendation(row)?.evidence ?? []).map(item => item.quote),
    ...(rc.clarifications ?? []).filter(record => record.requirement_id === row.id).flatMap(record => [record.question, record.answer]),
  ].some(value => value?.toLocaleLowerCase().includes(term)));
  const matching = searched.filter(row => matches(row, filter));
  const editorPinned = rc.requirements.some(row => editing(row) && !matching.includes(row));
  const filtered = rc.requirements.filter(row => matching.includes(row) || editing(row));
  const pending = filtered.filter(row => !reviewed(row));
  const filters = [{ key: 'all', label: '全部' }, { key: 'pending', label: '待决定' }, { key: 'draft', label: '填写草稿' }, { key: 'stale', label: '来源待复核' }, { key: 'clarification', label: '待澄清' }]
    .map(item => ({ ...item, count: searched.filter(row => matches(row, item.key)).length }));
  function focusRow(id: string) {
    const row = Array.from(table.current?.querySelectorAll<HTMLTableRowElement>('tr[data-row-key]') ?? []).find(item => item.dataset.rowKey === id);
    row?.scrollIntoView({ block: 'nearest' }); row?.focus({ preventScroll: true });
  }
  const dirty = !readOnly && (inline.dirty || rc.requirements.some(item => !!liveDraft(item)));
  useLayoutEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  async function recommend() {
    if (busy || readOnly || editLock || recommendationLock.current || Object.keys(drafts).length || !primarySpec || !rc.requirements.length) return;
    recommendationLock.current = true; setRecommending(true); setRecommendationFailed(false);
    try { setRecommendationFailed(!await command('recommend_requirements', {})); }
    finally { recommendationLock.current = false; setRecommending(false); }
  }
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
    if (busy || readOnly || editLock || !actorId) return;
    if (!batchRowCurrent(item) || !hasSuggestion(item) || decision === 'accept' && !canAccept(item)) return;
    const draft = liveDraft(item);
    void command('review_requirement', {
      requirement_id: item.id, requirement_revision: revision(item), decision,
      ...(currentAnalysis ? { analysis_id: analysis!.id } : {}),
      ...(batch && batchRowCurrent(item) ? { recommendation_batch_id: batch.id } : {}),
      ...(decision === 'reject' ? { reason: draft?.reason.trim() } : {}),
    }, () => { put(item.id); });
  }
  function evidence(items: SourceEvidence[], aid = analysis?.id ?? null) {
    return <RequirementEvidence project={project} researchCase={rc} evidence={items} analysisId={aid} />;
  }
  const columns: TableColumnsType<Requirement> = [
    { key: 'metric', title: '类别 / 指标', width: '14%', render: (_, row) => <div className="rd-req-metric"><span>{String(rc.requirements.indexOf(row) + 1).padStart(2, '0')}</span>{editing(row)
      ? <div className="rd-inline-field"><label htmlFor={'req-title-' + row.id}>需求标题</label><Input ref={titleInput} id={'req-title-' + row.id} value={inline.draft!.title} disabled={busy || inline.saving} onChange={event => inline.change({ title: event.target.value })} /></div>
      : <strong>{row.title}</strong>}</div> },
    { key: 'original', title: '原始指标', width: '18%', render: (_, row) => {
      const original = originals.get(row.id);
      if (editing(row)) return <div className="rd-inline-content">
        <div className="rd-inline-field"><label htmlFor={'req-content-' + row.id}>需求内容</label><Input.TextArea id={'req-content-' + row.id} value={inline.draft!.content} autoSize={{ minRows: 3, maxRows: 10 }} disabled={busy || inline.saving} onChange={event => inline.change({ content: event.target.value })} /></div>
        {original && <details className="rd-req-source"><summary>查看原始指标</summary><p className="rd-req-original">{original.content}</p>{evidence(original.evidence)}</details>}
        <details className="rd-inline-sources" open={inline.hasInvalidSource || undefined}><summary>关联来源</summary><SourcePicker sources={rc.sources} sourceSelection={rc.source_selection} value={inline.draft!.source_ids} onChange={source_ids => inline.change({ source_ids })} disabled={busy || inline.saving} label="需求记录来源" /></details>
      </div>;
      if (!original) return <p className="rd-req-original">{row.content}</p>;
      if (row.content !== original.content && !requirementDisplayResult(rc, row)) return <><Tag>已修订</Tag><p className="rd-req-original">{row.content}</p><details className="rd-req-source"><summary>查看原始指标</summary><p className="rd-req-original">{original.content}</p>{evidence(original.evidence)}</details></>;
      return original ? <><p className="rd-req-original">{original.content}</p>{!!original.evidence.length && <details className="rd-req-source"><summary>查看原文</summary>{evidence(original.evidence)}</details>}</> :
        <span className="rd-req-muted">未关联原文</span>;
    } },
    { key: 'recommend', title: 'AI 推荐', width: '16%', render: (_, row) => {
      const rec = recommendation(row), result = suggestions.get(row.id);
      const labels = { matched: '已找到规范依据', difference: '指标存在差异', needs_review: '适用性待核对', not_found: '规范未找到对应指标' };
      return rec ? <>{result && <Tag color={result.status === 'difference' || result.status === 'needs_review' ? 'warning' : undefined}>{labels[result.status]}</Tag>}
        <p className="rd-req-original">{rec.text}</p>{rec.status === 'needs_review'
          ? <small className="rd-review-hint">采纳后采用原始指标</small>
          : rec.proposed_value && <small className="rd-review-hint">建议指标：{rec.proposed_value}</small>}
        {batch && !batchRowCurrent(row) && <small className="rd-review-hint">建议已过期，请重新核对规范</small>}</> : <span className="rd-req-muted">尚未核对规范</span>;
    } },
    { key: 'evidence', title: '证据来源', width: '14%', render: (_, row) => {
      const rec = recommendation(row);
      return rec?.evidence.length ? evidence(rec.evidence, batch!.id) : <span className="rd-req-muted" aria-label="没有建议来源">—</span>;
    } },
    { key: 'action', title: '操作', width: '16%', render: (_, row) => {
      const rec = recommendation(row);
      const archived = row.source_ids.some(id => !sourceById.has(id) || !isCurrentSource(sourceById.get(id)!, rc.source_selection));
      const draft = liveDraft(row);
      const disableSuggestion = busy || editLock || !currentAnalysis || !batchRowCurrent(row) || clarified(row) || archived || !!drafts[row.id];
      const currentChoice = row.review?.requirement_revision === revision(row) && row.review.recommendation_batch_id === batch?.id ? row.review.decision : undefined;
      if (readOnly) return <span className="rd-req-muted">只读</span>;
      if (editing(row)) return <div className="rd-inline-actions">
        <div><Button type="primary" size="small" loading={inline.saving} disabled={busy || !inline.dirty || inline.stale} onClick={() => void inline.save()}>保存</Button><Button size="small" disabled={busy || inline.saving} onClick={inline.cancel}>取消</Button></div>
        <small className="rd-review-hint">修订后需重新核对，不会自动采纳。</small>
        {inline.error && <p className="rd-inline-error" role="alert">{inline.error}</p>}
      </div>;
      return <div className="rd-review-actions">
        {rec && rec.status !== 'matched' && hasSuggestion(row) && <div>{canAccept(row) && <Button size="small" disabled={disableSuggestion || currentChoice === 'accept'} onClick={() => submit(row, 'accept')}>采纳</Button>}
          <Button size="small" disabled={disableSuggestion || currentChoice === 'reject'} onClick={() => edit(row, { rejecting: true })}>不采纳</Button></div>}
        {draft?.rejecting && <div className="rd-review-reason"><Input.TextArea aria-label={row.title + ' 不采纳原因'} autoSize={{ minRows: 2, maxRows: 5 }} value={draft.reason} disabled={busy || editLock} onChange={event => edit(row, { reason: event.target.value })} placeholder="说明不采纳的原因" />
          <Button size="small" disabled={busy || editLock || !currentAnalysis || !batchRowCurrent(row) || archived || !draft.reason.trim()} onClick={() => submit(row, 'reject')}>确认不采纳</Button></div>}
        <div className="rd-req-actions">{rec?.status !== 'matched' && rec?.status !== 'needs_review' && <Button type="link" size="small" disabled={busy || editLock || !!drafts[row.id]} onClick={() => inline.begin(row)}>编辑需求</Button>}
          {onReviewClarification && <Button type="link" size="small" disabled={busy || editLock} onClick={() => onReviewClarification(row.id)}>办理澄清</Button>}</div>
      </div>;
    } },
    { key: 'actual', title: '实际结果', width: '22%', render: (_, row) => {
      const draft = liveDraft(row), staleDraft = drafts[row.id] && !draft;
      const result = requirementDisplayResult(rc, row);
      const archived = row.source_ids.some(id => !sourceById.has(id) || !isCurrentSource(sourceById.get(id)!, rc.source_selection));
      return <div className="rd-review-actual">
        <p className="rd-req-original" aria-label={row.title + ' 实际结果'}>{result?.value ?? '--'}</p>
        {result ? <Tag>{result.kind === 'clarified' ? '澄清已采用' : result.kind === 'baseline' ? '已确认基线' : result.kind === 'specification' ? (readOnly ? '规范指标已确认' : '规范建议 · 待确认') : '已采纳'}</Tag>
          : row.review?.decision === 'reject' && row.review.requirement_revision === revision(row) && <Tag>不采纳 · 待澄清</Tag>}
        {!result && row.review?.decision === 'manual' && row.review.actual_value && <details className="rd-review-old-draft"><summary>历史填写记录</summary><Typography.Paragraph copyable>{row.review.actual_value}</Typography.Paragraph><small>{row.review.reason}</small></details>}
        {archived && <small className="rd-review-hint">来源待更新</small>}
        {staleDraft && <details className="rd-review-old-draft"><summary>旧版草稿 · 不会应用</summary><Typography.Paragraph copyable>{drafts[row.id].value}</Typography.Paragraph><small>{drafts[row.id].reason}</small></details>}
        {drafts[row.id] && !readOnly && <Button size="small" type="link" disabled={busy} onClick={() => put(row.id)}>放弃{staleDraft ? '旧稿' : '草稿'}</Button>}
      </div>;
    } },
  ];
  return <><div className="rd-spec-review-toolbar">
    <div><strong>规范对照建议</strong><p className="rd-muted">{batch ? `${batch.items.length} 项 · ${batch.model_selection.name} · ${new Date(batch.created_at).toLocaleString()}` : '逐项查找规范指标，核对后再采纳。'}</p></div>
    {!readOnly && <Button loading={recommending} disabled={busy || editLock || !currentAnalysis || !primarySpec || !rc.requirements.length || !!Object.keys(drafts).length}
      onClick={() => void recommend()}>{recommending ? '正在逐项核对' : batch ? '重新核对规范' : '按规范生成建议'}</Button>}
  </div>
    {!primarySpec && !readOnly && <Alert type="info" showIcon message="请先在资料识别中上传并选择主产品规范。" />}
    {!!Object.keys(drafts).length && !readOnly && <p className="rd-muted">请先处理不采纳原因或放弃旧稿，再重新核对规范。</p>}
    {recommendationFailed && <Alert type="warning" showIcon message="本次规范核对未完成，原有结果已保留。请检查页面错误提示后重试。" />}
    {batch?.status === 'stale' && <Alert type="warning" showIcon message="需求或来源已变更，请重新核对规范。" />}
    {!!batch?.warnings.length && <details className="rd-req-source"><summary>核对提示（{batch.warnings.length}）</summary><ul>{batch.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></details>}
    {!!originals.size && !currentAnalysis && !readOnly && <p className="rd-warning" role="status">来源或分析版本已变化，请在“资料识别”重新核对并采用。</p>}
    {storageError && <p className="rd-warning" role="status">浏览器未能更新本地草稿。请复制当前填写后再离开。</p>}
    <RequirementReviewTools label="筛选需求确认" searchLabel="搜索需求确认" query={query} onQueryChange={value => { setQuery(value); setFocusedId(null); }} filters={filters} activeFilter={filter}
      onFilterChange={value => { setFilter(value); setFocusedId(null); }} nextDisabled={!pending.length} onNext={() => {
        const index = pending.findIndex(row => row.id === focusedId), id = pending[(index + 1) % pending.length].id;
        setFocusedId(id); focusRow(id);
      }} trailingAction={reviewAction} />
    <p className="rd-review-result-count" role="status">显示 {filtered.length} / {rc.requirements.length} 项；筛选不会丢弃填写草稿。</p>
    {editorPinned && <p className="rd-muted">正在编辑的需求保留显示，保存或取消后应用筛选。</p>}
    <div ref={table}><Table<Requirement> className="rd-requirement-list rd-req-table rd-decision-table" dataSource={filtered} columns={columns} rowKey="id" size="small" tableLayout="fixed" pagination={false}
      onRow={row => ({ tabIndex: -1, className: [row.id === focusedId ? 'rd-review-current-row' : '', editing(row) ? 'rd-requirement-editing' : ''].filter(Boolean).join(' ') })}
      locale={{ emptyText: rc.requirements.length ? '没有匹配的需求，请调整搜索或筛选。' : '尚未采用原文需求。先分析上传资料，核对识别结果后确认采用。' }} /></div></>;
}
