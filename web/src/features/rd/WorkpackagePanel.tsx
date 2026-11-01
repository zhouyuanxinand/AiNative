import { useEffect, useMemo, useRef, useState } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { artifactUrl } from './api';
import { isCurrentSource, readable, stageTitle, statusTitle } from './presentation';
import type { Catalog, PlanNode, Project, ResearchCase } from './types';
import { scenarioManifest, scenarioStage } from './scenarioManifest';
import { WorkflowCanvas } from './WorkflowCanvas';

export type CommandRunner = (command: string, data: unknown, onSuccess?: () => void) => Promise<boolean>;

export function WorkpackagePanel({ project, researchCase, catalog, busy, error, command, onDirtyChange, focusRequest }: {
  project: Project; researchCase: ResearchCase; catalog: Catalog | null; busy: boolean; error: string; command: CommandRunner; onDirtyChange: (dirty: boolean) => void; focusRequest?: { id: string; serial: number };
}) {
  const [selectedId, setSelectedId] = useState(researchCase.workpackages[0]?.id ?? '');
  const workpackage = researchCase.workpackages.find(item => item.id === selectedId) ?? researchCase.workpackages[0];
  const [nodes, setNodes] = useState<PlanNode[]>(workpackage?.nodes ?? []);
  const [dirty, setDirty] = useState(false);
  const [nodeId, setNodeId] = useState(workpackage?.nodes[0]?.id ?? '');
  const [optionalAction, setOptionalAction] = useState('');
  const [insertion, setInsertion] = useState('after');
  const [confirm, setConfirm] = useState<'submit' | 'cancel' | 'abandon' | null>(null);
  const [switchTo, setSwitchTo] = useState<string | null>(null);
  const currentNode = nodes.find(node => node.id === nodeId) ?? nodes[0];
  const editable = workpackage?.status === 'draft';
  const definition = catalog?.workpackage_definitions.find(item => item.id === workpackage?.definition_id && String(item.version ?? '1') === String(workpackage?.definition_version ?? '1'));
  const optionalActions = (catalog?.actions ?? []).filter(action => definition?.optional_actions?.includes(action.id));
  const previousCount = useRef(researchCase.workpackages.length);
  const [definitionId, setDefinitionId] = useState('');
  const definitions = (catalog?.workpackage_definitions ?? []).filter(definition => {
    const stages = definition.allowed_stages ?? definition.stages ?? (definition.stage ? [definition.stage] : []);
    return researchCase.status !== 'completed' && (definition.id !== 'taskbook' || String(definition.version ?? '1') === (researchCase.business_lifecycle?.policy_version === 'v2' ? '2' : '1')) && (stages.length ? stages.includes(researchCase.stage) : false);
  });
  const runnable = workpackage?.stage === researchCase.stage;
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!focusRequest || !researchCase.workpackages.some(item => item.id === focusRequest.id)) return;
    if (dirty && workpackage?.id !== focusRequest.id) setSwitchTo(focusRequest.id);
    else setSelectedId(focusRequest.id);
  }, [focusRequest]);
  useEffect(() => {
    if (researchCase.workpackages.length > previousCount.current && !dirty) setSelectedId(researchCase.workpackages[researchCase.workpackages.length - 1].id);
    previousCount.current = researchCase.workpackages.length;
  }, [researchCase.workpackages, dirty]);
  useEffect(() => {
    if (dirty) return;
    setNodes(workpackage?.nodes ?? []);
  }, [workpackage, dirty]);
  useEffect(() => { if (!nodes.some(node => node.id === nodeId)) setNodeId(nodes[0]?.id ?? ''); }, [nodes, nodeId]);
  const actionName = (id: string) => {
    const action = catalog?.actions.find(item => item.id === id);
    return action?.title ?? action?.name ?? ({ resolve_context: '解析与核对参数', template_plan: '模板路由与装配计划', content_completion: '内容补齐与证据核对', generate: '生成研制任务书', verify: '质量验证', consistency: '一致性检查' }[id] ?? id);
  };
  const completed = useMemo(() => (workpackage?.nodes ?? []).filter(node => node.status === 'completed').length, [workpackage]);
  const updateNode = (next: PlanNode) => { setNodes(current => current.map(node => node.id === next.id ? next : node)); setDirty(true); };
  const planData = () => ({ workpackage_id: workpackage!.id, nodes: nodes.map(({ id, action_id, action_version, depends_on, required }) => ({ id, action_id, action_version, depends_on, required })) });
  const addNode = () => {
    const action = optionalActions.find(item => item.id === optionalAction);
    if (!action) return;
    const id = `${action.id}-${Date.now().toString(36)}`;
    const currentIndex = nodes.findIndex(node => node.id === currentNode?.id);
    const terminalIds = nodes.filter(node => !nodes.some(other => other.depends_on.includes(node.id))).map(node => node.id);
    const depends_on = currentNode && insertion === 'before' ? currentNode.depends_on : currentNode && insertion === 'after' ? [currentNode.id] : terminalIds;
    const newNode = { id, action_id: action.id, action_version: action.version, depends_on, required: false };
    const revised = nodes.map(node => insertion === 'before' && node.id === currentNode?.id ? { ...node, depends_on: [id] } : insertion === 'after' && currentNode && node.depends_on.includes(currentNode.id) ? { ...node, depends_on: node.depends_on.map(dependency => dependency === currentNode.id ? id : dependency) } : node);
    revised.splice(insertion === 'before' ? currentIndex : insertion === 'after' ? currentIndex + 1 : revised.length, 0, newNode);
    setNodes(revised); setNodeId(id); setDirty(true); setOptionalAction('');
  };
  const removeNode = (id: string) => {
    const previousDependencies = nodes.find(node => node.id === id)?.depends_on ?? [];
    setNodes(current => current.filter(node => node.id !== id).map(node => ({ ...node, depends_on: [...new Set(node.depends_on.flatMap(dependency => dependency === id ? previousDependencies : [dependency]))] })));
    setDirty(true);
  };

  return <section className="rd-section" aria-labelledby="rd-workpackage-title">
    <div className="rd-section-head"><div><span className="rd-eyebrow">阶段内部 · 工作包</span><h3 id="rd-workpackage-title">工作包计划与执行</h3><p>工作包完成只代表局部任务完成；案例阶段由实际业务决定推进。</p></div></div>
    <div className="rd-pull-workpackage"><div className="rd-field"><label id="rd-definition-label">当前阶段可拉取的工作包 · {scenarioStage(researchCase, scenarioManifest(researchCase.scenario_id)).title}</label><StyledSelect aria-labelledby="rd-definition-label" value={definitionId} options={[{ value: '', label: definitions.length ? '选择工作包定义' : '当前阶段暂无可执行工作包' }, ...definitions.map(definition => ({ value: `${definition.id}@${definition.version ?? '1'}`, label: `${definition.title ?? definition.name ?? definition.id} · V${definition.version ?? '1'}` }))]} disabled={busy || !definitions.length} onChange={setDefinitionId} /></div><button className="rd-button primary" disabled={busy || !definitions.some(item => `${item.id}@${item.version ?? '1'}` === definitionId) || !catalog || dirty} onClick={() => { const selected = definitions.find(item => `${item.id}@${item.version ?? '1'}` === definitionId); if (selected) void command('pull_workpackage', { definition_id: selected.id, definition_version: selected.version ?? '1' }); }}>拉取工作包</button></div>
    {!workpackage ? <div className="rd-empty"><strong>此案例尚无工作包</strong><p>选择当前阶段可用的工作包。资料检查、参数澄清与任务书装配分别承担局部任务。</p></div> : <>
      <div className="rd-field"><label id="rd-wp-select-label">案例工作包记录</label><StyledSelect aria-labelledby="rd-wp-select-label" value={workpackage.id} options={researchCase.workpackages.map(item => ({ value: item.id, label: `${item.title} · ${statusTitle(item.status)} · ${item.id.slice(-8)}` }))} disabled={busy} onChange={id => { if (dirty) setSwitchTo(id); else setSelectedId(id); }} /></div>
      {!runnable && <p className="rd-notice">这是其他阶段的工作包记录。可查看固定成果与证据，提交仅在所属阶段开放。</p>}
      <div className="rd-workpackage-summary"><div><span className={`rd-badge ${workpackage.status}`}>{statusTitle(workpackage.status)}</span><span>计划版本 {workpackage.plan_revision}</span><span>节点完成 {completed} / {workpackage.nodes.length}</span></div><code>{workpackage.id}</code></div>
      <div className="rd-workpackage-layout rd-workpackage-canvas-layout">
        <div className="rd-workpackage-canvas-main">
          <WorkflowCanvas nodes={nodes} actions={catalog?.actions ?? []} selectedId={currentNode?.id} onSelectNode={setNodeId} title={editable ? '编排执行计划' : '执行记录画布'} />
          {editable && !!optionalActions.length && <div className="rd-add-node"><label id="rd-optional-action-label">增加可选节点</label><StyledSelect aria-labelledby="rd-optional-action-label" value={optionalAction} options={[{ value: '', label: '选择可选动作' }, ...optionalActions.map(action => ({ value: action.id, label: actionName(action.id) }))]} onChange={setOptionalAction} disabled={busy} /><StyledSelect aria-label="可选节点插入位置" value={insertion} options={[{ value: 'before', label: '插入当前节点之前' }, { value: 'after', label: '插入当前节点之后' }, { value: 'end', label: '追加到计划末尾' }]} onChange={setInsertion} disabled={busy} /><button className="rd-button" disabled={busy || !optionalAction} onClick={addNode}>加入执行计划</button></div>}
        </div>
        <div className="rd-node-detail" aria-live="polite">{currentNode && <>
          <div className="rd-section-head"><div><span className="rd-eyebrow">节点详情</span><h4>{actionName(currentNode.action_id)}</h4></div><span className={`rd-badge ${currentNode.status ?? 'draft'}`}>{statusTitle(currentNode.status)}</span></div>
          <dl className="rd-meta"><dt>动作标识</dt><dd><code>{currentNode.action_id}</code></dd><dt>动作版本</dt><dd><code>{currentNode.action_version}</code></dd><dt>节点要求</dt><dd>{currentNode.required ? '必需节点，不能移除' : '可选节点'}</dd><dt>执行尝试</dt><dd>{currentNode.attempt ?? 0}</dd></dl>
          <p className="rd-muted">{catalog?.actions.find(action => action.id === currentNode.action_id)?.description ?? '执行时使用提交快照中的来源、参数和固定动作版本。'}</p>
          {editable ? <fieldset className="rd-dependencies" disabled={busy}><legend>前置依赖</legend>{nodes.filter(node => node.id !== currentNode.id).map(node => <label key={node.id}><input type="checkbox" checked={currentNode.depends_on.includes(node.id)} onChange={event => updateNode({ ...currentNode, depends_on: event.target.checked ? [...currentNode.depends_on, node.id] : currentNode.depends_on.filter(id => id !== node.id) })} />{actionName(node.action_id)}<code>{node.id}</code></label>)}<p className="rd-muted">服务端校验依赖完整性与环路；必需检查始终保留。</p></fieldset> : <div className="rd-node-dependency-summary"><strong>前置依赖</strong><p>{currentNode.depends_on.length ? currentNode.depends_on.map(id => actionName(nodes.find(node => node.id === id)?.action_id ?? id)).join('、') : '无前置依赖'}</p></div>}
          {currentNode.result && Object.keys(currentNode.result).length > 0 && <div className="rd-result"><h4>执行结果与证据</h4><pre>{readable(currentNode.result)}</pre></div>}
          {editable && !currentNode.required && <button className="rd-button danger" disabled={busy} onClick={() => removeNode(currentNode.id)}>移除此可选节点</button>}
        </>}</div>
      </div>
      <div className="rd-actions rd-plan-actions"><p className="rd-muted">{dirty ? '计划有未保存修改。保存后才能确认提交。' : editable ? '计划已保存。提交会固定资料、参数、来源哈希、计划和版本。' : '已提交的执行快照只读；状态来自服务端运行记录。'}</p><div>{editable && <><button className="rd-button" disabled={busy || !dirty} onClick={() => void command('save_plan', planData(), () => setDirty(false))}>保存计划</button><button className="rd-button primary" disabled={busy || dirty || !runnable} onClick={() => setConfirm('submit')}>确认提交</button></>}{['submitted', 'running'].includes(workpackage.status) && <button className="rd-button danger" disabled={busy} onClick={() => setConfirm('cancel')}>取消工作包</button>}{['draft', 'blocked', 'failed'].includes(workpackage.status) && <button className="rd-button danger" disabled={busy} onClick={() => setConfirm('abandon')}>废止此工作包</button>}</div></div>
      {(workpackage.blocked_reasons?.length > 0 || workpackage.obligations?.length > 0) && <div className="rd-evidence-warning"><h4>待处理事项与阻塞证据</h4>{workpackage.blocked_reasons?.map((reason, index) => <pre key={`reason-${index}`}>{readable(reason)}</pre>)}{workpackage.obligations?.map((obligation, index) => <pre key={`obligation-${index}`}>{readable(obligation)}</pre>)}<p>先核对证据与缺口，再补充项目资料。当前工作包使用提交时的固定输入。</p></div>}
      <div className="rd-result"><h4>工作包成果</h4>{workpackage.artifacts?.length ? <ul className="rd-artifact-list">{workpackage.artifacts.map(artifact => <li key={artifact.id}><a href={artifactUrl(project.id, researchCase.id, workpackage.id, artifact.id)} target="_blank" rel="noreferrer">{artifact.name}<span>下载成果 ↗</span></a>{artifact.sha256 && <code>SHA-256 {artifact.sha256}</code>}</li>)}</ul> : <p className="rd-muted">尚无已登记成果。执行完成前不提供预设下载。</p>}</div>
      {workpackage.snapshot && <details className="rd-disclosure"><summary>查看固定执行快照{workpackage.run_id ? ` · ${workpackage.run_id}` : ''}</summary><pre>{readable(workpackage.snapshot)}</pre></details>}
    </>}
    {confirm && workpackage && <FeedbackConfirmDialog title={confirm === 'submit' ? '确认提交阶段工作包' : confirm === 'abandon' ? '废止此工作包' : '取消正在执行的工作包'} confirm={confirm === 'submit' ? '固定快照并提交' : confirm === 'abandon' ? '废止此工作包' : '取消工作包'} danger={confirm !== 'submit'} pending={busy} error={error} onCancel={() => setConfirm(null)} onConfirm={() => void command(confirm === 'submit' ? 'submit_workpackage' : 'cancel_workpackage', { workpackage_id: workpackage.id }, () => { if (confirm === 'abandon') setDirty(false); setConfirm(null); })}>
      <p>{confirm === 'submit' ? `提交将固定当前案例的 ${researchCase.sources.filter(source => isCurrentSource(source, researchCase.source_selection)).length} 份当前输入来源、两个独立决策项、六项参数与 ${nodes.length} 个计划节点，由工作包自主执行。历史技术资料和规范版本不作为本次输入。缺少真实证据时将阻塞；案例阶段仍需实际工程决定。` : confirm === 'abandon' ? `将废止“${workpackage.title}”。废止后，此工作包不再阻挡阶段确认，历史记录、固定快照和已登记的原成果继续保留。${dirty ? '当前未保存的计划修改将放弃。' : ''}` : '取消后，本次执行的迟到结果不会被采用。已登记的案例来源与成果继续保留。'}</p>
    </FeedbackConfirmDialog>}
    {switchTo && <FeedbackConfirmDialog title="放弃未保存的计划修改" confirm="放弃并切换" cancel="继续编辑" onCancel={() => setSwitchTo(null)} onConfirm={() => { setDirty(false); setSelectedId(switchTo); setSwitchTo(null); }}><p>当前工作包计划尚未保存。切换后未保存的节点修改会丢失。</p></FeedbackConfirmDialog>}
  </section>;
}
