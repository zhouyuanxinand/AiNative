import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Button, Checkbox, Modal, Table } from 'antd';
import { FullscreenOutlined, FullscreenExitOutlined } from '@ant-design/icons';
import type { TableColumnsType } from 'antd';
import { isCurrentClarification } from './clarificationReview';
import { RequirementReviewTools } from './RequirementReviewTools';
import type { Clarification, Requirement, SourceAnalysis, SourceEvidence } from './types';
import './sourceRequirementList.css';

type Candidate = SourceAnalysis['requirements'][number];
interface Row { number: number; original: Candidate; requirement?: Requirement; clarifications: Clarification[] }
const labels = { open: '待答复', answered: '待采用', adopted: '已采用' } as const;

function ClarificationText({ record }: { record: Clarification }) {
  return <div className="rd-req-record">
    <span className={'rd-req-state ' + record.status}>{labels[record.status]}</span>
    <strong>{record.question}</strong>
    {record.answer && <p><small>答复</small>{record.answer}</p>}
    {record.adoption && <p><small>采用结果 · 修订 {record.adoption.requirement_revision}</small>{record.adoption.requirement_content}</p>}
  </div>;
}

// 本体 Agent 接入后，按组件/型号、指标、工况与单位从 K-box 查询经版本核实的资料；
// 保留命中值及出处。原文要求、人工比对候选、澄清回复均不是企业组件的能力值。
function LookupNote() {
  return <details className="rd-req-lookup"><summary>自有组件指标查询思路</summary>
    <p>本体查询尚未接入，“—”表示暂无核实值。后续由本体 Agent 按产品系列、组件型号和指标查询 K-box，核对单位、适用工况及资料版本后，回填组件指标与出处。找不到依据时保留空值。</p>
  </details>;
}

