import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { createXiaohangGestureCycle, createXiaohangMotion, STILL_POSE } from './xiaohangMotion';
import { useXiaohangArt } from './useXiaohangArt';
import './xiaohangSprite.css';

const CELL = 124, DENSITY = 2;
// The boot bands of the normalized standing frames begin just below the gloves.
const LEG_TOP = 101, LEG_HEIGHT = CELL - LEG_TOP;

// Turn the camera toward the direction of travel, easing through each reversal.
function pacingYaw(t: number) {
  const stops = [[0, 14], [.16, 28], [.27, 30], [.40, -30], [.63, -32], [.77, 26], [.92, 20], [1, 14]];
  const end = stops.findIndex(([time]) => time >= t);
  if (end <= 0) return 14;
  const [startTime, from] = stops[end - 1], [endTime, to] = stops[end];
  const u = (t - startTime) / (endTime - startTime);
  return from + (to - from) * u * u * (3 - 2 * u);
}

/** Local frame playback. Model requests and business state never drive the clock. */
export function XiaohangSprite({ paused = false }: { paused?: boolean }) {
  const { art, setAtlasOnly } = useXiaohangArt();
  const [pose, setPose] = useState(STILL_POSE);
  const [gestureCycle] = useState(createXiaohangGestureCycle);
  const [fallbackFailed, setFallbackFailed] = useState(false);
  const [reduced, setReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden');
  const playback = useRef<ReturnType<typeof createXiaohangMotion> | null>(null), canvas = useRef<HTMLCanvasElement>(null);
  const leftLeg = useRef<HTMLCanvasElement>(null), rightLeg = useRef<HTMLCanvasElement>(null);
  const playing = Boolean(art) && !reduced && !paused && visible;
  const { frame, gesture, duration } = playing ? pose : STILL_POSE;
  const walking = gesture === 'march' || gesture === 'pace';

  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const motion = () => { if (preference.matches) playback.current?.stop(); setReduced(preference.matches); };
    const visibility = () => { if (document.visibilityState === 'hidden') playback.current?.stop(); setVisible(document.visibilityState !== 'hidden'); };
    motion(); visibility();
    preference.addEventListener('change', motion); document.addEventListener('visibilitychange', visibility);
    return () => { preference.removeEventListener('change', motion); document.removeEventListener('visibilitychange', visibility); };
  }, []);
  useLayoutEffect(() => {
    if (!playing) return;
    const motion = createXiaohangMotion(setPose, {
      now: () => Date.now(),
      setTimeout: (callback, delay) => window.setTimeout(callback, delay),
      clearTimeout: timer => window.clearTimeout(timer),
    }, Math.random, gestureCycle);
    playback.current = motion;
    return () => { motion.stop(); playback.current = null; };
  }, [playing, gestureCycle]);
  useLayoutEffect(() => {
    const surface = canvas.current, context = surface?.getContext('2d');
    if (!context || !art || !surface) return;
    const draw = (yaw?: number) => {
      context.setTransform(DENSITY, 0, 0, DENSITY, 0, 0);
      context.imageSmoothingEnabled = true; context.imageSmoothingQuality = 'high';
      if (art.kind === 'webgl') {
        const projected = art.renderer.draw(art.model, frame, yaw);
        if (!projected) { setAtlasOnly(true); return false; }
        context.clearRect(0, 0, CELL, CELL);
        context.drawImage(projected, 0, 0, CELL, CELL);
      } else {
        const { rect } = art.frames[frame];
        context.clearRect(0, 0, CELL, CELL);
        context.drawImage(art.image, rect.x, rect.y, rect.width, rect.height, 0, 0, CELL, CELL);
      }
      if (!walking) return true;
      // Copy only the two boot strips; CSS moves them between frame changes.
      const left = leftLeg.current?.getContext('2d'), right = rightLeg.current?.getContext('2d');
      const w = CELL / 2 * DENSITY, h = LEG_HEIGHT * DENSITY;
      for (const [index, leg] of [left, right].entries()) {
        if (!leg) continue;
        leg.clearRect(0, 0, w, h);
        leg.drawImage(surface, index * w, LEG_TOP * DENSITY, w, h, 0, 0, w, h);
      }
      return true;
    };
    if (art.kind !== 'webgl' || gesture !== 'pace') { draw(); return; }
    // Only pacing needs changing camera views. All other poses paint on demand.
    const movement = surface.parentElement?.getAnimations()[0];
    let timer = 0, previousYaw = Infinity;
    const turn = () => {
      const yaw = pacingYaw(Math.min(1, Number(movement?.currentTime ?? 0) / duration));
      if (Math.abs(yaw - previousYaw) >= .5) {
        if (!draw(yaw)) return;
        previousYaw = yaw;
      }
      timer = window.setTimeout(turn, 1000 / 24);
    };
    turn();
    return () => clearTimeout(timer);
  }, [art, frame, gesture, duration, walking, setAtlasOnly]);

  return <span className={`xiaohang-sprite ${art ? 'is-ready' : ''}`} data-renderer={art?.kind ?? 'portrait'}
    style={{ '--xiaohang-gesture-duration': `${duration}ms`, '--xiaohang-leg-height': `${100 * LEG_HEIGHT / CELL}%` } as CSSProperties}
    data-frame={frame} data-playing={playing ? 'true' : 'false'} data-gesture={gesture}
    onPointerEnter={() => { if (playing) playback.current?.greet(); }}>
    <span className="xiaohang-sprite-motion" style={{ animationDuration: `${duration}ms` }}>
      {art ? <canvas ref={canvas} className={walking ? 'xiaohang-step-body' : undefined} width={CELL * DENSITY} height={CELL * DENSITY} aria-hidden="true" /> : fallbackFailed ? <span className="xiaohang-sprite-fallback">航</span> : <img src="/assets/xiaohang-3d-portrait.png" alt="" draggable={false} onError={() => setFallbackFailed(true)} />}
      {walking && <>
        <canvas ref={leftLeg} className="xiaohang-step-leg is-left" width={CELL / 2 * DENSITY} height={LEG_HEIGHT * DENSITY} aria-hidden="true" />
        <canvas ref={rightLeg} className="xiaohang-step-leg is-right" width={CELL / 2 * DENSITY} height={LEG_HEIGHT * DENSITY} aria-hidden="true" />
      </>}
    </span>
    {gesture === 'float' && <svg className="xiaohang-flight-prop" viewBox="0 0 124 124" aria-hidden="true" focusable="false">
      <g className="xiaohang-thrust" fill="none" stroke="currentColor" strokeLinecap="round">
        <path d="M49 105v12m4-10v7M72 105v12m-4-10v7" strokeWidth="3" />
        <path d="M37 120h14m19 0h14" strokeWidth="1.5" opacity=".35" />
      </g>
    </svg>}
    {gesture === 'orbit' && <svg className="xiaohang-flight-prop" viewBox="0 0 124 124" aria-hidden="true" focusable="false">
      <ellipse className="xiaohang-orbit-trail" cx="62" cy="63" rx="49" ry="24" transform="rotate(-28 62 63)" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 6" />
      <g className="xiaohang-satellite" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
        <rect className="xiaohang-prop-surface" x="-5" y="-5" width="10" height="10" rx="2" />
        <path className="xiaohang-prop-panel" d="M-15-4h8v8h-8Zm22 0h8v8H7Z" />
        <path d="M0-5v-5m-2 0h4M-11-4v8m22-8v8" fill="none" />
        <circle cx="0" cy="0" r="1.5" fill="currentColor" stroke="none" />
      </g>
    </svg>}
    {gesture === 'dock' && <svg className="xiaohang-flight-prop" viewBox="0 0 124 124" aria-hidden="true" focusable="false">
      <g className="xiaohang-connector-left" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" fill="none">
        <path d="M37 91H21q-7 0-7 7" strokeLinecap="round" />
        <path className="xiaohang-prop-panel" d="M36 83h9v16h-9z" />
        <path className="xiaohang-prop-surface" d="M45 80h11v22H45z" />
        <path d="M56 85h7m-7 6h7m-7 6h7" />
      </g>
      <g className="xiaohang-connector-right" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" fill="none">
        <path d="M87 91h16q7 0 7 7" strokeLinecap="round" />
        <path className="xiaohang-prop-panel" d="M79 83h9v16h-9z" />
        <path className="xiaohang-prop-surface" d="M64 80h15v22H64z" />
        <path d="M69 85h5m-5 6h5m-5 6h5" />
      </g>
      <g className="xiaohang-connection-signal" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <path d="M58 72l4 4 6-8" />
        <path d="M53 68l-3-3m20 0 3-3M62 63v-4" opacity=".55" />
      </g>
    </svg>}
    {gesture === 'rocket' && <svg className="xiaohang-flight-prop" viewBox="0 0 124 124" aria-hidden="true" focusable="false">
      <g className="xiaohang-launch-trail" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <path d="M18 105c-5-17 1-33 4-49" strokeDasharray="2 6" />
        <path d="M11 113h24m-18 5h12" opacity=".55" />
      </g>
      <g className="xiaohang-mini-rocket" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
        <path className="xiaohang-prop-panel" d="m-6 1-6 8v5l7-4m11-9 6 8v5l-7-4" />
        <path className="xiaohang-prop-surface" d="M0-17C-7-10-8 1-5 10H5C8 1 7-10 0-17Z" />
        <circle className="xiaohang-prop-panel" cy="-3" r="3.5" />
        <path d="M-4 11h8" strokeLinecap="round" />
        <path className="xiaohang-rocket-flame" d="M-3 14Q-4 21 0 25Q4 21 3 14" fill="currentColor" stroke="none" />
      </g>
    </svg>}
    {gesture === 'moonwalk' && <svg className="xiaohang-flight-prop" viewBox="0 0 124 124" aria-hidden="true" focusable="false">
      <g className="xiaohang-moon-surface" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
        <path className="xiaohang-prop-panel" d="M14 111Q62 119 110 111Q91 123 62 123Q33 123 14 111Z" />
        <path d="M21 111q7-3 12 0m57 0q7-3 12 0" fill="none" opacity=".45" />
        <circle cx="29" cy="117" r="1.5" fill="currentColor" stroke="none" opacity=".45" />
        <circle cx="92" cy="117" r="2" fill="currentColor" stroke="none" opacity=".35" />
      </g>
      <g className="xiaohang-moon-footprints-left" fill="currentColor">
        <ellipse cx="36" cy="114" rx="1.8" ry="2.6" transform="rotate(-28 36 114)" />
        <ellipse cx="43" cy="116" rx="1.8" ry="2.6" transform="rotate(-28 43 116)" />
      </g>
      <g className="xiaohang-moon-footprints-right" fill="currentColor">
        <ellipse cx="81" cy="116" rx="1.8" ry="2.6" transform="rotate(28 81 116)" />
        <ellipse cx="88" cy="114" rx="1.8" ry="2.6" transform="rotate(28 88 114)" />
      </g>
      <g className="xiaohang-moon-dust" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
        <path d="m34 101-5-4m17 7-1-6m35 5 2-6m11 4 5-4" />
      </g>
    </svg>}
    {gesture === 'stargaze' && <svg className="xiaohang-flight-prop" viewBox="0 0 124 124" aria-hidden="true" focusable="false">
      <g className="xiaohang-telescope" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round">
        <path className="xiaohang-prop-panel" d="M-10-4H12V4H-10Z" />
        <path className="xiaohang-prop-surface" d="M10-7H18V7H10Z" />
        <path d="M-14-3v6m0-3h4M18-6v12M-1 5v7m-5 0h10" fill="none" />
        <path d="M14-4v8" opacity=".35" />
      </g>
      <g className="xiaohang-star-near" fill="currentColor" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round">
        <path d="m101 13 2.2 5.8L109 21l-5.8 2.2L101 29l-2.2-5.8L93 21l5.8-2.2Z" />
      </g>
      <g className="xiaohang-star-far" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <path d="M86 10v7m-3.5-3.5h7M114 36v8m-4-4h8" />
        <circle cx="116" cy="15" r="1.5" fill="currentColor" stroke="none" />
      </g>
    </svg>}
    {gesture === 'signal' && <svg className="xiaohang-flight-prop" viewBox="0 0 124 124" aria-hidden="true" focusable="false">
      <g className="xiaohang-radio-dish" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path className="xiaohang-prop-surface" d="M86 66Q85 82 103 83Z" />
        <path d="m96 76 8-9m-9 15v22m-7 0h14" fill="none" />
        <circle cx="105" cy="66" r="2.6" fill="currentColor" stroke="none" />
        <rect className="xiaohang-prop-panel" x="89" y="90" width="12" height="9" rx="2" />
      </g>
      <g className="xiaohang-radio-send" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <path d="M107 56q8 3 9 12M108 47q14 4 14 20" />
      </g>
      <g className="xiaohang-radio-receive" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <path d="M86 47q10-3 17 3M89 56q5-1 9 2" />
      </g>
      <g className="xiaohang-radio-reply" fill="currentColor">
        <circle cx="95" cy="94.5" r="2.5" />
        <circle cx="106" cy="91" r="1.6" opacity=".65" />
      </g>
    </svg>}
  </span>;
}
