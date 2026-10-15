import { useEffect, useState } from 'react';
import { HelpResourceIcon } from './HelpResourceIcon';
import { HELP_RESOURCES, type HelpResourceKind } from './helpResources';
import './helpResources.css';

export function HelpResourcePage({ kind }: { kind: HelpResourceKind }) {
  const resource = HELP_RESOURCES.find(item => item.kind === kind)!;
  const sourceUrl: string = resource.sourceUrl;
  const [videoFailed, setVideoFailed] = useState(false);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${resource.title} · 研制任务书平台`;
    return () => { document.title = previousTitle; };
  }, [resource.title]);

  return (
    <div className="help-page">
      <header className="help-page-header">
        <a className="help-page-brand" href="/">研制任务书平台</a>
        <a className="help-home-link" href="/">
          <span aria-hidden="true">←</span> 返回平台
        </a>
      </header>
      <main className="help-page-main">
        <nav className="help-page-nav" aria-label="使用帮助">
          {HELP_RESOURCES.map(item => (
            <a key={item.kind} href={item.path} aria-current={item.kind === kind ? 'page' : undefined}>
              <HelpResourceIcon kind={item.kind} />
              {item.title}
            </a>
          ))}
        </nav>
        <section className="help-content" aria-labelledby="help-title">
          <div className="help-content-heading">
            <h1 id="help-title">{resource.title}</h1>
            <p>{resource.description}</p>
          </div>
          {!sourceUrl ? (
            <div className={`help-placeholder help-placeholder-${kind}`}>
              <span className="help-placeholder-icon"><HelpResourceIcon kind={kind} /></span>
              <h2>{resource.title}待发布</h2>
              <p>{kind === 'video' ? '操作视频暂未上传，发布后可在此观看。' : '操作手册暂未上传，发布后可在此查阅。'}</p>
            </div>
          ) : kind === 'video' ? (
            <div className="help-media">
              <video controls preload="metadata" aria-label="平台操作视频" src={sourceUrl} onError={() => setVideoFailed(true)} />
              {videoFailed && <p className="help-media-error" role="alert">视频暂时无法播放，请尝试打开原文件。</p>}
              <a className="help-file-link" href={sourceUrl} target="_blank" rel="noopener noreferrer">打开视频原文件 ↗</a>
            </div>
          ) : (
            <div className="help-media">
              <a className="help-file-link" href={sourceUrl} target="_blank" rel="noopener noreferrer">在新标签页打开手册 ↗</a>
              <iframe className="help-manual-frame" src={sourceUrl} title="平台操作手册" />
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
