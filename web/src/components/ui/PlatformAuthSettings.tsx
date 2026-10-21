import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { createPortal } from 'react-dom';
import { AuthSettingsApiError, getAuthSettings, saveAuthSettings, type AuthSettingsResponse, type PlatformAuthConfig } from '../../api/authSettings';
import { StyledSelect } from './StyledSelect';
import './serviceCredentials.css';
import './platformAuthSettings.css';

interface Draft { enabled: boolean; app_id: string; platform_base_url: string; public_url: string; callback_mode: 'auto' | 'manual' }
type Field = 'app_id' | 'platform_base_url' | 'public_url';
const draftFor = (config: PlatformAuthConfig): Draft => ({ enabled: config.enabled, app_id: config.app_id === null ? '' : String(config.app_id), platform_base_url: config.platform_base_url, public_url: config.public_url || '', callback_mode: config.public_url ? 'manual' : 'auto' });
const draftSignature = (draft: Draft) => JSON.stringify({ ...draft, public_url: draft.callback_mode === 'auto' ? '' : draft.public_url });

export function PlatformAuthSettings({ disabled = false }: { disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return <>
    <button ref={trigger} type="button" className="auth-settings-trigger" disabled={disabled} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>统一登录设置</button>
    {open && createPortal(<AuthSettingsDialog onClose={() => {
      setOpen(false); requestAnimationFrame(() => trigger.current?.focus());
    }} />, document.body)}
  </>;
}

function AuthSettingsDialog({ onClose }: { onClose: () => void }) {
  const id = useId().replaceAll(':', '');
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const warning = useRef<HTMLDivElement>(null);
  const errorPanel = useRef<HTMLDivElement>(null);
  const inputs = useRef<Partial<Record<Field, HTMLInputElement | null>>>({});
  const request = useRef<AbortController>();
  const savingLock = useRef(false);
  const [response, setResponse] = useState<AuthSettingsResponse | null>(null);
  const [draft, setDraft] = useState<Draft>({ enabled: false, app_id: '', platform_base_url: '', public_url: '', callback_mode: 'auto' });
  const [baseline, setBaseline] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [invalid, setInvalid] = useState<Field | null>(null);
  const [conflict, setConflict] = useState(false);
  const [success, setSuccess] = useState('');
  const [confirm, setConfirm] = useState<'close' | 'reload' | null>(null);
  const dirty = !!response && draftSignature(draft) !== baseline;
  const busy = loading || saving;
  const editable = !!response?.can_edit;

  function accept(result: AuthSettingsResponse) {
    const next = draftFor(result.settings);
    setResponse(result); setDraft(next); setBaseline(draftSignature(next)); setInvalid(null); setConflict(false); setConfirm(null);
  }

  async function load() {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setLoading(true); setError(''); setSuccess(''); setConfirm(null);
    try {
      const result = await getAuthSettings(controller.signal);
      if (!controller.signal.aborted && request.current === controller) accept(result);
    } catch (reason) {
      if (!controller.signal.aborted && request.current === controller) setError(reason instanceof Error ? reason.message : '登录配置读取失败，请重试。');
    } finally {
      if (!controller.signal.aborted && request.current === controller) setLoading(false);
    }
  }

  useEffect(() => {
    const element = dialog.current!;
    element.showModal(); heading.current?.focus(); void load();
    return () => { request.current?.abort(); element.close(); };
  }, []);

  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [dirty]);

  useEffect(() => { if (confirm) warning.current?.focus(); }, [confirm]);

  function change<K extends keyof Draft>(field: K, value: Draft[K]) {
    setDraft(previous => ({ ...previous, [field]: value })); setError(''); setSuccess(''); setInvalid(null); setConfirm(null);
  }

  function applyPreset(name: keyof AuthSettingsResponse['presets']) {
    if (!response?.presets || !editable || busy) return;
    setDraft(previous => draftFor({ ...response.presets[name], enabled: previous.enabled }));
    setError(''); setSuccess(''); setInvalid(null); setConfirm(null);
  }

  function close() {
    if (savingLock.current) return;
    if (dirty) setConfirm('close'); else onClose();
  }

  function validationError(field: Field, message: string) {
    setInvalid(field); setError(message);
    requestAnimationFrame(() => inputs.current[field]?.focus());
    return null;
  }

  function values(): PlatformAuthConfig | null {
    const appId = draft.app_id.trim();
    if (!appId && draft.enabled) return validationError('app_id', '启用统一登录时，请填写登录应用 ID。');
    if (appId && (!/^\d+$/.test(appId) || !Number.isSafeInteger(Number(appId)) || Number(appId) <= 0)) {
      return validationError('app_id', '登录应用 ID 必须是正整数。');
    }
    const platform = draft.platform_base_url.trim();
    try {
      const url = new URL(platform);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || /\s/.test(platform)) throw new Error();
    } catch { return validationError('platform_base_url', '请填写有效的神州问学 HTTP(S) 地址，不要包含账号、查询参数或片段。'); }
    let callback = draft.callback_mode === 'manual' ? draft.public_url.trim() : '';
    if (!callback && draft.callback_mode === 'manual') return validationError('public_url', '手动指定时，请填写回跳地址；也可改为自动跟随访问地址。');
    if (callback) {
      try {
        const url = new URL(callback);
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/' || /\s/.test(callback)) throw new Error();
        callback = url.origin;
      } catch { return validationError('public_url', '回跳地址仅填写协议、主机和端口，不要包含路径、查询参数、片段或账号。'); }
    }
    return { enabled: draft.enabled, app_id: appId ? Number(appId) : null, platform_base_url: platform.replace(/\/+$/, ''), public_url: callback || null };
  }

  async function save(event: FormEvent) {
    event.preventDefault(); event.stopPropagation();
    if (!response || !editable || busy || savingLock.current || !dirty) return;
    const outgoing = values();
    if (!outgoing) return;
    savingLock.current = true; setSaving(true); setError(''); setSuccess(''); setConflict(false); setConfirm(null); setInvalid(null);
    const controller = new AbortController(); request.current = controller;
    try {
      const result = await saveAuthSettings(outgoing, response.version, controller.signal);
      if (!controller.signal.aborted && request.current === controller) { accept(result); setSuccess('已保存，重启平台后生效'); }
    } catch (reason) {
      if (!controller.signal.aborted && request.current === controller) {
        setError(reason instanceof Error ? reason.message : '登录配置未保存，请重试。');
        setConflict(reason instanceof AuthSettingsApiError && reason.status === 409);
        requestAnimationFrame(() => errorPanel.current?.focus());
      }
    } finally {
      savingLock.current = false;
      if (!controller.signal.aborted && request.current === controller) setSaving(false);
    }
  }

  function describedBy(field: Field) {
    return `${id}-${field}-hint${invalid === field ? ` ${id}-error` : ''}`;
  }

  return <dialog ref={dialog} className="credentials-dialog auth-settings-dialog" aria-labelledby={`${id}-title`} onKeyDown={event => event.stopPropagation()}
    onCancel={event => { event.preventDefault(); event.stopPropagation(); close(); }}>
    <form className="credentials-form" noValidate onSubmit={event => void save(event)}>
      <header className="credentials-header">
        <div><h2 ref={heading} tabIndex={-1} id={`${id}-title`}>统一登录设置</h2><p>配置神州问学统一登录，保存后需重启平台生效。</p></div>
        <button type="button" className="credentials-close" aria-label="关闭统一登录设置" disabled={saving} onClick={close}>
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
        </button>
      </header>
      <div className="credentials-body" aria-busy={busy}>
        {loading && <p className="credentials-notice" role="status">正在读取统一登录配置…</p>}
        {error && <div ref={errorPanel} tabIndex={-1} className="credentials-error" id={`${id}-error`} role="alert"><p>{error}</p>
          {conflict && <button type="button" disabled={busy} onClick={() => { if (dirty) setConfirm('reload'); else void load(); }}>读取最新配置</button>}
          {!response && !loading && <button type="button" onClick={() => void load()}>重试读取配置</button>}
        </div>}
        {success && <p className="credentials-success" role="status">{success}</p>}
        {response && <>
          <div className="auth-settings-active">
            <strong>{response.active ? response.active.enabled ? '当前生效：统一登录' : '当前生效：本地模式' : '当前生效配置请在主站查看'}</strong>
            {response.active?.enabled && <p>当前回跳地址：{response.active.public_url || '自动跟随主站访问地址'}</p>}
            {(!response.active || !response.active.enabled) && <p>未启用时本地可直接使用。启用后可自动跟随主站访问地址回跳。</p>}
            {response.requires_restart && <p>已保存的配置等待平台重启后生效。</p>}
          </div>
          {!editable && <p className="auth-settings-readonly" role="status">主站统一登录已启用，此处仅可查看配置。请通过反馈管理端口维护。</p>}
          <fieldset className="auth-settings-fields" disabled={busy || !editable}>
            <legend>下次启动使用的配置</legend>
            <label className="auth-settings-toggle" htmlFor={`${id}-enabled`}><input id={`${id}-enabled`} type="checkbox" checked={draft.enabled} onChange={event => change('enabled', event.target.checked)} /><span>启用统一登录</span></label>
            {response.presets && <div className="auth-settings-presets">
              <div className="credentials-history-actions">
                <button type="button" onClick={() => applyPreset('intranet')}>使用内网配置</button>
                <button type="button" onClick={() => applyPreset('external')}>使用外网配置</button>
              </div>
              <p className="auth-settings-field-hint">填写对应的应用 ID 和神州问学地址，并将回跳方式设为自动。启用状态保持不变，保存并重启后生效。</p>
            </div>}
            <div className="credentials-field"><label htmlFor={`${id}-app-id`}>登录应用 ID</label><div className="credentials-input-row">
              <input ref={element => { inputs.current.app_id = element; }} id={`${id}-app-id`} value={draft.app_id} inputMode="numeric" maxLength={16} autoComplete="off"
                required={draft.enabled} aria-invalid={invalid === 'app_id'} aria-describedby={describedBy('app_id')} onChange={event => change('app_id', event.target.value)} /></div>
              <p className="auth-settings-field-hint" id={`${id}-app_id-hint`}>用于统一登录，与模型应用 ID 分开配置。</p>
            </div>
            <div className="credentials-field"><label htmlFor={`${id}-platform-url`}>神州问学地址</label><div className="credentials-input-row">
              <input ref={element => { inputs.current.platform_base_url = element; }} id={`${id}-platform-url`} type="url" value={draft.platform_base_url} maxLength={2048} autoComplete="off" autoCapitalize="none" spellCheck={false}
                required aria-invalid={invalid === 'platform_base_url'} aria-describedby={describedBy('platform_base_url')} onChange={event => change('platform_base_url', event.target.value)} /></div>
              <p className="auth-settings-field-hint" id={`${id}-platform_base_url-hint`}>与登录应用 ID 对应，可使用上方的内网或外网配置。</p>
            </div>
            <div className="credentials-field"><label id={`${id}-callback-mode-label`} htmlFor={`${id}-callback-mode`}>回跳方式</label>
              <StyledSelect id={`${id}-callback-mode`} className="credentials-history-select" aria-labelledby={`${id}-callback-mode-label`}
                value={draft.callback_mode} disabled={busy || !editable} onChange={value => change('callback_mode', value === 'manual' ? 'manual' : 'auto')}
                options={[{ value: 'auto', label: '自动跟随访问地址' }, { value: 'manual', label: '手动指定地址' }]} />
              <p className="auth-settings-field-hint">自动模式使用发起登录时的主站访问地址和端口；重新部署后端口变化，无需修改回跳地址。</p>
            </div>
            {draft.callback_mode === 'manual' && <div className="credentials-field"><label htmlFor={`${id}-public-url`}>回跳地址</label><div className="credentials-input-row">
              <input ref={element => { inputs.current.public_url = element; }} id={`${id}-public-url`} type="url" value={draft.public_url} maxLength={2048} autoComplete="off" autoCapitalize="none" spellCheck={false}
                placeholder="例如：https://平台域名:端口" required aria-invalid={invalid === 'public_url'} aria-describedby={describedBy('public_url')} onChange={event => change('public_url', event.target.value)} /></div>
              <p className="auth-settings-field-hint" id={`${id}-public_url-hint`}>仅填写主站的协议、主机和端口，不含路径或查询参数。端口变化后需同步修改。</p>
            </div>}
          </fieldset>
        </>}
        {confirm && <div ref={warning} tabIndex={-1} className="credentials-discard" role="alert">
          <p>{confirm === 'reload' ? '读取最新配置会放弃当前未保存的修改。' : '尚有未保存的统一登录配置，是否放弃？'}</p>
          <button type="button" onClick={() => setConfirm(null)}>继续编辑</button>
          <button type="button" onClick={() => { if (confirm === 'reload') void load(); else onClose(); }}>{confirm === 'reload' ? '放弃修改并读取' : '放弃修改'}</button>
        </div>}
      </div>
      <footer className="credentials-footer"><span aria-live="polite">{dirty ? '有未保存的统一登录配置' : '保存后需重启平台生效'}</span><div>
        <button type="button" disabled={saving} onClick={close}>{dirty ? '取消' : '关闭'}</button>
        <button type="submit" className="credentials-save" disabled={busy || !editable || !dirty}>{saving ? '正在保存…' : '保存登录配置'}</button>
      </div></footer>
    </form>
  </dialog>;
}
