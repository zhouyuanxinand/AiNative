import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Button, Input, Modal, Table } from 'antd';
import { FullscreenOutlined, FullscreenExitOutlined, SearchOutlined } from '@ant-design/icons';
import type { TableColumnsType } from 'antd';
import { isCurrentClarification } from './clarificationReview';
import type { Clarification, Requirement, SourceAnalysis, SourceEvidence } from './types';
import './sourceRequirementList.css';

const PAGE_SIZE = 5;
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

export function SourceRequirementList({ analysis, requirements, clarifications, inputRevision, stale, evidenceList, onReviewClarification }: {
  analysis: SourceAnalysis; requirements: Requirement[]; clarifications: Clarification[]; inputRevision?: number; stale: boolean;
  evidenceList: (evidence: SourceEvidence[]) => ReactNode; onReviewClarification?: (requirementId: string) => void;
}) {
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const scroll = useRef<HTMLDivElement>(null);
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
  const term = query.trim().toLocaleLowerCase();
  const filtered = useMemo(() => term ? rows.filter(row => [
    row.original.title, row.original.content, ...row.original.evidence.map(item => item.quote),
    ...row.clarifications.flatMap(item => [item.question, item.answer, item.adoption?.requirement_content]),
  ].some(value => value?.toLocaleLowerCase().includes(term))) : rows, [rows, term]);
  const lastPage = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(page, lastPage);
  const firstIndex = (current - 1) * PAGE_SIZE;
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
    { key: 'metric', title: '指标', width: '25%', render: (_, row) => <div className="rd-req-metric"><span>{String(row.number).padStart(2, '0')}</span><strong>{row.original.title}</strong></div> },
    { key: 'original', title: '原文指标', width: '30%', render: (_, row) => <><p className="rd-req-original">{row.original.content}</p>{row.original.evidence.length > 0 && <details className="rd-req-source"><summary>核对来源原文</summary>{evidenceList(row.original.evidence)}</details>}</> },
    { key: 'company', title: '公司自有组件指标', width: '18%', render: () => <span className="rd-req-muted" aria-label="暂无核实的自有组件指标">—</span> },
    { key: 'clarification', title: '需求澄清', width: '27%', render: (_, row) => clarificationCell(row) },
  ];
  function table(data: Row[], searching = false) {
    return <Table<Row> className="rd-req-table" dataSource={data} columns={columns} rowKey="number" size="small" pagination={false} tableLayout="fixed"
      locale={{ emptyText: searching ? '没有匹配的需求，请调整搜索词。' : '本次尚未提取到可引用的原文需求，请核对资料后重新分析。' }} />;
  }
  return <section className="rd-analysis-requirements" aria-label="需求清单">
    <header className="rd-req-head"><div><h4>需求清单</h4><span>{rows.length} 项</span></div>
      <Button icon={<FullscreenOutlined aria-hidden />} disabled={!rows.length} onClick={() => { setQuery(''); setOpen(true); }}>全屏审阅</Button></header>
    <LookupNote />
    {table(rows.slice(firstIndex, firstIndex + PAGE_SIZE))}
    {lastPage > 1 && <nav className="rd-analysis-pagination" aria-label="需求清单分页">
      <Button size="small" disabled={current === 1} onClick={() => setPage(current - 1)}>上一页</Button><span>第 {current} / {lastPage} 页</span><Button size="small" disabled={current === lastPage} onClick={() => setPage(current + 1)}>下一页</Button>
    </nav>}
    <Modal title="需求清单审阅" rootClassName="rd-req-review-modal" open={open} width="100%" footer={null} closable={false} onCancel={() => setOpen(false)}
      afterClose={() => {
        const id = nextClarification.current;
        nextClarification.current = null;
        if (id) onReviewClarification?.(id);
      }}
      afterOpenChange={visible => {
        if (visible && scroll.current) {
          const row = scroll.current.querySelector('tr[data-row-key="' + (firstIndex + 1) + '"]');
          scroll.current.scrollTop = row && firstIndex ? row.getBoundingClientRect().top - scroll.current.getBoundingClientRect().top + scroll.current.scrollTop - 44 : 0;
        }
      }}>
      <div className="rd-req-review-tools"><div><span>{term ? filtered.length + ' / ' + rows.length : rows.length} 项需求</span>
        <span className={stale ? 'rd-req-warning' : ''}>{stale ? '历史分析 · 待重新分析' : analysis.status === 'adopted' ? '已采用' : '待核对采用'}</span></div>
        <Input aria-label="搜索需求" prefix={<SearchOutlined />} allowClear value={query} placeholder="搜索指标、原文或澄清" onChange={event => { setQuery(event.target.value); if (scroll.current) scroll.current.scrollTop = 0; }} />
        <Button icon={<FullscreenExitOutlined aria-hidden />} onClick={() => setOpen(false)}>退出全屏</Button></div>
      <LookupNote />
      <div className="rd-req-review-scroll" ref={scroll}>{table(filtered, !!term)}</div>
    </Modal>
  </section>;
}
