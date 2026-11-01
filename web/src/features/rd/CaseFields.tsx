import { useEffect, useState, type FormEvent } from 'react';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { formatTime, isCurrentSource } from './presentation';
import type { ResearchCase, Source } from './types';
import type { CommandRunner } from './WorkpackagePanel';

export function SourcePicker({ sources, sourceSelection, value, onChange, disabled, label = '关联来源证据' }: { sources: Source[]; sourceSelection: ResearchCase['source_selection']; value: string[]; onChange: (ids: string[]) => void; disabled: boolean; label?: string }) {
  const historySelected = sources.some(source => value.includes(source.id) && !isCurrentSource(source, sourceSelection));
  return <fieldset className="rd-source-picker" disabled={disabled}><legend>{label}</legend>{sources.length ? sources.map(source => {
    const current = isCurrentSource(source, sourceSelection);
    return <label key={source.id} data-current={current}><input type="checkbox" checked={value.includes(source.id)} disabled={disabled || !current && !value.includes(source.id)} onChange={event => onChange(event.target.checked ? [...value, source.id] : value.filter(id => id !== source.id))} /><span>{source.name}<small>{{ tech: '技术资料', spec: '规范标准', reference: '参考资料' }[source.role]} · v{source.version} · {current ? '当前输入' : '历史版本'}</small></span></label>;
  }) : <p className="rd-muted">尚无来源证据。先在“资料与参数”中上传实际文件。</p>}{historySelected && <p className="rd-warning">已关联历史版本。请取消旧来源，改为当前输入后保存；如需采用旧版本，先在资料列表中选择。</p>}</fieldset>;
}

export function RouteEditor({ axis, researchCase, busy, command, onDirtyChange }: { axis: 'product' | 'composition'; researchCase: ResearchCase; busy: boolean; command: CommandRunner; onDirtyChange: (dirty: boolean) => void }) {
  const saved = axis === 'product' ? researchCase.product_route : researchCase.composition_route;
  const options = axis === 'product' ? [{ value: 'direct', label: '直接选用' }, { value: 'modification', label: '改型' }, { value: 'new', label: '新研' }] : [{ value: 'direct', label: '直接使用现有模板' }, { value: 'adapt', label: '适配现有模板' }, { value: 'new', label: '新建任务书模板' }];
  const [value, setValue] = useState(saved?.value ?? '');
  const [rationale, setRationale] = useState(saved?.rationale ?? '');
  const [sourceIds, setSourceIds] = useState(saved?.source_ids ?? []);
  const [comparisonId, setComparisonId] = useState(saved?.comparison_id ?? '');
  const [base, setBase] = useState(JSON.stringify([value, rationale, sourceIds, comparisonId]));
  const [validation, setValidation] = useState('');
  const dirty = JSON.stringify([value, rationale, sourceIds, comparisonId]) !== base;
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (dirty) return;
    const next = [saved?.value ?? '', saved?.rationale ?? '', saved?.source_ids ?? [], saved?.comparison_id ?? ''] as const;
    setValue(next[0]); setRationale(next[1]); setSourceIds(next[2]); setComparisonId(next[3]); setBase(JSON.stringify(next));
  }, [saved, dirty]);
  const enabled = ['selection', 'planning'].includes(researchCase.stage) && researchCase.status !== 'completed';
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!comparisonId || !(researchCase.comparisons ?? []).some(record => record.id === comparisonId && record.kind === (axis === 'product' ? 'product' : 'document') && !record.invalidated_at && record.input_revision === researchCase.input_revision)) { setValidation('请先保存当前需求的对应逐项比对，再选择有效比对记录。'); document.getElementById(`rd-route-${axis}-comparison`)?.focus(); return; }
    if (!value || !rationale.trim() || !sourceIds.length || sourceIds.some(id => { const source = researchCase.sources.find(item => item.id === id); return !source || !isCurrentSource(source, researchCase.source_selection); })) { setValidation('请选择分类或策略、填写决定理由，并关联当前输入。历史资料请先更新来源关联。'); document.getElementById(`rd-route-${axis}`)?.focus(); return; }
    setValidation('');
    void command('record_route_decision', { axis, value, rationale, source_ids: sourceIds, ...(comparisonId ? { comparison_id: comparisonId } : {}) }, () => setBase(JSON.stringify([value, rationale, sourceIds, comparisonId])));
  };
  return <form noValidate onSubmit={submit} className="rd-route-editor"><div className="rd-section-head"><div><span className="rd-eyebrow">{axis === 'product' ? '产品维度' : '文档维度'}</span><h4>{axis === 'product' ? '产品研制分类' : '任务书编制策略'}</h4></div><span className={`rd-badge ${saved ? 'completed' : 'draft'}`}>{saved ? '已记录决定' : '尚未决定'}</span></div>
    <p className="rd-muted">{axis === 'product' ? '决定产品直接选用、改型或新研，与任务书模板策略相互独立。' : '决定任务书模板直接使用、适配或新建，不改变产品分类和研制流程。'}</p>
    <div className="rd-field"><label id={`rd-route-${axis}-label`}>{axis === 'product' ? '产品研制分类' : '任务书编制策略'}</label><StyledSelect id={`rd-route-${axis}`} aria-labelledby={`rd-route-${axis}-label`} value={value} options={[{ value: '', label: '请选择实际决定的分类或策略' }, ...options]} onChange={setValue} disabled={busy || !enabled} invalid={!!validation && !value} /></div>
    <div className="rd-field"><label htmlFor={`rd-route-${axis}-reason`}>决定理由</label><textarea id={`rd-route-${axis}-reason`} className="resize-none" rows={3} value={rationale} onChange={event => setRationale(event.target.value)} disabled={busy || !enabled} aria-invalid={!!validation && !rationale.trim()} aria-describedby={validation ? `rd-route-${axis}-error` : undefined} placeholder="填写实际分析、适用条件及决定依据" /></div>
    <SourcePicker sources={researchCase.sources} sourceSelection={researchCase.source_selection} value={sourceIds} onChange={setSourceIds} disabled={busy || !enabled} />
    <div className="rd-field"><label id={`rd-route-${axis}-comparison-label`}>采用的当前逐项比对（必选）</label><StyledSelect id={`rd-route-${axis}-comparison`} required invalid={!!validation && !comparisonId} aria-labelledby={`rd-route-${axis}-comparison-label`} value={comparisonId} disabled={busy || !enabled} onChange={setComparisonId} options={[{ value: '', label: '先保存对应比对，再选择' }, ...(researchCase.comparisons ?? []).filter(record => record.kind === (axis === 'product' ? 'product' : 'document') && !record.invalidated_at && record.input_revision === researchCase.input_revision).map(record => ({ value: record.id, label: `${record.title} · v${record.revision} · 满足 ${record.statistics.matches}/${record.statistics.total}` }))]} /><small>先在上方完成并保存产品或文档的逐项比对。决定固定比对编号、版本与哈希；产品直接选用需全部满足。</small></div>
    {validation && <p id={`rd-route-${axis}-error`} className="rd-error" role="alert">{validation}</p>}
    {saved && <p className="rd-muted">决定人 {saved.actor} · {formatTime(saved.created_at)}</p>}
    <button className="rd-button primary" disabled={busy || !enabled || !dirty} type="submit">保存{axis === 'product' ? '产品分类' : '编制策略'}决定</button>
    {!enabled && <p className="rd-muted">分类与策略决定在“选型决策”或“分类决定落实”阶段记录；其他阶段只读。</p>}
  </form>;
}
