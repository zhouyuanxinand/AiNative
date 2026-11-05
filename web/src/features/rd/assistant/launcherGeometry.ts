export interface LauncherPoint { x: number; y: number }
export interface LauncherAnchor { edge: 'left' | 'right'; x?: number; y: number; hidden?: boolean }
export interface LauncherGeometry {
  viewport: { width: number; height: number };
  /** Character bounds relative to the button; speech bubbles have their own placement. */
  footprint: { width: number; height: number; offsetX: number; offsetY: number };
}

function bounds(geometry: LauncherGeometry) {
  const { viewport, footprint } = geometry;
  const marginX = Math.min(24, Math.max(0, (viewport.width - footprint.width) / 2));
  const marginY = Math.min(24, Math.max(0, (viewport.height - footprint.height) / 2));
  const left = marginX - footprint.offsetX, top = marginY - footprint.offsetY;
  return { left, top, right: Math.max(left, viewport.width - footprint.width - marginX - footprint.offsetX), bottom: Math.max(top, viewport.height - footprint.height - marginY - footprint.offsetY) };
}

export function clampLauncherPosition(point: LauncherPoint, geometry: LauncherGeometry): LauncherPoint {
  const area = bounds(geometry);
  return { x: Math.max(area.left, Math.min(area.right, point.x)), y: Math.max(area.top, Math.min(area.bottom, point.y)) };
}

export function launcherPosition(anchor: LauncherAnchor, geometry: LauncherGeometry): LauncherPoint {
  const area = bounds(geometry);
  const x = anchor.x ?? (anchor.edge === 'left' ? 0 : 1);
  return { x: area.left + x * (area.right - area.left), y: area.top + anchor.y * (area.bottom - area.top) };
}

export function launcherAnchorAt(point: LauncherPoint, geometry: LauncherGeometry): LauncherAnchor {
  const area = bounds(geometry), clamped = clampLauncherPosition(point, geometry);
  const center = clamped.x + geometry.footprint.offsetX + geometry.footprint.width / 2;
  return { edge: center < geometry.viewport.width / 2 ? 'left' : 'right', x: area.right === area.left ? 0 : (clamped.x - area.left) / (area.right - area.left), y: area.bottom === area.top ? 0 : (clamped.y - area.top) / (area.bottom - area.top) };
}

export function crossedLauncherDragThreshold(dx: number, dy: number): boolean {
  return Math.hypot(dx, dy) >= 6;
}

/** Only a pointer released in this edge strip docks the freely positioned pet. */
export function launcherDockEdge(pointerX: number, viewportWidth: number): LauncherAnchor['edge'] | null {
  if (pointerX <= 24) return 'left';
  if (pointerX >= viewportWidth - 24) return 'right';
  return null;
}

export function parseLauncherAnchor(value: string | null): LauncherAnchor | null {
  if (!value) return null;
  try {
    const anchor = JSON.parse(value) as Partial<LauncherAnchor> | null;
    if (anchor && (anchor.edge === 'left' || anchor.edge === 'right') && typeof anchor.y === 'number' && Number.isFinite(anchor.y) && anchor.y >= 0 && anchor.y <= 1
      && (anchor.x === undefined || (typeof anchor.x === 'number' && Number.isFinite(anchor.x) && anchor.x >= 0 && anchor.x <= 1))) {
      return { edge: anchor.edge, ...(anchor.x === undefined ? {} : { x: anchor.x }), y: anchor.y, ...(anchor.hidden === true ? { hidden: true } : {}) };
    }
  } catch { /* Invalid UI preferences use the default corner. */ }
  return null;
}
