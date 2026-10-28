/** Service settings follow the sister platforms' dialog, defaults and persistence behavior. */
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import {
  requestServiceCredentials, changeCredentialHistory, type CredentialHistoryEntry, type CredentialGroup, type CredentialOverrides,
  type CredentialValues, type ServiceCredentialsResponse,
} from '../api/serviceCredentials';
import { ModelConnectionTest } from './ModelConnectionTest';
import { StyledSelect } from '../../../shared/ui/StyledSelect';
import { PlatformAuthSettings } from './PlatformAuthSettings';
import './serviceCredentials.css';

interface Field { key: string; label: string; url?: boolean; secret?: boolean }
const baseUrl: Field = { key: 'base_url', label: '服务地址（Base URL）', url: true };
const apiKey: Field = { key: 'api_key', label: 'API Key', secret: true };
const groups: { key: CredentialGroup; label: string; description: string; fields: Field[] }[] = [
  { key: 'model', label: '模型', description: '用于模型目录、需求语义分类与路由。模型名称仍以服务真实返回为准。',
    fields: [baseUrl, { key: 'app_id', label: '应用 ID（App ID）' }, apiKey, { key: 'tenant_id', label: '租户 ID（Tenant ID）' }] },
];
const emptyValues = (): CredentialValues => ({ model: {} });
const payloadFor = (draft: CredentialValues, overridden: CredentialGroup[]): CredentialOverrides => ({
  model: overridden.includes('model') ? draft.model : null,
});
const historyTime = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
};
const historyHost = (value: string) => {
  try { return new URL(value).host; } catch { return value; }
};

