import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import {
  loadRule, loadRules, restoreRule, saveRule, validateRule,
  type RuleAvailability, type RuleDetail, type RuleField, type RuleListItem,
  type RulePath, type RuleValue,
} from '../../api/rules';
import './rules.css';
import { useApplicationLeaveGuard } from '../../hooks/useApplicationLeaveGuard';

const pathKey = (path: RulePath) => JSON.stringify(path);
function readValue(data: Record<string, unknown>, path: RulePath): RuleValue {
  let value: unknown = data;
  for (const part of path) {
    if (value === null || typeof value !== 'object') return '';
    value = (value as Record<string | number, unknown>)[part];
  }
  return value as RuleValue;
}
function valuesFor(detail: RuleDetail): Record<string, RuleValue> {
  return Object.fromEntries(detail.fields.map((field) => [pathKey(field.path), readValue(detail.data, field.path)]));
}
function displayValue(value: RuleValue) {
  if (Array.isArray(value)) return value.length ? value.join('；') : '（空列表）';
  if (typeof value === 'boolean') return value ? '启用' : '停用';
  return String(value ?? '') || '（未填写）';
}
function errorMessage(error: unknown) { return error instanceof Error ? error.message : '操作失败，请重试'; }
function shortRevision(revision: string) { return revision.length > 16 ? revision.slice(0, 12) : revision; }
function displayTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

