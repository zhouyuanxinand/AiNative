import { ArrowLeftOutlined, FileTextOutlined, SearchOutlined } from '@ant-design/icons';
import { Button, Empty, Input, Table, Tag } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { loadProductCatalog } from '../../api/catalog';
import type { ProductCatalog } from '../../types';
import { sourceUrl } from './api';
import { contextValueLabel } from './contextLabels';
import { CONTEXT_FIELDS, formatTime, isCurrentSource, stageTitle } from './presentation';
import { useDirectoryState } from './useDirectoryState';
import type { CaseWorkspaceView, Project, ResearchCase, SourceEvidence } from './types';
import './projectProfiles.css';

export type ProfileKind = 'customer' | 'product';
const titleOf = (kind: ProfileKind) => kind === 'customer' ? '客户画像' : '产品画像';
const nameOf = (kind: ProfileKind, project: Project) => (kind === 'customer' ? project.customer_name : project.product_name) || (kind === 'customer' ? '客户未登记' : '产品未登记');
const projectFields: Record<string, string> = { project_brief: '研发目标', project_product_name: '产品名称', project_customer_name: '客户名称', project_title: '项目名称' };

/** Only the supplied, authorized project is projected. Equal names never imply a shared enterprise entity. */
function Evidence({ project, researchCase, evidence }: { project: Project; researchCase: ResearchCase; evidence: SourceEvidence[] }) {
  return <ul className="rd-profile-evidence-list">{evidence.map((reference, index) => {
    const source = researchCase.sources.find(item => item.id === reference.source_id);
    const projectField = projectFields[reference.source_id];
    const analysisHash = researchCase.source_analysis?.source_hashes?.[reference.source_id];
    const changed = !!source && !!analysisHash && analysisHash !== source.sha256;
    return <li key={`${reference.source_id}-${index}`}>
      {source ? <div className="rd-profile-citation"><a href={sourceUrl(project.id, researchCase.id, source.id)} target="_blank" rel="noreferrer"><FileTextOutlined /> {source.name}</a><Tag>V{source.version}</Tag><Tag color={changed ? 'warning' : isCurrentSource(source, researchCase.source_selection) ? 'blue' : undefined}>{changed ? '来源已变化' : isCurrentSource(source, researchCase.source_selection) ? '当前资料' : '历史版本'}</Tag></div> : <span>{projectField ? `项目登记 · ${projectField}` : '来源记录不可用'}</span>}
      {reference.quote && <blockquote>{reference.kind === 'source_filename' && <span>文件名依据： </span>}{reference.quote}</blockquote>}
    </li>;
  })}</ul>;
}

interface FactRow { key: string; researchCase: ResearchCase; title: string; original: string; actual: string; status: string; originalEvidence: SourceEvidence[]; actualEvidence: SourceEvidence[]; stale: boolean }
function requirementFacts(researchCase: ResearchCase): FactRow[] {
  const analysis = researchCase.source_analysis;
  const stale = analysis?.status === 'stale' || !!analysis && (analysis.adopted_input_revision ?? analysis.input_revision) !== researchCase.input_revision;
  const adoptedIds = new Set(researchCase.requirements.map(item => item.id));
  const saved = researchCase.requirements.map(requirement => {
    const original = analysis?.requirements.find(item => item.requirement_id === requirement.id);
    const review = requirement.review;
    const matchingRevision = !!review && review.requirement_revision === (requirement.revision ?? requirement.version ?? 1);
    const reviewed = matchingRevision && (!review.analysis_id || review.analysis_id === analysis?.id);
    const acceptedEvidence = matchingRevision && review.decision === 'accept' && review.actual_value === requirement.content ? review.recommendation?.evidence ?? [] : [];
    const actualEvidence = [...acceptedEvidence, ...requirement.source_ids.filter(id => !acceptedEvidence.some(item => item.source_id === id)).map(source_id => ({ source_id, quote: '' }))];
    return { key: `${researchCase.id}/${requirement.id}`, researchCase, title: requirement.title,
      original: original?.content ?? '未保留对应原文摘录，请核对来源文件', actual: requirement.content,
      status: review && !reviewed ? '决定待复核' : reviewed ? ({ accept: '已采纳建议', reject: '保留原值', manual: '已人工修订' }[review.decision]) : '已登记需求',
      originalEvidence: original?.evidence ?? [], actualEvidence, stale: !!original && !!stale };
  });
  return saved.concat((analysis?.requirements ?? []).filter(item => !item.requirement_id || !adoptedIds.has(item.requirement_id)).map((item, index) => ({
    key: `${researchCase.id}/analysis/${index}`, researchCase, title: item.title, original: item.content, actual: '尚未采用', status: '识别候选', originalEvidence: item.evidence, actualEvidence: [], stale: !!stale,
  })));
}

