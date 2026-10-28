import { useLayoutEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent, type RefObject } from 'react';
import { clampLauncherPosition, crossedLauncherDragThreshold, launcherAnchorAt, launcherPosition, parseLauncherAnchor, type LauncherAnchor, type LauncherGeometry, type LauncherPoint } from '../model/assistantLauncher';

const POSITION_KEY = 'xiaohang-launcher-position-v1';
const DEFAULT_ANCHOR: LauncherAnchor = { edge: 'right', y: 1 };
interface DragSession { pointerId: number; x: number; y: number; start: LauncherPoint; current: LauncherPoint; moved: boolean }

/** Pointer dragging and keyboard placement share the same measured visual bounds. */
export function useAssistantLauncherDrag(launcher: RefObject<HTMLButtonElement>, enabled: boolean, activate: () => void) {
  const [position, setPosition] = useState<LauncherPoint | null>(null), [launcherDragging, setLauncherDragging] = useState(false);
  const anchor = useRef<LauncherAnchor>({ ...DEFAULT_ANCHOR }), initialized = useRef(false), geometry = useRef<LauncherGeometry | null>(null);
  const gesture = useRef<DragSession | null>(null), suppressClick = useRef(false);

  function measure() {
    const button = launcher.current;
    if (!button) return null;
    const rect = button.getBoundingClientRect();
    const visual = [rect, ...Array.from(button.querySelectorAll('.xiaohang-figure, .xiaohang-figure img, .xiaohang-figure svg')).map(node => node.getBoundingClientRect())];
    const left = Math.min(...visual.map(box => box.left)), top = Math.min(...visual.map(box => box.top));
    const right = Math.max(...visual.map(box => box.right)), bottom = Math.max(...visual.map(box => box.bottom));
    const measured: LauncherGeometry = { viewport: { width: window.innerWidth, height: window.innerHeight }, footprint: { width: right - left, height: bottom - top, offsetX: left - rect.left, offsetY: top - rect.top } };
    geometry.current = measured;
    return measured;
  }
  function remember(next: LauncherAnchor) {
    anchor.current = next;
    try { window.localStorage.setItem(POSITION_KEY, JSON.stringify(next)); } catch { /* Position remains usable when browser storage is unavailable. */ }
  }
  function snap(point: LauncherPoint, area: LauncherGeometry) {
    const next = launcherAnchorAt(point, area);
    remember(next); setPosition(launcherPosition(next, area));
  }

  useLayoutEffect(() => {
    if (!enabled) return;
    if (!initialized.current) {
      initialized.current = true;
      try { anchor.current = parseLauncherAnchor(window.localStorage.getItem(POSITION_KEY)) || { ...DEFAULT_ANCHOR }; } catch { /* Browser storage is optional for this UI preference. */ }
    }
    const reposition = () => { const area = measure(); if (area && !gesture.current) setPosition(launcherPosition(anchor.current, area)); };
    reposition();
    const observer = new ResizeObserver(reposition);
    if (launcher.current) observer.observe(launcher.current);
    const figure = launcher.current?.querySelector('.xiaohang-figure');
    if (figure) observer.observe(figure);
    window.addEventListener('resize', reposition);
    return () => { observer.disconnect(); window.removeEventListener('resize', reposition); gesture.current = null; };
  }, [enabled, launcher]);

  function pointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0 || !event.isPrimary) return;
    const area = measure();
    if (!area) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const start = { x: rect.left, y: rect.top };
    suppressClick.current = false;
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
    setPosition(session.current);
  }
  function finishPointer(event: PointerEvent<HTMLButtonElement>, cancelled = false) {
    const session = gesture.current, area = geometry.current;
    if (!session || session.pointerId !== event.pointerId) return;
    gesture.current = null;
    suppressClick.current = session.moved && !cancelled;
    if (session.moved && area) snap(session.current, area);
    setLauncherDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    // Touch/pen can omit a compatibility click after pointer capture. Complete
    // an unmoved tap here; the launcher unmounts before a later synthetic click.
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
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home'].includes(event.key)) return;
    event.preventDefault();
    const area = measure();
    if (!area) return;
    let next = anchor.current;
    if (event.key === 'Home') next = { ...DEFAULT_ANCHOR };
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') next = { ...next, edge: event.key === 'ArrowLeft' ? 'left' : 'right' };
    else {
      const current = launcherPosition(next, area), step = event.shiftKey ? 72 : 24;
      next = launcherAnchorAt({ ...current, y: current.y + (event.key === 'ArrowUp' ? -step : step) }, area);
    }
    remember(next); setPosition(launcherPosition(next, area));
  }
  return { position, launcherDragging, launcherEvents: { onPointerDown: pointerDown, onPointerMove: pointerMove,
    onPointerUp: (event: PointerEvent<HTMLButtonElement>) => finishPointer(event),
    onPointerCancel: (event: PointerEvent<HTMLButtonElement>) => finishPointer(event, true),
    onLostPointerCapture: (event: PointerEvent<HTMLButtonElement>) => finishPointer(event, true), onClick: click, onKeyDown: keyDown } };
}
