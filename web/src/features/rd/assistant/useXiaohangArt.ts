import { useEffect, useState } from 'react';
import type { PilotModel, createPilotRenderer } from './xiaohang3d';

interface AtlasCell { rect: { x: number; y: number; width: number; height: number } }
type Art =
  | { kind: 'webgl'; renderer: NonNullable<ReturnType<typeof createPilotRenderer>>; model: PilotModel }
  | { kind: 'atlas'; image: HTMLImageElement; frames: AtlasCell[] };

async function readAsset<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`无法读取小航资源：${response.status}`);
  return response.json();
}

/** The fallback atlas is baked from the same posed model, and only fetched if needed. */
export function useXiaohangArt() {
  const [art, setArt] = useState<Art | null>(null);
  const [atlasOnly, setAtlasOnly] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let renderer: ReturnType<typeof createPilotRenderer> = null;
    setArt(null);
    async function load() {
      if (!atlasOnly) {
        try {
          const { createPilotRenderer } = await import('./xiaohang3d');
          if (signal.aborted) return;
          renderer = createPilotRenderer(() => { if (!signal.aborted) setAtlasOnly(true); });
          if (renderer) {
            const model = await readAsset<PilotModel>('/assets/xiaohang-3d-model.json', signal);
            if (signal.aborted) return;
            if (renderer.draw(model, 0)) { setArt({ kind: 'webgl', renderer, model }); return; }
          }
        } catch { /* The pre-rendered frames remain usable without a GL context. */ }
        renderer?.dispose();
        renderer = null;
      }
      if (signal.aborted) return;
      const image = new Image();
      image.src = '/assets/xiaohang-3d.png';
      const [atlas] = await Promise.all([readAsset<{ frames: AtlasCell[] }>('/assets/xiaohang-3d.json', signal), image.decode()]);
      if (!signal.aborted && atlas.frames.length === 16) setArt({ kind: 'atlas', image, frames: atlas.frames });
    }
    void load().catch(() => { /* Leave the static portrait visible if animation assets are unavailable. */ });
    return () => { controller.abort(); renderer?.dispose(); renderer = null; };
  }, [atlasOnly]);
  return { art, setAtlasOnly };
}
