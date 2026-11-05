import { Button, Tag } from 'antd';
import { useEffect, useReducer, useRef, useState } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { useApplicationLeaveGuard } from '../../hooks/useApplicationLeaveGuard';
import { makeRequestKey, RdApiError, rdCatalogItems, rdGovernanceSession, rdWorkflowHistory, rdWorkflowSave, rdWorkflowTemplate, rdWorkflowTemplates, rdWorkflowValidate } from './api';
import { FlowGraphEditor } from './FlowGraphEditor';
import { draftReducer } from './flowDraftReducer';
import { formatTime, messageOf } from './presentation';
import { workflowTemplateDiff } from './workflowTemplateDiff';
import { useDirectoryState } from './useDirectoryState';
import type { BusinessWorkflowTemplate, GovernanceSession, ResourceSummary, WorkflowCheck, WorkflowHistory } from './types';
import './workflowTemplateWorkbench.css';

const stateLabel = (state: string) => ({ draft: '草稿', published: '已发布', retired: '已停用' }[state] ?? state);
const eventLabel = (state: string) => ({ save: '保存新修订', validate: '校验', publish: '发布', retire: '停用' }[state] ?? state);
const emptyGraph = { nodes: [], edges: [] };

export function WorkflowTemplateWorkbench({ onOpenCase, onStartWorkflow }: { onOpenCase: (project: string, researchCase: string) => void; onStartWorkflow?: (template: BusinessWorkflowTemplate) => void }) {
  const [access, setAccess] = useState<GovernanceSession | null>(null), [accessLoaded, setAccessLoaded] = useState(false);
  const directory = useDirectoryState('workflow', { category: 'project', q: '', page: '1', item: '', version: '', detail: 'canvas', history_page: '1', compare: '' });
  const { state: location, update: updateLocation } = directory;
  const category = location.category as BusinessWorkflowTemplate['category'], query = location.q, page = directory.page;
  const detailTab = location.detail === 'history' ? 'history' : 'canvas';
  const historyPage = Number(location.history_page) || 1, compareVersion = location.compare;
  const [pages, setPages] = useState(1), [total, setTotal] = useState(0);
  const [items, setItems] = useState<BusinessWorkflowTemplate[]>([]), [selected, setSelected] = useState<BusinessWorkflowTemplate | null>(null);
  const [teams, setTeams] = useState<ResourceSummary[]>([]), [teamError, setTeamError] = useState('');
  const [revision, setRevision] = useState(0), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [loadedDirectory, setLoadedDirectory] = useState('');
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [draft, dispatch] = useReducer(draftReducer, { graph: emptyGraph, operations: [], past: [], future: [] });
  const [editing, setEditing] = useState(false), [newId, setNewId] = useState(''), [title, setTitle] = useState(''), [route, setRoute] = useState('modification'), [note, setNote] = useState('');
  const [validation, setValidation] = useState<WorkflowCheck | null>(null);
  const [pendingLeave, setPendingLeave] = useState<(() => void) | null>(null);
  const [confirm, setConfirm] = useState<'publish' | 'retire' | null>(null);
  const [history, setHistory] = useState<WorkflowHistory | null>(null), [historyError, setHistoryError] = useState(''), [historyLoading, setHistoryLoading] = useState(false);
  const [compared, setCompared] = useState<BusinessWorkflowTemplate | null>(null), [compareError, setCompareError] = useState('');
  const selectedRef = useRef(selected); selectedRef.current = selected;
  const editingRef = useRef(editing); editingRef.current = editing;
  const accessRef = useRef(access); accessRef.current = access;
  const retry = useRef({ fingerprint: '', key: '' }), epoch = useRef(0);
  const focusTitle = useRef<HTMLInputElement>(null);
  const management = !!access && (access.can_edit_workflows || access.can_publish_workflows);
  const directoryKey = JSON.stringify([category, query, page, location.item, location.version, management, revision]);
  const dirty = editing && (!!newId || title !== selected?.title || route !== (selected?.product_route || 'modification') || !!note || JSON.stringify(draft.graph) !== JSON.stringify(selected?.graph));
  useApplicationLeaveGuard({ dirty, busyMessage: busy ? '正在保存或核验流程模板，请稍候。' : undefined });

  function choose(item: BusinessWorkflowTemplate, persist = true) {
    if (persist) updateLocation({
      item: item.id, version: item.version, compare: '',
      ...(selectedRef.current?.id !== item.id ? { history_page: '1' } : {}),
    }, false);
    selectedRef.current = item; editingRef.current = false;
    setSelected(item); dispatch({ type: 'reset', graph: item.graph }); setTitle(item.title); setRoute(item.product_route || 'modification');
    setEditing(false); setNewId(''); setNote(''); setValidation(null); setError(''); retry.current = { fingerprint: '', key: '' };
  }
  function leave(action: () => void) { if (busy) return; if (dirty) setPendingLeave(() => action); else action(); }
  function denied(reason: unknown) {
    if (reason instanceof RdApiError && [401, 403].includes(reason.status)) {
      epoch.current++; selectedRef.current = null; editingRef.current = false;
      setAccess(null); setItems([]); setSelected(null); setEditing(false); setHistory(null); setTeams([]); setConfirm(null); setPendingLeave(null);
      if (management) updateLocation({ item: '', version: '', history_page: '1', compare: '' }, false);
    }
    setError(messageOf(reason));
  }
  useEffect(() => {
    const controller = new AbortController(); setAccessLoaded(false);
    void rdGovernanceSession(controller.signal).then(value => {
      if (controller.signal.aborted) return;
      const previous = accessRef.current;
      if (previous && (previous.can_edit_workflows && !value.can_edit_workflows || previous.can_publish_workflows && !value.can_publish_workflows)) {
        epoch.current++; setSelected(null); selectedRef.current = null; setItems([]); setHistory(null); setEditing(false); editingRef.current = false; setNewId(''); setValidation(null); setConfirm(null); setPendingLeave(null); setCompared(null);
        updateLocation({ item: '', version: '', history_page: '1', compare: '' }, false);
        setNotice('模板维护权限已更新，已按当前权限重新读取。');
      }
      setAccess(value);
    }).catch(reason => { if (!controller.signal.aborted) denied(reason); }).finally(() => { if (!controller.signal.aborted) setAccessLoaded(true); });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    if (!accessLoaded) return;
    const controller = new AbortController(), currentEpoch = epoch.current; setLoading(true); setLoadedDirectory('');
    void rdWorkflowTemplates(category, { page, q: query }, management, controller.signal).then(async result => {
      if (controller.signal.aborted || currentEpoch !== epoch.current) return;
      setItems(result.items); setTotal(result.total); setPages(Math.max(1, result.total_pages));
      if (page > Math.max(1, result.total_pages)) { updateLocation({ page: String(Math.max(1, result.total_pages)) }, false); return; }
      if (!editingRef.current) {
        if (location.item) {
          // An explicit address identifies a fixed template, even outside the current directory page.
          // A missing/inaccessible address must not silently display a different template.
          const current = selectedRef.current;
          if (current?.id !== location.item || (location.version && current.version !== location.version)) setSelected(null);
          const fixed = await rdWorkflowTemplate(location.item, location.version || 'latest', management, controller.signal);
          if (controller.signal.aborted || currentEpoch !== epoch.current || editingRef.current) return;
          if (fixed.category !== category) { setSelected(null); selectedRef.current = null; setError('该模板不属于当前流程用途，请切换流程用途后查看。'); return; }
          if (current?.id === fixed.id && current.version === fixed.version) setSelected(fixed);
          else choose(fixed, false);
          if (!location.version) updateLocation({ version: fixed.version }, false);
        } else if (result.items[0]) {
          choose(result.items[0], false);
          updateLocation({ item: result.items[0].id, version: result.items[0].version, history_page: '1', compare: '' }, false);
        } else { setSelected(null); selectedRef.current = null; }
      }
      if (!controller.signal.aborted && currentEpoch === epoch.current) setLoadedDirectory(directoryKey);
    }).catch(reason => { if (!controller.signal.aborted) denied(reason); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [category, query, page, location.item, location.version, management, accessLoaded, revision]);
  useEffect(() => {
    const controller = new AbortController(); setTeamError('');
    void (async () => {
      const first = await rdCatalogItems<ResourceSummary>('actions', { page: 1 }, controller.signal); const all = [...first.items];
      for (let next = 2; next <= first.total_pages; next++) all.push(...(await rdCatalogItems<ResourceSummary>('actions', { page: next }, controller.signal)).items);
      if (!controller.signal.aborted) setTeams(all.filter(item => item.kind === 'team' && item.executable));
    })().catch(reason => { if (!controller.signal.aborted) { setTeams([]); setTeamError(messageOf(reason)); } });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    if (!selected || detailTab !== 'history') return;
    const controller = new AbortController(); setHistoryLoading(true); setHistoryError(''); setHistory(null);
    void rdWorkflowHistory(selected.id, management, historyPage, controller.signal).then(value => { if (!controller.signal.aborted) { if (historyPage > Math.max(1, value.total_pages)) updateLocation({ history_page: String(Math.max(1, value.total_pages)) }, false); else setHistory(value); } }).catch(reason => { if (!controller.signal.aborted) { if (reason instanceof RdApiError && [401,403].includes(reason.status)) denied(reason); setHistoryError(messageOf(reason)); } }).finally(() => { if (!controller.signal.aborted) setHistoryLoading(false); });
    return () => controller.abort();
  }, [selected?.id, detailTab, management, historyPage, revision]);
  useEffect(() => {
    setCompared(null); setCompareError('');
    if (!selected || !compareVersion) return;
    const controller = new AbortController();
    void rdWorkflowTemplate(selected.id, compareVersion, management, controller.signal).then(value => { if (!controller.signal.aborted) setCompared(value); }).catch(reason => { if (!controller.signal.aborted) setCompareError(messageOf(reason)); });
    return () => controller.abort();
  }, [selected?.id, compareVersion, management]);
  useEffect(() => { if (editing) focusTitle.current?.focus(); }, [editing]);

  function edit(copy = false) {
    if (!selected) return;
    dispatch({ type: 'reset', graph: selected.graph }); setTitle(copy ? selected.title + '（副本）' : selected.title); setRoute(selected.product_route || 'modification');
    setNewId(copy ? 'workflow-' + makeRequestKey() : ''); setNote(''); setEditing(true); updateLocation({ detail: 'canvas' }, false); setValidation(null); setError(''); setNotice('');
  }
  async function readVersion(version: string) {
    if (!selected || busy) return; setBusy(true); setError('');
    try { choose(await rdWorkflowTemplate(selected.id, version, management)); } catch (reason) { denied(reason); } finally { setBusy(false); }
  }
  function payload(operation: string) {
    return { operation, id: newId || selected!.id, version: selected!.version, expected_version: newId ? 0 : Number(selected!.head_version ?? selected!.version), expected_state_revision: selected!.publication_revision,
      category: selected!.category, title, product_route: selected!.category === 'research' ? route : null, graph: editing ? draft.graph : selected!.graph,
      change_note: note.trim(), based_on: { id: selected!.id, version: selected!.version, digest: selected!.digest } };
  }
  async function mutate(operation: 'save' | 'publish' | 'retire' | 'validate') {
    if (!selected || busy) return;
    if (operation === 'save' && (!title.trim() || !note.trim())) { setError(!title.trim() ? '请填写流程名称。' : '请填写本次修改说明，方便后续回溯。'); return; }
    const data = payload(operation), fingerprint = JSON.stringify(data);
    if (retry.current.fingerprint !== fingerprint) retry.current = { fingerprint, key: makeRequestKey() };
    const currentEpoch = epoch.current; setBusy(true); setError(''); setNotice('');
    try {
      const result = await rdWorkflowSave(data, retry.current.key); if (currentEpoch !== epoch.current) return;
      choose(result); setConfirm(null); if (operation === 'validate') setValidation(result.validation ?? null);
      setNotice({ save: `草稿 V${result.version} 已保存。校验、发布后，项目才能采用。`, publish: `V${result.version} 已发布。已有项目继续使用原来采用的版本。`, retire: `V${result.version} 已停用，历史版本和项目记录仍然保留。`, validate: result.validation?.valid ? '已保存版本校验通过，记录已留存。' : '已保存版本存在待调整项，请查看校验结果。' }[operation]);
      setRevision(value => value + 1);
    } catch (reason) { denied(reason); } finally { setBusy(false); }
  }
  async function validate() {
    if (!selected || busy) return;
    if (!editing && management) { await mutate('validate'); return; }
    setBusy(true); setError('');
    try { const data = payload('validate'); setValidation(await rdWorkflowValidate({ id: data.id, version: data.version, category: data.category, product_route: data.product_route, title: data.title, graph: data.graph })); } catch (reason) { denied(reason); } finally { setBusy(false); }
  }
  const canEdit = !!access?.can_edit_workflows, canPublish = !!access?.can_publish_workflows;
  const canStartWorkflow = !!onStartWorkflow && accessLoaded && !loading && !busy && !editing && !error && loadedDirectory === directoryKey && selected?.category === 'project' && selected.status === 'published' && !!selected.digest;
  const changes = compared && selected ? workflowTemplateDiff(compared, selected, Object.fromEntries(teams.map(item => [item.id, item.name]))) : [];
  return <div className="rd-template-manager">
    <div className="rd-template-directory-tools">
      <div className="rd-field"><label htmlFor="workflow-template-search">查找流程模板</label><input id="workflow-template-search" type="search" placeholder="输入模板名称" value={directory.input} disabled={editing || busy} onChange={event => directory.setInput(event.target.value)} onCompositionStart={() => directory.setComposing(true)} onCompositionEnd={event => { directory.setComposing(false); directory.setInput(event.currentTarget.value); }} onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing && !directory.composing) directory.commit(); }} /></div>
      <div className="rd-field"><label id="workflow-category-label">流程用途</label><StyledSelect aria-labelledby="workflow-category-label" value={category} disabled={busy} onChange={value => leave(() => { selectedRef.current = null; editingRef.current = false; setSelected(null); setEditing(false); directory.setInput(''); updateLocation({ category: value, q: '', item: '', version: '', detail: 'canvas', history_page: '1', compare: '' }); })} options={[{ value: 'project', label: '项目流程' }, { value: 'research', label: '研发阶段流程' }, { value: 'selection', label: '选型阶段流程' }]} /></div>
      <Button autoInsertSpace={false} htmlType="button" className="rd-button" disabled={busy || loading || editing} onClick={() => { setError(''); setRevision(value => value + 1); }}>刷新模板</Button>
    </div>
    {!accessLoaded && <p className="rd-loading" role="status">正在读取模板维护权限…</p>}
    {accessLoaded && !canEdit && <p className="rd-notice">当前可查看已获准的流程模板。编辑和发布由流程维护人员办理。</p>}
    {error && <div className="rd-error" role="alert"><p>{error}</p><Button autoInsertSpace={false} className="rd-button compact" htmlType="button" disabled={busy} onClick={() => { setError(''); setRevision(value => value + 1); }}>重试读取</Button>{editing && selected && <Button autoInsertSpace={false} type="link" htmlType="button" className="rd-link-button" disabled={busy} onClick={async () => { setBusy(true); try { const latest = await rdWorkflowTemplate(selected.id, 'latest', true); setSelected(current => current ? { ...current, head_version: latest.head_version } : current); setNotice(`最新内容已到 V${latest.version}，当前编辑仍保留；保存将新增修订，不覆盖其他版本。`); } catch (reason) { denied(reason); } finally { setBusy(false); } }}>核对最新修订，保留当前编辑</Button>}</div>}
    {notice && <p className="rd-success" role="status">{notice}</p>}
    <div className="rd-template-workbench">
      <aside className="rd-template-list" aria-label="流程模板目录"><header><strong>流程模板</strong><span>{total} 项</span></header>
        {loading && <p role="status" className="rd-muted">正在读取…</p>}
        {!loading && !items.length && <p className="rd-muted">{query ? '没有匹配的模板，请调整关键词。' : '暂无可用模板。'}</p>}
        {items.map(item => <button type="button" key={item.id} className={selected?.id === item.id ? 'is-selected' : ''} aria-pressed={selected?.id === item.id} disabled={busy || loading} onClick={() => leave(() => choose(item))}><strong>{item.title}</strong><span>V{item.version} · {stateLabel(item.status)}</span><small>{item.category === 'project' ? '项目流程' : item.category === 'selection' ? '需求与选型' : item.product_route === 'new' ? '全新研发' : '改型研发'} · {item.graph.nodes.length} 个节点</small></button>)}
        <div className="rd-template-pagination"><Button autoInsertSpace={false} htmlType="button" className="rd-button compact" disabled={busy || editing || page <= 1} onClick={() => updateLocation({ page: String(page - 1), item: '', version: '', history_page: '1', compare: '' }, false)}>上一页</Button><span>{page}/{pages}</span><Button autoInsertSpace={false} htmlType="button" className="rd-button compact" disabled={busy || editing || page >= pages} onClick={() => updateLocation({ page: String(page + 1), item: '', version: '', history_page: '1', compare: '' }, false)}>下一页</Button></div>
      </aside>
      <main className="rd-template-detail">
        {!selected ? <p className="rd-management-empty">从左侧选择流程模板，查看画布与版本记录。</p> : <>
          <header className="rd-template-detail-head"><div><span className="rd-eyebrow">{editing ? newId ? '新模板草稿' : `基于 V${selected.version} 编排新修订` : '固定流程模板'}</span><h3>{editing ? title || '未命名流程' : selected.title}</h3><p>通过节点依赖和业务参数配置流程；拖动仅调整布局。</p></div><Tag className={`rd-badge ${editing ? 'draft' : selected.status}`}>{editing ? '编辑中 · 未保存' : `V${selected.version} · ${stateLabel(selected.status)}`}</Tag></header>
          <div className="rd-template-actions">
            {onStartWorkflow && selected.category === 'project' && selected.status === 'published' && !editing && <Button autoInsertSpace={false} type="primary" htmlType="button" className="rd-button primary" disabled={!canStartWorkflow} onClick={() => { if (canStartWorkflow) onStartWorkflow(selected); }}>使用此流程新建项目</Button>}
            {canEdit && (!editing ? <><Button autoInsertSpace={false} type="primary" htmlType="button" className="rd-button primary" disabled={busy} onClick={() => edit()}>编辑新版本</Button><Button autoInsertSpace={false} htmlType="button" className="rd-button" disabled={busy} onClick={() => edit(true)}>新建流程模板</Button></> : <><Button autoInsertSpace={false} type="primary" htmlType="button" className="rd-button primary" disabled={busy || !dirty} onClick={() => void mutate('save')}>{busy ? '处理中…' : '保存草稿'}</Button><Button autoInsertSpace={false} htmlType="button" className="rd-button" disabled={busy} onClick={() => leave(() => { choose(selected); setNotice('已取消编辑，保存的版本保持不变。'); })}>取消编辑</Button><Button autoInsertSpace={false} htmlType="button" className="rd-button" disabled={busy || !draft.past.length} onClick={() => { dispatch({ type: 'undo' }); setValidation(null); }}>撤销</Button><Button autoInsertSpace={false} htmlType="button" className="rd-button" disabled={busy || !draft.future.length} onClick={() => { dispatch({ type: 'redo' }); setValidation(null); }}>重做</Button></>)}
            {management && <Button autoInsertSpace={false} htmlType="button" className="rd-button" disabled={busy} onClick={() => void validate()}>校验流程</Button>}
            {canPublish && !editing && <><Button autoInsertSpace={false} htmlType="button" className="rd-button" disabled={busy || selected.status !== 'draft'} onClick={() => setConfirm('publish')}>发布版本</Button><Button autoInsertSpace={false} danger htmlType="button" className="rd-button danger" disabled={busy || selected.status !== 'published'} onClick={() => setConfirm('retire')}>停用版本</Button></>}
          </div>
          {editing && <div className="rd-template-edit-fields"><div className="rd-field"><label htmlFor="workflow-template-title">流程名称</label><input ref={focusTitle} id="workflow-template-title" value={title} disabled={busy} onChange={event => { setTitle(event.target.value); setValidation(null); }} /></div>{selected.category === 'research' && <div className="rd-field"><label id="workflow-route-label">适用条件 · 研发路线</label><StyledSelect aria-labelledby="workflow-route-label" value={route} disabled={busy} onChange={value => { setRoute(value); setValidation(null); }} options={[{ value: 'modification', label: '改型研发' }, { value: 'new', label: '全新研发' }]} /></div>}<div className="rd-field rd-template-note"><label htmlFor="workflow-change-note">本次修改说明 <span aria-hidden="true">*</span></label><textarea id="workflow-change-note" className="resize-none" rows={2} value={note} disabled={busy} placeholder={selected.category === 'project' ? '例如：在任务书生成前增加资料一致性检查' : '例如：在任务书范围批准前增加资料一致性检查'} onChange={event => setNote(event.target.value)} /></div></div>}
          {validation && <section className={validation.valid ? 'rd-success' : 'rd-warning'} role="status"><strong>{validation.valid ? '校验通过' : '请调整以下内容'}</strong>{validation.errors.length > 0 && <ul>{validation.errors.map((item, index) => <li key={index}>{item.message}</li>)}</ul>}<p>{editing ? '结果对应当前草稿；修改后需要重新校验。' : '发布时会再次检查当前版本的依赖与动作能力。'}</p></section>}
          <div className="rd-template-view-tabs"><button type="button" aria-pressed={detailTab === 'canvas'} onClick={() => updateLocation({ detail: 'canvas' }, false)}>流程画布</button><button type="button" aria-pressed={detailTab === 'history'} onClick={() => updateLocation({ detail: 'history' }, false)}>版本与回溯</button><div className="rd-template-fixed-version"><StyledSelect aria-label="查看固定版本" value={selected.version} disabled={busy || editing} options={(selected.available_versions ?? [selected.version]).map(version => ({ value: version, label: `V${version}${version === selected.head_version ? ' · 最新修订' : ''}` }))} onChange={version => void readVersion(version)} /></div></div>
          {detailTab === 'canvas' ? <>
            {teamError && <p className="rd-warning">可选动作暂时无法读取：{teamError}。已有配置仍保留，可重试读取模板。</p>}
            <FlowGraphEditor key={selected.id} business businessCategory={selected.category} graph={editing ? draft.graph : selected.graph} readOnly={!editing} disabled={busy} choices={teams.map(item => ({ id: item.id, version: item.version, title: item.name || item.id, kind: 'resource' as const }))} onChange={operations => { dispatch({ type: 'apply', operations }); setValidation(null); }} />
            {!editing && <p className="rd-muted">查看的是固定版本。点击“编辑新版本”调整配置；{selected.category === 'project' ? '发布后可使用此流程新建项目，已有项目保留采用的版本。' : '发布后由项目单独选择采用。'}</p>}
          </> : <section className="rd-template-history" aria-label="模板版本与回溯">
            {editing && <p className="rd-notice">当前编辑已保留。这里展示保存过的历史，返回画布可继续修改。</p>}
            {historyLoading && <p role="status">正在读取版本与引用记录…</p>}{historyError && <p className="rd-error" role="alert">{historyError}</p>}
            {history && <>
              <h4>版本记录</h4><ul className="rd-template-version-list">{history.items.map(item => <li key={item.version}><div><strong>V{item.version} · {stateLabel(item.status)}</strong><p>{item.change_note || '初始版本 / 未记录修改说明'}</p><small>{formatTime(item.created_at)} · {item.actor === 'system-bootstrap' ? '系统初始模板' : item.actor || '历史未记录'}</small>{item.based_on && <small>基于 {item.based_on.id === selected.id ? '本模板' : '来源模板'} V{item.based_on.version}</small>}</div><Button autoInsertSpace={false} htmlType="button" className="rd-button compact" disabled={busy || editing} onClick={() => void readVersion(item.version)}>查看 V{item.version}</Button></li>)}</ul>
              <div className="rd-template-pagination"><Button autoInsertSpace={false} htmlType="button" className="rd-button compact" disabled={historyPage <= 1 || historyLoading} onClick={() => updateLocation({ history_page: String(historyPage - 1) }, false)}>较新记录</Button><span>{historyPage}/{Math.max(1, history.total_pages)}</span><Button autoInsertSpace={false} htmlType="button" className="rd-button compact" disabled={historyPage >= history.total_pages || historyLoading} onClick={() => updateLocation({ history_page: String(historyPage + 1) }, false)}>较早记录</Button></div>
              <h4>变更对比</h4><div className="rd-template-compare"><StyledSelect aria-label="对比基准版本" value={compareVersion} disabled={busy} options={[{ value: '', label: '选择较早的版本作为基准' }, ...(selected.available_versions ?? []).filter(version => version !== selected.version).map(version => ({ value: version, label: `V${version}` }))]} onChange={version => updateLocation({ compare: version }, false)} /><span>→ 当前查看 V{selected.version}</span></div>{compareError && <p className="rd-error">{compareError}</p>}{compareVersion && !compared && !compareError && <p role="status">正在读取对比版本…</p>}{compared && <>{!changes.length ? <p className="rd-muted">两版业务配置和布局相同。</p> : <ul className="rd-template-diff-list">{changes.map((item, index) => <li key={index}><Tag className="rd-badge">{item.kind}</Tag><div><strong>{item.title}</strong>{(item.before || item.after) && <p><span>{item.before}</span><span aria-hidden="true"> → </span><span>{item.after}</span></p>}</div></li>)}</ul>}</>}
              {canEdit && <Button autoInsertSpace={false} htmlType="button" className="rd-button" disabled={busy || editing} onClick={() => edit()}>基于当前查看版本创建新修订</Button>}
              <h4>操作记录 · 本页版本</h4>{!history.events.length ? <p className="rd-muted">这些版本暂无操作记录。</p> : <ol className="rd-template-event-list">{history.events.map(event => <li key={event.id}><strong>V{event.version} · {eventLabel(event.operation)}</strong><span>{formatTime(event.created_at)} · {event.actor === 'system-bootstrap' ? '系统' : event.actor}</span></li>)}</ol>}
              <h4>项目引用 · 本页版本</h4><p className="rd-muted">仅展示你有权查看的项目；停用模板不会抹去采用时的记录。</p>{!history.usages.length ? <p className="rd-muted">暂无可见项目引用这些版本。</p> : <ul className="rd-template-usage-list">{history.usages.map((usage, index) => <li key={index}><div><strong>{usage.project_title} / {usage.case_title}</strong><p>V{usage.template_version} · {usage.current ? '当前采用' : '历史引用'} · {formatTime(usage.adopted_at)}</p></div><Button autoInsertSpace={false} htmlType="button" className="rd-button compact" disabled={busy} onClick={() => leave(() => onOpenCase(usage.project_id, usage.case_id))}>查看项目</Button></li>)}</ul>}
            </>}
          </section>}
        </>}
      </main>
    </div>
    {pendingLeave && <FeedbackConfirmDialog title="放弃未保存的流程修改" confirm="放弃修改" cancel="继续编辑" onCancel={() => setPendingLeave(null)} onConfirm={() => { const action = pendingLeave; setPendingLeave(null); action(); }}><p>未保存的节点、连线、参数和布局将被放弃，已保存的版本仍然保留。</p></FeedbackConfirmDialog>}
    {confirm && selected && <FeedbackConfirmDialog title={confirm === 'publish' ? '发布流程版本' : '停用流程版本'} confirm={confirm === 'publish' ? '确认发布' : '确认停用'} cancel="取消" pending={busy} danger={confirm === 'retire'} error={error} onCancel={() => setConfirm(null)} onConfirm={() => void mutate(confirm)}><p>“{selected.title}” V{selected.version} {confirm === 'publish' ? '将通过完整校验后供新项目采用。' : '将不再供新项目采用。'}已有项目仍保留当时固定的版本。</p></FeedbackConfirmDialog>}
  </div>;
}
