import { useEffect, useState } from 'react';
import { getHelpResources, helpResourceDownloadUrl, type HelpResource } from '../api/resources';
import type { ReviewBlock, ReviewDocument } from '../../taskbook/api/review';
import { HelpResourceIcon } from './HelpResourceIcon';
import { HELP_RESOURCES, type HelpResourceKind } from '../model/helpResources';
import './helpResources.css';

function DocumentBlocks({ blocks }: { blocks: ReviewBlock[] }) {
  return <>{blocks.map(block => {
    if (block.kind === 'table') return <div className="help-document-table" key={block.id} tabIndex={0} role="region" aria-label="手册表格">
      <table><tbody>{block.rows.map((row, index) => <tr key={index}>{row.cells.map(cell =>
        <td key={cell.id} colSpan={cell.colspan || 1} rowSpan={cell.rowspan || 1}><DocumentBlocks blocks={cell.blocks} /></td>,
      )}</tr>)}</tbody></table>
    </div>;
    const Heading = `h${Math.min(6, Math.max(2, (block.heading_level || 1) + 1))}` as 'h2' | 'h3' | 'h4' | 'h5' | 'h6';
    return <div key={block.id}>
      {block.text && (block.heading_level ? <Heading>{block.text}</Heading> : <p>{block.text}</p>)}
      {block.images?.map(image => <figure key={image.id}>{image.available === false || !image.src
        ? <figcaption>{image.reason || '此图片无法预览，请下载原件查看。'}</figcaption>
        : <img src={image.src} alt={image.alt || '手册中的图片'} loading="lazy" />}</figure>)}
    </div>;
  })}</>;
}

function ManualDocument({ url }: { url: string }) {
  const [document, setDocument] = useState<ReviewDocument | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setDocument(null); setError('');
    void (async () => {
      try {
        const response = await fetch(url, { signal: controller.signal, credentials: 'same-origin', cache: 'no-store' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || '手册内容暂时无法加载，请重试或下载原文件。');
        if (!controller.signal.aborted) setDocument(data);
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error && !(cause instanceof SyntaxError || cause instanceof TypeError)
          ? cause.message : '手册内容暂时无法加载，请重试或下载原文件。');
      }
    })();
    return () => controller.abort();
  }, [url, attempt]);
  if (error) return <div className="help-status"><p className="help-media-error" role="alert">{error}</p><button type="button" onClick={() => setAttempt(value => value + 1)}>重新加载手册</button></div>;
  if (!document) return <p className="help-status" role="status">正在加载手册内容…</p>;
  return <>
    <p className="help-note">以下为手册内容预览，原始排版请下载文件查看。</p>
    {document.warnings?.length > 0 && <div className="help-note" role="status">{document.warnings.map((warning, index) => <p key={index}>{warning}</p>)}</div>}
    <article className="help-document" aria-label="操作手册正文">
      {document.blocks.length ? <DocumentBlocks blocks={document.blocks} /> : <p>未读取到可预览的内容，请下载原文件查看。</p>}
    </article>
  </>;
}

function ResourcePreview({ item }: { item: HelpResource }) {
  const [videoFailed, setVideoFailed] = useState(false);
  const target = item.content_url || item.source_url;
  const download = helpResourceDownloadUrl(item);
  return <section className="help-selected-resource" aria-labelledby="help-resource-title">
    <div className="help-resource-heading"><h2 id="help-resource-title">{item.title}</h2>
      {target && <a className="help-file-link" href={download || target} target="_blank" rel="noopener noreferrer">
        {item.source_type === 'file' ? '下载原文件' : '打开原链接'}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M10 4H4v16h16v-6" /></svg>
      </a>}
    </div>
    {item.preview_type === 'video' && item.preview_url ? <div className="help-media">
      <video controls preload="metadata" aria-label={item.title} src={item.preview_url} onError={() => setVideoFailed(true)} />
      {videoFailed && <p className="help-media-error" role="alert">视频暂时无法播放，请打开原文件或链接查看。</p>}
    </div> : item.preview_type === 'pdf' && item.preview_url ? <div className="help-media">
      <p className="help-note">若预览未显示，请使用上方入口打开原文件或链接。</p>
      <iframe className="help-manual-frame" src={item.preview_url} title={item.title} />
    </div> : item.preview_type === 'document' && item.preview_url ? <ManualDocument url={item.preview_url} /> : <div className="help-external-resource">
      <p>此资料以链接发布，点击“打开原链接”查看。</p>
      <p className="help-note">{item.source_url}</p>
    </div>}
  </section>;
}

export function HelpResourcePage({ kind }: { kind: HelpResourceKind }) {
  const resource = HELP_RESOURCES.find(item => item.kind === kind)!;
  const [items, setItems] = useState<HelpResource[]>([]);
  const [selected, setSelected] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${resource.title} · 研制任务书平台`;
    return () => { document.title = previousTitle; };
  }, [resource.title]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    void getHelpResources(kind, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      setItems(result.items);
      setSelected(value => result.items.some(item => item.id === value) ? value : result.items[0]?.id || '');
    }).catch(cause => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : '资料加载失败，请重试。');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [kind, attempt]);
  const item = items.find(entry => entry.id === selected);

  return <div className="help-page">
    <header className="help-page-header">
      <a className="help-page-brand" href="/">研制任务书平台</a>
      <a className="help-home-link" href="/"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="m10 5-7 7 7 7M3 12h18" /></svg>返回平台</a>
    </header>
    <main className="help-page-main">
      <nav className="help-page-nav" aria-label="使用帮助">{HELP_RESOURCES.map(entry =>
        <a key={entry.kind} href={entry.path} aria-current={entry.kind === kind ? 'page' : undefined}><HelpResourceIcon kind={entry.kind} />{entry.title}</a>,
      )}</nav>
      <section className="help-content" aria-labelledby="help-title">
        <div className="help-content-heading"><div><h1 id="help-title">{resource.title}</h1><p>{resource.description}</p></div>
          <button type="button" className="help-refresh" disabled={loading} onClick={() => setAttempt(value => value + 1)}>{loading ? '正在加载…' : '刷新资料'}</button>
        </div>
        {loading ? <p className="help-status" role="status">正在加载已发布资料…</p> : error ? <div className="help-status"><p className="help-media-error" role="alert">{error}</p><button type="button" onClick={() => setAttempt(value => value + 1)}>重新加载</button></div> : items.length === 0 ?
          <div className={`help-placeholder help-placeholder-${kind}`}><span className="help-placeholder-icon"><HelpResourceIcon kind={kind} /></span><h2>{resource.title}待发布</h2><p>管理员尚未发布{resource.title}，请稍后再来查看。</p></div> : <>
            <nav className="help-resource-list" aria-label="已发布资料">{items.map(entry => <button type="button" key={entry.id} aria-current={entry.id === selected ? 'true' : undefined} onClick={() => setSelected(entry.id)}>
              <span>{entry.title}</span><small>{entry.source_type === 'link' ? '链接' : entry.filename?.split('.').pop()?.toUpperCase() || '文件'}</small>
            </button>)}</nav>
            {item && <ResourcePreview key={item.id} item={item} />}
          </>}
      </section>
    </main>
  </div>;
}
