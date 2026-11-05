import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Button } from 'antd';
import { FeedbackDialog } from '../../components/feedback/FeedbackDialog';
import { rdEvidencePreview, RdApiError, sourceUrl } from './api';
import type { EvidenceLocationResult, EvidencePreview as PreviewData } from './types';
import './evidencePreview.css';

export function EvidencePreview({ projectId, caseId, location, locationId, onClose, onRefresh }: {
  projectId: string; caseId: string; location: EvidenceLocationResult; locationId: string;
  onClose: () => void; onRefresh?: () => void;
}) {
  const [data, setData] = useState<PreviewData | null>(null);
  const [error, setError] = useState<{ message: string; stale: boolean } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState(locationId);
  const scroll = useRef<HTMLDivElement>(null);
  const navigationClosed = useRef(false);
  const closePreview = useRef(onClose);
  closePreview.current = onClose;
  useEffect(() => {
    const close = () => { navigationClosed.current = true; closePreview.current(); };
    window.addEventListener('popstate', close);
    return () => window.removeEventListener('popstate', close);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError(null);
    void rdEvidencePreview(projectId, caseId, location, locationId, controller.signal).then(value => {
      if (!controller.signal.aborted) setData(value);
    }).catch(reason => {
      if (!controller.signal.aborted) setError({ message: reason instanceof Error ? reason.message : '原文预览读取失败，请重试。', stale: reason instanceof RdApiError && reason.status === 409 });
    });
    return () => controller.abort();
  }, [projectId, caseId, location, locationId, attempt]);
  useLayoutEffect(() => {
    const container = scroll.current;
    const target = container?.querySelector<HTMLElement>(`[data-evidence-anchor="${selected}"]`);
    if (container && target) container.scrollTop += target.getBoundingClientRect().top - container.getBoundingClientRect().top - 12;
  }, [data, selected]);
  const current = data || location;
  const history = current.source_state === 'deleted' ? '已删除来源 · 仅供追溯' : current.source_state === 'historical' ? '历史来源 · 使用前需复核' : '';
  const available = Boolean(data?.blocks.length);
  return <FeedbackDialog title="原文预览" className="rd-evidence-preview-dialog" onCancel={onClose} shouldRestoreFocus={() => !navigationClosed.current}>
    <div className="rd-evidence-preview-header">
      <p className="rd-evidence-preview-source">{current.source_name || '原文件'}{current.source_version ? ` · V${current.source_version}` : ''}</p>
      {history && <p className="rd-evidence-status">{history}</p>}
      <p className="rd-muted">{current.coordinate_space === 'normalized' ? '转换文档文字预览，位置对应此分析保留的转换副本；版式以原文件为准。' : '原文件文字预览，位置对应正文块、表格行或文本行；版式以原文件为准。'}</p>
    </div>
    <div className="rd-evidence-preview-quote"><span>引用摘录</span><blockquote>{location.quote}</blockquote></div>
    {available && <nav className="rd-evidence-preview-locations" aria-label="原文匹配位置">
      <span>{current.status === 'ambiguous' ? '多处匹配，选择位置核对：' : '引用位置：'}</span>
      {current.locations.map(point => <button type="button" key={point.id} aria-current={selected === point.id ? 'location' : undefined}
        className="rd-evidence-location-id" title={point.label} onClick={() => setSelected(point.id)}>{point.id}</button>)}
    </nav>}
    {!data && !error && <p role="status">正在读取原文预览…</p>}
    {error && <div role="alert" className="rd-evidence-preview-error"><p>{error.message}</p>
      {error.stale && onRefresh ? <Button onClick={() => { onRefresh(); onClose(); }}>刷新定位</Button> : <Button onClick={() => setAttempt(value => value + 1)}>重试预览</Button>}
    </div>}
    {data && !available && <p role="status">{data.reason || '此资料暂不支持文字预览。'}。可下载原文件，按引用摘录和下方位置核对。</p>}
    {available && <div ref={scroll} className="rd-evidence-preview-content" role="region" aria-label="原文件正文" tabIndex={0}>
      {data!.blocks.map(block => <div key={block.id} data-evidence-anchor={block.id}
        className={`rd-evidence-preview-block${selected === block.id ? ' is-selected' : ''}`} aria-label={block.label}>
        <span className="rd-evidence-preview-coordinate" title={block.label}>{block.id}</span>
        <p>{block.segments.map((segment, index) => segment.highlighted ? <mark key={index}>{segment.text}</mark> : <span key={index}>{segment.text}</span>)}</p>
      </div>)}
    </div>}
    {!available && <p className="rd-muted">定位参考：{location.locations.map(point => `${point.id}（${point.label}）`).join('、') || '暂无可核验位置'}{location.coordinate_space === 'normalized' ? '；此位置属于转换副本。' : ''}</p>}
    <div className="feedback-dialog-actions rd-evidence-preview-actions">
      <a href={sourceUrl(projectId, caseId, location.source_id)} target="_blank" rel="noreferrer">下载原文件 ↗</a>
      <Button autoInsertSpace={false} onClick={onClose}>关闭预览</Button>
    </div>
  </FeedbackDialog>;
}
