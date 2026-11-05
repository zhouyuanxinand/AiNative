import { useEffect, useId, useRef, useState } from 'react';
import { Button, Input } from 'antd';
import type { ResearchCase } from './types';
import type { CommandRunner } from './WorkpackagePanel';

/** Used after source recognition, only when no series has been adopted. */
export function ProductSeriesConfirmation({ researchCase, busy, command, onDirtyChange }: {
  researchCase: ResearchCase; busy: boolean; command: CommandRunner; onDirtyChange: (dirty: boolean) => void;
}) {
  const fieldId = useId();
  const [value, setValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [validation, setValidation] = useState('');
  const request = useRef(false);
  const missing = !researchCase.context.product_series?.trim();
  const editable = missing && researchCase.status !== 'completed' && researchCase.project_workflow_status?.status !== 'completed';
  useEffect(() => { onDirtyChange(editable && !!value); }, [editable, value, onDirtyChange]);
  useEffect(() => { if (!missing) setValue(''); }, [missing]);
  if (!editable) return null;
  return <section className="rd-section rd-series-confirm" aria-labelledby={`${fieldId}-title`}>
    <div><h3 id={`${fieldId}-title`}>确认产品系列</h3><p className="rd-muted">尚未识别到产品系列，请核对需求文件后补充。</p></div>
    <form onSubmit={async event => {
      event.preventDefault();
      if (busy || request.current) return;
      if (!value.trim()) { setValidation('请填写产品系列。'); return; }
      request.current = true; setSaving(true); setValidation('');
      try { await command('save_context', { context: { product_series: value.trim() } }, () => setValue('')); }
      finally { request.current = false; setSaving(false); }
    }}>
      <div className="rd-field"><label htmlFor={fieldId}>产品系列</label><Input id={fieldId} value={value} maxLength={200} placeholder="如 YLZJ、CY" disabled={busy || saving} status={validation ? 'error' : undefined} aria-describedby={validation ? `${fieldId}-error` : undefined} onChange={event => { setValue(event.target.value); setValidation(''); }} /></div>
      <Button type="primary" htmlType="submit" disabled={busy || saving} loading={saving}>确认系列</Button>
    </form>
    {validation && <p id={`${fieldId}-error`} className="rd-error" role="alert">{validation}</p>}
  </section>;
}