/** Shared by management details and in-project read-only dialogs; never writes project or requirement facts. */
export function ProjectProfileDetail({ kind, project, researchCase }: { kind: ProfileKind; project: Project; researchCase?: ResearchCase }) {
  const [catalog, setCatalog] = useState<ProductCatalog | null>(null);
  const cases = researchCase ? project.cases.filter(item => item.id === researchCase.id) : project.cases;
  const facts = cases.flatMap(requirementFacts);
  useEffect(() => {
    if (kind !== 'product') return;
    let active = true;
    void loadProductCatalog().then(value => { if (active) setCatalog(value); }).catch(() => {});
    return () => { active = false; };
  }, [kind]);
  return <section className="rd-project-profile-detail" aria-label={`${titleOf(kind)}详情`}>
    <div className="rd-profile-heading"><div><span className="rd-eyebrow">项目资料视图</span><h2>{nameOf(kind, project)}</h2></div><Tag>画像主档尚未接入</Tag></div>
    <p className="rd-profile-scope">仅展示本项目登记与资料依据；同名{kind === 'customer' ? '客户' : '产品'}分别保留，不代表企业统一画像。</p>
    <dl className="rd-profile-registration">
      <div><dt>来源项目</dt><dd>{project.title}</dd></div>
      <div><dt>{kind === 'customer' ? '关联产品' : '项目客户'}</dt><dd>{(kind === 'customer' ? project.product_name : project.customer_name) || '未登记'}</dd></div>
      <div className="rd-profile-wide"><dt>研发目标</dt><dd>{project.brief || '未登记'}</dd></div>
      <div><dt>登记依据</dt><dd>项目登记信息 · 修订 {project.version}</dd></div>
      <div><dt>最近更新</dt><dd>{formatTime(project.updated_at)}</dd></div>
    </dl>
    {kind === 'product' && <section className="rd-profile-section"><h3>产品参数与适用范围</h3>{!cases.length && <p className="rd-profile-muted">尚无流程参数。</p>}{cases.map(item => <article key={item.id} className="rd-profile-context"><h4>{item.title}</h4><dl>{CONTEXT_FIELDS.map(field => {
      const provenance = item.context_provenance?.[field.key], fact = item.parameter_facts?.[field.key];
      const evidence = provenance?.evidence ?? (fact?.source_refs ?? []).map(ref => ({ source_id: ref.source_id, quote: '' }));
      return <div key={field.key}><dt>{field.label}</dt><dd><span>{contextValueLabel(field.key, item.context[field.key] ?? '', catalog)}</span>{fact?.evidence_status === 'stale' && <Tag color="warning">依据待复核</Tag>}{evidence.length > 0 ? <details><summary>参数依据</summary><Evidence project={project} researchCase={item} evidence={evidence} /></details> : <small>{item.context[field.key] ? '项目登记 / 流程记录' : '尚无确认依据'}</small>}</dd></div>;
    })}</dl></article>)}</section>}
    <section className="rd-profile-section"><div className="rd-profile-section-title"><h3>{kind === 'customer' ? '项目相关需求' : '来源指标与当前记录'}</h3><span>{facts.length} 条</span></div>
      <p className="rd-profile-muted">{kind === 'customer' ? '原文、当前记录与建议采用状态分别保留；项目要求不自动成为客户长期偏好。' : '以下为项目技术要求；不能据此认定企业产品已验证满足。'}</p>
      <Table<FactRow> className="rd-profile-facts" rowKey="key" dataSource={facts} size="small" scroll={{ x: 700 }} pagination={{ pageSize: 6, hideOnSinglePage: true, showSizeChanger: false }} locale={{ emptyText: '尚无可追溯的需求记录' }} columns={[
        { title: '指标 / 流程', key: 'title', width: 165, render: (_, row) => <><strong>{row.title}</strong><small>{row.researchCase.title}</small></> },
        { title: '原文记录', key: 'original', width: 250, render: (_, row) => <><p>{row.original}</p>{row.stale && <Tag color="warning">历史分析 · 待复核</Tag>}{row.originalEvidence.length > 0 && <details><summary>来源与原文</summary><Evidence project={project} researchCase={row.researchCase} evidence={row.originalEvidence} /></details>}</> },
        { title: '当前记录', key: 'actual', width: 250, render: (_, row) => <><p>{row.actual}</p><Tag>{row.status}</Tag>{row.actualEvidence.length > 0 && <details><summary>当前记录依据</summary><Evidence project={project} researchCase={row.researchCase} evidence={row.actualEvidence} /></details>}</> },
      ]} />
    </section>
    <section className="rd-profile-section"><h3>{kind === 'customer' ? '客户长期特征与历史经验' : '企业产品能力与验证记录'}</h3><div className="rd-profile-unavailable"><strong>{kind === 'customer' ? '客户长期画像尚未接入' : '企业已验证能力尚未接入'}</strong><p>{kind === 'customer' ? '待取得客户主档、适用条件和对应版本后展示。' : '待取得企业组件指标、验证条件和可追溯出处后展示。'}</p></div></section>
  </section>;
}

