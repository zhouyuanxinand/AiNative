import { Button, Tabs } from 'antd';
import { lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from 'react';
import { PlatformAuthSettings } from '../../components/ui/PlatformAuthSettings';
import { ModelServiceOverview } from '../../components/ui/ModelServiceOverview';
import { loadModelCatalog } from '../../api/catalog';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { sourceUrl } from './api';
import { formatTime, stageTitle } from './presentation';
import type { BusinessWorkflowTemplate, Catalog, CaseWorkspaceView, Project, ResearchCase, ReuseCandidate } from './types';
import './platformManagement.css';
import { FlowManagement } from './FlowManagement';
import { useDirectoryState } from './useDirectoryState';
import { ProjectProfiles, type ProfileKind } from './ProjectProfiles';
const OperationsDashboard = lazy(() => import('./OperationsDashboard').then(module => ({ default: module.OperationsDashboard })));

interface Props {
  view: string;
  projects: Project[];
  catalog: Catalog | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  catalogLoading: boolean;
  catalogError: string;
  onRefreshCatalog: () => void;
  onOpenCase: (projectId: string, caseId: string, target?: CaseWorkspaceView) => void;
  onOpenWorkspace: () => void;
  onStartWorkflow?: (template: BusinessWorkflowTemplate) => void;
}
const TITLES: Record<string, [string, string]> = {
  management: ['研发管理', '在项目之间查看研发工作、当前进展与需要关注的事项。'],
  flows: ['流程管理', '管理研发能力与流程模板，查看节点关系，在项目中编排执行。'],
  knowledge: ['知识管理', '查看项目形成的复用候选，沿来源返回对应成果。'],
  operations: ['运营管理', '查看工作包的真实运行状态，定位失败与阻塞。'],
  system: ['系统管理', '管理登录与模型连接，进入管理员工作区。'],
};
const rowMatches = (query: string, ...values: unknown[]) => values.some(value => String(value ?? '').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
const Empty = ({ children }: { children: ReactNode }) => <div className="rd-management-empty">{children}</div>;
function reuseState(researchCase: ResearchCase, candidate: ReuseCandidate) {
  if (researchCase.input_revision === undefined) return { label: '输入版本待核对 · 尚未发布', historical: true, note: '尚未取得当前输入版本，请进入项目核对适用范围。' };
  if (candidate.input_revision !== researchCase.input_revision) return { label: '历史候选 · 尚未发布', historical: true, note: '候选来自历史输入版本，尚未针对当前输入重新确认。' };
  const disposition = researchCase.reuse_disposition;
  if (disposition?.kind === 'not_publish' && disposition.input_revision === researchCase.input_revision) return { label: '已决定不发布', historical: false, note: `本案例已登记不发布处置：${String(disposition.reason ?? '')}` };
  return { label: '案例内候选 · 尚未发布', historical: false, note: '候选保存在本案例中，尚未提交或发布为共享知识。' };
}

/** Read projections only: each entry navigates to its existing project object. */
export function PlatformManagement({ view, projects, catalog, loading, error, onRefresh, catalogLoading, catalogError, onRefreshCatalog, onOpenCase, onOpenWorkspace, onStartWorkflow }: Props) {
  const [modelCatalogStatus, setModelCatalogStatus] = useState('');
  async function refreshConfiguredModels() {
    setModelCatalogStatus('');
    try {
      const result = await loadModelCatalog();
      if (result.success === false) throw new Error(result.error || '模型服务暂不可用');
      setModelCatalogStatus(`模型目录已刷新，共 ${result.models?.length ?? 0} 项。`);
    } catch (reason) {
      throw new Error(`凭证已生效，但模型目录刷新失败：${reason instanceof Error ? reason.message : '请稍后重试'}。可重新打开设置测试连接。`);
    }
  }
  const directory = useDirectoryState(view, { q: '', kind: 'all', page: '1', tab: 'tasks', item: '' });
  const { state, page, update } = directory;
  const managementTab = ['customer', 'product'].includes(state.tab) ? state.tab as ProfileKind : 'tasks';
  const showTasks = view === 'management' && managementTab === 'tasks';
  const query = state.q, filter = ['all', 'attention', 'completed'].includes(state.kind) ? state.kind : 'all';
  const candidateId = directory.state.item;
  const setCandidateId = (item: string) => directory.update({ item }, false);
  const cases = useMemo(() => projects.flatMap(project => project.cases.map(researchCase => ({ project, researchCase }))), [projects]);
  const candidates = useMemo(() => cases.flatMap(item => (item.researchCase.reuse_candidates ?? []).map(candidate => ({ ...item, candidate }))), [cases]);
  const rows = view === 'knowledge' ? candidates.filter(item => rowMatches(query, item.candidate.title, item.candidate.content, item.project.title))
    : cases.filter(item => (filter === 'all' || (filter === 'attention' ? item.researchCase.workpackages.some(workpackage => ['failed', 'blocked'].includes(workpackage.status)) : (item.researchCase.status === 'completed' || item.researchCase.project_workflow_status?.status === 'completed'))) && rowMatches(query, item.project.title, item.researchCase.title, item.project.customer_name, item.project.product_name));
  const currentPage = Math.max(1, Math.min(page, Math.ceil(rows.length / 5) || 1));
  const visibleCases = view === 'management' ? (rows as typeof cases).slice((currentPage - 1) * 5, currentPage * 5) : [];
  const visibleCandidates = view === 'knowledge' ? (rows as typeof candidates).slice((currentPage - 1) * 5, currentPage * 5) : [];
  const selectedCandidate = candidates.find(item => `${item.researchCase.id}/${item.candidate.id}` === candidateId);
  const [title, description] = TITLES[view] ?? TITLES.management;
  const projectRowsKnown = !loading && !error;
  useEffect(() => {
    if (['management', 'knowledge'].includes(view) && projectRowsKnown && currentPage !== page) update({ page: String(currentPage) }, false);
  }, [view, projectRowsKnown, currentPage, page, update]);
  const selectedCandidateState = selectedCandidate ? reuseState(selectedCandidate.researchCase, selectedCandidate.candidate) : undefined;
  const open = (project: Project, researchCase: ResearchCase, target: CaseWorkspaceView = 'current') => onOpenCase(project.id, researchCase.id, target);
  const pageControls = (projectRowsKnown || rows.length > 0) ? <div className="rd-pagination"><span>{rows.length ? `${(currentPage - 1) * 5 + 1}–${Math.min(currentPage * 5, rows.length)} / ${rows.length} 条` : '0 条记录'}</span><div><Button type="default" htmlType="button" className="rd-button" disabled={currentPage === 1} onClick={() => update({ page: String(currentPage - 1) }, false)}>上一页</Button><span>{currentPage} / {Math.ceil(rows.length / 5) || 1}</span><Button type="default" htmlType="button" className="rd-button" disabled={currentPage * 5 >= rows.length} onClick={() => update({ page: String(currentPage + 1) }, false)}>下一页</Button></div></div> : null;
  if (view === 'operations') return <Suspense fallback={<main className="rd-page-content rd-management-page"><h1>运营管理</h1><p className="rd-loading" role="status">正在载入运营看板…</p></main>}><OperationsDashboard projects={projects} loading={loading} error={error} onRefresh={onRefresh} onOpenCase={onOpenCase} /></Suspense>;
  return <main className="rd-page-content rd-management-page">
    <div className="rd-page-title"><div><h1>{title}</h1><p>{description}</p></div>{view !== 'system' && <div className="rd-management-refresh"><Button type="default" htmlType="button" className="rd-button" disabled={loading} onClick={onRefresh}>{loading ? '读取中…' : '刷新项目'}</Button>{view === 'flows' && <Button type="default" htmlType="button" className="rd-button" onClick={onOpenWorkspace}>打开能力工作台 ↗</Button>}</div>}</div>
    {view !== 'system' && <div className="rd-management-data-state">{loading && <p className="rd-loading" role="status">正在读取项目状态…{projects.length > 0 && '现有记录继续保留。'}</p>}{error && <div className="rd-error rd-banner" role="alert"><p>项目状态读取失败：{error}</p><p>{projects.length ? '当前显示上次读取的项目记录，请刷新后核对。' : '本次项目状态尚未取得，不能据此判断没有记录。'}</p><Button type="link" htmlType="button" className="rd-link-button" onClick={onRefresh}>重新读取项目</Button></div>}</div>}
    {view === 'management' && <Tabs className="rd-profile-tabs" activeKey={managementTab} onChange={tab => update({ tab }, false)} items={[{ key: 'customer', label: '客户画像' }, { key: 'product', label: '产品画像' }, { key: 'tasks', label: '项目与任务' }]} />}
    {view === 'management' && managementTab !== 'tasks' && <ProjectProfiles key={managementTab} kind={managementTab} projects={projects} loading={loading} error={error} onOpenCase={onOpenCase} />}
    {(showTasks || view === 'knowledge') && <div className="rd-management-tools"><div className="rd-field rd-management-search-field"><label htmlFor="rd-management-search">搜索{title}记录</label><div className="rd-search"><input id="rd-management-search" value={directory.input} placeholder={view === 'knowledge' ? '搜索候选名称、内容或项目' : '搜索项目或工作名称'} onCompositionStart={() => directory.setComposing(true)} onCompositionEnd={event => { directory.setComposing(false); directory.setInput(event.currentTarget.value); }} onChange={event => directory.setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing && !directory.composing) { event.preventDefault(); directory.commit(); } }} />{directory.input && <button type="button" aria-label="清空搜索" onClick={() => { directory.commit(''); document.getElementById('rd-management-search')?.focus(); }}>×</button>}</div></div>{view !== 'knowledge' && <div className="rd-field rd-management-filter"><label id="rd-management-filter-label">工作范围</label><StyledSelect aria-labelledby="rd-management-filter-label" value={filter} onChange={value => update({ kind: value })} options={ [{ value: 'all', label: '全部工作' }, { value: 'attention', label: '存在运行问题' }, { value: 'completed', label: '已完成案例' }]} /></div>}</div>}
    {showTasks && <><section className="rd-management-surface"><h2>项目与工作</h2><p className="rd-management-note">仅展示当前身份有权访问的项目。客户与产品为项目登记信息，工作包问题不代表全部工程风险。</p><div className="rd-management-table"><table><thead><tr><th>项目 / 工作</th><th>客户 / 产品</th><th>当前阶段</th><th>需要关注</th><th>办理</th></tr></thead><tbody>{visibleCases.map(({ project, researchCase }) => {
      const blocked = researchCase.workpackages.filter(item => ['blocked', 'failed'].includes(item.status));
      return <tr key={`${project.id}/${researchCase.id}`}><td><strong>{project.title}</strong><small>{researchCase.title}</small></td><td>{project.customer_name || '未登记客户'}<small>{project.product_name || '未登记产品'}</small></td><td>{stageTitle(researchCase.stage)}</td><td>{blocked.length ? <span className="rd-warning-text">{blocked.length} 个工作包需处理</span> : '暂无运行问题'}<small>{researchCase.requirements.length} 条需求 · {researchCase.sources.length} 份资料</small></td><td><Button type="link" htmlType="button" className="rd-link-button" onClick={() => open(project, researchCase)}>进入工作 →</Button></td></tr>;
    })}</tbody></table></div>{projectRowsKnown && !rows.length && <Empty>{query || filter !== 'all' ? '没有符合条件的工作，可调整搜索与筛选。' : '还没有项目工作。发起研发工作后，可在这里按项目查看进展。'}</Empty>}</section>{pageControls}</>}
    {view === 'flows' && <FlowManagement catalog={catalog} catalogLoading={catalogLoading} catalogError={catalogError} onRefreshCatalog={onRefreshCatalog} projects={projects} onOpenCase={onOpenCase} onOpenWorkspace={onOpenWorkspace} onStartWorkflow={onStartWorkflow} />}
    {view === 'knowledge' && <>
      <section className="rd-management-surface"><h2>项目复用候选</h2><p className="rd-management-note">候选保留在所属项目中，尚未发布为共享知识。历史输入和已决定不发布的记录分别标明。</p>
        {visibleCandidates.map(({ project, researchCase, candidate }) => {
          const state = reuseState(researchCase, candidate);
          return <button type="button" className="rd-candidate-row" key={`${researchCase.id}/${candidate.id}`} aria-pressed={candidateId === `${researchCase.id}/${candidate.id}`} onClick={() => setCandidateId(`${researchCase.id}/${candidate.id}`)}>
            <span><strong>{candidate.title}</strong><small>{project.title} / {researchCase.title}</small></span><span className={`rd-badge ${state.historical ? 'draft' : ''}`}>{state.label}</span>
          </button>;
        })}
        {projectRowsKnown && !rows.length && <Empty>{query ? '未找到匹配的复用候选。' : '尚无复用候选。在项目的知识治理阶段整理成果后，会出现在这里。'}</Empty>}
      </section>{pageControls}
      {selectedCandidate && selectedCandidateState && <section className="rd-management-surface rd-candidate-detail">
        <div className="rd-section-head"><h2>{selectedCandidate.candidate.title}</h2><Button type="link" htmlType="button" className="rd-link-button" onClick={() => open(selectedCandidate.project, selectedCandidate.researchCase, 'evidence')}>查看所属成果 ↗</Button></div>
        <p className={selectedCandidateState.historical ? 'rd-warning' : 'rd-management-note'}>{selectedCandidateState.note}</p>
        <p className="rd-prewrap">{selectedCandidate.candidate.content}</p>
        <p className="rd-management-note">整理时间 {formatTime(selectedCandidate.candidate.created_at)} · 候选输入修订 {selectedCandidate.candidate.input_revision} · 当前流程输入修订 {selectedCandidate.researchCase.input_revision ?? '待核对'}</p>
        <ul>{selectedCandidate.candidate.source_ids.map(id => {
          const source = selectedCandidate.researchCase.sources.find(item => item.id === id);
          return <li key={id}>{source ? <a href={sourceUrl(selectedCandidate.project.id, selectedCandidate.researchCase.id, id)} target="_blank" rel="noreferrer">{source.name} · v{source.version}</a> : '来源记录不可用'}</li>;
        })}</ul>
      </section>}
    </>}
    {view === 'system' && <div className="rd-system-sections"><section className="rd-management-surface"><div><h2>账号与登录</h2><p>设置 OA／问学登录及应用入口。</p></div><PlatformAuthSettings /></section><section className="rd-management-surface"><ModelServiceOverview onSaved={refreshConfiguredModels} />{modelCatalogStatus && <p role="status">{modelCatalogStatus}</p>}</section><section className="rd-management-surface"><div><h2>管理员工作区</h2><p>管理员名单、运行日志、用户反馈和操作资料。</p></div><a className="rd-button" href="/admin">打开管理员页面 ↗</a></section><section className="rd-management-surface"><div><h2>能力与数据接入</h2><p>本地 Workspace 管理当前能力；外部平台接入契约在工作台查看。</p></div><Button type="default" htmlType="button" className="rd-button" onClick={onOpenWorkspace}>打开能力工作台 ↗</Button></section></div>}
  </main>;
}
