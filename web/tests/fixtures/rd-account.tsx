import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CurrentUserProvider } from '../../src/hooks/useCurrentUser';
import { useApplicationLeaveGuard } from '../../src/hooks/useApplicationLeaveGuard';
import { RdAccountDock } from '../../src/features/rd/RdAccountDock';
import '../../src/styles.css';
import '../../src/features/rd/rdApplicationShell.css';

function AccountFixture() {
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  useApplicationLeaveGuard({ dirty: !!draft, busyMessage: busy ? '操作尚未完成，请稍候再退出。' : undefined });
  return <div className={`rd-application-shell${collapsed ? ' is-sidebar-collapsed' : ''}`}>
    <aside className="rd-sidebar" style={{ display: 'flex', flexDirection: 'column', height: '100vh', justifyContent: 'flex-end' }}>
      <RdAccountDock onExpand={() => setCollapsed(false)} onOpenSettings={() => {}} settingsActive={false} settingsDisabled={false} />
    </aside>
    <main><label>未保存内容<input aria-label="未保存内容" value={draft} onChange={event => setDraft(event.target.value)} /></label>
      <label><input type="checkbox" checked={busy} onChange={event => setBusy(event.target.checked)} />模拟操作处理中</label>
      <button onClick={() => setCollapsed(value => !value)}>切换侧栏</button>
    </main>
  </div>;
}
createRoot(document.getElementById('root')!).render(<CurrentUserProvider><AccountFixture /></CurrentUserProvider>);