export function RulesView() {
  const [items, setItems] = useState<RuleListItem[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState<RuleDetail | null>(null);
  const [values, setValues] = useState<Record<string, RuleValue>>({});
  const [availability, setAvailability] = useState<RuleAvailability | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [listError, setListError] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [search, setSearch] = useState('');
  const [fieldSearch, setFieldSearch] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState<'save' | 'validate' | 'restore' | 'refresh' | ''>('');
  const [showChanges, setShowChanges] = useState(false);
  const [restoreRevision, setRestoreRevision] = useState('');
  const [restoreNote, setRestoreNote] = useState('');
  const [reloadCount, setReloadCount] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);

  const changedFields = useMemo(() => detail?.fields.filter((field) =>
    JSON.stringify(values[pathKey(field.path)]) !== JSON.stringify(readValue(detail.data, field.path)),
  ) || [], [detail, values]);
  const dirty = changedFields.length > 0;
  useApplicationLeaveGuard({ dirty, busyMessage: busy ? '规则正在处理，请完成后再退出登录。' : undefined });

  useEffect(() => {
    let active = true;
    setLoadingList(true);
    setListError('');
    loadRules().then((data) => {
      if (!active) return;
      setItems(data.items);
      setAvailability(data);
      setSelectedId((current) => data.items.some((item) => item.id === current) ? current : data.items[0]?.id || '');
    }).catch((failure) => active && setListError(errorMessage(failure)))
      .finally(() => active && setLoadingList(false));
    return () => { active = false; };
  }, [reloadCount]);

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    setLoadingDetail(true);
    setDetail(null);
    setError('');
    setNotice('');
    setFieldSearch('');
    setNote('');
    setShowChanges(false);
    setRestoreRevision('');
    loadRule(selectedId).then((data) => {
      if (!active) return;
      setDetail(data);
      setValues(valuesFor(data));
      setAvailability(data);
    }).catch((failure) => active && setError(errorMessage(failure)))
      .finally(() => active && setLoadingDetail(false));
    return () => { active = false; };
  }, [selectedId, reloadCount]);

  useEffect(() => {
    if (!dirty && !busy) return;
    const beforeNavigation = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Element) || rootRef.current?.contains(target) || !target.closest('button, a')) return;
      if (target.closest('[data-application-logout]')) return;
      if (busy) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      if (!window.confirm('规则修改尚未保存。确定放弃修改并离开吗？')) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    document.addEventListener('click', beforeNavigation, true);
    return () => {
      document.removeEventListener('click', beforeNavigation, true);
    };
  }, [dirty, busy]);

  const groups = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    const result = new Map<string, RuleListItem[]>();
    items.filter((item) => `${item.title} ${item.group} ${item.description}`.toLocaleLowerCase().includes(query))
      .forEach((item) => result.set(item.group, [...(result.get(item.group) || []), item]));
    return result;
  }, [items, search]);

  const sections = useMemo(() => {
    const query = fieldSearch.trim().toLocaleLowerCase();
    const result = new Map<string, RuleField[]>();
    detail?.fields.filter((field) => `${field.label} ${field.section} ${field.description || ''} ${displayValue(values[pathKey(field.path)])}`.toLocaleLowerCase().includes(query))
      .forEach((field) => result.set(field.section || '规则内容', [...(result.get(field.section || '规则内容') || []), field]));
    return result;
  }, [detail, fieldSearch, values]);

  const acceptDetail = (data: RuleDetail) => {
    setDetail(data);
    setValues(valuesFor(data));
    setAvailability(data);
    setItems((current) => current.map((item) => item.id === data.id ? { ...item, revision: data.revision } : item));
    setNote('');
    setRestoreRevision('');
    setRestoreNote('');
    setShowChanges(false);
  };

  const selectRule = (id: string) => {
    if (id === selectedId || busy) return;
    if (dirty && !window.confirm('规则修改尚未保存。确定放弃修改并切换规则吗？')) return;
    setSelectedId(id);
  };

  const discard = () => {
    if (!detail || !window.confirm('确定放弃当前未保存的规则修改吗？')) return;
    setValues(valuesFor(detail));
    setNote('');
    setError('');
    setNotice('已放弃修改，恢复为当前生效版本。');
    setShowChanges(false);
  };

  const mutate = async (action: 'save' | 'validate') => {
    if (!detail || !dirty || busy) return;
    setBusy(action);
    setError('');
    setNotice('');
    const body = {
      expected_revision: detail.revision,
      changes: changedFields.map((field) => {
        const value = values[pathKey(field.path)];
        return { path: field.path, value: field.type === 'string_list' && Array.isArray(value) ? value.map((item) => item.trim()).filter(Boolean) : value };
      }),
      note: note.trim(),
    };
    try {
      const validation = await validateRule(detail.id, body);
      if (!validation.valid) throw new Error('规则检查未通过，请检查修改内容。');
      if (action === 'validate') {
        setShowChanges(true);
        setNotice(`检查通过，共 ${validation.changes.length} 项修改。保存后对新任务生效。`);
      } else {
        const saved = await saveRule(detail.id, body);
        acceptDetail(saved);
        setNotice('规则已保存并生效，新建任务将使用当前版本。');
      }
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(''); }
  };

  const restore = async () => {
    if (!detail || !restoreRevision || busy || dirty) return;
    setBusy('restore');
    setError('');
    setNotice('');
    try {
      const saved = await restoreRule(detail.id, detail.revision, restoreRevision, restoreNote.trim());
      acceptDetail(saved);
      setNotice('历史规则已恢复并生效，已保留本次恢复记录。');
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(''); }
  };

  const refreshAvailability = async () => {
    setBusy('refresh');
    setError('');
    try { setAvailability(await loadRules()); }
    catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(''); }
  };

  const submit = (event: FormEvent) => { event.preventDefault(); void mutate('save'); };
  const readyToSave = availability?.can_save === true;

  return (
    <div className="rules-center" id="management-rules" ref={rootRef}>
      <div className="rules-intro">
        <p>按业务需要调整生成规则，保存后对新任务生效。</p>
        <span>每次保存保留版本，可查看修改记录并恢复。</span>
      </div>
      {listError ? <div className="rules-feedback error" role="alert">规则目录读取失败：{listError}<button type="button" onClick={() => setReloadCount((count) => count + 1)}>重新读取</button></div> : null}
      <div className="rules-layout">
        <aside className="rules-navigation" aria-label="规则分组">
          <label className="rules-search-label" htmlFor="rules-search">查找规则</label>
          <input id="rules-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索名称或产品类型" />
          <div className="rules-navigation-list">
            {loadingList ? <RuleLoading label="正在读取规则目录" /> : groups.size ? [...groups].map(([group, rules]) => (
              <div className="rules-navigation-group" key={group}>
                <h3>{group}</h3>
                {rules.map((item) => <button key={item.id} type="button" className={`rules-nav-item ${selectedId === item.id ? 'selected' : ''}`} aria-current={selectedId === item.id ? 'true' : undefined} onClick={() => selectRule(item.id)} disabled={Boolean(busy)}>
                  <span>{item.title}</span><small>{item.field_count} 个可调项</small>
                </button>)}
              </div>
            )) : <p className="rules-empty">{search ? '没有找到对应规则，请尝试其他关键词。' : '当前没有开放编辑的业务规则。'}</p>}
          </div>
        </aside>
        <div className="rules-content" aria-busy={loadingDetail || Boolean(busy)}>
          {loadingDetail || loadingList ? <RuleLoading label="正在读取规则内容" /> : detail ? <>
            <div className="rules-detail-head">
              <div><h3>{detail.title}</h3><p>{detail.description}</p></div>
              <div className="rules-version"><span>当前版本</span><strong title={detail.revision}>{shortRevision(detail.revision)}</strong>{detail.updated_at && <time dateTime={detail.updated_at}>{displayTime(detail.updated_at)}</time>}</div>
            </div>
            {!readyToSave && <div className="rules-feedback warning" role="status"><span>{availability?.blocking_reason || '当前暂时不能保存规则。可以继续编辑，稍后刷新运行状态。'}</span><button type="button" disabled={Boolean(busy)} onClick={() => void refreshAvailability()}>刷新运行状态</button></div>}
            {error && <div className="rules-feedback error" role="alert"><span>{error}</span><button type="button" disabled={Boolean(busy)} onClick={() => {
              if (!dirty || window.confirm('重新读取将放弃未保存的修改，是否继续？')) setReloadCount((count) => count + 1);
            }}>重新读取当前版本</button></div>}
            {notice && <div className="rules-feedback success" role="status">{notice}</div>}
            <form onSubmit={submit}>
              <div className="rules-field-toolbar">
                <label htmlFor="rule-field-search">规则内容 <span>{detail.fields.length} 个可调项</span></label>
                <input id="rule-field-search" type="search" value={fieldSearch} onChange={(event) => setFieldSearch(event.target.value)} placeholder="查找字段或内容" />
              </div>
              <fieldset className="rules-fields" disabled={Boolean(busy)}>
                {[...sections].map(([section, fields], index) => <details className="rules-section" key={section} open={Boolean(fieldSearch.trim()) || index < 2}>
                  <summary>{section}<span>{fields.length} 项</span></summary>
                  <div>{fields.map((field) => <RuleFieldInput key={pathKey(field.path)} field={field} value={values[pathKey(field.path)]} changed={changedFields.includes(field)} onChange={(value) => {
                    setValues((current) => ({ ...current, [pathKey(field.path)]: value }));
                    setNotice('');
                    setShowChanges(false);
                    setRestoreRevision('');
                  }} />)}</div>
                </details>)}
                {!sections.size && <p className="rules-empty">{fieldSearch ? '没有匹配的字段，请调整搜索内容。' : '该规则暂无开放编辑的字段。'}</p>}
              </fieldset>
              <div className="rules-save-area">
                <label htmlFor="rule-note">修改说明 <span>选填，便于后续追溯</span></label>
                <input id="rule-note" type="text" value={note} maxLength={500} disabled={Boolean(busy)} onChange={(event) => setNote(event.target.value)} placeholder="例如：补充射频产品的识别关键词" />
                <div className="rules-save-bar">
                  <span className={dirty ? 'rules-unsaved' : ''}>{dirty ? `${changedFields.length} 项修改尚未保存` : '当前内容与生效版本一致'}</span>
                  <div className="rules-actions">
                    <button className="rule-button secondary" type="button" disabled={!dirty || Boolean(busy)} onClick={discard}>放弃修改</button>
                    <button className="rule-button secondary" type="button" disabled={!dirty || Boolean(busy)} onClick={() => void mutate('validate')}>{busy === 'validate' ? '正在检查…' : '检查修改'}</button>
                    <button className="rule-button primary" type="submit" disabled={!dirty || Boolean(busy) || !readyToSave}>{busy === 'save' ? '正在保存…' : '保存并生效'}</button>
                  </div>
                </div>
                {showChanges && <div className="rules-change-preview"><h4>本次修改</h4>{changedFields.map((field) => <div key={pathKey(field.path)}><strong>{field.label}</strong><dl><dt>原值</dt><dd>{displayValue(readValue(detail.data, field.path))}</dd><dt>新值</dt><dd>{displayValue(values[pathKey(field.path)])}</dd></dl></div>)}</div>}
              </div>
            </form>
            <details className="rules-history" open={Boolean(restoreRevision) || undefined}>
              <summary>修改记录与恢复<span>{detail.history.length} 个版本</span></summary>
              <p>{detail.history.length ? '恢复会新增一条修改记录，已有任务和历史版本仍保留。' : '还没有修改记录，首次保存后会保留修改前后版本。'}</p>
              <ol>{detail.history.map((entry, index) => <li key={entry.event_id || `${entry.revision}-${index}`}>
                <div><strong title={entry.revision}>{shortRevision(entry.revision)}</strong>{entry.is_current && <span className="rules-current">当前生效</span>}<p>{entry.note || '未填写修改说明'}</p><small>{displayTime(entry.created_at)}{entry.actor ? ` · ${entry.actor}` : ''}</small></div>
                {!entry.is_current && entry.revision !== detail.revision && <button className="rule-button secondary" type="button" disabled={Boolean(busy) || dirty || !readyToSave} onClick={() => { setRestoreRevision(entry.revision); setRestoreNote(''); }}>恢复此版本</button>}
              </li>)}</ol>
              {dirty && <p>请先保存或放弃当前修改，再恢复历史版本。</p>}
              {restoreRevision && <div className="rules-restore-confirm"><h4>恢复到版本 {shortRevision(restoreRevision)}</h4><p>恢复后，新建任务将使用该版本的规则。</p><label htmlFor="rule-restore-note">恢复说明（选填）</label><input id="rule-restore-note" value={restoreNote} maxLength={500} disabled={Boolean(busy)} onChange={(event) => setRestoreNote(event.target.value)} placeholder="填写恢复原因" /><div className="rules-actions"><button className="rule-button secondary" type="button" disabled={Boolean(busy)} onClick={() => setRestoreRevision('')}>取消恢复</button><button className="rule-button primary" type="button" disabled={Boolean(busy) || !readyToSave} onClick={() => void restore()}>{busy === 'restore' ? '正在恢复…' : '确认恢复并生效'}</button></div></div>}
            </details>
          </> : !loadingList && <div className="rules-empty">{error || '从左侧选择一组规则，查看并调整业务配置。'}{error && <button className="rule-button secondary" type="button" onClick={() => setReloadCount((count) => count + 1)}>重新读取</button>}</div>}
        </div>
      </div>
    </div>
  );
}