export function ServiceCredentialsSettings({ onSaved }: { onSaved: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return <>
    <button ref={trigger} className="credentials-trigger" type="button" title="服务凭证设置"
      aria-label="服务凭证设置" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="m9.5 3-.6 2.1-1.8 1-2.1-.5-2.5 4.3L4 11.5v2L2.5 15 5 19.3l2.1-.5 1.8 1 .6 2.2h5l.6-2.2 1.8-1 2.1.5 2.5-4.3-1.5-1.5v-2l1.5-1.6L19 5.6l-2.1.5-1.8-1-.6-2.1h-5Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
        <circle cx="12" cy="12.5" r="3" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    </button>
    {open && createPortal(<CredentialsDialog onClose={() => {
      setOpen(false);
      trigger.current?.focus();
    }} onSaved={onSaved} />, document.body)}
  </>;
}

function CredentialsDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const requestController = useRef<AbortController>();
  const loadVersion = useRef(0);
  const alive = useRef(true);
  const mutationPending = useRef(false);
  const active: CredentialGroup = 'model';
  const [defaults, setDefaults] = useState<CredentialValues>(emptyValues);
  const [draft, setDraft] = useState<CredentialValues>(emptyValues);
  const [overridden, setOverridden] = useState<CredentialGroup[]>([]);
  const [revealed, setRevealed] = useState<CredentialGroup[]>([]);
  const [baseline, setBaseline] = useState('');
  const [loading, setLoading] = useState(true);
  const [pendingAction, setPendingAction] = useState<'save' | 'activate' | 'delete' | null>(null);
  const saving = pendingAction !== null;
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [history, setHistory] = useState<CredentialHistoryEntry[]>([]);
  const [selectedHistoryId, setSelectedHistoryId] = useState('');
  const [confirmHistory, setConfirmHistory] = useState<{ id: string; action: 'activate' | 'delete' } | null>(null);
  const [probeVersion, setProbeVersion] = useState(0);
  const selectedHistory = history.find(item => item.id === selectedHistoryId);
  const busy = loading || saving;
  const dirty = loaded && JSON.stringify(payloadFor(draft, overridden)) !== baseline;
  const group = groups.find(item => item.key === active)!;

  function accept(result: ServiceCredentialsResponse) {
    setProbeVersion(value => value + 1);
    setDefaults(result.defaults);
    setDraft(result.effective);
    setOverridden(result.overridden);
    setBaseline(JSON.stringify(payloadFor(result.effective, result.overridden)));
    setHistory(result.history);
    setSelectedHistoryId(result.history.find(item => item.active)?.id || result.history[0]?.id || '');
    setConfirmDiscard(false);
    setConfirmHistory(null);
    setLoaded(true);
  }

  async function withRequest(request: (signal: AbortSignal) => Promise<ServiceCredentialsResponse>) {
    const controller = new AbortController();
    requestController.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 20000);
    try {
      return await request(controller.signal);
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function requestError(reason: unknown) {
    return reason instanceof Error && reason.name !== 'AbortError'
      ? reason.message : '请求超时，请重试加载，确认服务端是否已保存。';
  }

  async function load() {
    const version = ++loadVersion.current;
    setLoading(true);
    setError('');
    try {
      const result = await withRequest(signal => requestServiceCredentials(undefined, signal));
      if (alive.current && version === loadVersion.current) accept(result);
    } catch (reason) {
      if (alive.current && version === loadVersion.current) setError(requestError(reason));
    } finally {
      if (alive.current && version === loadVersion.current) setLoading(false);
    }
  }

  useEffect(() => {
    alive.current = true;
    const element = dialog.current!;
    element.showModal();
    void load();
    return () => {
      alive.current = false;
      loadVersion.current += 1;
      requestController.current?.abort();
      element.close();
    };
  }, []);

  function close() {
    if (saving) return;
    setProbeVersion(value => value + 1);
    if (dirty) setConfirmDiscard(true);
    else dismiss();
  }

  function dismiss() {
    dialog.current?.close();
    onClose();
  }

  function edited(field: string, value: string) {
    setProbeVersion(previous => previous + 1);
    setDraft(previous => ({ ...previous, [active]: { ...previous[active], [field]: value } }));
    setOverridden(previous => previous.includes(active) ? previous : [...previous, active]);
    setError('');
    setSuccess('');
    setConfirmDiscard(false);
    setConfirmHistory(null);
  }

  function restore() {
    setProbeVersion(value => value + 1);
    setDraft(previous => ({ ...previous, [active]: { ...defaults[active] } }));
    setOverridden(previous => previous.filter(key => key !== active));
    setError('');
    setSuccess('');
    setConfirmDiscard(false);
    setConfirmHistory(null);
  }

  async function save() {
    if (busy || mutationPending.current || !dirty) return;
    setProbeVersion(value => value + 1);
    const outgoing = payloadFor(draft, overridden);
    for (const item of groups) {
      const values = outgoing[item.key];
      if (values && item.fields.some(field => !values[field.key]?.trim())) {
        setError(`请完整填写“${item.label}”凭证，或选择恢复本组默认。`);
        return;
      }
    }
    setError('');
    setSuccess('');
    setConfirmHistory(null);
    mutationPending.current = true;
    setPendingAction('save');
    try {
      const result = await withRequest(signal => requestServiceCredentials(outgoing, signal));
      if (!alive.current) return;
      accept(result);
      setRevealed([]);
      setSuccess('已保存。凭证已记入历史，新发起的模型请求将使用此配置。');
      await onSaved();
    } catch (reason) {
      if (alive.current) setError(requestError(reason));
    } finally {
      mutationPending.current = false;
      if (alive.current) setPendingAction(null);
    }
  }

  async function changeHistory(action: 'activate' | 'delete', confirmed = false) {
    if (busy || mutationPending.current || !selectedHistory || selectedHistory.active) return;
    if (!confirmed && (action === 'delete' || dirty)) {
      setConfirmHistory({ id: selectedHistory.id, action });
      setConfirmDiscard(false);
      setError('');
      setSuccess('');
      return;
    }
    const target = selectedHistory;
    setProbeVersion(value => value + 1);
    mutationPending.current = true;
    setPendingAction(action);
    setError('');
    setSuccess('');
    setConfirmHistory(null);
    try {
      const result = await withRequest(signal => changeCredentialHistory(target.id, action, signal));
      if (!alive.current) return;
      if (action === 'activate') {
        accept(result);
        setRevealed([]);
        setSuccess(`已切换到“${target.name}”，后续模型请求将使用此凭证。`);
        await onSaved();
      } else {
        setHistory(result.history);
        setSelectedHistoryId(result.history.find(item => item.active)?.id || result.history[0]?.id || '');
        setSuccess(`已删除“${target.name}”的历史记录。当前使用的凭证未变更。`);
      }
    } catch (reason) {
      if (alive.current) setError(requestError(reason));
    } finally {
      mutationPending.current = false;
      if (alive.current) setPendingAction(null);
    }
  }

  function keepDialogFocus(event: KeyboardEvent) {
    if (event.key !== 'Tab' || !dialog.current) return;
    const controls = Array.from(dialog.current.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]',
    )).filter(element => element.tabIndex >= 0 && element.getClientRects().length > 0);
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }

  return <dialog ref={dialog} className="credentials-dialog" aria-labelledby="credentials-title"
    aria-describedby="credentials-scope" onKeyDown={keepDialogFocus}
    onCancel={event => { event.preventDefault(); close(); }}>
    <form className="credentials-form" noValidate onSubmit={event => { event.preventDefault(); void save(); }}>
      <header className="credentials-header">
        <div><h2 id="credentials-title">服务凭证设置</h2><p id="credentials-scope">对当前研制任务书平台生效，保存后自动刷新模型列表。</p></div>
        <button className="credentials-close" type="button" aria-label="关闭凭证设置" disabled={saving} onClick={close}>
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
        </button>
      </header>
      <div className="credentials-tabs" role="tablist" aria-label="模型服务">
        {groups.map(item => <button key={item.key} id={`credentials-tab-${item.key}`} type="button"
          role="tab" aria-selected={active === item.key} aria-controls={`credentials-panel-${item.key}`}
          tabIndex={0}>{item.label}</button>)}
      </div>
      <div className="credentials-body" aria-busy={busy}>
        <div className="auth-settings-entry"><p>登录入口和回跳地址在统一登录设置中单独保存。</p><PlatformAuthSettings disabled={saving} /></div>
        {loading && <p className="credentials-notice" role="status">正在读取已保存的配置与部署默认凭证…</p>}
        {error && <div className="credentials-error" role="alert"><p>{error}</p>
          {!loaded && !loading && <button type="button" onClick={() => void load()}>重新加载</button>}
        </div>}
        {success && <p className="credentials-success" role="status">{success}</p>}
        {loaded && !loading && <section id={`credentials-panel-${active}`} role="tabpanel"
          aria-labelledby={`credentials-tab-${active}`} tabIndex={0}>
          <section className="credentials-history" aria-labelledby="credentials-history-title">
            <h3 id="credentials-history-title">历史凭证</h3>
            {history.length > 0 ? <>
              <label id="credentials-history-picker-label" className="credentials-history-label"
                htmlFor="credentials-history-picker">选择已保存的环境</label>
              <StyledSelect id="credentials-history-picker" className="credentials-history-select"
                value={selectedHistoryId} disabled={saving}
                aria-labelledby="credentials-history-picker-label"
                options={history.map(item => {
                  const label = `${item.name} · ${historyHost(item.base_url)}${item.active ? '（当前使用）' : ''}`;
                  return { value: item.id, label, title: label };
                })}
                onChange={value => {
                  setSelectedHistoryId(value);
                  setConfirmHistory(null);
                  setError('');
                  setSuccess('');
                }} />
              {selectedHistory && <>
                <dl className="credentials-history-details">
                  <div className="credentials-history-address"><dt>服务地址</dt><dd>{selectedHistory.base_url}</dd></div>
                  <div><dt>App ID</dt><dd>{selectedHistory.app_id}</dd></div>
                  <div><dt>租户 ID</dt><dd>{selectedHistory.tenant_id}</dd></div>
                  <div className="credentials-history-address"><dt>{selectedHistory.last_used_at ? '最近使用' : '添加时间'}</dt>
                    <dd>{historyTime(selectedHistory.last_used_at || selectedHistory.created_at)}</dd></div>
                </dl>
                <div className="credentials-history-actions">
                  <button className="credentials-history-activate" type="button" disabled={saving || selectedHistory.active}
                    onClick={() => void changeHistory('activate')}>
                    {pendingAction === 'activate' ? '正在切换…' : selectedHistory.active ? '当前使用' : '使用此凭证'}
                  </button>
                  <button className="credentials-history-delete" type="button" disabled={saving || selectedHistory.active}
                    onClick={() => void changeHistory('delete')}>{pendingAction === 'delete' ? '正在删除…' : '删除记录'}</button>
                </div>
                {confirmHistory?.id === selectedHistory.id && <div className="credentials-discard" role="alert">
                  <p>{confirmHistory.action === 'activate'
                    ? `当前表单有未保存的修改。切换到“${selectedHistory.name}”将放弃这些修改。`
                    : `删除“${selectedHistory.name}”后，需要重新填写凭证才能再次使用。是否删除这条历史记录？`}</p>
                  <button type="button" onClick={() => setConfirmHistory(null)}>取消</button>
                  <button type="button" onClick={() => void changeHistory(confirmHistory.action, true)}>
                    {confirmHistory.action === 'activate' ? '放弃修改并切换' : '确认删除'}
                  </button>
                </div>}
              </>}
              <p className="credentials-history-hint">选择记录后，点击“使用此凭证”立即切换并刷新模型列表。</p>
            </> : <p className="credentials-history-hint">尚无历史记录。保存凭证后可在这里快速切换。</p>}
          </section>
          <div className="credentials-section-head">
            <span>{overridden.includes(active) ? '当前使用自定义凭证' : '当前使用部署默认凭证'}</span>
            <button type="button" disabled={saving || !overridden.includes(active)} onClick={restore}>恢复本组默认</button>
          </div>
          <p className="credentials-description">{group.description}</p>
          <div className="credentials-fields">
            {group.fields.map(field => <div key={field.key} className={`credentials-field ${field.url || field.secret ? 'credentials-field-wide' : ''}`}>
              <label htmlFor={`credential-${active}-${field.key}`}>{field.label}</label>
              <div className="credentials-input-row">
                <input id={`credential-${active}-${field.key}`} value={draft[active][field.key] || ''}
                  type={field.secret && !revealed.includes(active) ? 'password' : field.url ? 'url' : 'text'}
                  disabled={saving} autoComplete={field.secret ? 'new-password' : 'off'} spellCheck={false}
                  autoCapitalize="none" maxLength={4096}
                  onChange={event => edited(field.key, event.target.value)} />
                {field.secret && <button type="button" aria-label={`${revealed.includes(active) ? '隐藏' : '显示'}${field.label}`}
                  aria-pressed={revealed.includes(active)} onClick={() => setRevealed(previous => previous.includes(active)
                    ? previous.filter(key => key !== active) : [...previous, active])}>{revealed.includes(active) ? '隐藏' : '显示'}</button>}
              </div>
            </div>)}
          </div>
          <p className="credentials-hint">默认值来自服务端部署配置。敏感字段可点击“显示”查看；不会写入浏览器本地存储。</p>
          <ModelConnectionTest key={probeVersion} credentials={payloadFor(draft, overridden)} disabled={busy} />
        </section>}
        {confirmDiscard && <div className="credentials-discard" role="alert"><p>尚有未保存的修改，是否放弃？</p>
          <button type="button" onClick={() => setConfirmDiscard(false)}>继续编辑</button>
          <button type="button" onClick={dismiss}>放弃修改</button>
        </div>}
      </div>
      <footer className="credentials-footer"><span aria-live="polite">{dirty ? '有未保存的修改' : '保存不执行研制任务书生成'}</span>
        <div><button type="button" disabled={saving} onClick={close}>{dirty ? '取消' : '关闭'}</button>
          <button className="credentials-save" type="submit" disabled={busy || !loaded || !dirty}>{pendingAction === 'save' ? '正在保存…' : '保存凭证'}</button>
        </div>
      </footer>
    </form>
  </dialog>;
}
