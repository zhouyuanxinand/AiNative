import { useEffect, useRef, useState } from 'react';
import { requestDefaultModel, requestDefaultModelCatalog, type DefaultModelResponse, type TestableModel } from '../../api/serviceCredentials';
import { modelSelectionKey } from '../../lib/model';
import { StyledSelect } from './StyledSelect';
import { PlatformButton } from './PlatformButton';

const identity = (item: TestableModel) => ({ provider: item.provider, name: item.model, id: item.id || '' });
const label = (item: TestableModel) => `${item.vendor || item.provider} · ${item.model}${item.id ? ` · ID ${item.id}` : ''}`;

export function DefaultModelSettings({ disabled, credentialsDirty, onDirty, onBusy, onSaved }: {
  disabled: boolean; credentialsDirty: boolean; onDirty: (value: boolean) => void;
  onBusy: (value: boolean) => void; onSaved: () => Promise<void>;
}) {
  const [current, setCurrent] = useState<DefaultModelResponse | null>(null);
  const [models, setModels] = useState<TestableModel[]>([]);
  const [editing, setEditing] = useState(false);
  const [choice, setChoice] = useState('');
  const [task, setTask] = useState<'read' | 'catalog' | 'save' | null>('read');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const request = useRef<AbortController>();
  const saving = useRef(false);
  const chosen = models.find(item => modelSelectionKey(identity(item)) === choice);
  const dirty = editing && !!chosen && (current?.requires_selection || choice !== modelSelectionKey(current?.selection ?? null));

  useEffect(() => { onDirty(!!dirty); }, [dirty, onDirty]);

  async function run(action: 'read' | 'catalog' | 'save') {
    if (saving.current || (action !== 'read' && disabled) || (action === 'save' && (!chosen || !dirty))) return;
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    const timer = window.setTimeout(() => controller.abort(), 20000);
    setTask(action); setError(''); setSuccess('');
    if (action === 'save') { saving.current = true; onBusy(true); }
    try {
      if (action === 'catalog') {
        const result = await requestDefaultModelCatalog(controller.signal);
        if (request.current !== controller || controller.signal.aborted) return;
        setModels(result); setEditing(true);
        const retained = choice || modelSelectionKey(current?.selection ?? null);
        setChoice(result.some(item => modelSelectionKey(identity(item)) === retained) ? retained : '');
      } else {
        const result = await requestDefaultModel(action === 'save' ? identity(chosen!) : undefined, controller.signal);
        if (request.current !== controller || controller.signal.aborted) return;
        setCurrent(result); setEditing(false); onDirty(false);
        if (action === 'save') {
          setSuccess('默认模型已确认，小航后续对话将使用此模型。');
          try { await onSaved(); }
          catch { if (request.current === controller) setError('默认模型已保存，但页面模型列表未刷新。可稍后重新打开设置核对。'); }
        }
      }
    } catch (reason) {
      if (request.current !== controller) return;
      setError(reason instanceof Error && reason.name !== 'AbortError' ? reason.message : '等待默认模型服务超时，请重试并核对保存结果。');
    } finally {
      window.clearTimeout(timer);
      if (request.current === controller) {
        request.current = undefined; setTask(null);
        if (action === 'save') { saving.current = false; onBusy(false); }
      }
    }
  }

  useEffect(() => {
    void run('read');
    return () => { request.current?.abort(); request.current = undefined; };
  }, []);

  return <section className="credentials-default-model" aria-labelledby="default-model-title" aria-busy={task !== null}>
    <div className="credentials-default-heading"><div><h3 id="default-model-title">平台默认模型</h3>
      <p>用于小航自由对话，以及选择“平台默认模型”的任务。</p></div>
      {current && <span className="credentials-default-state" data-ready={!current.requires_selection}>{current.requires_selection ? '待确认' : '已生效'}</span>}
    </div>
    {task === 'read' && <p className="credentials-default-status" role="status">正在读取默认模型…</p>}
    {current && <>
      <p className="credentials-default-current">{current.requires_selection ? '请选择并确认一个可用模型' : current.selection?.name || '尚未选择模型'}</p>
      {!current.requires_selection && current.selection && <p className="credentials-default-meta">{current.source === 'settings' ? '当前环境已保存' : '部署默认'}{current.selection.id ? ` · ID ${current.selection.id}` : ''}</p>}
    </>}
    {credentialsDirty && <p className="credentials-default-status">请先保存下方凭证，再选择此环境的默认模型。</p>}
    {editing && <div className="credentials-default-editor">
      <label id="default-model-picker-label" htmlFor="default-model-picker">选择默认模型</label>
      <StyledSelect id="default-model-picker" aria-labelledby="default-model-picker-label" className="credentials-default-select"
        value={choice} disabled={disabled || task !== null} placeholder="从当前环境的可用模型中选择"
        options={models.map(item => ({ value: modelSelectionKey(identity(item)), label: label(item), title: label(item), disabled: item.configured === false }))}
        onChange={value => { setChoice(value); setError(''); setSuccess(''); }} />
      {models.length === 0 && <p className="credentials-default-status">当前环境没有返回可用模型。请检查凭证或重新读取目录。</p>}
      {current?.selection && !models.some(item => modelSelectionKey(identity(item)) === modelSelectionKey(current.selection))
        && <p className="credentials-default-status">原模型不在当前目录中，请重新选择。</p>}
    </div>}
    <div className="credentials-default-actions">
      {editing && <PlatformButton className="primary" type="button" disabled={disabled || task !== null || !dirty || chosen?.configured === false} onClick={() => void run('save')}>{task === 'save' ? '正在确认…' : '确认默认模型'}</PlatformButton>}
      {current && <button type="button" disabled={disabled || task !== null} onClick={() => void run('catalog')}>
        {task === 'catalog' ? '正在读取目录…' : editing ? '重新读取目录' : current.requires_selection ? '选择默认模型' : '更改默认模型'}</button>}
      {!current && task === null && <button type="button" disabled={disabled} onClick={() => void run('read')}>重新读取默认模型</button>}
      {editing && <button type="button" disabled={disabled || task !== null} onClick={() => { setChoice(modelSelectionKey(current?.selection ?? null)); setEditing(false); setError(''); onDirty(false); }}>取消选择</button>}
    </div>
    {error && <p className="credentials-error" role="alert">{error}</p>}
    {success && <p className="credentials-success" role="status">{success}</p>}
  </section>;
}
