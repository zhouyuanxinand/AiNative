import { useEffect } from 'react';
import { RuntimeLogsView } from './RuntimeLogsView';
import './standaloneRuntimeLogs.css';

export function StandaloneRuntimeLogsPage() {
  useEffect(() => {
    const previousTitle = document.title;
    document.title = '最新运行日志 · 研制任务书平台';
    document.body.dataset.page = 'runtime-logs';
    document.body.classList.add('runtime-logs-page');

    return () => {
      document.title = previousTitle;
      document.body.classList.remove('runtime-logs-page');
      delete document.body.dataset.page;
    };
  }, []);

  return (
    <div className="runtime-logs-standalone">
      <header className="runtime-logs-page-header">
        <div className="runtime-logs-page-brand">
          <span className="runtime-logs-page-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 5h16M4 12h16M4 19h10" />
              <path d="m17 17 2 2 4-4" />
            </svg>
          </span>
          <div>
            <h1>运行日志</h1>
            <p>研制任务书服务诊断 · 仅显示当前日志源的最新记录</p>
          </div>
        </div>
        <a className="runtime-logs-home-link" href="/">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="m15 18-6-6 6-6" />
          </svg>
          返回研制任务书平台
        </a>
      </header>
      <main className="runtime-logs-page-main">
        <RuntimeLogsView />
      </main>
    </div>
  );
}
