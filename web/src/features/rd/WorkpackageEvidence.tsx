import { readable, statusTitle } from './presentation';
import './derivationExperience.css';

function recordOf(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function textOf(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) if (typeof record[key] === 'string' && record[key].trim()) return record[key];
  return '';
}
function reasonText(value: unknown, index: number): string {
  return typeof value === 'string' ? value : textOf(recordOf(value), ['message', 'reason', 'title']) || `阻断记录 ${index + 1}（详见原始证据）`;
}

export function WorkpackageEvidence({ reasons = [], obligations = [] }: { reasons?: unknown[]; obligations?: unknown[] }) {
  if (!reasons.length && !obligations.length) return null;
  return <section className="rd-evidence-warning rd-workpackage-evidence" aria-label="待处理事项与阻塞证据">
    <h4>待处理事项与阻塞证据</h4>
    <p>阻断原因：{reasons.length} 项 · 待处理台账：{obligations.length} 项</p>
    {!!reasons.length && <ul className="rd-evidence-reasons">{reasons.slice(0, 3).map((item, index) => <li key={index}>{reasonText(item, index)}</li>)}</ul>}
    {reasons.length > 3 && <details className="rd-disclosure"><summary>查看全部阻断原因（{reasons.length} 项）</summary><ol className="rd-evidence-list" tabIndex={0} aria-label="全部阻断原因">{reasons.map((item, index) => <li key={index}>{reasonText(item, index)}</li>)}</ol></details>}
    {!!obligations.length && <details className="rd-disclosure rd-obligation-ledger"><summary>查看完整待处理台账（{obligations.length} 项）</summary>
      <ol className="rd-evidence-list" tabIndex={0} aria-label="完整待处理台账">{obligations.map((item, index) => {
        const record = recordOf(item);
        const title = typeof item === 'string' ? item : textOf(record, ['title', 'field_label', 'semantic_path']) || `待处理项 ${index + 1}`;
        const reason = textOf(record, ['reason', 'message']), path = textOf(record, ['semantic_path']);
        return <li key={index}><div className="rd-obligation-heading"><strong>{title}</strong>{typeof record.status === 'string' && <span className="rd-badge">{statusTitle(record.status)}</span>}</div>{path && path !== title && <p className="rd-muted">位置：{path}</p>}{reason && <p>{reason}</p>}<details><summary>查看此项原始证据</summary><pre>{readable(item)}</pre></details></li>;
      })}</ol>
    </details>}
    {!!reasons.length && <details className="rd-disclosure"><summary>阻断原因原始证据</summary><pre>{readable(reasons)}</pre></details>}
  </section>;
}
