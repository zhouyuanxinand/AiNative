import { useEffect, useMemo, useRef, useState } from 'react';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { loadTemplateDirectory, templateDownloadUrl } from '../../api/templates';
import type { TemplateItem } from '../../types';
import { rdResources } from './api';
import { messageOf, readable, stageTitle, statusTitle } from './presentation';
import type { Action, Catalog, CaseWorkspaceView, PlanNode, Project, WorkspaceResource } from './types';
import { WorkflowCanvas } from './WorkflowCanvas';
import './flowManagement.css';

const CATEGORIES = [{ id: 'resources', label: '智能体与 Skill' }, { id: 'actions', label: '动作模板' }, { id: 'flows', label: '流程模板' }, { id: 'reports', label: '报告模板' }] as const;
type Category = typeof CATEGORIES[number]['id'];
const ACTION_DESCRIPTIONS: Record<string, string> = {
  resolve_context: '核对项目业务参数与资料来源，为后续模板选择提供上下文。',
  template_plan: '依据已确认的产品类型与编制策略，选择受控模板并形成装配计划。',
  content_completion: '检查模板内容缺口与补齐依据，保留尚未解决的义务。',
  generate: '调用研制任务书生成能力，按模板与填写规则装配来源内容。',
  verify: '核查已生成成果与质量门禁，记录问题及核验依据。',
  consistency: '检查当前输入资料的一致性，记录问题与来源依据。',
};
const ENGINEERING_TITLES: Record<string, string> = { taskbook: '研制任务书', scheme: '方案设计', detail: '详细设计', integration: '整合', verification: '验证', delivery: '交付' };
function readState() {
  const params = new URLSearchParams(window.location.search);
  const requested = params.get('flow_tab');
  return { tab: (CATEGORIES.some(item => item.id === requested) ? requested : 'flows') as Category, kind: params.get('flow_kind') === 'research' ? 'research' : 'workpackage', selected: params.get('flow_item') ?? '', query: params.get('flow_q') ?? '' };
}
const matches = (query: string, ...values: unknown[]) => values.join(' ').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());

