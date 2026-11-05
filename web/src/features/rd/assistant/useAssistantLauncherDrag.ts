import { useLayoutEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent, type RefObject } from 'react';
import { clampLauncherPosition, crossedLauncherDragThreshold, launcherAnchorAt, launcherDockEdge, launcherPosition, parseLauncherAnchor, type LauncherAnchor, type LauncherGeometry, type LauncherPoint } from './launcherGeometry';

const POSITION_KEY = 'rd-xiaohang-launcher-position-v1';
const DEFAULT_ANCHOR: LauncherAnchor = { edge: 'right', y: 1 };
interface DragSession { pointerId: number; x: number; y: number; start: LauncherPoint; current: LauncherPoint; moved: boolean }

/** Pointer dragging and keyboard placement share the same measured visual bounds. */
export function useAssistantLauncherDrag(launcher: RefObject<HTMLButtonElement>, enabled: boolean, activate: () => void) {
  const [position, setPosition] = useState<LauncherPoint | null>(null), [launcherDragging, setLauncherDragging] = useState(false);
  const [launcherPressed, setLauncherPressed] = useState(false);
  const [dockedEdge, setDockedEdge] = useState<LauncherAnchor['edge'] | null>(null);
  const [dockingEdge, setDockingEdge] = useState<LauncherAnchor['edge'] | null>(null);
  const anchor = useRef<LauncherAnchor>({ ...DEFAULT_ANCHOR }), initialized = useRef(false), geometry = useRef<LauncherGeometry | null>(null);
  const gesture = useRef<DragSession | null>(null), suppressClick = useRef(false);

  function measure() {
    const button = launcher.current;
    if (!button) return null;
    const rect = button.getBoundingClientRect();
    const visual = [rect, ...Array.from(button.querySelectorAll('.rd-floating-figure')).map(node => node.getBoundingClientRect())];
    const left = Math.min(...visual.map(box => box.left)), top = Math.min(...visual.map(box => box.top));
    const right = Math.max(...visual.map(box => box.right)), bottom = Math.max(...visual.map(box => box.bottom));
    const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
    const measured: LauncherGeometry = { viewport: { width: window.innerWidth, height: Math.max(0, viewportHeight) }, footprint: { width: right - left, height: bottom - top, offsetX: left - rect.left, offsetY: top - rect.top } };
    geometry.current = measured;
    return measured;
  }
  function remember(next: LauncherAnchor) {
    anchor.current = next;
    setDockedEdge(next.hidden ? next.edge : null);
    try { window.localStorage.setItem(POSITION_KEY, JSON.stringify(next)); } catch { /* Position remains usable when browser storage is unavailable. */ }
  }
  function place(point: LauncherPoint, area: LauncherGeometry, edge: LauncherAnchor['edge'] | null = null) {
    const next = { ...launcherAnchorAt(point, area), ...(edge ? { edge, x: edge === 'left' ? 0 : 1, hidden: true } : {}) };
    remember(next); setPosition(launcherPosition(next, area));
  }

  useLayoutEffect(() => {
    if (!enabled) return;
    if (!initialized.current) {
      initialized.current = true;
      try { anchor.current = parseLauncherAnchor(window.localStorage.getItem(POSITION_KEY)) || { ...DEFAULT_ANCHOR }; } catch { /* Browser storage is optional for this UI preference. */ }
      setDockedEdge(anchor.current.hidden ? anchor.current.edge : null);
    }
    const reposition = () => { const area = measure(); if (area && !gesture.current) setPosition(launcherPosition(anchor.current, area)); };
    reposition();
    const observer = new ResizeObserver(reposition);
    if (launcher.current) observer.observe(launcher.current);
    const figure = launcher.current?.querySelector('.rd-floating-figure');
    if (figure) observer.observe(figure);
    window.addEventListener('resize', reposition);
    window.visualViewport?.addEventListener('resize', reposition);
    return () => { observer.disconnect(); window.removeEventListener('resize', reposition); window.visualViewport?.removeEventListener('resize', reposition); gesture.current = null; setLauncherDragging(false); setLauncherPressed(false); setDockingEdge(null); };
  }, [enabled, launcher]);

  function pointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0 || !event.isPrimary) return;
    const area = measure();
    if (!area) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const start = { x: rect.left, y: rect.top };
    suppressClick.current = false;
    setLauncherPressed(true);
    gesture.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, start, current: start, moved: false };
    event.currentTarget.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function pointerMove(event: PointerEvent<HTMLButtonElement>) {
    const session = gesture.current, area = geometry.current;
    if (!session || session.pointerId !== event.pointerId || !area) return;
    const dx = event.clientX - session.x, dy = event.clientY - session.y;
    if (!session.moved && !crossedLauncherDragThreshold(dx, dy)) return;
    if (!session.moved) { session.moved = true; setLauncherDragging(true); }
    event.preventDefault();
    session.current = clampLauncherPosition({ x: session.start.x + dx, y: session.start.y + dy }, area);
    setDockingEdge(launcherDockEdge(event.clientX, area.viewport.width));
    setPosition(session.current);
  }
  function finishPointer(event: PointerEvent<HTMLButtonElement>, cancelled = false) {
    const session = gesture.current, area = geometry.current;
    if (!session || session.pointerId !== event.pointerId) return;
    gesture.current = null;
    suppressClick.current = session.moved && !cancelled;
    if (session.moved && area) place(session.current, area, cancelled ? null : launcherDockEdge(event.clientX, area.viewport.width));
    setLauncherDragging(false);
    setLauncherPressed(false); setDockingEdge(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    // Touch/pen can omit a compatibility click after pointer capture. Complete
    // an unmoved tap here; the launcher hides before a later synthetic click.
    if (!cancelled && !session.moved && event.pointerType !== 'mouse') {
      suppressClick.current = true;
      event.preventDefault(); activate();
    }
  }
  function click(event: MouseEvent<HTMLButtonElement>) {
    if (event.detail > 0 && suppressClick.current) { suppressClick.current = false; event.preventDefault(); event.stopPropagation(); return; }
    suppressClick.current = false; activate();
  }
  function keyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === 'Escape') { event.preventDefault(); remember({ ...anchor.current, hidden: true }); return; }
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home'].includes(event.key)) return;
    event.preventDefault();
    const area = measure();
    if (!area) return;
    let next: LauncherAnchor = { ...anchor.current, hidden: false };
    if (event.key === 'Home') next = { ...DEFAULT_ANCHOR };
    else {
      const current = launcherPosition(next, area), step = event.shiftKey ? 72 : 24;
      const dx = event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0;
      const dy = event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0;
      next = launcherAnchorAt({ x: current.x + dx, y: current.y + dy }, area);
    }
    remember(next); setPosition(launcherPosition(next, area));
  }
  function reveal() {
    remember({ ...anchor.current, hidden: false });
    window.requestAnimationFrame(() => launcher.current?.focus({ preventScroll: true }));
  }
  return { position, launcherDragging, launcherPressed, dockedEdge, dockingEdge, reveal, launcherEvents: { onPointerDown: pointerDown, onPointerMove: pointerMove,
    onPointerUp: (event: PointerEvent<HTMLButtonElement>) => finishPointer(event),
    onPointerCancel: (event: PointerEvent<HTMLButtonElement>) => finishPointer(event, true),
    onLostPointerCapture: (event: PointerEvent<HTMLButtonElement>) => finishPointer(event, true), onClick: click, onKeyDown: keyDown } };
}