export function SourceRequirementList({ analysis, requirements, clarifications, inputRevision, stale, evidenceList, onReviewClarification, selectedRows, selectionDisabled, onSelectSuggestion, adoption }: {
  analysis: SourceAnalysis; requirements: Requirement[]; clarifications: Clarification[]; inputRevision?: number; stale: boolean;
  evidenceList: (evidence: SourceEvidence[]) => ReactNode; onReviewClarification?: (requirementId: string) => void;
  selectedRows: number[]; selectionDisabled: boolean; onSelectSuggestion: (index: number) => void;
  adoption?: { disabled: boolean; pending: boolean; error: string; submit: () => Promise<boolean> };
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [previewQuery, setPreviewQuery] = useState('');
  const [previewFilter, setPreviewFilter] = useState('all');
  const [focusedNumber, setFocusedNumber] = useState<number | null>(null);
  const [adoptionFailed, setAdoptionFailed] = useState(false);
  const scroll = useRef<HTMLDivElement>(null);
  const preview = useRef<HTMLDivElement>(null);
  const firstVisible = useRef<number>(1);
  const nextClarification = useRef<string | null>(null);
  const rows = useMemo(() => {
    const byId = new Map(requirements.map(req => [req.id, req]));
    const records = new Map<string, Clarification[]>();
    for (const record of clarifications) {
      const existing = records.get(record.requirement_id);
      if (existing) existing.push(record); else records.set(record.requirement_id, [record]);
    }
    return analysis.requirements.map((original, index): Row => {
      const requirement = original.requirement_id ? byId.get(original.requirement_id) : undefined;
      return { original, number: index + 1, requirement, clarifications: requirement ? records.get(requirement.id) ?? [] : [] };
    });
  }, [analysis.requirements, requirements, clarifications]);
  function searchRows(query: string) {
    const term = query.trim().toLocaleLowerCase();
    return term ? rows.filter(row => [
    row.original.title, row.original.content, ...row.original.evidence.map(item => item.quote),
    row.original.recommendation?.text, row.original.recommendation?.proposed_value, ...(row.original.recommendation?.evidence ?? []).map(item => item.quote),
    ...row.clarifications.flatMap(item => [item.question, item.answer, item.adoption?.requirement_content]),
    ].some(value => value?.toLocaleLowerCase().includes(term))) : rows;
  }
  const searched = searchRows(query);
  const hasClarification = (row: Row) => row.clarifications.some(record => record.status !== 'adopted' && isCurrentClarification(record, inputRevision, row.requirement?.revision ?? row.requirement?.version));
  const isPending = (row: Row) => analysis.status !== 'adopted' || !row.requirement?.review || row.requirement.review.requirement_revision !== (row.requirement.revision ?? row.requirement.version ?? 1)
    || !!row.requirement.review.analysis_id && row.requirement.review.analysis_id !== analysis.id;
  const matches = (row: Row, key: string) => key === 'pending' ? isPending(row) : key === 'selected' ? selectedRows.includes(row.number - 1) : key === 'clarification' ? hasClarification(row) : key === 'stale' ? stale : true;
  const filtered = searched.filter(row => matches(row, filter));
  const previewSearched = searchRows(previewQuery);
  const previewFiltered = previewSearched.filter(row => matches(row, previewFilter));
  function focusRow(number: number) {
    const container = open ? scroll.current : preview.current;
    const row = container?.querySelector<HTMLTableRowElement>('tr[data-row-key="' + number + '"]');
    row?.scrollIntoView({ block: 'nearest' }); row?.focus({ preventScroll: true });
  }
  function tools(fullscreen = false) {
    const pending = (fullscreen ? filtered : previewFiltered).filter(isPending);
    const filters = [{ key: 'all', label: '全部' }, { key: 'pending', label: '待处理' }, { key: 'selected', label: '已选建议' }, { key: 'clarification', label: '待澄清' }, { key: 'stale', label: '来源待复核' }]
      .map(item => ({ ...item, count: (fullscreen ? searched : previewSearched).filter(row => matches(row, item.key)).length }));
    return <RequirementReviewTools label="筛选原文需求" searchLabel="搜索需求" query={fullscreen ? query : previewQuery} filters={filters} activeFilter={fullscreen ? filter : previewFilter}
      onQueryChange={value => { (fullscreen ? setQuery : setPreviewQuery)(value); setFocusedNumber(null); if (scroll.current) scroll.current.scrollTop = 0; }}
      onFilterChange={value => { (fullscreen ? setFilter : setPreviewFilter)(value); setFocusedNumber(null); }} nextDisabled={!pending.length} onNext={() => {
        const index = pending.findIndex(row => row.number === focusedNumber), number = pending[(index + 1) % pending.length].number;
        setFocusedNumber(number); focusRow(number);
      }} />;
  }
  useEffect(() => {
    if (!open) return;
    const close = () => { nextClarification.current = null; setOpen(false); };
    window.addEventListener('popstate', close);
    return () => window.removeEventListener('popstate', close);
  }, [open]);

  function clarificationCell(row: Row) {
    const requirementId = row.requirement?.id;
    const latest = (record: Clarification) => isCurrentClarification(record, inputRevision, row.requirement?.revision ?? row.requirement?.version);
    const currentRecords = row.clarifications.filter(latest);
    const history = row.clarifications.filter(record => !latest(record));
    return <>
      {currentRecords.map(record => <ClarificationText key={record.id} record={record} />)}
      {!currentRecords.length && <span className="rd-req-muted">{history.length ? '当前版本无澄清' : row.requirement ? '尚无澄清记录' : analysis.status === 'proposed' ? '采用后可澄清' : '未关联需求记录'}</span>}
      {history.length > 0 && <details className="rd-req-history"><summary>历史澄清（{history.length}）</summary>{history.map(record => <ClarificationText key={record.id} record={record} />)}</details>}
      {requirementId && onReviewClarification && <Button size="small" type="link" className="rd-req-link" onClick={() => {
        if (!open) { onReviewClarification(requirementId); return; }
        nextClarification.current = requirementId;
        setOpen(false);
      }}>办理澄清</Button>}
    </>;
  }
  const columns: TableColumnsType<Row> = [
    { key: 'metric', title: '指标', width: '18%', render: (_, row) => <div className="rd-req-metric"><span>{String(row.number).padStart(2, '0')}</span><strong>{row.original.title}</strong></div> },
    { key: 'original', title: '原文指标', width: '22%', render: (_, row) => <><p className="rd-req-original">{row.original.content}</p>{row.original.evidence.length > 0 && <details className="rd-req-source"><summary>核对来源原文</summary>{evidenceList(row.original.evidence)}</details>}</> },
    { key: 'company', title: '公司自有组件指标', width: '12%', render: () => <span className="rd-req-muted" aria-label="暂无核实的自有组件指标">—</span> },
    { key: 'recommendation', title: 'AI 推荐', width: '20%', render: (_, row) => {
      const suggestion = row.original.recommendation;
      if (!suggestion) return <span className="rd-req-muted">暂无建议</span>;
      return <div className="rd-req-record"><strong>{suggestion.text}</strong><p>建议指标：{suggestion.proposed_value}</p>
        {analysis.status === 'proposed' && <Checkbox checked={selectedRows.includes(row.number - 1)} disabled={selectionDisabled}
          onChange={() => onSelectSuggestion(row.number - 1)}>选用此建议</Checkbox>}
      </div>;
    } },
    { key: 'basis', title: '证据来源', width: '12%', render: (_, row) => row.original.recommendation?.evidence.length
      ? <details className="rd-req-source"><summary>建议依据</summary>{evidenceList(row.original.recommendation.evidence)}</details> : <span className="rd-req-muted">—</span> },
    { key: 'clarification', title: '需求澄清', width: '16%', render: (_, row) => clarificationCell(row) },
  ];
  function table(data: Row[]) {
    return <Table<Row> className="rd-req-table rd-analysis-grid" dataSource={data} columns={columns} rowKey="number" size="small" pagination={false} tableLayout="fixed"
      onRow={row => ({ tabIndex: -1, className: row.number === focusedNumber ? 'rd-review-current-row' : '' })}
      locale={{ emptyText: rows.length ? '没有匹配的需求，请调整搜索词或筛选。' : '本次尚未提取到可引用的原文需求，请核对资料后重新分析。' }} />;
  }
  return <section className="rd-analysis-requirements" aria-label="需求清单">
    <header className="rd-req-head"><div><h4>需求清单</h4><span>{rows.length} 项</span></div>
      <Button icon={<FullscreenOutlined aria-hidden />} disabled={!rows.length} onClick={() => {
        const el = preview.current;
        if (el) {
          const top = el.getBoundingClientRect().top + (el.querySelector('thead')?.offsetHeight ?? 0);
          firstVisible.current = Number(Array.from(el.querySelectorAll('tr[data-row-key]')).find(row => row.getBoundingClientRect().bottom > top)?.getAttribute('data-row-key')) || 1;
        }
        setQuery(previewQuery); setFilter(previewFilter); setAdoptionFailed(false); setOpen(true);
      }}>全屏审阅</Button></header>
    {tools()}
    <p className="rd-review-result-count" role="status">显示 {previewFiltered.length} / {rows.length} 项需求</p>
    <LookupNote />
    <div ref={preview} className="rd-analysis-scroll" role="region" aria-label="原文需求对照" tabIndex={0}>{table(previewFiltered)}</div>
    <Modal title="需求清单审阅" rootClassName="rd-req-review-modal" open={open} width="100%" footer={null} closable={false} onCancel={() => { if (!adoption?.pending) setOpen(false); }}
      afterClose={() => {
        const id = nextClarification.current;
        nextClarification.current = null;
        if (id) onReviewClarification?.(id);
      }}
      afterOpenChange={visible => {
        if (visible && scroll.current) {
          const row = scroll.current.querySelector('tr[data-row-key="' + firstVisible.current + '"]');
          scroll.current.scrollTop = row && firstVisible.current > 1 ? row.getBoundingClientRect().top - scroll.current.getBoundingClientRect().top + scroll.current.scrollTop - (scroll.current.querySelector('thead')?.offsetHeight ?? 0) : 0;
        }
      }}>
      <div className="rd-req-review-tools"><div><span>{filtered.length + ' / ' + rows.length} 项需求</span>
        <span className={stale ? 'rd-req-warning' : ''}>{stale ? '历史分析 · 待重新分析' : analysis.status === 'adopted' ? '已采用' : '待核对采用'}</span></div>
        <Button icon={<FullscreenExitOutlined aria-hidden />} disabled={adoption?.pending} onClick={() => setOpen(false)}>退出全屏</Button></div>
      <div className="rd-req-review-filters">{tools(true)}</div>
      <LookupNote />
      <div className="rd-req-review-scroll" ref={scroll}>{table(filtered)}</div>
      {adoption && <div className="rd-req-review-adopt"><div><p>筛选仅影响显示；确认采用将采用全部 {rows.length} 项原文需求、可采用的识别信息和已选 {selectedRows.length} 条建议。</p>
        {stale && <p className="rd-warning">来源已变化，请退出全屏并重新分析后再采用。</p>}
        {adoptionFailed && <p className="rd-warning" role="status">{adoption.error || '采用尚未成功。'} 当前选择已保留，请核对错误后重试；也可退出全屏检查资料与模型设置。</p>}</div>
        <Button type="primary" disabled={adoption.disabled} onClick={async () => {
          setAdoptionFailed(false); const ok = await adoption.submit(); if (ok) setOpen(false); else setAdoptionFailed(true);
        }}>{adoption.pending ? '正在采用…' : '确认采用'}</Button></div>}
    </Modal>
  </section>;
}
