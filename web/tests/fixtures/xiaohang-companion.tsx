import React from 'react';
import { createRoot } from 'react-dom/client';
import { PlatformTheme } from '../../src/components/ui/PlatformTheme';
import { FloatingAssistant } from '../../src/features/rd/FloatingAssistant';
import '../../src/styles.css';
function Fixture() {
  const [action, setAction] = React.useState('');
  return <PlatformTheme><main style={{ padding: 32 }}><h1>小航交互验证</h1><p>隔离页面，不访问业务项目。</p><button onClick={() => setAction('outside')}>页面操作</button><output>{action}</output></main><FloatingAssistant onStartTask={() => setAction('start')} onOpenProjects={() => setAction('projects')} /></PlatformTheme>;
}
createRoot(document.getElementById('root')!).render(<Fixture />);
