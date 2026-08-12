/**
 * 左右栏拖拽调宽 hook——从原 SPA initPanelResizers 全套原样迁移。
 * 通过 CSS 变量 --sidebar-width / --review-width 控制宽度。
 */
import { useRef, useCallback, useEffect } from 'react';
import { PANEL_WIDTH_KEY, PANEL_WIDTH_LIMITS, type PanelKind } from '../constants';
import { useTaskbook } from './useTaskbook';

interface ActiveResize {
  kind: PanelKind;
  startX: number;
  startWidth: number;
}

function clampPanelWidth(kind: PanelKind, value: number): number | null {
  const limits = PANEL_WIDTH_LIMITS[kind];
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return Math.round(Math.max(limits.min, Math.min(limits.max, numeric)));
}

function panelDefaultWidth(kind: PanelKind): number {
  if (kind === 'left') {
    if (window.innerWidth >= 1600) return 280;
    if (window.innerWidth >= 1440) return 248;
    return 220;
  }
  if (window.innerWidth >= 1600) return 480;
  if (window.innerWidth >= 1440) return 400;
  return 360;
}

export function usePanelResize() {
  const { showToast } = useTaskbook();
  const activeRef = useRef<ActiveResize | null>(null);
  const leftWidthRef = useRef<number>(panelDefaultWidth('left'));
  const rightWidthRef = useRef<number>(panelDefaultWidth('right'));

  const setPanelCssVar = useCallback((kind: PanelKind, width: number) => {
    const cssVar = kind === 'left' ? '--sidebar-width' : '--review-width';
    const target =
      kind === 'left'
        ? document.getElementById('workspace-shell')
        : document.querySelector<HTMLElement>('.app-shell');
    target?.style.setProperty(cssVar, `${width}px`);
    document
      .getElementById(kind === 'left' ? 'left-resizer' : 'right-resizer')
      ?.setAttribute('aria-valuenow', String(width));
  }, []);

  const persist = useCallback((changedKind: PanelKind) => {
    try {
      const saved = JSON.parse(localStorage.getItem(PANEL_WIDTH_KEY) || '{}');
      const savedLeft = clampPanelWidth('left', saved.left);
      const savedRight = clampPanelWidth('right', saved.right);
      localStorage.setItem(
        PANEL_WIDTH_KEY,
        JSON.stringify({
          left: changedKind === 'left' ? leftWidthRef.current : savedLeft ?? leftWidthRef.current,
          right: changedKind === 'right' ? rightWidthRef.current : savedRight ?? rightWidthRef.current,
        }),
      );
    } catch {
      /* ignore */
    }
  }, []);

  const setPanelWidth = useCallback(
    (kind: PanelKind, value: number, persistFlag = true) => {
      const width = clampPanelWidth(kind, value);
      if (width === null) return;
      if (kind === 'left') leftWidthRef.current = width;
      else rightWidthRef.current = width;
      setPanelCssVar(kind, width);
      if (persistFlag) persist(kind);
    },
    [persist, setPanelCssVar],
  );

  const resetPanelWidth = useCallback(
    (kind: PanelKind) => {
      setPanelWidth(kind, panelDefaultWidth(kind), true);
      showToast(
        kind === 'left' ? '左侧任务栏已恢复默认宽度' : '右侧结果栏已恢复默认宽度',
        'ok',
      );
    },
    [setPanelWidth, showToast],
  );

  const beginResize = useCallback(
    (kind: PanelKind, event: React.PointerEvent) => {
      if (event.button !== 0) return;
      activeRef.current = {
        kind,
        startX: event.clientX,
        startWidth: kind === 'left' ? leftWidthRef.current : rightWidthRef.current,
      };
      document.body.classList.add('resizing');
      event.preventDefault();
    },
    [],
  );

  useEffect(() => {
    // 恢复保存的宽度
    try {
      const saved = JSON.parse(localStorage.getItem(PANEL_WIDTH_KEY) || '{}');
      if (clampPanelWidth('left', saved.left) !== null)
        setPanelWidth('left', saved.left, false);
      if (clampPanelWidth('right', saved.right) !== null)
        setPanelWidth('right', saved.right, false);
    } catch {
      /* ignore */
    }

    const onMove = (e: PointerEvent) => {
      if (!activeRef.current) return;
      const { kind, startX, startWidth } = activeRef.current;
      const delta = e.clientX - startX;
      const next = kind === 'left' ? startWidth + delta : startWidth - delta;
      setPanelWidth(kind, next, false);
      e.preventDefault();
    };
    const onEnd = () => {
      if (!activeRef.current) return;
      const { kind } = activeRef.current;
      activeRef.current = null;
      document.body.classList.remove('resizing');
      persist(kind);
    };
    document.addEventListener('pointermove', onMove, { passive: false });
    document.addEventListener('pointerup', onEnd);
    document.addEventListener('pointercancel', onEnd);
    return () => {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onEnd);
      document.removeEventListener('pointercancel', onEnd);
      document.body.classList.remove('resizing');
    };
  }, [persist, setPanelWidth]);

  return { beginResize, resetPanelWidth, leftWidthRef, rightWidthRef };
}
