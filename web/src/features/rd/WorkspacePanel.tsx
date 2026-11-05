import { Button } from 'antd';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { useApplicationLeaveGuard } from '../../hooks/useApplicationLeaveGuard';
import { RdApiError, makeRequestKey, rdCatalogResource, rdCatalogResources, rdResource, rdResourceGrant, rdResourceSave, rdResources, rdWorkspaceSession } from './api';
import { messageOf, readable, statusTitle } from './presentation';
import type { Catalog, DirectoryPage, ResourceSummary, WorkspaceResource, WorkspaceSession } from './types';
import { useDirectoryState } from './useDirectoryState';
import { WorkspaceContracts } from './WorkspaceContracts';
import './workspacePanel.css';
import { TeamConfiguration } from './TeamConfiguration';

const EMPTY = JSON.stringify(['agent', '', '', '{}']);
type Operation = 'publish' | 'retire' | 'grant' | 'revoke';
const operationName: Record<Operation, string> = { publish: '发布版本', retire: '停用资源', grant: '授予应用', revoke: '撤销授权' };
const operationTitle = (operation: Operation, resource: WorkspaceResource) => operation === 'publish' && resource.resource_retired ? '恢复发布' : operationName[operation];
const isManagementResource = (resource: ResourceSummary): resource is WorkspaceResource => 'configuration' in resource;
export function WorkspacePanel({ onDirtyChange, onBusyChange, onCatalogChange }: { catalog: Catalog | null; onDirtyChange: (dirty: boolean) => void; onBusyChange: (busy: boolean) => void; onCatalogChange?: () => void }) {
  const directory = useDirectoryState('workspace', { q: '', kind: '', item: '', version: '', page: '1' });
  const { state, update, page } = directory;
  const [session, setSession] = useState<WorkspaceSession | null>(null);
  const [result, setResult] = useState<DirectoryPage<ResourceSummary> | null>(null);
  const [detail, setDetail] = useState<ResourceSummary | null>(null);
  const [loading, setLoading] = useState(true), [detailLoading, setDetailLoading] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [fieldError, setFieldError] = useState<'name' | 'configuration' | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState<WorkspaceResource | null>(null);
  const [kind, setKind] = useState('agent'), [name, setName] = useState(''), [description, setDescription] = useState(''), [configuration, setConfiguration] = useState('{}');
  const [base, setBase] = useState(EMPTY), [discard, setDiscard] = useState(false);
  const [confirm, setConfirm] = useState<{ operation: Operation; resource: WorkspaceResource } | null>(null);
  const [conflict, setConflict] = useState<{ id: string; version: number | string; operation: string } | null>(null);
  const inFlight = useRef(false), retry = useRef({ fingerprint: '', key: '' }), newResourceId = useRef(makeRequestKey());
  const sensitiveEpoch = useRef(0);
  const search = useRef<HTMLInputElement>(null);
  const canManage = !!session && (session.can_edit_resources || session.can_publish_resources || session.can_manage_application_grants);
  const dirty = JSON.stringify([kind, name, description, configuration]) !== base;
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);
  useApplicationLeaveGuard({ dirty, busyMessage: busy ? '资源操作尚未完成，请等待结果后再离开。' : undefined });
  function clearForm() { setEditing(null); newResourceId.current = makeRequestKey(); setKind('agent'); setName(''); setDescription(''); setConfiguration('{}'); setBase(EMPTY); setDiscard(false); setConfigOpen(false); setFieldError(null); setError(''); setConflict(null); }
  function focusEditor() { document.getElementById('rd-resource-name')?.focus(); }
  function showFieldError(field: 'name' | 'configuration', message: string) {
    setFieldError(field); setError(message);
    if (field === 'configuration') setConfigOpen(true);
    requestAnimationFrame(() => document.getElementById(`rd-resource-${field}`)?.focus());
  }
  function clearUnauthorized() {
    sensitiveEpoch.current += 1; setResult(null); setDetail(null); setConfirm(null); setConflict(null); clearForm(); retry.current = { fingerprint: '', key: '' };
    setSession(null); setDetailLoading(false); onCatalogChange?.(); setNotice('资源权限已变化，管理信息已清除。请刷新资源，重新读取当前可用目录。');
  }
  useEffect(() => {
    const controller = new AbortController(), epoch = sensitiveEpoch.current;
    setLoading(true); setError('');
    void (async () => {
      const access = await rdWorkspaceSession(controller.signal);
      if (controller.signal.aborted || epoch !== sensitiveEpoch.current) return;
      setSession(access);
      const manage = access.can_edit_resources || access.can_publish_resources || access.can_manage_application_grants;
      if (!manage) { setDetail(null); setResult(null); setConfirm(null); }
      if (!access.can_edit_resources) { clearForm(); if (session?.can_edit_resources) retry.current = { fingerprint: '', key: '' }; }
      setConfirm(current => current && ((current.operation === 'publish' || current.operation === 'retire') ? !access.can_publish_resources : !access.can_manage_application_grants) ? null : current);
      const query = { q: state.q, kind: state.kind, page };
      const response = manage ? await rdResources(controller.signal, query) : await rdCatalogResources(query, controller.signal);
      if (controller.signal.aborted || epoch !== sensitiveEpoch.current) return;
      setResult(response);
      const last = Math.max(1, response.total_pages);
      if (page > last) update({ page: String(last) }, false);
    })().catch(reason => {
      if (controller.signal.aborted || epoch !== sensitiveEpoch.current) return;
      if (reason instanceof RdApiError && (reason.status === 403 || reason.status === 401)) clearUnauthorized();
      setError(messageOf(reason));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [state.q, state.kind, page, revision, update]);
  useEffect(() => {
    setDetail(null);
    if (!state.item || !session) return;
    const controller = new AbortController(), epoch = sensitiveEpoch.current; setDetailLoading(true);
    void (canManage ? rdResource(state.item, state.version || 'latest', controller.signal) : rdCatalogResource(state.item, state.version, controller.signal)).then(resource => {
      if (!controller.signal.aborted && epoch === sensitiveEpoch.current) setDetail(resource);
    }).catch(reason => {
      if (controller.signal.aborted || epoch !== sensitiveEpoch.current) return;
      if (reason instanceof RdApiError && (reason.status === 403 || reason.status === 401)) clearUnauthorized();
      setError(messageOf(reason));
    }).finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [state.item, state.version, session, canManage, revision]);
  function loadIntoForm(resource: WorkspaceResource) {
    const values = [resource.kind, resource.name, resource.description ?? '', JSON.stringify(resource.configuration ?? {}, null, 2)] as const;
    setEditing(resource); setKind(values[0]); setName(values[1]); setDescription(values[2]); setConfiguration(values[3]); setBase(JSON.stringify(values)); setError(''); setFieldError(null); setConfigOpen(false); setConflict(null);
    requestAnimationFrame(focusEditor);
  }
  async function refreshConflict() {
    if (!conflict || inFlight.current) return;
    const epoch = sensitiveEpoch.current;
    inFlight.current = true; setBusy(true);
    try {
      const resource = await rdResource(conflict.id, conflict.operation === 'save' ? 'latest' : conflict.version);
      if (epoch !== sensitiveEpoch.current) return;
      setDetail(resource);
      if (conflict.operation === 'save') setEditing(resource);
      update({ item: resource.id, version: String(resource.version) }, false);
      setConflict(null); setError(''); setNotice('已读取目标最新修订，当前填写保留。请核对后重新操作。');
      setRevision(value => value + 1); onCatalogChange?.();
    } catch (reason) { if (epoch !== sensitiveEpoch.current) return; if (reason instanceof RdApiError && (reason.status === 403 || reason.status === 401)) clearUnauthorized(); setError(messageOf(reason)); }
    finally { inFlight.current = false; setBusy(false); }
  }
  async function mutate(operation: 'save' | Operation, resource?: WorkspaceResource) {
    if (inFlight.current || !session) return;
    const epoch = sensitiveEpoch.current;
    if (operation === 'save' ? !session.can_edit_resources : operation === 'grant' || operation === 'revoke' ? !session.can_manage_application_grants : !session.can_publish_resources) return;
    const target = resource ?? editing;
    let payload: Record<string, unknown>;
    if (operation === 'save') {
      if (!name.trim()) { showFieldError('name', '请填写资源名称。'); return; }
      let config: unknown;
      try { config = JSON.parse(configuration); if (!config || typeof config !== 'object' || Array.isArray(config)) throw new Error(); }
      catch { showFieldError('configuration', '资源配置必须是 JSON 对象，请检查括号和字段格式。'); return; }
      payload = { id: target?.id ?? newResourceId.current, expected_version: target?.head_version ?? target?.version ?? 0, kind, name: name.trim(), description, configuration: config, operation };
    } else if (target) payload = operation === 'grant' || operation === 'revoke'
      ? { id: target.id, version: target.version, operation, expected_revision: target.grant?.revision ?? 0 }
      : { id: target.id, version: target.version, expected_version: target.head_version ?? target.version, operation, expected_state_revision: target.publication_revision ?? target.state_revision, expected_control_revision: target.control_revision };
    else return;
    const fingerprint = JSON.stringify(payload);
    if (retry.current.fingerprint !== fingerprint) retry.current = { fingerprint, key: makeRequestKey() };
    inFlight.current = true; setBusy(true); setError(''); setFieldError(null); setNotice('');
    try {
      if (operation === 'grant' || operation === 'revoke') await rdResourceGrant(payload as Parameters<typeof rdResourceGrant>[0], retry.current.key);
      else await rdResourceSave(payload as Parameters<typeof rdResourceSave>[0], retry.current.key);
      if (epoch !== sensitiveEpoch.current) return;
      retry.current = { fingerprint: '', key: '' }; setConflict(null); setConfirm(null);
      setNotice(operation === 'save' ? '草稿已保存；发布与应用授权需分别办理。' : operation === 'publish' ? target?.resource_retired ? '已解除资源整体停用并发布固定版本；仍须当前有效授权，项目采用版本保持不变。' : '固定版本已发布；尚未授权的应用不会自动获得此版本。' : operation === 'retire' ? '资源已整体停用，所有版本暂停；历史成果保留。' : operation === 'grant' ? '已向当前应用授予固定版本。' : '当前应用授权已撤销；历史成果保留。');
      if (operation === 'save') clearForm();
      setRevision(value => value + 1); onCatalogChange?.();
    } catch (reason) {
      if (epoch !== sensitiveEpoch.current) return;
      if (reason instanceof RdApiError && (reason.status === 403 || reason.status === 401)) clearUnauthorized();
      if (reason instanceof RdApiError && reason.status === 409) { setConflict({ id: String(payload.id), version: target?.version ?? 'latest', operation }); setConfirm(null); }
      setError(messageOf(reason));
    } finally { inFlight.current = false; setBusy(false); }
  }
  function submit(event: FormEvent) { event.preventDefault(); void mutate('save'); }
  const detailVersions = detail?.available_versions ?? result?.items.find(resource => resource.id === detail?.id)?.available_versions ?? (detail ? [detail.version] : []);
  const managedDetail = canManage && detail && isManagementResource(detail) ? detail : null;
  const configField = <div className="rd-field"><label htmlFor="rd-resource-configuration">资源配置（JSON）</label><textarea id="rd-resource-configuration" className="resize-none rd-code-input" rows={10} value={configuration} onChange={event => { setConfiguration(event.target.value); if (fieldError === 'configuration') { setFieldError(null); setError(''); } }} disabled={busy} aria-invalid={fieldError === 'configuration'} aria-describedby={fieldError === 'configuration' ? 'rd-resource-config-error rd-resource-config-help' : 'rd-resource-config-help'} />{fieldError === 'configuration' && <small id="rd-resource-config-error" className="rd-field-error">{error}</small>}<small id="rd-resource-config-help">成员、输入输出合同和内部执行图按固定版本保存。保存产生新草稿，不自动发布或授权。</small></div>;
  const grantHint = managedDetail?.resource_retired ? '资源已整体停用。恢复发布后才可授予应用。' : managedDetail?.status !== 'published' ? '此版本尚未发布，发布后才可授予应用。' : '';
  return <div className="rd-page-content rd-workspace-page">
    <div className="rd-page-title"><div><span className="rd-eyebrow">与研发平台同部署</span><h1>本地 Workspace</h1><p>资源定义、固定版发布与应用授权分别办理；项目采用版本保持固定。</p></div><Button type="default" className="rd-button" disabled={loading || busy} onClick={() => setRevision(value => value + 1)}>刷新资源</Button></div>
    {session && <div className="rd-workspace-capabilities"><span>当前应用：<code>{session.application_id}</code></span><span>编辑：{session.can_edit_resources ? '允许' : '只读'}</span><span>发布：{session.can_publish_resources ? '允许' : '只读'}</span><span>应用授权：{session.can_manage_application_grants ? '允许' : '只读'}</span>{session.local_bootstrap && <span>本地回环开发权限</span>}</div>}
    {error && <div className="rd-error rd-banner" role="alert"><p id="rd-resource-error">{error}</p>{conflict && <><p>修订发生变化，当前填写保留。请先读取目标的最新修订。</p><Button type="default" className="rd-button" disabled={busy} onClick={() => void refreshConflict()}>读取最新版本并保留填写</Button></>}</div>}
    {notice && <p className="rd-success rd-banner" role="status">{notice}</p>}
    {!loading && !canManage && <p className="rd-notice">当前为只读获准目录。资源发布与应用授权由服务端分别验证；主站管理员身份不自动获得资源治理权限。</p>}
    {dirty && <aside className="rd-workspace-draft-notice"><div><strong>当前填写尚未保存</strong><p id="rd-workspace-dirty-help">有未保存的资源填写。保存或取消后可切换固定版本及办理发布、授权。</p></div><Button type="default" size="small" htmlType="button" className="rd-button compact" onClick={focusEditor} disabled={busy}>定位填写区</Button></aside>}
    <div className={`rd-workspace-layout${session?.can_edit_resources ? '' : ' is-readonly'}`}>
      <section className="rd-section" aria-label={canManage ? '资源管理目录' : '当前应用获准目录'}><div className="rd-section-head"><h2>{canManage ? '资源管理目录' : '当前应用获准目录'}</h2><span className="rd-badge">{result?.total ?? 0} 项</span></div>
        <div className="rd-workspace-tools"><div className="rd-search"><label htmlFor="workspace-search" className="rd-visually-hidden">搜索资源</label><input id="workspace-search" ref={search} type="search" value={directory.input} onCompositionStart={() => directory.setComposing(true)} onCompositionEnd={event => { directory.setComposing(false); directory.setInput(event.currentTarget.value); }} onChange={event => directory.setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing && !directory.composing) { event.preventDefault(); directory.commit(); } }} />{directory.input && <button type="button" aria-label="清空资源搜索" onClick={() => { directory.commit(''); search.current?.focus(); }}>×</button>}</div><StyledSelect aria-label="资源目录类型" value={state.kind} onChange={value => update({ kind: value, item: '', version: '' })} options={[{ value: '', label: '全部类型' }, { value: 'agent', label: 'Agent' }, { value: 'skill', label: 'Skill' }, { value: 'team', label: '团队' }]} /></div>
        {loading && <p className="rd-loading" role="status">正在读取资源目录…</p>}
        {!loading && <div className="rd-resource-list">{result?.items.map(resource => <article key={`${resource.id}@${resource.version}`}><div className="rd-section-head"><div><span className="rd-eyebrow">{{ agent: 'Agent', skill: 'Skill', team: '团队' }[resource.kind]} · v{resource.version}</span><h3>{resource.name}</h3></div><span className={`rd-badge ${resource.status ?? 'draft'}`}>{statusTitle(resource.status)}</span></div><p>{resource.description || '未填写说明'}</p><p className="rd-muted">{resource.executable ? '已绑定执行能力' : '仅保存定义，尚未绑定执行器'}</p><code>{resource.id}</code><Button type="link" htmlType="button" className="rd-link-button" disabled={busy || dirty} onClick={() => update({ item: resource.id, version: String(resource.version) }, false)}>查看固定版本</Button></article>)}</div>}
        {!loading && !error && !result?.total && <p className="rd-empty-inline">{state.q ? '没有匹配的资源，请调整关键词。' : '当前目录没有可读取的资源。'}</p>}
        <div className="rd-flow-directory-footer"><span>{result?.total ?? 0} 项 · 第 {page} / {Math.max(1, result?.total_pages ?? 1)} 页 · 每页 5 项</span><div><Button type="default" size="small" htmlType="button" className="rd-button compact" disabled={loading || busy || page <= 1} onClick={() => update({ page: String(page - 1) }, false)}>上一页</Button><Button type="default" size="small" htmlType="button" className="rd-button compact" disabled={loading || busy || page >= (result?.total_pages ?? 1)} onClick={() => update({ page: String(page + 1) }, false)}>下一页</Button></div></div>
        {detailLoading && <p role="status">正在读取固定版本…</p>}
        {detail && <div className="rd-resource-detail"><h3>{detail.name} · v{detail.version}</h3>{!!detailVersions.length && <StyledSelect aria-label="查看固定版本" value={String(detail.version)} disabled={busy || dirty} options={detailVersions.map(version => ({ value: String(version), label: `固定版本 v${version}` }))} onChange={version => update({ version }, false)} />}<p>{detail.description}</p><p className="rd-muted">{detail.executable ? '已绑定执行能力，仍受许可和固定版本检查。' : '尚未绑定执行器；团队成员引用不会自动接通执行能力。'}</p>
          {managedDetail && <><p>资源整体状态：{managedDetail.resource_retired ? '已停用，所有版本暂停' : '未整体停用'} · 控制修订 {managedDetail.control_revision}</p><p>固定版状态：{statusTitle(managedDetail.status)} · 状态修订 {managedDetail.publication_revision ?? managedDetail.state_revision}</p><p>当前应用授权记录：{managedDetail.grant?.expires_at && Date.parse(managedDetail.grant.expires_at) <= Date.now() ? '已到期' : managedDetail.grant?.status === 'active' || managedDetail.grant?.status === 'granted' ? '已授予' : managedDetail.grant?.status === 'revoked' ? '已撤销' : '未授予'}{managedDetail.grant?.expires_at ? ` · 失效时间 ${new Date(managedDetail.grant.expires_at).toLocaleString('zh-CN')}` : ''} · 授权修订 {managedDetail.grant?.revision ?? 0}</p>{managedDetail.kind === 'team' && <details className="rd-disclosure"><summary>查看团队组成与内部图</summary><TeamConfiguration configuration={managedDetail.configuration} resources={result?.items} /></details>}<details className="rd-disclosure"><summary>查看资源配置</summary><pre>{readable(managedDetail.configuration)}</pre></details><div className="rd-inline-actions" aria-describedby={dirty ? "rd-workspace-dirty-help" : undefined}>{session?.can_edit_resources && <Button type="default" size="small" htmlType="button" className="rd-button compact" disabled={busy || dirty} onClick={() => loadIntoForm(managedDetail)}>编辑资源</Button>}{session?.can_publish_resources && <><Button type="default" size="small" htmlType="button" className="rd-button compact" disabled={busy || dirty || (managedDetail.status === 'published' && !managedDetail.resource_retired)} onClick={() => setConfirm({ resource: managedDetail, operation: 'publish' })}>{operationTitle('publish', managedDetail)}</Button><Button type="default" danger size="small" htmlType="button" className="rd-button compact danger" disabled={busy || dirty || managedDetail.resource_retired} onClick={() => setConfirm({ resource: managedDetail, operation: 'retire' })}>停用资源</Button></>}{session?.can_manage_application_grants && <><Button type="default" size="small" htmlType="button" className="rd-button compact" disabled={busy || dirty || managedDetail.resource_retired || managedDetail.status !== 'published'} onClick={() => setConfirm({ resource: managedDetail, operation: 'grant' })}>授予应用</Button><Button type="default" danger size="small" htmlType="button" className="rd-button compact danger" disabled={busy || dirty || !managedDetail.grant || !['granted', 'active'].includes(managedDetail.grant.status)} onClick={() => setConfirm({ resource: managedDetail, operation: 'revoke' })}>撤销授权</Button></>}</div>{session?.can_manage_application_grants && grantHint && <p className="rd-muted rd-resource-action-help">{grantHint}</p>}</>}
        </div>}
      </section>
      {session?.can_edit_resources && <section className="rd-section rd-resource-editor" aria-label={editing ? '编辑资源填写区' : '新建资源填写区'}>
        <div className="rd-section-head"><h2>{editing ? '编辑资源' : '新建资源'}</h2><span className={`rd-badge ${dirty ? 'draft' : ''}`}>{dirty ? '有未保存修改' : editing ? `基于 v${editing.version}` : '填写后保存草稿'}</span></div>
        <p className="rd-muted rd-resource-editor-intro">{editing ? `正在编辑“${editing.name}”。保存后形成新草稿版本。` : '先填写名称与用途，再配置执行能力。'}</p>
        <form noValidate onSubmit={submit} onKeyDown={event => { if (event.key === 'Enter' && event.nativeEvent.isComposing) event.preventDefault(); }}>
          <div className="rd-field"><label id="rd-resource-kind-label">资源类型</label><StyledSelect aria-labelledby="rd-resource-kind-label" value={kind} onChange={setKind} disabled={busy || !!editing} options={[{ value: 'agent', label: 'Agent' }, { value: 'skill', label: 'Skill' }, { value: 'team', label: '团队' }]} /></div>
          <div className="rd-field"><label htmlFor="rd-resource-name">资源名称 <span className="rd-muted">（必填）</span></label><input id="rd-resource-name" aria-label="资源名称" maxLength={200} value={name} onChange={event => { setName(event.target.value); if (fieldError === 'name') { setFieldError(null); setError(''); } }} disabled={busy} aria-invalid={fieldError === 'name'} aria-describedby={fieldError === 'name' ? 'rd-resource-name-error' : undefined} />{fieldError === 'name' && <small id="rd-resource-name-error" className="rd-field-error">{error}</small>}</div>
          <div className="rd-field"><label htmlFor="rd-resource-description">用途说明</label><textarea id="rd-resource-description" className="resize-none" rows={3} maxLength={10000} value={description} onChange={event => setDescription(event.target.value)} disabled={busy} /></div>
          {kind === 'team' && (() => { try { const config = JSON.parse(configuration); if (!config || typeof config !== 'object' || Array.isArray(config)) throw new Error(); return <TeamConfiguration configuration={config} resources={result?.items} disabled={busy} onChange={value => { setConfiguration(JSON.stringify(value, null, 2)); setFieldError(null); setError(''); }} />; } catch { return <p className="rd-notice">团队配置暂时无法显示，请在高级配置中修正 JSON。当前填写已保留。</p>; } })()}
          {kind === 'team' ? <details className="rd-disclosure rd-resource-advanced" open={configOpen} onToggle={event => setConfigOpen(event.currentTarget.open)}><summary>高级配置（JSON）</summary><p className="rd-muted">与上方团队组成及画布使用同一份配置，按需查看或修改。</p>{configField}</details> : configField}
          <p className="rd-muted" id="rd-resource-save-help">{conflict ? '请先读取最新修订，再核对并保存。' : dirty ? '保存后可继续办理发布与应用授权。' : editing ? '当前没有未保存修改。' : '填写资源内容后即可保存。'}</p>
          <div className="rd-resource-form-feedback">{error && !fieldError && !confirm && <p className="rd-error">{error}</p>}</div><div className="rd-actions"><Button type="default" htmlType="button" className="rd-button" disabled={busy} onClick={() => dirty ? setDiscard(true) : clearForm()}>{editing ? '取消编辑' : '清空填写'}</Button><Button type="primary" htmlType="submit" className="rd-button primary" aria-describedby="rd-resource-save-help" disabled={busy || !dirty || !!conflict}>{busy ? '正在保存…' : '保存资源'}</Button></div>
        </form>
      </section>}
    </div>
    <WorkspaceContracts />
    {confirm && <FeedbackConfirmDialog title={operationTitle(confirm.operation, confirm.resource)} confirm={operationTitle(confirm.operation, confirm.resource)} danger={confirm.operation === 'retire' || confirm.operation === 'revoke'} pending={busy} error={error} onCancel={() => { setConfirm(null); setError(''); }} onConfirm={() => void mutate(confirm.operation, confirm.resource)}><p>{confirm.operation === 'retire' ? `将整体停用“${confirm.resource.name}”的所有版本。` : `将对“${confirm.resource.name}”固定版本 v${confirm.resource.version}办理${operationTitle(confirm.operation, confirm.resource)}。`}</p><p>{confirm.operation === 'publish' ? confirm.resource.resource_retired ? '此操作将解除资源整体停用；已发布且具有有效授权的其他版本也会恢复可用。未授权应用仍须分别授予，项目已采用版本保持不变。' : '发布不会自动向应用授权；项目已采用版本保持不变。' : confirm.operation === 'retire' ? '此操作将整体停用资源，所有版本暂停新读取和执行；历史成果保留。' : confirm.operation === 'grant' ? `授权目标为当前应用 ${session?.application_id}，本次不设置失效时间；成员许可由服务端核验。` : '新读取和执行将重新核验有效许可；已完成成果保留。'}</p></FeedbackConfirmDialog>}
    {discard && <FeedbackConfirmDialog title="放弃资源填写" confirm="放弃填写" cancel="继续编辑" onCancel={() => setDiscard(false)} onConfirm={clearForm}><p>当前未保存的资源字段与配置将清空。</p></FeedbackConfirmDialog>}
  </div>;
}