export function FlowManagement({ catalog, catalogLoading, catalogError, onRefreshCatalog, projects, onOpenCase, onOpenWorkspace }: {
  catalog: Catalog | null; catalogLoading: boolean; catalogError: string; onRefreshCatalog: () => void; projects: Project[];
  onOpenCase: (projectId: string, caseId: string, target?: CaseWorkspaceView) => void; onOpenWorkspace: () => void;
}) {
  const [state, setState] = useState(readState);
  const [nodeId, setNodeId] = useState('');
  const [resources, setResources] = useState<WorkspaceResource[]>([]);
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [resourceLoading, setResourceLoading] = useState(false), [templateLoading, setTemplateLoading] = useState(false);
  const [resourceError, setResourceError] = useState(''), [templateError, setTemplateError] = useState('');
  const [revision, setRevision] = useState(0), [page, setPage] = useState(1), [caseId, setCaseId] = useState('');
  const search = useRef<HTMLInputElement>(null);
  const tabButtons = useRef<Array<HTMLButtonElement | null>>([]);
  function update(next: Partial<typeof state>) {
    const value = { ...state, ...next }; setState(value); setPage(1); setNodeId('');
    const url = new URL(window.location.href);
    for (const [key, content] of Object.entries({ flow_tab: value.tab, flow_kind: value.kind, flow_item: value.selected, flow_q: value.query })) {
      if (content) url.searchParams.set(key, content); else url.searchParams.delete(key);
    }
    window.history.replaceState(window.history.state, '', url);
  }
  useEffect(() => { const onPop = () => { setState(readState()); setPage(1); }; window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop); }, []);
  useEffect(() => {
    if (state.tab !== 'resources') return;
    const controller = new AbortController(); setResourceLoading(true); setResourceError('');
    void rdResources(controller.signal).then(data => { if (!controller.signal.aborted) setResources(data.resources); }).catch(reason => { if (!controller.signal.aborted) setResourceError(messageOf(reason)); }).finally(() => { if (!controller.signal.aborted) setResourceLoading(false); });
    return () => controller.abort();
  }, [state.tab, revision]);
  useEffect(() => {
    if (state.tab !== 'reports') return;
    let active = true; setTemplateLoading(true); setTemplateError('');
    void loadTemplateDirectory().then(data => { if (active) setTemplates(data); }).catch(reason => { if (active) setTemplateError(messageOf(reason)); }).finally(() => { if (active) setTemplateLoading(false); });
    return () => { active = false; };
  }, [state.tab, revision]);
  const definitions = catalog?.workpackage_definitions ?? [];
  const workflows = catalog?.research_workflow_templates ?? [];
  const visibleDefinitions = definitions.filter(item => matches(state.query, item.title, item.name, item.description));
  const visibleWorkflows = workflows.filter(item => matches(state.query, item.title));
  const definition = visibleDefinitions.find(item => `${item.id}@${item.version ?? '1'}` === state.selected) ?? visibleDefinitions.find(item => item.id === state.selected) ?? visibleDefinitions[0];
  const workflow = visibleWorkflows.find(item => `${item.id}@${item.version ?? '1'}` === state.selected) ?? visibleWorkflows.find(item => item.id === state.selected) ?? visibleWorkflows[0];
  const selected = state.kind === 'workpackage' ? definition : workflow;
  const nodes = useMemo<PlanNode[]>(() => state.kind === 'workpackage' ? definition?.nodes ?? [] : (workflow?.nodes ?? []).map((id, index, all) => ({ id, action_id: id, action_version: workflow!.version, required: true, depends_on: index ? [all[index - 1]] : [] })), [state.kind, definition, workflow]);
  const actions: Action[] = state.kind === 'workpackage' ? catalog?.actions ?? [] : (workflow?.nodes ?? []).map(id => ({ id, title: ENGINEERING_TITLES[id] ?? id, version: workflow!.version }));
  const currentNode = nodes.find(item => item.id === nodeId) ?? nodes[0];
  const nodeName = (id: string) => actions.find(item => item.id === id)?.title ?? id;
  const cases = projects.flatMap(project => project.cases.map(researchCase => ({ project, researchCase })));
  const targetCase = cases.find(item => item.researchCase.id === caseId);
  const visibleResources = resources.filter(item => matches(state.query, item.name, item.description, item.kind, item.id));
  const visibleActions = (catalog?.actions ?? []).filter(item => matches(state.query, item.title, item.name, item.id, ACTION_DESCRIPTIONS[item.id]));
  const visibleTemplates = templates.filter(item => matches(state.query, item.product_type, item.product_domain, item.filename));
  const total = state.tab === 'resources' ? visibleResources.length : state.tab === 'actions' ? visibleActions.length : state.tab === 'reports' ? visibleTemplates.length : 0;
  const currentPage = Math.min(page, Math.max(1, Math.ceil(total / 12)));
  const paged = <T,>(items: T[]) => items.slice((currentPage - 1) * 12, currentPage * 12);
  const loading = state.tab === 'resources' ? resourceLoading : state.tab === 'reports' ? templateLoading : catalogLoading;
  const error = state.tab === 'resources' ? resourceError : state.tab === 'reports' ? templateError : catalogError;
  const refresh = () => state.tab === 'resources' || state.tab === 'reports' ? setRevision(value => value + 1) : onRefreshCatalog();
  return <div className="rd-flow-management">
    <div className="rd-flow-tabs" role="tablist" aria-label="流程资源分类">{CATEGORIES.map((item, index) => <button key={item.id} ref={element => { tabButtons.current[index] = element; }} type="button" role="tab" id={`flow-tab-${item.id}`} aria-controls={`flow-panel-${item.id}`} aria-selected={state.tab === item.id} tabIndex={state.tab === item.id ? 0 : -1} onClick={() => update({ tab: item.id, query: '', selected: '' })} onKeyDown={event => {
      const target = event.key === 'Home' ? 0 : event.key === 'End' ? CATEGORIES.length - 1 : event.key === 'ArrowRight' ? (index + 1) % CATEGORIES.length : event.key === 'ArrowLeft' ? (index + CATEGORIES.length - 1) % CATEGORIES.length : -1;
      if (target >= 0) { event.preventDefault(); tabButtons.current[target]?.focus(); }
    }}>{item.label}</button>)}</div>
    <section role="tabpanel" id={`flow-panel-${state.tab}`} aria-labelledby={`flow-tab-${state.tab}`}>
      <div className="rd-flow-tools"><div><h2>{CATEGORIES.find(item => item.id === state.tab)?.label}</h2><p>{state.tab === 'flows' ? '先查看模板与节点关系，进入项目后拉取工作包并编排。' : state.tab === 'resources' ? '查看当前资源及执行绑定，定义与真实可执行能力分别标明。' : state.tab === 'actions' ? '以下是工作包内已接通的本地执行步骤；专家团动作模板的资源编组与授权将在后续批次接入。' : '当前接入研制任务书受控 Word 模板，可按产品与体系查找。'}</p></div><div className="rd-flow-tool-actions"><div className="rd-search"><label htmlFor="flow-search" className="rd-visually-hidden">搜索{CATEGORIES.find(item => item.id === state.tab)?.label}</label><input ref={search} id="flow-search" type="search" value={state.query} placeholder="搜索名称或关键词" onChange={event => update({ query: event.target.value })} />{state.query && <button type="button" aria-label="清空搜索" onClick={() => { update({ query: '' }); search.current?.focus(); }}>×</button>}</div><button type="button" className="rd-button" disabled={loading} onClick={refresh}>{loading ? '读取中…' : '刷新目录'}</button></div></div>
      {loading && <p className="rd-loading" role="status">正在读取目录…</p>}{error && <div className="rd-error rd-banner" role="alert"><p>目录读取失败：{error}。已有记录保留，请刷新后核对。</p><button type="button" className="rd-link-button" onClick={refresh}>重试读取</button></div>}
      {state.tab === 'flows' && <>
        <div className="rd-flow-subnav" aria-label="模板层级"><button type="button" aria-pressed={state.kind === 'workpackage'} onClick={() => update({ kind: 'workpackage', selected: '', query: '' })}>工作包模板 <span>{definitions.length}</span></button><button type="button" aria-pressed={state.kind === 'research'} onClick={() => update({ kind: 'research', selected: '', query: '' })}>研发流程 <span>{workflows.length}</span></button><span>{catalog?.scenarios.map(item => item.title ?? item.name).join(' / ') || '业务目录待加载'}</span></div>
        <div className="rd-flow-workbench"><aside className="rd-flow-template-list" aria-label="可用流程模板"><h3>{state.kind === 'workpackage' ? '工作包目录' : '研发流程目录'}</h3>{(state.kind === 'workpackage' ? visibleDefinitions : visibleWorkflows).map(item => <button type="button" key={`${item.id}@${item.version}`} aria-pressed={selected?.id === item.id && selected?.version === item.version} onClick={() => update({ selected: `${item.id}@${item.version ?? '1'}` })}><span className="rd-flow-template-icon" aria-hidden="true">◇</span><span><strong>{item.title}</strong><small>v{item.version} · {state.kind === 'workpackage' ? '动作编排' : '研发路径'}</small></span><span aria-hidden="true">›</span></button>)}{!selected && !loading && !error && <p className="rd-management-empty">{state.query ? '没有匹配的模板。' : '暂无可用模板。'}</p>}</aside>
          <div className="rd-flow-preview">{selected ? <><div className="rd-flow-preview-head"><div><span className="rd-eyebrow">{state.kind === 'workpackage' ? '工作包模板' : '研发流程模板'}</span><h3>{selected.title}</h3><p>{state.kind === 'workpackage' ? `适用阶段：${(definition?.stages ?? definition?.allowed_stages ?? []).map(stageTitle).join('、') || '以项目条件为准'}` : '研发路径中的业务节点；各节点的成果与审签在项目中办理。'}</p></div><span className="rd-badge">v{selected.version}</span></div>
            <WorkflowCanvas key={`${state.kind}/${selected.id}/${selected.version}`} nodes={nodes} actions={actions} selectedId={currentNode?.id} onSelectNode={setNodeId} title={state.kind === 'workpackage' ? '工作包节点预览' : '研发路径预览'} definition />
            {currentNode && <div className="rd-flow-node-inspector"><div><span className="rd-eyebrow">已选节点</span><h4>{nodeName(currentNode.action_id)}</h4><p>{state.kind === 'workpackage' ? ACTION_DESCRIPTIONS[currentNode.action_id] ?? '按动作定义执行，结果保留来源与证据。' : '在项目流程中记录该业务节点的成果与决定。'}</p></div><dl><dt>前置依赖</dt><dd>{currentNode.depends_on.map(id => nodeName(nodes.find(node => node.id === id)?.action_id ?? id)).join('、') || '起始节点'}</dd><dt>节点版本</dt><dd>v{currentNode.action_version}</dd></dl></div>}
            {state.kind === 'workpackage' && !!definition?.optional_actions?.length && <div className="rd-flow-optional"><span>可增加的动作</span>{definition.optional_actions.map(id => <span className="rd-badge" key={id}>＋ {nodeName(id)}</span>)}<small>在项目工作包草稿中选择插入位置。</small></div>}
          </> : <div className="rd-management-empty">选择左侧模板查看节点画布。</div>}</div>
        </div>
        <div className="rd-flow-project-entry"><div><strong>在项目中编排与执行</strong><p>拉取工作包 → 调整可选节点 → 保存计划 → 确认提交。提交后自动执行，并保留固定快照。</p></div><div><StyledSelect aria-label="选择编排项目" value={caseId} options={[{ value: '', label: cases.length ? '选择项目与工作' : '暂无项目，请先新建项目' }, ...cases.map(item => ({ value: item.researchCase.id, label: `${item.project.title} / ${item.researchCase.title}` }))]} onChange={setCaseId} disabled={!cases.length} /><button type="button" className="rd-button primary" disabled={!targetCase} onClick={() => { if (targetCase) onOpenCase(targetCase.project.id, targetCase.researchCase.id, 'process'); }}>进入项目编排 →</button></div></div>
      </>}
      {state.tab === 'resources' && <div className="rd-flow-card-grid">{paged(visibleResources).map(resource => <article key={resource.id} className="rd-flow-resource-card"><header><span className="rd-flow-card-icon" aria-hidden="true">{resource.kind === 'agent' ? 'AI' : resource.kind === 'team' ? '组' : 'S'}</span><div><span className="rd-eyebrow">{{ agent: '智能体', skill: 'Skill', team: '团队' }[resource.kind]} · v{resource.version}</span><h3>{resource.name}</h3></div></header><p>{resource.description || '暂未填写用途说明。'}</p><div className="rd-flow-card-status"><span className={`rd-badge ${resource.status ?? 'draft'}`}>{statusTitle(resource.status)}</span><span>{resource.executable ? '已绑定执行能力' : '仅定义 · 未绑定执行能力'}</span></div><details><summary>查看资源说明</summary><p>资源标识：{resource.id}</p><pre>{readable(resource.configuration)}</pre></details></article>)}</div>}
      {state.tab === 'actions' && <div className="rd-flow-card-grid">{paged(visibleActions).map(action => <article key={action.id} className="rd-flow-resource-card"><header><span className="rd-flow-card-icon" aria-hidden="true">↗</span><div><span className="rd-eyebrow">本地执行步骤 · v{action.version}</span><h3>{action.title ?? action.name}</h3></div></header><p>{action.description ?? ACTION_DESCRIPTIONS[action.id] ?? '按固定输入与动作版本执行，保留结果证据。'}</p><div className="rd-flow-card-status"><span className="rd-badge published">已发布</span><span>用于工作包节点</span></div><details><summary>查看适用工作包</summary><ul>{definitions.filter(item => [...item.required_actions ?? [], ...item.optional_actions ?? []].includes(action.id)).map(item => <li key={`${item.id}@${item.version}`}><button type="button" className="rd-link-button" onClick={() => update({ tab: 'flows', kind: 'workpackage', selected: `${item.id}@${item.version ?? '1'}`, query: '' })}>{item.title} · {item.required_actions?.includes(action.id) ? '必需动作' : '可选动作'} →</button></li>)}</ul><code>{action.id}</code></details></article>)}</div>}
      {state.tab === 'reports' && <div className="rd-flow-card-grid">{paged(visibleTemplates).map(template => <article key={`${template.product_type_id}/${template.product_domain_id}`} className="rd-flow-resource-card"><header><span className="rd-flow-card-icon" aria-hidden="true">文</span><div><span className="rd-eyebrow">{template.product_domain} · 研制任务书</span><h3>{template.product_type}</h3></div></header><p>{template.filename}</p><div className="rd-flow-card-status"><span className="rd-badge">版本 {template.version}</span></div><a className="rd-link-button" href={templateDownloadUrl(template)}>下载当前模板 ↗</a></article>)}</div>}
      {state.tab !== 'flows' && !loading && !error && !total && <div className="rd-management-empty">{state.query ? '没有匹配的记录，请调整关键词。' : '当前目录暂无记录。'}</div>}
      {state.tab !== 'flows' && <div className="rd-flow-directory-footer"><span>{total} 项{total > 12 ? ` · 第 ${currentPage} / ${Math.ceil(total / 12)} 页` : ''}</span>{total > 12 && <div><button type="button" className="rd-button compact" disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}>上一页</button><button type="button" className="rd-button compact" disabled={currentPage >= Math.ceil(total / 12)} onClick={() => setPage(currentPage + 1)}>下一页</button></div>}{state.tab === 'resources' && <button type="button" className="rd-link-button" onClick={onOpenWorkspace}>在资源工作台管理 →</button>}</div>}
    </section>
  </div>;
}
