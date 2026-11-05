import { useState } from 'react';
import { sourceUrl } from './api';
import { useEvidenceLocation } from './EvidenceLocations';
import { EvidencePreview } from './EvidencePreview';
import { isCurrentSource } from './presentation';
import { ProjectProfileLinks } from './ProjectProfileLinks';
import type { Project, ResearchCase, SourceEvidence } from './types';
import './requirementEvidence.css';

const projectFields: Record<string, string> = {
  project_brief: '研发目标', project_product_name: '产品名称',
  project_customer_name: '客户名称', project_title: '项目名称',
};

function EvidenceReference({ project, researchCase, evidence, analysisId }: {
  project: Project; researchCase: ResearchCase; evidence: SourceEvidence; analysisId: string | null;
}) {
  const source = researchCase.sources.find(record => record.id === evidence.source_id);
  const [preview, setPreview] = useState<string | null>(null);
  const { location, loading, error, retry } = useEvidenceLocation(evidence.source_id, evidence.quote, analysisId);
  const name = location?.source_name || source?.name;
  const version = location?.source_version ?? source?.version;
  const fileTitle = name ? `${name}${version ? ` · V${version}` : ''}` : '原文件';
  const url = sourceUrl(project.id, researchCase.id, evidence.source_id);
  const field = projectFields[evidence.source_id];
  const historyLabel = location?.source_state === 'deleted' ? '已删除来源 · 仅供追溯'
    : location?.source_state === 'historical' || (source && !isCurrentSource(source, researchCase.source_selection)) ? '历史来源 · 使用前需复核' : '';
  const history = historyLabel ? <span className="rd-evidence-status">{historyLabel}</span> : null;
  if (field) return <span>项目登记 · {field}</span>;
  if (!name) return <span>来源未关联</span>;
  if (evidence.kind === 'source_filename') return <><a href={url} title={fileTitle} target="_blank" rel="noreferrer">文件名依据 ↗</a>{history}</>;
  const located = location && ['located', 'ambiguous'].includes(location.status) && location.locations.length > 0;
  return <><div className="rd-evidence-location">
    {located ? <>
      {location.status === 'ambiguous' && <span className="rd-evidence-location-message">多处匹配</span>}
      <span className="rd-evidence-location-list">{location.locations.map(point => <button type="button"
        key={point.id} className="rd-evidence-location-id" onClick={() => setPreview(point.id)}
        aria-label={`预览原文，定位 ${point.id}`}
        title={`${fileTitle} · ${point.label}${location.coordinate_space === 'normalized' ? ' · 转换文档定位' : ''}`}
      >{point.id}<span aria-hidden="true">↗</span></button>)}</span>
      <span className="rd-evidence-location-label">{location.locations.length === 1 ? location.locations[0].label : `${location.locations.length} 个位置`}{location.coordinate_space === 'normalized' ? ' · 转换文档' : ''}</span>
    </> : <>
      <span className="rd-evidence-location-message" title={error || location?.reason}>
        {loading ? '正在定位…' : error ? '定位读取失败' : location?.status === 'unavailable' ? '暂无法定位' : '未找到原文位置'}
      </span>
      {error && <button type="button" className="rd-link-button" onClick={retry}>重试定位</button>}
      {location?.reason && <span className="rd-evidence-location-message">{location.reason}</span>}
      <a href={url} title={fileTitle} target="_blank" rel="noreferrer">下载原文件 ↗</a>
    </>}
  </div>{history}{preview && location && <EvidencePreview projectId={project.id} caseId={researchCase.id}
    location={location} locationId={preview} onClose={() => setPreview(null)} onRefresh={retry} />}</>;
}

export function RequirementEvidence({ project, researchCase, evidence, analysisId }: {
  project: Project; researchCase: ResearchCase; evidence: SourceEvidence[]; analysisId: string | null;
}) {
  const occurrences = new Map<string, number>();
  return <ul className="rd-analysis-evidence">{evidence.map(item => {
    const identity = JSON.stringify([project.id, researchCase.id, item.source_id, analysisId, item.kind ?? null, item.quote]);
    const occurrence = occurrences.get(identity) || 0;
    occurrences.set(identity, occurrence + 1);
    const kind = item.source_id === 'project_customer_name' ? 'customer' : item.source_id === 'project_product_name' ? 'product' : undefined;
    return <li key={`${identity}:${occurrence}`} className="rd-review-proof">
      <EvidenceReference project={project} researchCase={researchCase} evidence={item} analysisId={analysisId} />
      <blockquote>{item.kind === 'source_filename' && <span className="rd-muted">文件名依据： </span>}{item.quote}</blockquote>
      {kind && <ProjectProfileLinks project={project} researchCase={researchCase} kind={kind} />}
    </li>;
  })}</ul>;
}
