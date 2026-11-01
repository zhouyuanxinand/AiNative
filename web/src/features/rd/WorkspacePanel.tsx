import { useEffect, useRef, useState, type FormEvent } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { useApplicationLeaveGuard } from '../../hooks/useApplicationLeaveGuard';
import { RdApiError, makeRequestKey, rdResourceSave, rdResources } from './api';
import { messageOf, readable, statusTitle } from './presentation';
import type { Catalog, WorkspaceResource } from './types';
import { WorkspaceContracts } from './WorkspaceContracts';
import './workspacePanel.css';

export function WorkspacePanel({ catalog, onDirtyChange, onBusyChange }: { catalog: Catalog | null; onDirtyChange: (dirty: boolean) => void; onBusyChange: (busy: boolean) => void }) {
  const [resources, setResources] = useState<WorkspaceResource[]>([]);
  const [canManage, setCanManage] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState<WorkspaceResource | null>(null);
  const [kind, setKind] = useState('agent');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [configuration, setConfiguration] = useState('{}');
  const [base, setBase] = useState(JSON.stringify(['agent', '', '', '{}']));
  const [confirm, setConfirm] = useState<{ operation: 'publish' | 'retire'; resource: WorkspaceResource } | null>(null);
  const [discard, setDiscard] = useState(false);
  const [conflict, setConflict] = useState(false);
  const rebaseOnRefresh = useRef(false);
  const inFlight = useRef(false);
  const retry = useRef({ fingerprint: '', key: '' });
  const newResourceId = useRef(makeRequestKey());
  const dirty = JSON.stringify([kind, name, description, configuration]) !== base;
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);
  useApplicationLeaveGuard({ dirty, busyMessage: busy ? '资源保存尚未完成，请等待结果后再离开。' : undefined });
  useEffect(() => {
    const controller = new AbortController(); setLoading(true);
    void rdResources(controller.signal).then(response => {
      if (!controller.signal.aborted) {
        setResources(response.resources); setCanManage(response.can_manage === true); setLoading(false); setError('');
        if (rebaseOnRefresh.current) {
          setEditing(current => response.resources.find(resource => resource.id === (current?.id ?? newResourceId.current)) ?? current);
          rebaseOnRefresh.current = false; setConflict(false); setNotice('已读取资源最新版本，填写内容继续保留。请核对后重新保存。');
        }
      }
    }).catch(reason => { if (!controller.signal.aborted) { setError(messageOf(reason)); setLoading(false); } });
    return () => controller.abort();
  }, [revision]);
  const loadIntoForm = (resource: WorkspaceResource) => {
    const values = [resource.kind, resource.name, resource.description ?? '', JSON.stringify(resource.configuration ?? {}, null, 2)] as const;
    setEditing(resource); setKind(values[0]); setName(values[1]); setDescription(values[2]); setConfiguration(values[3]); setBase(JSON.stringify(values)); setError('');
  };
  const clearForm = () => { setEditing(null); newResourceId.current = makeRequestKey(); setKind('agent'); setName(''); setDescription(''); setConfiguration('{}'); setBase(JSON.stringify(['agent', '', '', '{}'])); setDiscard(false); };
  async function save(operation = 'save', resource?: WorkspaceResource) {
    if (inFlight.current || !canManage) return;
    let config: Record<string, unknown>;
    try { const value: unknown = JSON.parse(resource ? JSON.stringify(resource.configuration) : configuration); if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(); config = value as Record<string, unknown>; }
    catch { setError('资源配置必须是 JSON 对象，请检查括号和字段格式。'); document.getElementById('rd-resource-configuration')?.focus(); return; }
    if (!resource && !name.trim()) { setError('请填写资源名称。'); document.getElementById('rd-resource-name')?.focus(); return; }
    const target = resource ?? editing;
    const payload = { id: target?.id ?? newResourceId.current, ...(target ? { expected_version: target.version } : {}), kind: (resource?.kind ?? kind) as WorkspaceResource['kind'], name: resource?.name ?? name, description: resource?.description ?? description, configuration: config, operation };
    const fingerprint = JSON.stringify(payload);
    if (retry.current.fingerprint !== fingerprint) retry.current = { fingerprint, key: makeRequestKey() };
    inFlight.current = true; setBusy(true); setError(''); setNotice(''); setConflict(false);
    try {
      await rdResourceSave(payload, retry.current.key);
      retry.current = { fingerprint: '', key: '' };
      setNotice(operation === 'publish' ? '资源已发布；执行仍受动作绑定与版本校验约束。' : operation === 'retire' ? '资源已停用。' : '资源已保存。');
      setConfirm(null); clearForm(); setRevision(value => value + 1);
    } catch (reason) {
      setError(messageOf(reason)); setConflict(reason instanceof RdApiError && reason.status === 409); if (reason instanceof RdApiError && reason.status === 403) setCanManage(false);
    } finally { inFlight.current = false; setBusy(false); }
  }
  function submit(event: FormEvent) { event.preventDefault(); void save(); }
  return <div className="rd-page-content rd-workspace-page"><div className="rd-page-title"><div><span className="rd-eyebrow">与研发平台同部署</span><h1>本地 Workspace</h1><p>管理 Agent、Skill 与团队资源；发布版本与工作包实际执行使用同一身份。</p></div><button className="rd-button" disabled={loading || busy} onClick={() => setRevision(value => value + 1)}>刷新资源</button></div>
    {error && <div className="rd-error rd-banner" role="alert"><p>{error}</p>{conflict && <><p>资源版本发生变化；当前填写保留。</p><button className="rd-button" disabled={busy || loading} onClick={() => { rebaseOnRefresh.current = true; setRevision(value => value + 1); }}>读取最新版本并保留填写</button></>}</div>}{notice && <p className="rd-success rd-banner" role="status">{notice}</p>}
    {loading && <p className="rd-loading" role="status">正在读取本地资源…</p>}
    {!loading && !canManage && <p className="rd-notice">当前为只读。资源写入由服务端验证本地模式或已授权管理员身份；权限失败不会显示成保存成功。</p>}
    <div className={`rd-workspace-layout${canManage ? '' : ' is-readonly'}`}><section className="rd-section"><div className="rd-section-head"><h2>资源目录</h2><span className="rd-badge">{resources.length} 项</span></div>{resources.length ? <div className="rd-resource-list">{resources.map(resource => <article key={resource.id}><div className="rd-section-head"><div><span className="rd-eyebrow">{{ agent: 'Agent', skill: 'Skill', team: '团队' }[resource.kind]} · v{resource.version}</span><h3>{resource.name}</h3></div><span className={`rd-badge ${resource.status ?? 'draft'}`}>{statusTitle(resource.status)}</span></div><p>{resource.description || '未填写说明'}</p><p className="rd-muted">{resource.execution_mode === 'contract_example' ? '契约示例，不可作为真实证据' : resource.execution_mode === 'remote_real' ? '远端真实执行模式' : resource.execution_mode === 'local_real' ? '本地真实执行模式' : '未绑定执行模式'} · {resource.executable ? '已绑定执行能力' : '未绑定执行能力'}</p><code>{resource.id}</code><details className="rd-disclosure"><summary>查看资源配置</summary><pre>{readable(resource.configuration)}</pre></details>{canManage && <div className="rd-inline-actions"><button className="rd-button compact" disabled={busy || dirty} onClick={() => loadIntoForm(resource)}>编辑资源</button>{resource.status !== 'published' && <button className="rd-button compact" disabled={busy || dirty} onClick={() => setConfirm({ resource, operation: 'publish' })}>发布版本</button>}{resource.status !== 'retired' && <button className="rd-button compact danger" disabled={busy || dirty} onClick={() => setConfirm({ resource, operation: 'retire' })}>停用资源</button>}</div>}</article>)}</div> : !loading && <p className="rd-empty-inline">没有可读取的本地资源。可刷新重试，或由资源管理员建立资源。</p>}</section>
    {canManage && <section className="rd-section"><div className="rd-section-head"><div><span className="rd-eyebrow">资源管理员</span><h2>{editing ? '编辑资源' : '新建资源'}</h2></div>{editing && <span className="rd-badge">基于 v{editing.version}</span>}</div><form noValidate onSubmit={submit}><div className="rd-field"><label id="rd-resource-kind-label">资源类型</label><StyledSelect aria-labelledby="rd-resource-kind-label" value={kind} onChange={setKind} disabled={busy || !!editing} options={[{ value: 'agent', label: 'Agent' }, { value: 'skill', label: 'Skill' }, { value: 'team', label: '团队' }]} /></div><div className="rd-field"><label htmlFor="rd-resource-name">资源名称</label><input id="rd-resource-name" value={name} onChange={event => setName(event.target.value)} disabled={busy} /></div><div className="rd-field"><label htmlFor="rd-resource-description">用途说明</label><textarea id="rd-resource-description" className="resize-none" rows={3} value={description} onChange={event => setDescription(event.target.value)} disabled={busy} /></div><div className="rd-field"><label htmlFor="rd-resource-configuration">资源配置（JSON）</label><textarea id="rd-resource-configuration" className="resize-none rd-code-input" rows={10} value={configuration} onChange={event => setConfiguration(event.target.value)} disabled={busy} /><small>保存定义不会自动获得可执行能力。执行绑定、模式及版本由服务端核验。</small></div><div className="rd-actions"><button type="button" className="rd-button" disabled={busy} onClick={() => dirty ? setDiscard(true) : clearForm()}>清空填写</button><button type="submit" className="rd-button primary" disabled={busy || !dirty}>{busy ? '正在保存…' : '保存资源'}</button></div></form></section>}</div>
    <section className="rd-section"><h2>已发布动作目录</h2><p className="rd-muted">以下版本来自服务端目录，计划节点引用相同动作身份。</p><div className="rd-action-catalog">{catalog?.actions.map(action => <article key={`${action.id}-${action.version}`}><strong>{action.title ?? action.name ?? action.id}</strong><code>{action.id} · v{action.version}</code><p>{action.description ?? '按固定输入执行，结果保留来源与证据。'}</p></article>)}</div></section>
    <WorkspaceContracts />
    {confirm && <FeedbackConfirmDialog title={confirm.operation === 'publish' ? '发布资源版本' : '停用资源'} confirm={confirm.operation === 'publish' ? '发布此版本' : '停用此资源'} danger={confirm.operation === 'retire'} pending={busy} error={error} onCancel={() => setConfirm(null)} onConfirm={() => void save(confirm.operation, confirm.resource)}><p>将{confirm.operation === 'publish' ? '发布' : '停用'}“{confirm.resource.name}”。工作包使用固定资源版本，失效版本会按执行规则阻塞。</p></FeedbackConfirmDialog>}
    {discard && <FeedbackConfirmDialog title="放弃资源填写" confirm="放弃填写" cancel="继续编辑" onCancel={() => setDiscard(false)} onConfirm={clearForm}><p>当前未保存的资源字段与配置将清空。</p></FeedbackConfirmDialog>}
  </div>;
}
