import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react';

const STORAGE_KEY = 'rd.sidebar.width.v1';
const DEFAULT_WIDTH = 216;
const MIN_WIDTH = 200;
const MAX_WIDTH = 360;
const CONTENT_MIN_WIDTH = 480;

function clamp(value: number, maximum = MAX_WIDTH) {
  return Math.max(MIN_WIDTH, Math.min(maximum, Math.round(value)));
}

function readWidth() {
  try {
    const saved = Number(localStorage.getItem(STORAGE_KEY));
    return Number.isFinite(saved) && saved >= MIN_WIDTH && saved <= MAX_WIDTH ? saved : DEFAULT_WIDTH;
  } catch { return DEFAULT_WIDTH; }
}

function saveWidth(value: number) {
  try { localStorage.setItem(STORAGE_KEY, String(value)); } catch { /* Width still works when browser storage is unavailable. */ }
}

type Drag = { id: number; startX: number; startWidth: number; original: number; current: number; element: HTMLDivElement };

/** The saved preference survives temporary viewport limits and sidebar collapse. */
export function useSidebarResize(collapsed: boolean) {
  const shellRef = useRef<HTMLDivElement>(null);
  const [preferredWidth, setPreferredWidth] = useState(readWidth);
  const [availableWidth, setAvailableWidth] = useState(() => document.documentElement.clientWidth);
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 700px)').matches);
  const [resizing, setResizing] = useState(false);
  const drag = useRef<Drag | null>(null);
  const maxWidth = clamp(availableWidth - CONTENT_MIN_WIDTH);
  const width = clamp(preferredWidth, maxWidth);
  const enabled = !collapsed && !mobile;

  useLayoutEffect(() => {
    const shell = shellRef.current;
    if (!shell) return;
    const measure = () => {
      setAvailableWidth(shell.clientWidth);
      setMobile(window.matchMedia('(max-width: 700px)').matches);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(shell);
    window.addEventListener('resize', measure);
    return () => { observer.disconnect(); window.removeEventListener('resize', measure); };
  }, []);

  function finish(commit: boolean) {
    const current = drag.current;
    if (!current) return;
    drag.current = null;
    setResizing(false);
    if (commit) saveWidth(current.current);
    else setPreferredWidth(current.original);
    if (current.element.hasPointerCapture(current.id)) current.element.releasePointerCapture(current.id);
  }

  useEffect(() => { if (!enabled) finish(false); }, [enabled]);

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (!enabled || event.button !== 0 || !event.isPrimary || drag.current) return;
    event.preventDefault();
    event.currentTarget.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { id: event.pointerId, startX: event.clientX, startWidth: width, original: preferredWidth, current: preferredWidth, element: event.currentTarget };
    setResizing(true);
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    const current = drag.current;
    if (!current || current.id !== event.pointerId) return;
    const next = clamp(current.startWidth + event.clientX - current.startX, maxWidth);
    current.current = next;
    setPreferredWidth(next);
  }

  function reset() {
    finish(false);
    setPreferredWidth(DEFAULT_WIDTH);
    saveWidth(DEFAULT_WIDTH);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!enabled) return;
    if (event.key === 'Escape' && drag.current) { event.preventDefault(); finish(false); return; }
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'Home') { reset(); return; }
    if (drag.current) return;
    const next = event.key === 'End' ? maxWidth : clamp(width + (event.key === 'ArrowRight' ? 8 : -8), maxWidth);
    setPreferredWidth(next);
    saveWidth(next);
  }

  return {
    shellRef, enabled, resizing,
    style: { '--rd-sidebar-width': `${width}px` } as CSSProperties,
    separatorProps: {
      role: 'separator', tabIndex: 0,
      'aria-label': '调整侧栏宽度', 'aria-orientation': 'vertical' as const, 'aria-controls': 'rd-platform-sidebar',
      'aria-valuemin': MIN_WIDTH, 'aria-valuemax': maxWidth, 'aria-valuenow': width, 'aria-valuetext': `${width} 像素`,
      title: '拖动调整侧栏宽度；方向键调整，Home 还原默认宽度',
      onPointerDown, onPointerMove, onKeyDown, onDoubleClick: reset,
      onPointerUp: (event: PointerEvent<HTMLDivElement>) => { if (event.pointerId === drag.current?.id) finish(true); },
      onPointerCancel: (event: PointerEvent<HTMLDivElement>) => { if (event.pointerId === drag.current?.id) finish(false); },
      onLostPointerCapture: () => finish(false),
    },
  };
}
