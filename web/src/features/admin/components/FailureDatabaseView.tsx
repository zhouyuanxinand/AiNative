import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  deleteFailure, failureOptions, getFailure, listFailures, saveFailure,
  type FailureFields, type FailureOptions, type FailurePage, type FailureRecord,
} from '../api/failures';
import './failures.css';

const emptyFilters = { q: '', product_type: '', series: '' };
const dateLabel = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false });
type Selection = { mode: 'view' | 'edit' | 'create'; record: FailureRecord | null };

export function FailureDatabaseView() {
  const [options, setOptions] = useState<FailureOptions | null>(null);
  const [data, setData] = useState<FailurePage | null>(null);
  const [filters, setFilters] = useState(emptyFilters);
  const [query, setQuery] = useState(emptyFilters);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [selected, setSelected] = useState<Selection | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    Promise.all([failureOptions(), listFailures(filters, page)])
      .then(([meta, result]) => { if (active) { setOptions(meta); setData(result); } })
      .catch(err => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [filters, page, revision]);

  async function open(record: FailureRecord, mode: 'view' | 'edit') {
    setBusy(true); setError(''); setNotice('');
    try { setSelected({ mode, record: await getFailure(record.id) }); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  async function remove(record: FailureRecord) {
    if (!window.confirm('删除这条故障记录？\n' + record.product_name + ' / ' + (record.product_series || record.product_model) + '\n删除后，新生成的任务书将不再引用该记录。')) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await deleteFailure(record);
      setSelected(null);
      setNotice('故障记录已删除，后续生成将不再引用。');
      if (data?.items.length === 1 && page > 1) setPage(value => value - 1);
      setRevision(value => value + 1);
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  function search(event: FormEvent) {
    event.preventDefault(); setFilters({ ...query }); setPage(1); setNotice('');
  }

  return (
    <div className="management-view active failure-manager">
      {notice && <p className="failure-notice" role="status">{notice}</p>}
      {error && <p className="failure-error" role="alert">{error}
        <button type="button" className="failure-link" onClick={() => setRevision(value => value + 1)}>刷新列表</button>
      </p>}
      {selected && options ? <FailureRecordPanel key={selected.mode + '/' + (selected.record?.id || 'new')}
        selected={selected} options={options} busy={busy}
        onBack={() => setSelected(null)} onEdit={() => setSelected({ ...selected, mode: 'edit' })}
        onDelete={remove} onSaved={record => {
          setSelected({ mode: 'view', record }); setNotice('故障记录已保存，后续生成将使用最新内容。');
          setRevision(value => value + 1);
        }} /> : <>
        <div className="failure-toolbar">
          <div><p className="failure-intro">维护产品发生过的故障、原因及改进经验，供同产品、同系列的任务书引用。</p>
            {options && <p className="failure-meta">共 {options.total} 条记录 · 已接入原故障库 {options.imported_count} 条历史记录</p>}
          </div>
          <button className="failure-button primary" type="button" disabled={!options || busy}
            onClick={() => { setSelected({ mode: 'create', record: null }); setNotice(''); }}>新增故障</button>
        </div>
        <form className="failure-search" onSubmit={search} aria-label="查询故障记录">
          <label>产品类型<select aria-label="产品类型" value={query.product_type} onChange={e => setQuery({ ...query, product_type: e.target.value })}>
            <option value="">全部产品</option>
            {options?.products.map(product => <option key={product.id} value={product.id}>{product.label}（{product.count}）</option>)}
            {!!options?.unclassified_count && <option value="__unclassified__">其他历史产品（{options.unclassified_count}）</option>}
          </select></label>
          <label>系列或型号<input value={query.series} maxLength={200} placeholder="输入系列或型号"
            onChange={e => setQuery({ ...query, series: e.target.value })} /></label>
          <label className="failure-keyword">关键词<input type="search" value={query.q} maxLength={500}
            placeholder="搜索产品、部位、故障或改进经验" onChange={e => setQuery({ ...query, q: e.target.value })} /></label>
          <div className="failure-actions">
            <button className="failure-button primary" type="submit" disabled={busy}>查询</button>
            <button className="failure-button" type="button" disabled={busy} onClick={() => {
              setQuery(emptyFilters); setFilters(emptyFilters); setPage(1);
            }}>重置</button>
          </div>
        </form>
        {loading ? <p className="failure-loading" role="status">正在读取故障记录…</p>
          : !data?.items.length ? <p className="failure-loading">没有找到故障记录。可调整查询条件，或点击“新增故障”记录产品经验。</p>
          : <>
            <div className="failure-table-wrap">
              <table className="failure-table" aria-label="故障及改进经验列表">
                <thead><tr><th scope="col">产品 / 系列与型号</th><th scope="col">部位与故障现象</th><th scope="col">改进措施与经验</th><th scope="col">操作</th></tr></thead>
                <tbody>{data.items.map(record => <tr key={record.id}>
                  <td data-label="产品"><strong>{record.product_name}</strong><span className="failure-model">{record.product_series ? '系列：' + record.product_series : '系列未指定'}</span>
                    <span className="failure-model">{record.product_model || '未单列型号'}</span></td>
                  <td data-label="故障"><span className="failure-location">{record.failure_location || '未注明部位'}</span><p className="failure-excerpt">{record.failure_mode || '待补充故障现象'}</p></td>
                  <td data-label="改进经验"><p className="failure-excerpt">{record.improvement || '待补充改进措施'}</p></td>
                  <td data-label="操作"><div className="failure-row-actions">
                    <button className="failure-link" type="button" disabled={busy} onClick={() => open(record, 'view')}>查看</button>
                    <button className="failure-link" type="button" disabled={busy} onClick={() => open(record, 'edit')}>编辑</button>
                    <button className="failure-link danger" type="button" disabled={busy} onClick={() => remove(record)}>删除</button>
                  </div></td>
                </tr>)}</tbody>
              </table>
            </div>
            <div className="failure-pagination">
              <span>找到 {data.total} 条 · 第 {page} / {data.pages} 页</span>
              <div className="failure-actions">
                <button className="failure-button" type="button" disabled={page <= 1 || busy} onClick={() => setPage(value => value - 1)}>上一页</button>
                <button className="failure-button" type="button" disabled={page >= data.pages || busy} onClick={() => setPage(value => value + 1)}>下一页</button>
              </div>
            </div>
          </>}
      </>}
    </div>
  );
}

function FailureRecordPanel({ selected, options, busy, onBack, onEdit, onDelete, onSaved }: {
  selected: Selection; options: FailureOptions; busy: boolean; onBack: () => void; onEdit: () => void;
  onDelete: (record: FailureRecord) => void; onSaved: (record: FailureRecord) => void;
}) {
  const { record, mode } = selected;
  const [fields, setFields] = useState<FailureFields>(() => ({
    product_type: record?.product_type || '', product_name: record?.product_name || '',
    product_series: record?.product_series || '', product_model: record?.product_model || '',
    failure_location: record?.failure_location || '', failure_mode: record?.failure_mode || '',
    failure_analysis: record?.failure_analysis || '', improvement: record?.improvement || '',
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  const readOnly = mode === 'view';
  useEffect(() => { heading.current?.focus(); }, []);

  async function submit(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError('');
    try { onSaved(await saveFailure(fields, record)); }
    catch (err) { setError((err as Error).message); }
    finally { setSaving(false); }
  }
  const change = (name: keyof FailureFields, value: string) => setFields(previous => ({ ...previous, [name]: value }));
  const productLabel = options.products.find(product => product.id === fields.product_type)?.label || '未归类的历史产品';
  return <section className="failure-record">
    <div className="failure-toolbar">
      <div><h3 ref={heading} tabIndex={-1}>{mode === 'create' ? '新增故障' : readOnly ? '故障详情' : '编辑故障'}</h3>
        {record && <p className="failure-meta">记录 #{record.id} · 最近维护 {dateLabel(record.updated_at)}</p>}</div>
      <button type="button" className="failure-button" onClick={onBack} disabled={saving || busy}>返回故障列表</button>
    </div>
    {error && <p className="failure-error" role="alert">{error}</p>}
    {readOnly && record ? <>
      <dl className="failure-detail">
        <div><dt>产品类型</dt><dd>{productLabel}</dd></div>
        <div><dt>数据所属产品</dt><dd>{record.product_name}</dd></div>
        <div><dt>产品系列</dt><dd>{record.product_series || '未指定，按所属型号匹配'}</dd></div>
        <div><dt>所属型号</dt><dd>{record.product_model || '未单列型号'}</dd></div>
        <div className="wide"><dt>失效部位</dt><dd>{record.failure_location || '未注明'}</dd></div>
        <div className="wide"><dt>故障现象</dt><dd>{record.failure_mode || '待补充'}</dd></div>
        <div className="wide"><dt>故障原因</dt><dd>{record.failure_analysis || '待补充'}</dd></div>
        <div className="wide"><dt>改进措施与经验</dt><dd>{record.improvement || '待补充'}</dd></div>
      </dl>
      <div className="failure-actions"><button className="failure-button primary" type="button" disabled={busy} onClick={onEdit}>编辑记录</button>
        <button className="failure-button danger" type="button" disabled={busy} onClick={() => onDelete(record)}>删除记录</button></div>
    </> : <form onSubmit={submit} aria-label="维护故障记录">
      <fieldset className="failure-form" disabled={saving || busy}>
        <label>产品类型{mode === 'create' ? ' *' : ''}<select aria-label="产品类型" required={mode === 'create'} value={fields.product_type} onChange={event => {
          const id = event.target.value;
          const oldLabel = options.products.find(product => product.id === fields.product_type)?.label;
          const label = options.products.find(product => product.id === id)?.label || '';
          setFields({ ...fields, product_type: id, product_name: !fields.product_name || fields.product_name === oldLabel ? label : fields.product_name });
        }}><option value="">{mode === 'create' ? '请选择产品类型' : '未归类的历史产品'}</option>
          {options.products.map(product => <option key={product.id} value={product.id}>{product.label}</option>)}
        </select></label>
        <label>数据所属产品 *<input value={fields.product_name} maxLength={500} required onChange={e => change('product_name', e.target.value)} /></label>
        <label>产品系列<input value={fields.product_series} maxLength={200} placeholder="系列归属已确认时填写，如 J599L" onChange={e => change('product_series', e.target.value)} /></label>
        <label>所属型号<input value={fields.product_model} maxLength={2000} required={!fields.product_series.trim()} placeholder="如 J599L-01；多个型号可用顿号分隔" onChange={e => change('product_model', e.target.value)} /></label>
        <p className="failure-hint wide">系列、型号至少填写一项。系列不确定时留空，保留原始型号；不同系列的记录不会自动合并。</p>
        <label className="wide">失效部位<input value={fields.failure_location} maxLength={500} placeholder="如接触件、绝缘体、壳体" onChange={e => change('failure_location', e.target.value)} /></label>
        <label className="wide">故障现象 *<textarea aria-label="故障现象" value={fields.failure_mode} required maxLength={20000} rows={5} placeholder="记录实际发生的问题及使用场景" onChange={e => change('failure_mode', e.target.value)} /></label>
        <label>故障原因<textarea aria-label="故障原因" value={fields.failure_analysis} maxLength={20000} rows={6} placeholder="记录已查明的原因；尚未明确可留空" onChange={e => change('failure_analysis', e.target.value)} /></label>
        <label>改进措施与经验<textarea aria-label="改进措施与经验" value={fields.improvement} maxLength={20000} rows={6} placeholder="记录实际采用的改进措施和可复用经验" onChange={e => change('improvement', e.target.value)} /></label>
        <div className="failure-actions wide"><button className="failure-button primary" type="submit">{saving ? '正在保存…' : '保存记录'}</button>
          <button className="failure-button" type="button" onClick={onBack}>取消</button></div>
      </fieldset>
    </form>}
    {record?.source_file && <details className="failure-source"><summary>原始导入信息</summary>
      <p>{record.source_file} · {record.source_sheet} · 第 {record.source_row} 行</p>
      <dl>{Object.entries(record.source_data || {}).filter(([, value]) => value).map(([label, value]) =>
        <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    </details>}
  </section>;
}
