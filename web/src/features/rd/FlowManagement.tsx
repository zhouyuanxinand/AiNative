import { Button, Tag } from 'antd';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { applicationLeaveState } from '../../hooks/useApplicationLeaveGuard';
import { ActionTemplateDetail } from './ActionTemplateDetail';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { templateDownloadUrl } from '../../api/templates';
import type { TemplateItem } from '../../types';
import { RdApiError, rdCatalogItems, rdCatalogResources } from './api';
import { useDirectoryState } from './useDirectoryState';
import { messageOf, stageTitle, statusTitle } from './presentation';
import type { Action, BusinessWorkflowTemplate, Catalog, CaseWorkspaceView, PlanNode, Project, ResourceSummary, ResearchWorkflowTemplate, WorkpackageDefinition } from './types';
import { WorkflowCanvas } from './WorkflowCanvas';
import './flowManagement.css';
import { WorkflowTemplateWorkbench } from './WorkflowTemplateWorkbench';

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
export function FlowManagement({ catalog, onRefreshCatalog, projects, onOpenCase, onOpenWorkspace, onStartWorkflow }: {
  catalog: Catalog | null; catalogLoading: boolean; catalogError: string; onRefreshCatalog: () => void; projects: Project[];
  onOpenCase: (projectId: string, caseId: string, target?: CaseWorkspaceView) => void; onOpenWorkspace: () => void;
  onStartWorkflow?: (template: BusinessWorkflowTemplate) => void;
}) {
  const directory = useDirectoryState('flow', { tab: 'flows', kind: 'research', item: '', version: '', detail: '', q: '', page: '1' });
  const { state: rawState, page, update: updateDirectory } = directory;
  const state = { ...rawState, tab: (rawState.tab === 'derivation' ? 'reports' : CATEGORIES.some(item => item.id === rawState.tab) ? rawState.tab : 'flows') as Category, kind: rawState.kind === 'workpackage' ? 'workpackage' : 'research', query: rawState.q, selected: rawState.item };
  const [pendingTab, setPendingTab] = useState<Partial<{ tab: string; kind: string; selected: string; query: string }> | null>(null);
  const [nodeId, setNodeId] = useState('');
  const [resources, setResources] = useState<ResourceSummary[]>([]);
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [definitions, setDefinitions] = useState<WorkpackageDefinition[]>([]);
  const [workflows, setWorkflows] = useState<ResearchWorkflowTemplate[]>([]);
  const [visibleActions, setVisibleActions] = useState<Action[]>([]);
  const [actionSizes, setActionSizes] = useState<Record<string, number>>({});
  const recordActionSize = useCallback((id: string, version: string, count: number) => setActionSizes(previous => ({ ...previous, [`${id}@${version}`]: count })), []);
  const [loading, setLoading] = useState(true), [error, setError] = useState('');
  const [total, setTotal] = useState(0), [totalPages, setTotalPages] = useState(1);
  const [revision, setRevision] = useState(0), [caseId, setCaseId] = useState('');
  const search = useRef<HTMLInputElement>(null);
  const tabButtons = useRef<Array<HTMLButtonElement | null>>([]);
  function update(next: Partial<{ tab: string; kind: string; selected: string; query: string }>, confirmed = false) {
    const leaveState = applicationLeaveState();
    if (leaveState.busyMessage) return;
    if ((next.tab && next.tab !== state.tab || next.kind && next.kind !== state.kind) && !confirmed && leaveState.dirty) { setPendingTab(next); return; }
    const patch: Record<string, string> = {};
    if (next.tab !== undefined) { patch.tab = next.tab; patch.detail = ''; patch.version = ''; }
    if (next.kind !== undefined) patch.kind = next.kind;
    if (next.selected !== undefined) patch.item = next.selected;
    if (next.query !== undefined) { patch.q = next.query; directory.setInput(next.query); }
    updateDirectory(patch, next.selected === undefined || next.tab !== undefined || next.kind !== undefined); setNodeId('');
  }
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError('');
    if (state.tab === 'flows' && state.kind === 'research') { setLoading(false); setTotal(0); return () => controller.abort(); }
    const query = { q: state.query, page };
    const category = state.tab === 'flows' ? state.kind === 'research' ? 'research' : 'workpackages' : state.tab;
    void (state.tab === 'resources' ? rdCatalogResources(query, controller.signal) : rdCatalogItems<unknown>(category, query, controller.signal)).then(response => {
      if (controller.signal.aborted) return;
      setResources(state.tab === 'resources' ? response.items as ResourceSummary[] : []);
      setTemplates(state.tab === 'reports' ? response.items as TemplateItem[] : []);
      setVisibleActions(state.tab === 'actions' ? response.items as Action[] : []);
      setDefinitions(category === 'workpackages' ? response.items as WorkpackageDefinition[] : []);
      setWorkflows(category === 'research' ? response.items as ResearchWorkflowTemplate[] : []);
      setTotal(response.total); setTotalPages(Math.max(1, response.total_pages));
      if (page > Math.max(1, response.total_pages)) updateDirectory({ page: String(Math.max(1, response.total_pages)) }, false);
    }).catch(reason => {
      if (controller.signal.aborted) return;
      setError(messageOf(reason));
      if (reason instanceof RdApiError && [401, 403, 404].includes(reason.status)) { setResources([]); setTemplates([]); setVisibleActions([]); setDefinitions([]); setWorkflows([]); setTotal(0); }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [state.tab, state.kind, state.query, page, revision, updateDirectory]);
  const definition = definitions.find(item => `${item.id}@${item.version ?? '1'}` === state.selected) ?? definitions.find(item => item.id === state.selected) ?? definitions[0];
  const workflow = workflows.find(item => `${item.id}@${item.version ?? '1'}` === state.selected) ?? workflows.find(item => item.id === state.selected) ?? workflows[0];
  const selected = state.kind === 'workpackage' ? definition : workflow;
  const nodes = useMemo<PlanNode[]>(() => state.kind === 'workpackage' ? definition?.nodes ?? [] : (workflow?.nodes ?? []).map((id, index, all) => ({ id, action_id: id, action_version: workflow!.version, required: true, depends_on: index ? [all[index - 1]] : [] })), [state.kind, definition, workflow]);
  const actions: Action[] = state.kind === 'workpackage' ? catalog?.actions ?? [] : (workflow?.nodes ?? []).map(id => ({ id, title: ENGINEERING_TITLES[id] ?? id, version: workflow!.version }));
  const currentNode = nodes.find(item => item.id === nodeId) ?? nodes[0];
  const nodeName = (id: string) => actions.find(item => item.id === id)?.title ?? id;
  const cases = projects.flatMap(project => project.cases.map(researchCase => ({ project, researchCase })));
  const targetCase = cases.find(item => item.researchCase.id === caseId);
  const directoryTab = state.tab !== 'flows' || state.kind === 'workpackage';
  const actionDetail = state.tab === 'actions' && rawState.detail === 'canvas' && !!rawState.item && !!rawState.version;
  const openAction = (action: Action) => updateDirectory({ q: directory.input, item: action.id, version: String(action.version), detail: 'canvas' }, directory.input !== state.query);
  const description = { flows: '拖动节点、配置办理依赖与业务参数，保存并发布流程版本；随时查看历史与项目引用。', resources: '当前应用获准的固定资源版本；定义与真实执行绑定分别标明。', actions: '获准专家团动作的固定版本与组成；采用后展开为已注册的内部执行步骤。', reports: '文档资产目录：现有受控 Word 模板，沿用原下载权限，与 Workspace 能力授权分开。' }[state.tab];
  const refresh = () => { setRevision(value => value + 1); onRefreshCatalog(); };
  return <div className={`rd-flow-management${state.tab === 'flows' && state.kind === 'research' ? ' is-template-workbench' : ''}`}>
    <div className="rd-flow-tabs" role="tablist" aria-label="流程资源分类">{CATEGORIES.map((item, index) => <button key={item.id} ref={element => { tabButtons.current[index] = element; }} type="button" role="tab" id={`flow-tab-${item.id}`} aria-controls={`flow-panel-${item.id}`} aria-selected={state.tab === item.id} tabIndex={state.tab === item.id ? 0 : -1} onClick={() => update({ tab: item.id, query: '', selected: '' })} onKeyDown={event => {
      const target = event.key === 'Home' ? 0 : event.key === 'End' ? CATEGORIES.length - 1 : event.key === 'ArrowRight' ? (index + 1) % CATEGORIES.length : event.key === 'ArrowLeft' ? (index + CATEGORIES.length - 1) % CATEGORIES.length : -1;
      if (target >= 0) { event.preventDefault(); tabButtons.current[target]?.focus(); }
    }}>{item.label}</button>)}</div>
    <section role="tabpanel" id={`flow-panel-${state.tab}`} aria-labelledby={`flow-tab-${state.tab}`}>
      {!actionDetail && <div className="rd-flow-tools"><div><h2>{CATEGORIES.find(item => item.id === state.tab)?.label}</h2><p>{description}</p></div>{directoryTab && <div className="rd-flow-tool-actions"><div className="rd-search"><label htmlFor="flow-search" className="rd-visually-hidden">搜索{CATEGORIES.find(item => item.id === state.tab)?.label}</label><input ref={search} id="flow-search" type="search" value={directory.input} placeholder="搜索名称或关键词" onCompositionStart={() => directory.setComposing(true)} onCompositionEnd={event => { directory.setComposing(false); directory.setInput(event.currentTarget.value); }} onChange={event => directory.setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing && !directory.composing) { event.preventDefault(); directory.commit(); } }} />{directory.input && <button type="button" aria-label="清空搜索" onClick={() => { directory.commit(''); search.current?.focus(); }}>×</button>}</div><Button autoInsertSpace={false} htmlType="button" className="rd-button" disabled={loading} onClick={refresh}>{loading ? '读取中…' : '刷新目录'}</Button></div>}</div>}
      {!actionDetail && loading && <p className="rd-loading" role="status">正在读取目录…</p>}{!actionDetail && error && <div className="rd-error rd-banner" role="alert"><p>目录读取失败：{error}。请重试读取后核对当前可用目录。</p><Button autoInsertSpace={false} type="link" htmlType="button" className="rd-link-button" onClick={refresh}>重试读取</Button></div>}
      {state.tab === 'flows' && <>
        <div className="rd-flow-subnav" aria-label="模板层级"><button type="button" aria-pressed={state.kind === 'research'} onClick={() => update({ kind: 'research', selected: '', query: '' })}>流程编排与版本</button><button type="button" aria-pressed={state.kind === 'workpackage'} onClick={() => update({ kind: 'workpackage', selected: '', query: '' })}>可调用工作包</button></div>
        {state.kind === 'research' ? <WorkflowTemplateWorkbench onOpenCase={(projectId, caseId) => onOpenCase(projectId, caseId, 'process')} onStartWorkflow={onStartWorkflow} /> : <>
        <div className="rd-flow-workbench"><aside className="rd-flow-template-list" aria-label="可用流程模板"><h3>{state.kind === 'workpackage' ? '工作包目录' : '研发流程目录'}</h3>{(state.kind === 'workpackage' ? definitions : workflows).map(item => <button type="button" key={`${item.id}@${item.version}`} aria-pressed={selected?.id === item.id && selected?.version === item.version} onClick={() => update({ selected: `${item.id}@${item.version ?? '1'}` })}><span className="rd-flow-template-icon" aria-hidden="true">◇</span><span><strong>{item.title}</strong><small>v{item.version} · {state.kind === 'workpackage' ? '动作编排' : '研发路径'}</small></span><span aria-hidden="true">›</span></button>)}{!selected && !loading && !error && <p className="rd-management-empty">{state.query ? '没有匹配的模板。' : '暂无可用模板。'}</p>}</aside>
          <div className="rd-flow-preview">{selected ? <><div className="rd-flow-preview-head"><div><span className="rd-eyebrow">{state.kind === 'workpackage' ? '工作包模板' : '研发流程模板'}</span><h3>{selected.title}</h3><p>{state.kind === 'workpackage' ? `适用阶段：${(definition?.stages ?? definition?.allowed_stages ?? []).map(stageTitle).join('、') || '以项目条件为准'}` : '研发路径中的业务节点；各节点的成果与审签在项目中办理。'}</p></div><Tag className="rd-badge">v{selected.version}</Tag></div>
            <WorkflowCanvas key={`${state.kind}/${selected.id}/${selected.version}`} nodes={nodes} actions={actions} selectedId={currentNode?.id} onSelectNode={setNodeId} title={state.kind === 'workpackage' ? '工作包节点预览' : '研发路径预览'} definition />
            {currentNode && <div className="rd-flow-node-inspector"><div><span className="rd-eyebrow">已选节点</span><h4>{nodeName(currentNode.action_id)}</h4><p>{state.kind === 'workpackage' ? ACTION_DESCRIPTIONS[currentNode.action_id] ?? '按动作定义执行，结果保留来源与证据。' : '在项目流程中记录该业务节点的成果与决定。'}</p></div><dl><dt>前置依赖</dt><dd>{currentNode.depends_on.map(id => nodeName(nodes.find(node => node.id === id)?.action_id ?? id)).join('、') || '起始节点'}</dd><dt>节点版本</dt><dd>v{currentNode.action_version}</dd></dl></div>}
            {state.kind === 'workpackage' && !!definition?.optional_actions?.length && <div className="rd-flow-optional"><span>可增加的动作</span>{definition.optional_actions.map(id => <Tag className="rd-badge" key={id}>＋ {nodeName(id)}</Tag>)}<small>在项目工作包草稿中选择插入位置。</small></div>}
          </> : <div className="rd-management-empty">选择左侧模板查看节点画布。</div>}</div>
        </div>
        <div className="rd-flow-project-entry"><div><strong>在项目中编排与执行</strong><p>拉取工作包 → 调整可选节点 → 保存计划 → 确认提交。提交后自动执行，并保留固定快照。</p></div><div><StyledSelect aria-label="选择编排项目" value={caseId} options={[{ value: '', label: cases.length ? '选择项目与工作' : '暂无项目，请先新建项目' }, ...cases.map(item => ({ value: item.researchCase.id, label: `${item.project.title} / ${item.researchCase.title}` }))]} onChange={setCaseId} disabled={!cases.length} /><Button autoInsertSpace={false} type="primary" htmlType="button" className="rd-button primary" disabled={!targetCase} onClick={() => { if (targetCase) onOpenCase(targetCase.project.id, targetCase.researchCase.id, 'process'); }}>进入项目编排 →</Button></div></div>
      </>}
      </>}
      {state.tab === 'resources' && <div className="rd-flow-card-grid">{resources.map(resource => <article key={resource.id} className="rd-flow-resource-card"><header><span className="rd-flow-card-icon" aria-hidden="true">{resource.kind === 'agent' ? 'AI' : resource.kind === 'team' ? '组' : 'S'}</span><div><span className="rd-eyebrow">{{ agent: '智能体', skill: 'Skill', team: '团队' }[resource.kind]} · v{resource.version}</span><h3>{resource.name}</h3></div></header><p>{resource.description || '暂未填写用途说明。'}</p><div className="rd-flow-card-status"><Tag className={`rd-badge ${resource.status ?? 'draft'}`}>{statusTitle(resource.status)}</Tag><span>{resource.executable ? '已绑定执行能力' : '仅定义 · 未绑定执行能力'}</span></div><details open={state.selected === `${resource.id}@${resource.version}`} onToggle={event => { const fixed = `${resource.id}@${resource.version}`; if (event.currentTarget.open && state.selected !== fixed) update({ selected: fixed }); else if (!event.currentTarget.open && state.selected === fixed) update({ selected: '' }); }}><summary>查看资源说明</summary><p>资源标识：{resource.id}</p><p>获准版本：{resource.available_versions?.map(version => `v${version}`).join('、') || `v${resource.version}`}</p></details></article>)}</div>}
      {state.tab === 'actions' && (actionDetail ? <ActionTemplateDetail id={rawState.item} version={rawState.version} actions={catalog?.actions ?? []} onBack={() => updateDirectory({ detail: '' }, false)} onStructure={recordActionSize} /> : <div className="rd-flow-card-grid">{visibleActions.map(action => {
        const fixed = `${action.id}@${action.version}`, size = actionSizes[fixed], title = action.title ?? action.name ?? '未命名动作模板';
        const status = typeof action.status === 'string' ? action.status : '';
        return <article key={fixed} className="rd-flow-resource-card"><Button autoInsertSpace={false} htmlType="button" className="rd-action-card-button" aria-label={`打开${title}画布`} onClick={() => openAction(action)}><span className="rd-action-card-heading"><span className="rd-flow-card-icon" aria-hidden="true">↗</span><span><span className="rd-eyebrow">动作模板 · v{action.version}</span><strong className="rd-action-card-title">{title}</strong></span></span><span className="rd-action-card-description">{action.description ?? ACTION_DESCRIPTIONS[action.id] ?? '查看固定版本的执行步骤与前后依赖。'}</span><span className="rd-action-card-open"><span>{size === undefined ? '查看完整画布' : size === 1 ? '单动作封装 · 1 个执行步骤' : size ? `多步骤编排 · ${size} 个执行步骤` : '查看动作配置'}</span><span aria-hidden="true">→</span></span></Button><div className="rd-flow-card-status">{status && <Tag className={`rd-badge ${status}`}>{statusTitle(status)}</Tag>}<span>{action.executable ? '已绑定执行能力' : '定义尚未绑定执行能力'}</span></div><details><summary>查看适用工作包</summary><ul>{(catalog?.workpackage_definitions ?? []).filter(item => [...item.required_actions ?? [], ...item.optional_actions ?? []].includes(action.id)).map(item => <li key={`${item.id}@${item.version}`}><Button autoInsertSpace={false} type="link" htmlType="button" className="rd-link-button" onClick={() => update({ tab: 'flows', kind: 'workpackage', selected: `${item.id}@${item.version ?? '1'}`, query: '' })}>{item.title} · {item.required_actions?.includes(action.id) ? '必需动作' : '可选动作'} →</Button></li>)}</ul><code>{action.id}</code></details></article>;
      })}</div>)}
      {state.tab === 'reports' && <div className="rd-flow-card-grid">{templates.map(template => <article key={`${template.product_type_id}/${template.product_domain_id}`} className="rd-flow-resource-card"><header><span className="rd-flow-card-icon" aria-hidden="true">文</span><div><span className="rd-eyebrow">{template.product_domain} · 研制任务书</span><h3>{template.product_type}</h3></div></header><p>{template.filename}</p><div className="rd-flow-card-status"><Tag className="rd-badge">版本 {template.version}</Tag></div><a className="rd-link-button" href={templateDownloadUrl(template)}>下载当前模板 ↗</a></article>)}</div>}
      {!actionDetail && state.tab !== 'flows' && !loading && !error && !total && <div className="rd-management-empty">{state.query ? '没有匹配的记录，请调整关键词。' : '当前目录暂无记录。'}</div>}
      {directoryTab && !actionDetail && <div className="rd-flow-directory-footer"><span>{total} 项 · 第 {page} / {totalPages} 页 · 每页 5 项</span><div><Button autoInsertSpace={false} htmlType="button" className="rd-button compact" disabled={loading || page <= 1} onClick={() => updateDirectory({ page: String(page - 1), item: '' }, false)}>上一页</Button><Button autoInsertSpace={false} htmlType="button" className="rd-button compact" disabled={loading || page >= totalPages} onClick={() => updateDirectory({ page: String(page + 1), item: '' }, false)}>下一页</Button></div>{state.tab === 'resources' && <Button autoInsertSpace={false} type="link" htmlType="button" className="rd-link-button" onClick={onOpenWorkspace}>在资源工作台查看 →</Button>}</div>}
    </section>
    {pendingTab && <FeedbackConfirmDialog title="放弃未保存的流程修改" confirm="放弃修改并切换" cancel="继续编辑" onCancel={() => setPendingTab(null)} onConfirm={() => { const next = pendingTab; setPendingTab(null); update(next, true); }}><p>切换后将放弃尚未保存的画布配置，已保存的版本保持不变。</p></FeedbackConfirmDialog>}
  </div>;
}
