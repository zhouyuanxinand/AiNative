import { useCallback, useEffect, useRef, useState } from 'react';
import { rdAssistantWeather } from '../api';
import './assistantWeather.css';

export interface AssistantWeatherData {
  status: 'ok' | 'unavailable';
  location: string;
  temperature_c?: number;
  apparent_temperature_c?: number | null;
  condition?: string;
  weather_code?: number | null;
  is_day?: boolean | null;
  wind_speed_kmh?: number | null;
  observed_at?: string;
  fetched_at?: string;
  source?: string;
  source_url?: string;
  notice?: string;
}

export function useAssistantWeather(enabled: boolean) {
  const [data, setData] = useState<AssistantWeatherData | null>(null);
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden');
  const lastRead = useRef(0);
  useEffect(() => {
    const change = () => setVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', change);
    return () => document.removeEventListener('visibilitychange', change);
  }, []);
  useEffect(() => {
    if (!enabled || !visible) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const read = async () => {
      setLoading(true);
      try {
        const result = await rdAssistantWeather(controller.signal);
        if (!controller.signal.aborted) { setData(result); lastRead.current = Date.now(); }
      } catch {
        if (!controller.signal.aborted) {
          setData({ status: 'unavailable', location: '洛阳 · 涧西区', notice: '天气暂时未能获取，请稍后重试。' });
          lastRead.current = Date.now();
        }
      } finally {
        if (!controller.signal.aborted) { setLoading(false); timer = setTimeout(() => void read(), 600_000); }
      }
    };
    timer = setTimeout(() => void read(), Math.max(0, 600_000 - (Date.now() - lastRead.current)));
    return () => { controller.abort(); clearTimeout(timer); setLoading(false); };
  }, [enabled, visible, revision]);
  const refresh = useCallback(() => { lastRead.current = 0; setRevision(value => value + 1); }, []);
  return { data, loading, refresh };
}

/** Occasional, dismissible hints only while the user is idle. */
export function useWeatherNudge(enabled: boolean) {
  const [show, setShow] = useState(false);
  const [allowed, setAllowed] = useState(false);
  const nextAt = useRef(Date.now() + 12_000);
  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setAllowed(!preference.matches && document.visibilityState !== 'hidden');
    update(); preference.addEventListener('change', update); document.addEventListener('visibilitychange', update);
    return () => { preference.removeEventListener('change', update); document.removeEventListener('visibilitychange', update); };
  }, []);
  const dismiss = useCallback(() => { setShow(false); nextAt.current = Date.now() + 300_000; }, []);
  useEffect(() => {
    if (!enabled || !allowed) { setShow(false); return; }
    let closeTimer: ReturnType<typeof setTimeout>;
    const activity = (event: Event) => {
      if (event.target instanceof Element && event.target.closest('.rd-weather-nudge')) return;
      setShow(false); nextAt.current = Math.max(nextAt.current, Date.now() + 60_000);
    };
    const timer = setInterval(() => {
      if (Date.now() < nextAt.current || document.querySelector('[role="dialog"][aria-modal="true"],dialog[open]')) return;
      setShow(true); nextAt.current = Date.now() + 300_000 + Math.random() * 120_000;
      closeTimer = setTimeout(() => setShow(false), 10_000);
    }, 1000);
    document.addEventListener('pointerdown', activity); document.addEventListener('keydown', activity);
    return () => { clearInterval(timer); clearTimeout(closeTimer); document.removeEventListener('pointerdown', activity); document.removeEventListener('keydown', activity); };
  }, [enabled, allowed]);
  return { show: show && enabled && allowed, dismiss };
}

function conditionOf(data: AssistantWeatherData) {
  if (data.condition) return data.condition;
  const code = data.weather_code;
  if (code === 0) return '晴';
  if (code != null && code <= 3) return '多云';
  if (code != null && code >= 95) return '雷雨';
  if (code != null && [71,73,75,77,85,86].includes(code)) return '雪';
  if (code != null && code >= 51) return '雨';
  return '天气预报';
}

