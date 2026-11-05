import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { CaseAssistant } from './CaseAssistant';
import { XiaohangSprite } from './assistant/XiaohangSprite';
import { useAssistantLauncherDrag } from './assistant/useAssistantLauncherDrag';
import { AssistantWeatherCard, WeatherIcon, useAssistantWeather, useWeatherNudge } from './assistant/AssistantWeather';
import { WelcomeAssistant, type WelcomeAssistantHandle } from './assistant/WelcomeAssistant';
import { useGreetingBubble } from './assistant/useGreetingBubble';
import type { Project, ResearchCase } from './types';
import type { AssistantNavigation } from './assistant/nativeNavigation';
import './FloatingAssistant.css';

const ignoreBoolean = (_value: boolean) => {};
const ignoreTarget = (_target: AssistantNavigation) => {};
const viewportSize = () => ({ width: window.innerWidth, height: window.visualViewport?.height ?? window.innerHeight });

export interface FloatingAssistantProps {
  project?: Project;
  researchCase?: ResearchCase;
  onNavigate?: (target: AssistantNavigation) => void;
  onDirtyChange?: (dirty: boolean) => void;
  onBusyChange?: (busy: boolean) => void;
  onStartTask?: () => void;
  onOpenProjects?: () => void;
}

/** A visual shell only. The case conversation retains its original API and draft ownership. */
export function FloatingAssistant({ project, researchCase, onNavigate = ignoreTarget,
  onDirtyChange = ignoreBoolean, onBusyChange = ignoreBoolean, onStartTask, onOpenProjects }: FloatingAssistantProps) {
  const [open, setOpen] = useState(false);
  const [weatherExpanded, setWeatherExpanded] = useState(false);
  const [weatherPreview, setWeatherPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [viewport, setViewport] = useState(viewportSize);
  const launcher = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const welcome = useRef<WelcomeAssistantHandle>(null);
  const dock = useRef<HTMLButtonElement>(null);
  const weatherBubble = useRef<HTMLDivElement>(null);
  const weatherOverlay = useRef<HTMLDivElement>(null);
  const weatherShortcut = useRef<HTMLButtonElement>(null);
  const previewTimer = useRef<ReturnType<typeof setTimeout>>();
  const leaveTimer = useRef<ReturnType<typeof setTimeout>>();
  const skipPreviewFocus = useRef(false);
  const wasOpen = useRef(false);
  const restoreFocus = useRef(true);
  const activate = useCallback(() => setOpen(true), []);
  const close = useCallback(() => { setOpen(false); setWeatherExpanded(false); }, []);
  const { position, launcherDragging, launcherPressed, dockedEdge, dockingEdge, reveal, launcherEvents } = useAssistantLauncherDrag(launcher, !open, activate);
  const hasCase = Boolean(project && researchCase);
  const requestClose = useCallback(() => { if (hasCase) close(); else welcome.current?.requestClose(); }, [hasCase, close]);
  const weather = useAssistantWeather(open || !dockedEdge);
  const nudge = useWeatherNudge(!open && !dockedEdge && !launcherPressed && !launcherDragging && !busy && weather.data?.status === 'ok');
  const canPreviewWeather = !open && !dockedEdge && !launcherPressed && !launcherDragging && !busy;
  const weatherSpeaking = canPreviewWeather && (weatherPreview || nudge.show);
  const greetingVisible = useGreetingBubble(!open && !dockedEdge && !launcherPressed && !launcherDragging && !busy && !weatherSpeaking);
  const showWeather = useCallback(() => setWeatherExpanded(true), []);
  const changeBusy = useCallback((value: boolean) => { setBusy(value); onBusyChange(value); }, [onBusyChange]);

  function clearPreviewTimers() { clearTimeout(previewTimer.current); clearTimeout(leaveTimer.current); }
  function previewWeather() {
    clearPreviewTimers();
    if (canPreviewWeather) previewTimer.current = setTimeout(() => setWeatherPreview(true), 500);
  }
  function leaveWeather(next: EventTarget | null) {
    if (next instanceof Node && (launcher.current?.contains(next) || weatherBubble.current?.contains(next))) return;
    clearPreviewTimers();
    leaveTimer.current = setTimeout(() => { setWeatherPreview(false); nudge.dismiss(); }, 300);
  }
  function dismissWeatherBubble(restore = false) {
    clearPreviewTimers(); setWeatherPreview(false); nudge.dismiss();
    if (restore && document.activeElement !== launcher.current) { skipPreviewFocus.current = true; launcher.current?.focus({ preventScroll: true }); }
  }

  useEffect(() => {
    if (!canPreviewWeather) { clearPreviewTimers(); setWeatherPreview(false); }
    return clearPreviewTimers;
  }, [canPreviewWeather]);

  useEffect(() => {
    const hidden = () => { if (document.visibilityState === 'hidden') { clearPreviewTimers(); setWeatherPreview(false); } };
    document.addEventListener('visibilitychange', hidden);
    return () => document.removeEventListener('visibilitychange', hidden);
  }, []);

  useEffect(() => {
    if (!weatherExpanded && !weatherSpeaking) return;
    const outside = (event: PointerEvent) => {
      if (!(event.target instanceof Node)) return;
      if (weatherExpanded && !weatherOverlay.current?.contains(event.target) && !weatherShortcut.current?.contains(event.target)) setWeatherExpanded(false);
      if (weatherSpeaking && !weatherBubble.current?.contains(event.target) && !launcher.current?.contains(event.target)) dismissWeatherBubble();
    };
    document.addEventListener('pointerdown', outside, true);
    return () => document.removeEventListener('pointerdown', outside, true);
  }, [weatherExpanded, weatherSpeaking]);

  useEffect(() => {
    if (dockedEdge && document.activeElement === launcher.current) dock.current?.focus({ preventScroll: true });
  }, [dockedEdge]);

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
    if (wasOpen.current && restoreFocus.current && !document.querySelector('dialog[open], [role="dialog"][aria-modal="true"]')) launcher.current?.focus({ preventScroll: true });
  }, [open, project?.id, researchCase?.id]);

  useEffect(() => {
    if (!open) return;
    let startedOutside = false;
    const isOutside = (event: MouseEvent) => event.target instanceof Node
      && !panel.current?.contains(event.target) && !launcher.current?.contains(event.target)
      && !document.querySelector('dialog[open], [role="dialog"][aria-modal="true"]');
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
      requestClose();
    };
    document.addEventListener('pointerdown', pointerDown, true);
    document.addEventListener('pointercancel', pointerCancel, true);
    document.addEventListener('click', click);
    return () => {
      document.removeEventListener('pointerdown', pointerDown, true);
      document.removeEventListener('pointercancel', pointerCancel, true);
      document.removeEventListener('click', click);
    };
  }, [open, requestClose]);

  const margin = viewport.width <= 600 ? 12 : 24;
  const width = Math.min(420, viewport.width - margin * 2);
  const reserve = 96;
  const height = Math.max(120, Math.min(560, viewport.height - reserve - 24));
  const floatingPosition = position;
  const leftSide = floatingPosition !== null && floatingPosition.x < viewport.width / 2;
  const left = leftSide ? margin : Math.max(margin, viewport.width - width - margin);
  const top = Math.max(12, Math.min(floatingPosition ? floatingPosition.y + 100 - height : viewport.height - reserve - height, viewport.height - height - 12));
  const figureSize = viewport.height <= 480 ? 76 : viewport.width <= 600 ? 70 : 100;
  const weatherAnchorX = (position?.x ?? viewport.width - margin - figureSize) + figureSize / 2;
  const weatherAnchorY = position?.y ?? viewport.height - reserve - 24 - figureSize;
  const weatherLeft = Math.max(12, Math.min(weatherAnchorX - 120, viewport.width - 252));
  const weatherSpaceAbove = Math.max(0, weatherAnchorY - 28);
  const weatherSpaceBelow = Math.max(0, viewport.height - weatherAnchorY - figureSize - 24);
  const weatherAbove = weatherSpaceAbove >= weatherSpaceBelow;
  const greetingBelow = position !== null && position.y < 96;

  const launcherButton = <button ref={launcher} type="button" className="rd-floating-launcher" hidden={open}
    aria-label="打开小航助手" aria-expanded={open} aria-controls="rd-floating-assistant-panel"
    aria-description="悬停或聚焦查看天气；点击或Enter打开对话。可拖至屏幕边缘收起，方向键移动，Escape收起，Home恢复默认位置"
    aria-hidden={!!dockedEdge || undefined} tabIndex={dockedEdge ? -1 : 0}
    title="悬停看天气 · 点击问小航 · 拖至边缘收起"
    style={floatingPosition ? { left: floatingPosition.x, top: floatingPosition.y, right: 'auto', bottom: 'auto' } : undefined}
    {...launcherEvents}
    onPointerEnter={event => { if (event.pointerType === 'mouse') previewWeather(); }}
    onPointerLeave={event => leaveWeather(event.relatedTarget)}
    onFocus={event => { if (skipPreviewFocus.current) { skipPreviewFocus.current = false; return; } if (event.currentTarget.matches(':focus-visible')) previewWeather(); }}
    onBlur={event => leaveWeather(event.relatedTarget)}
    onKeyDown={event => {
      if (event.key === 'Escape' && weatherSpeaking) { event.preventDefault(); dismissWeatherBubble(); }
      else launcherEvents.onKeyDown(event);
    }}>
      <span className="rd-floating-figure" aria-hidden="true"><XiaohangSprite paused={launcherPressed || launcherDragging || !!dockedEdge || open} /></span>
      <span className="rd-floating-launcher-label" aria-hidden={!greetingVisible} data-visible={greetingVisible}>小航<span>有事问我</span></span>
  </button>;

  return createPortal(<div className={`rd-floating-assistant ${launcherDragging ? 'is-dragging' : ''} ${dockedEdge ? 'is-docked' : ''} ${weatherSpeaking ? 'is-weather-speaking' : ''}${greetingBelow ? ' is-greeting-below' : ''}`}>
    {launcherButton}
    {dockedEdge && !open && <button ref={dock} type="button" className={`rd-assistant-dock is-${dockedEdge}`} aria-label="唤回小航助手" title="唤回小航 · Home恢复默认位置"
      style={{ top: Math.max(12, Math.min((position?.y ?? viewport.height - 180) + 12, viewport.height - 148)) }} onClick={reveal}
      onKeyDown={event => { if (event.key === 'Home') { launcherEvents.onKeyDown(event); reveal(); } }}><span aria-hidden="true">{dockedEdge === 'left' ? '›' : '‹'}</span><span>小航<span className="rd-assistant-dock-latin">AI</span>智能助手</span></button>}
    {dockingEdge && launcherDragging && <div className={`rd-assistant-dock-hint is-${dockingEdge}`} role="status" style={{ top: Math.max(16, Math.min(position?.y ?? 100, viewport.height - 150)) }}>松手收起</div>}
    {weatherSpeaking && <div ref={weatherBubble} className={`rd-weather-nudge ${weatherAbove ? 'is-above' : 'is-below'}`} style={{ left: weatherLeft, top: weatherAbove ? weatherAnchorY - 14 : weatherAnchorY + figureSize + 12, '--weather-tail-x': `${Math.max(16, Math.min(weatherAnchorX - weatherLeft, 224))}px`, '--weather-available-height': `${weatherAbove ? weatherSpaceAbove : weatherSpaceBelow}px` } as CSSProperties}
      onPointerEnter={() => clearPreviewTimers()} onPointerLeave={event => leaveWeather(event.relatedTarget)}
      onFocusCapture={() => clearPreviewTimers()} onBlurCapture={event => leaveWeather(event.relatedTarget)}
      onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); dismissWeatherBubble(true); } }}>
      <AssistantWeatherCard data={weather.data} loading={weather.loading} onClose={() => dismissWeatherBubble(true)} onRefresh={weather.refresh} compact />
    </div>}
    <div ref={panel} id="rd-floating-assistant-panel" className="rd-floating-panel" hidden={!open}
      role="dialog" aria-modal="false" aria-label={hasCase ? `${researchCase?.title} · 小航助手` : '小航助手'}
      style={{ left, top, width, height }} onKeyDown={event => {
        if (event.key === 'Escape' && !document.querySelector('dialog[open], [role="dialog"][aria-modal="true"]')) { event.stopPropagation(); if (weatherExpanded) setWeatherExpanded(false); else requestClose(); }
      }}>
      <button ref={weatherShortcut} type="button" className="rd-weather-shortcut" aria-label="查看洛阳涧西天气" aria-expanded={weatherExpanded} aria-controls="rd-assistant-weather-overlay" onClick={() => setWeatherExpanded(value => !value)} title="洛阳涧西天气"><WeatherIcon condition="晴" /></button>
      {weatherExpanded && <div ref={weatherOverlay} id="rd-assistant-weather-overlay" className="rd-weather-overlay"><AssistantWeatherCard data={weather.data} loading={weather.loading} onClose={() => { setWeatherExpanded(false); weatherShortcut.current?.focus(); }} onRefresh={weather.refresh}/></div>}
      {project && researchCase ? <CaseAssistant key={`${project.id}/${researchCase.id}`} project={project} researchCase={researchCase}
        visible={open} onClose={close} onNavigate={onNavigate} onDirtyChange={onDirtyChange} onBusyChange={changeBusy} />
        : <WelcomeAssistant ref={welcome} visible={open} onClose={close} onStartTask={onStartTask} onOpenProjects={onOpenProjects} onWeather={showWeather} onDirtyChange={onDirtyChange} onBusyChange={changeBusy} />}
    </div>
  </div>, document.body);
}
