import { useEffect, useState } from 'react';
import { rdContracts } from './api';
import { messageOf, readable } from './presentation';

export function WorkspaceContracts() {
  const [open, setOpen] = useState(() => new URLSearchParams(window.location.search).get('rd_view') === 'contracts');
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void rdContracts(controller.signal).then(value => { if (!controller.signal.aborted) { setData(value); setError(''); } }).catch(reason => { if (!controller.signal.aborted) setError(messageOf(reason)); });
    return () => controller.abort();
  }, [open, revision]);
  return <details className="rd-section rd-evidence-group" open={open} onToggle={event => setOpen(event.currentTarget.open)}><summary><span><strong>接入边界与未来契约</strong><small>只读说明 · 不影响当前项目办理</small></span></summary><div><p className="rd-notice">外部 Workspace、本体 Agent 与 K-box 以当前实际接入为准。契约示例不能作为生产证据，也不表示远端服务已联通。</p>{error && <p className="rd-error" role="alert">{error}</p>}{!data && !error && <p className="rd-muted" role="status">正在读取接入说明…</p>}{data && <pre className="rd-contract-data">{readable(data)}</pre>}<button className="rd-button" onClick={() => setRevision(value => value + 1)}>刷新接入说明</button></div></details>;
}