export function WeatherIcon({ condition = '', night = false }: { condition?: string; night?: boolean }) {
  const rainy = /雨|rain|sleet/i.test(condition), snow = /雪|snow/i.test(condition);
  return <svg viewBox="0 0 40 40" fill="none" aria-hidden="true" className="rd-weather-icon">
    {night ? <path d="M26 7a12 12 0 1 0 7 19A12 12 0 0 1 26 7Z" fill="currentColor" opacity=".35" /> : <><circle cx="16" cy="15" r="7" fill="currentColor" opacity=".55"/><path d="M16 3v3m0 18v3M4 15H1m30 0h-3M7 6l2 2m14 14 2 2M7 24l2-2M23 8l2-2" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></>}
    {!/^(晴|clear)/i.test(condition) && <path d="M13 28a7 7 0 0 1-1-14 9 9 0 0 1 17 2 6 6 0 1 1 1 12Z" fill="var(--color-bg-surface)" stroke="currentColor" strokeWidth="1.5"/>}
    {(rainy || snow) && <path d={snow ? 'M16 32v5m-2-2h4m8-3v5m-2-2h4' : 'm16 32-2 4m12-4-2 4'} stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>}
  </svg>;
}

export function AssistantWeatherCard({ data, loading, onClose, onRefresh, compact = false }: {
  data: AssistantWeatherData | null; loading: boolean; onClose: () => void; onRefresh: () => void; compact?: boolean;
}) {
  const good = data?.status === 'ok' && Number.isFinite(data.temperature_c);
  const condition = data ? conditionOf(data) : '';
  const time = data?.observed_at ? new Date(data.observed_at) : null;
  const timeLabel = time && Number.isFinite(time.getTime()) ? time.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) : '';
  const sourceUrl = data?.source_url?.startsWith('https://') ? data.source_url : undefined;
  return <section className={`rd-weather-card ${compact ? 'is-compact' : ''}`} aria-label="洛阳涧西天气">
    <header><span>{data?.location || '洛阳 · 涧西区'}</span><button type="button" aria-label="收起天气" onClick={onClose}>×</button></header>
    {good ? <><div className="rd-weather-current"><WeatherIcon condition={condition} night={data?.is_day === false}/><strong>{Math.round(data!.temperature_c!)}<span>°C</span></strong><div><b>{condition}</b><span>当地预报</span></div></div>
      <p className="rd-weather-advice">{/雨|雪|rain|snow|sleet/i.test(condition) ? '出门记得带伞，路上慢一点。' : data!.temperature_c! < 12 ? '外面有些凉，记得添件衣服。' : data!.temperature_c! >= 30 ? '天气有些热，记得喝水。' : '忙碌之余，也记得伸个懒腰。'}</p>
      {!compact && <p className="rd-weather-details">{timeLabel && `${timeLabel} 预报 · 北京时间`}{data?.wind_speed_kmh != null && ` · 风速 ${Math.round(data.wind_speed_kmh)} km/h`}</p>}
    </> : <p className="rd-weather-empty" role={compact ? undefined : 'status'}>{loading ? '正在看看涧西的天气…' : data?.notice || '天气暂时未能获取。'}</p>}
    <footer className="rd-weather-actions">
      {(!compact || !good) && <button className="rd-weather-refresh" type="button" onClick={onRefresh} disabled={loading}>{loading ? '正在更新…' : '刷新天气'}</button>}
      {good && <details className="rd-weather-source"><summary>天气来源</summary><div>
        {sourceUrl ? <a href={sourceUrl} target="_blank" rel="noreferrer">{data?.source || '天气来源'} ↗</a> : <span>{data?.source || '天气服务'}</span>}
        {/MET Norway/i.test(data?.source || '') && <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0 · 已转译</a>}
      </div></details>}
    </footer>
  </section>;
}
