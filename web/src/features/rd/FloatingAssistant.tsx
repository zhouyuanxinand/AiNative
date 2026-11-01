import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CaseAssistant } from './CaseAssistant';
import { XiaohangSprite } from './assistant/XiaohangSprite';
import { useAssistantLauncherDrag } from './assistant/useAssistantLauncherDrag';
import type { AssistantTarget, Project, ResearchCase } from './types';
import './FloatingAssistant.css';

const ignoreBoolean = (_value: boolean) => {};
const ignoreTarget = (_target: AssistantTarget) => {};
const viewportSize = () => ({ width: window.innerWidth, height: window.visualViewport?.height ?? window.innerHeight });

export interface FloatingAssistantProps {
  project?: Project;
  researchCase?: ResearchCase;
  onNavigate?: (target: AssistantTarget) => void;
  onDirtyChange?: (dirty: boolean) => void;
  onBusyChange?: (busy: boolean) => void;
  onStartTask?: () => void;
  onOpenProjects?: () => void;
}

/** A visual shell only. The case conversation retains its original API and draft ownership. */
export function FloatingAssistant({ project, researchCase, onNavigate = ignoreTarget,
  onDirtyChange = ignoreBoolean, onBusyChange = ignoreBoolean, onStartTask, onOpenProjects }: FloatingAssistantProps) {
  const [open, setOpen] = useState(false);
  const [viewport, setViewport] = useState(viewportSize);
  const launcher = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(false);
  const restoreFocus = useRef(true);
  const activate = useCallback(() => setOpen(true), []);
  const close = useCallback(() => setOpen(false), []);
  const { position, launcherDragging, launcherEvents } = useAssistantLauncherDrag(launcher, !open, activate);
  const hasCase = Boolean(project && researchCase);

  useEffect(() => {
    const resize = () => setViewport(viewportSize());
    window.addEventListener('resize', resize);
    window.visualViewport?.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); window.visualViewport?.removeEventListener('resize', resize); };
  }, []);
  useEffect(() => {
    if (open) {
      restoreFocus.current = true;
      const frame = window.requestAnimationFrame(() => (panel.current?.querySelector<HTMLElement>('textarea') ?? panel.current?.querySelector<HTMLElement>('.rd-floating-primary') ?? panel.current?.querySelector<HTMLElement>('button'))?.focus());
      wasOpen.current = true;
      return () => window.cancelAnimationFrame(frame);
    }
    if (wasOpen.current && restoreFocus.current && !document.querySelector('dialog[open]')) launcher.current?.focus({ preventScroll: true });
  }, [open, project?.id, researchCase?.id]);

  useEffect(() => {
    if (!open) return;
    let startedOutside = false;
    const isOutside = (event: MouseEvent) => event.target instanceof Node
      && !panel.current?.contains(event.target) && !launcher.current?.contains(event.target)
      && !document.querySelector('dialog[open]');
    const pointerDown = (event: PointerEvent) => {
      startedOutside = event.isPrimary && event.button === 0 && isOutside(event);
    };
    const pointerCancel = () => { startedOutside = false; };
    const click = (event: MouseEvent) => {
      const dismiss = startedOutside && event.button === 0 && isOutside(event);
      startedOutside = false;
      if (!dismiss) return;
      // Keep the conversation mounted, and do not steal focus from the clicked field.
      restoreFocus.current = document.activeElement === document.body || !!panel.current?.contains(document.activeElement);
      close();
    };
    document.addEventListener('pointerdown', pointerDown, true);
    document.addEventListener('pointercancel', pointerCancel, true);
    document.addEventListener('click', click);
    return () => {
      document.removeEventListener('pointerdown', pointerDown, true);
      document.removeEventListener('pointercancel', pointerCancel, true);
      document.removeEventListener('click', click);
    };
  }, [open, close]);

  const margin = viewport.width <= 600 ? 12 : 24;
  const width = Math.min(400, viewport.width - margin * 2);
  const reserve = 96;
  const height = Math.max(120, Math.min(560, viewport.height - reserve - 24));
  const leftSide = position !== null && position.x < viewport.width / 2;
  const left = leftSide ? margin : Math.max(margin, viewport.width - width - margin);
  const top = Math.max(12, Math.min(position ? position.y + 100 - height : viewport.height - reserve - height, viewport.height - height - 12));

  return createPortal(<div className={`rd-floating-assistant ${launcherDragging ? 'is-dragging' : ''}`}>
    <button ref={launcher} type="button" className="rd-floating-launcher" hidden={open}
      aria-label="打开小航助手" aria-expanded={open} aria-controls="rd-floating-assistant-panel"
      aria-description="可拖动到屏幕两侧，方向键移动，Home恢复默认位置，Enter打开"
      title="打开小航 · 可拖动，方向键移动，Home复位"
      style={position ? { left: position.x, top: position.y, right: 'auto', bottom: 'auto' } : undefined}
      {...launcherEvents} onClick={launcherEvents.onClick}>
      <span className="rd-floating-figure" aria-hidden="true"><XiaohangSprite paused={launcherDragging || open} /></span>
      <span className="rd-floating-launcher-label">小航<span>有事问我</span></span>
    </button>
    <div ref={panel} id="rd-floating-assistant-panel" className="rd-floating-panel" hidden={!open}
      role="dialog" aria-modal="false" aria-label={hasCase ? `${researchCase?.title} · 小航助手` : '小航助手'}
      style={{ left, top, width, height }} onKeyDown={event => {
        if (event.key === 'Escape' && !document.querySelector('dialog[open]')) { event.stopPropagation(); close(); }
      }}>
      {project && researchCase ? <CaseAssistant key={`${project.id}/${researchCase.id}`} project={project} researchCase={researchCase}
        visible={open} onClose={close} onNavigate={onNavigate} onDirtyChange={onDirtyChange} onBusyChange={onBusyChange} />
        : <div className="rd-floating-welcome">
          <header><div><strong>小航</strong><span>研发助手</span></div><button type="button" className="rd-floating-close" aria-label="收起小航助手" title="收起（Esc）" onClick={close}>×</button></header>
          <div className="rd-floating-welcome-content"><span className="rd-floating-welcome-mark" aria-hidden="true">航</span><h2>你好，我是小航</h2><p>先开始一项任务，或打开已有项目。进入案例后，我可以帮你查资料、看进度、找到下一步。</p>
            <div className="rd-floating-welcome-actions">{onStartTask && <button type="button" className="rd-floating-primary" onClick={() => { close(); onStartTask(); }}>开始任务<span aria-hidden="true">↗</span></button>}{onOpenProjects && <button type="button" className="rd-floating-secondary" onClick={() => { close(); onOpenProjects(); }}>查看项目<span aria-hidden="true">→</span></button>}</div>
          </div><p className="rd-floating-welcome-foot">选定案例后，在这里继续对话。</p>
        </div>}
    </div>
  </div>, document.body);
}