function RuleLoading({ label }: { label: string }) {
  return <div className="rules-loading" role="status"><span>{label}…</span><i /><i /><i /></div>;
}

function RuleFieldInput({ field, value, changed, onChange }: { field: RuleField; value: RuleValue; changed: boolean; onChange: (value: RuleValue) => void }) {
  const id = `rule-field-${encodeURIComponent(pathKey(field.path))}`;
  const descriptionId = `${id}-description`;
  const choices = field.type === 'string_list' && field.options?.length ? field.options : null;
  return <div className={`rule-field ${changed ? 'changed' : ''} ${field.type === 'boolean' ? 'boolean' : ''}`}>
    <div className="rule-field-copy"><label id={`${id}-label`} htmlFor={choices ? undefined : id}>{field.label}</label>{changed && <span className="rule-changed-marker">已修改</span>}{field.description && <p id={descriptionId}>{field.description}</p>}</div>
    {field.type === 'boolean' ? <label className="rule-checkbox"><input id={id} type="checkbox" checked={Boolean(value)} aria-describedby={field.description ? descriptionId : undefined} onChange={(event) => onChange(event.target.checked)} /><span>{value ? '启用' : '停用'}</span></label>
      : field.type === 'enum' ? <select id={id} value={String(value)} aria-describedby={field.description ? descriptionId : undefined} onChange={(event) => onChange(event.target.value)}>{(field.options || []).map((option) => <option key={option} value={option}>{field.option_labels?.[option] || option}</option>)}</select>
      : field.type === 'number' ? <input id={id} type="number" step="any" required value={String(value)} aria-describedby={field.description ? descriptionId : undefined} onChange={(event) => onChange(event.target.value === '' ? '' : Number(event.target.value))} />
      : choices ? <fieldset className="rule-choice-list" aria-labelledby={`${id}-label`} aria-describedby={field.description ? descriptionId : undefined}>{choices.map((choice) => <label key={choice}><input type="checkbox" checked={Array.isArray(value) && value.includes(choice)} onChange={(event) => onChange(event.target.checked ? [...(Array.isArray(value) ? value : []), choice] : (Array.isArray(value) ? value : []).filter((item) => item !== choice))} /><span>{field.option_labels?.[choice] || choice}</span></label>)}</fieldset>
      : <textarea id={id} rows={field.type === 'string_list' ? Math.min(7, Math.max(3, Array.isArray(value) ? value.length : 3)) : String(value || '').length > 120 ? 4 : 2} value={Array.isArray(value) ? value.join('\n') : String(value ?? '')} aria-describedby={field.description ? descriptionId : undefined} onChange={(event) => onChange(field.type === 'string_list' ? event.target.value.split('\n') : event.target.value)} />}
    {field.type === 'string_list' && <small className="rule-field-format">{choices ? '可选择多个适用项。' : '每行一项，可增删。空白行会在保存时清除。'}</small>}
  </div>;
}
