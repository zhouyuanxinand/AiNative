import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { rdEvidenceLocations } from './api';
import type { EvidenceLocationResult, Project, ResearchCase } from './types';

const evidenceKey = (sourceId: string, quote: string, analysisId?: string | null) => JSON.stringify([sourceId, quote, analysisId ?? null]);
interface LocationState {
  loading: boolean; error: string; items: Map<string, EvidenceLocationResult>; retry: () => void;
}
const LocationContext = createContext<LocationState | null>(null);

/** One authorized read shared by the main table, fullscreen review and confirmation. */
export function EvidenceLocationsProvider({ actorId, project, researchCase, children }: {
  actorId: string; project: Project; researchCase: ResearchCase; children: ReactNode;
}) {
  const key = JSON.stringify([actorId, project.id, researchCase.id, project.version]);
  const hasEvidence = Boolean(researchCase.source_analysis || researchCase.requirements.length || Object.keys(researchCase.context_provenance || {}).length);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ key: string; items: EvidenceLocationResult[]; error: string } | null>(null);
  useEffect(() => {
    if (!actorId || !hasEvidence) return;
    const controller = new AbortController();
    setResult(null);
    void rdEvidenceLocations(project.id, researchCase.id, controller.signal).then(data => {
      if (!controller.signal.aborted) setResult({ key, items: data.items, error: '' });
    }).catch(error => {
      if (!controller.signal.aborted) setResult({ key, items: [], error: error instanceof Error ? error.message : '无法读取原文定位' });
    });
    return () => controller.abort();
  }, [actorId, project.id, researchCase.id, key, hasEvidence, attempt]);
  const value = useMemo<LocationState>(() => {
    const current = actorId && result?.key === key ? result : null;
    return {
      loading: Boolean(actorId && hasEvidence && !current), error: current?.error || '',
      items: new Map((current?.items || []).map(item => [evidenceKey(item.source_id, item.quote, item.analysis_id), item])),
      retry: () => setAttempt(value => value + 1),
    };
  }, [actorId, hasEvidence, key, result]);
  return <LocationContext.Provider value={value}>{children}</LocationContext.Provider>;
}

export function useEvidenceLocation(sourceId: string, quote: string, analysisId?: string | null) {
  const context = useContext(LocationContext);
  return { location: context?.items.get(evidenceKey(sourceId, quote, analysisId)), loading: context?.loading || false, error: context?.error || '', retry: context?.retry };
}