export function ProjectProfiles({ kind, projects, loading, error, onOpenCase }: { kind: ProfileKind; projects: Project[]; loading: boolean; error: string; onOpenCase: (projectId: string, caseId: string, target?: CaseWorkspaceView) => void }) {
  const directory = useDirectoryState(`management_${kind}`, { q: '', page: '1', item: '' });
  const heading = useRef<HTMLHeadingElement>(null);
  const title = titleOf(kind), query = directory.state.q.trim().toLocaleLowerCase();
  const rows = projects.filter(project => [nameOf(kind, project), project.title, project.customer_name, project.product_name].some(value => (value ?? '').toLocaleLowerCase().includes(query)));
  const currentPage = Math.max(1, Math.min(directory.page, Math.ceil(rows.length / 5) || 1));
  const selected = projects.find(project => project.id === directory.state.item);
  const known = !loading && !error;
  useEffect(() => { if (known && currentPage !== directory.page) directory.update({ page: String(currentPage) }, false); }, [known, currentPage, directory.page, directory.update]);
  useEffect(() => { if (directory.state.item) heading.current?.focus({ preventScroll: true }); }, [directory.state.item]);
  function back() { directory.update({ item: '' }, false); requestAnimationFrame(() => document.getElementById(`rd-${kind}-profile-search`)?.focus({ preventScroll: true })); }
  if (directory.state.item) return <div className="rd-profile-detail-page">
    <div className="rd-profile-detail-toolbar"><Button aria-label={`返回${title}目录`} icon={<ArrowLeftOutlined />} onClick={back}>返回{title}目录</Button><h2 ref={heading} tabIndex={-1}>{title}</h2></div>
    {selected ? <><ProjectProfileDetail kind={kind} project={selected} /><div className="rd-profile-project-links"><h3>本项目流程</h3>{selected.cases.length ? selected.cases.map(item => <Button key={item.id} onClick={() => onOpenCase(selected.id, item.id, 'evidence')}>{item.title} · {stageTitle(item.stage)} ↗</Button>) : <span>尚无业务流程。</span>}</div></> : known ? <Empty description="该项目已移除或当前身份不可访问，请返回目录。" /> : <p role="status">{loading ? '正在读取画像依据…' : '画像依据读取失败，请重试。'}</p>}
  </div>;
  return <section aria-label={`${title}目录`} className="rd-project-profiles">
    <div className="rd-profile-directory-tools"><Input id={`rd-${kind}-profile-search`} prefix={<SearchOutlined />} aria-label={`搜索${title}`} placeholder={`查找${kind === 'customer' ? '客户' : '产品'}或来源项目`} value={directory.input} allowClear onCompositionStart={() => directory.setComposing(true)} onCompositionEnd={event => { directory.setComposing(false); directory.setInput(event.currentTarget.value); }} onChange={event => directory.setInput(event.target.value)} onPressEnter={event => { if (!event.nativeEvent.isComposing && !directory.composing) directory.commit(); }} /><span>按项目分别查看</span></div>
    <div className="rd-profile-directory-grid">{rows.slice((currentPage - 1) * 5, currentPage * 5).map(project => <article className="rd-profile-directory-card" key={project.id}><div><h2>{nameOf(kind, project)}</h2><Tag>项目资料</Tag></div><p>{project.title}</p><dl><div><dt>{kind === 'customer' ? '产品' : '客户'}</dt><dd>{(kind === 'customer' ? project.product_name : project.customer_name) || '未登记'}</dd></div><div><dt>业务流程</dt><dd>{project.cases.length} 个</dd></div><div><dt>来源资料</dt><dd>{project.cases.reduce((sum, item) => sum + item.sources.length, 0)} 份</dd></div></dl><footer><small>{formatTime(project.updated_at)}</small><Button onClick={() => directory.update({ item: project.id }, false)}>查看画像</Button></footer></article>)}</div>
    {known && !rows.length && <Empty description={query ? '未找到匹配的记录，请调整搜索。' : `暂无可查看的${title}。`} />}
    {(known || rows.length > 0) && <div className="rd-pagination"><span>{rows.length ? `${(currentPage - 1) * 5 + 1}–${Math.min(currentPage * 5, rows.length)} / ${rows.length} 条` : '0 条记录'}</span><div><Button disabled={currentPage === 1} onClick={() => directory.update({ page: String(currentPage - 1) }, false)}>上一页</Button><span>{currentPage} / {Math.ceil(rows.length / 5) || 1}</span><Button disabled={currentPage * 5 >= rows.length} onClick={() => directory.update({ page: String(currentPage + 1) }, false)}>下一页</Button></div></div>}
  </section>;
}
