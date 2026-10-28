import { useEffect, useRef, useState } from 'react';
import './xiaohangSprite.css';

const SPRITE_URL = '/assets/xiaohang-idle-sprite.png';
const IDLE = [
  { frame: 0, delay: 1500 }, { frame: 1, delay: 1600 },
  { frame: 2, delay: 75 }, { frame: 3, delay: 95 }, { frame: 2, delay: 70 },
  { frame: 1, delay: 1800 }, { frame: 0, delay: 1600 },
];
const GREET = [4, 5, 6, 7, 8, 9, 10, 9, 10, 11, 12, 13, 14, 15].map(frame => ({ frame, delay: frame >= 8 && frame <= 11 ? 130 : 100 }));
interface SpriteFrame { rect: { x: number; y: number; width: number; height: number }; anchor: { x: number; y: number } }
interface SpriteAsset { image: HTMLImageElement; frames: SpriteFrame[] }

/** Local frame playback. Model requests and business state never drive the clock. */
export function XiaohangSprite({ paused = false }: { paused?: boolean }) {
  const [asset, setAsset] = useState<SpriteAsset | null>(null), [frame, setFrame] = useState(0);
  const [reduced, setReduced] = useState(false), [visible, setVisible] = useState(true), [greeting, setGreeting] = useState(1);
  const lastGreeting = useRef(Date.now()), playedGreeting = useRef(0), canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    const image = new Image();
    const loaded = new Promise<HTMLImageElement>((resolve, reject) => { image.onload = () => resolve(image); image.onerror = reject; });
    image.decoding = 'async';
    image.src = SPRITE_URL;
    const controller = new AbortController();
    void Promise.all([loaded, fetch('/assets/xiaohang-idle-sprite.json', { signal: controller.signal }).then(response => {
      if (!response.ok) throw new Error('帧图信息尚未就绪');
      return response.json() as Promise<{ frames: SpriteFrame[] }>;
    })]).then(([image, metadata]) => {
      if (!cancelled && metadata.frames.length === 16) setAsset({ image, frames: metadata.frames });
    }).catch(() => { /* The original character remains visible if an asset cannot load. */ });
    return () => { cancelled = true; controller.abort(); image.onload = null; image.onerror = null; };
  }, []);
  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const motion = () => setReduced(preference.matches);
    const visibility = () => setVisible(document.visibilityState !== 'hidden');
    motion(); visibility();
    preference.addEventListener('change', motion); document.addEventListener('visibilitychange', visibility);
    return () => { preference.removeEventListener('change', motion); document.removeEventListener('visibilitychange', visibility); };
  }, []);
  useEffect(() => {
    if (!asset || reduced || paused || !visible) { setFrame(0); return; }
    let stopped = false;
    let timer: ReturnType<typeof window.setTimeout>;
    // Breathing/rotor frames keep the body anchored. Blinks and greetings are
    // short, distinct actions, separated by quiet intervals rather than shaking.
    const prelude = greeting > playedGreeting.current ? [{ frame: 0, delay: 260 }, ...GREET] : [];
    if (prelude.length) playedGreeting.current = greeting;
    let index = 0;
    let greetingIndex = 0;
    const tick = () => {
      if (stopped) return;
      const current = greetingIndex < prelude.length ? prelude[greetingIndex++] : IDLE[index++ % IDLE.length];
      setFrame(current.frame);
      timer = window.setTimeout(tick, current.delay);
    };
    tick();
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [asset, reduced, paused, visible, greeting]);
  useEffect(() => {
    const context = canvas.current?.getContext('2d'), item = asset?.frames[frame];
    if (!context || !asset || !item) return;
    const { rect, anchor } = item;
    // Generated cells can drift by a few pixels. Use the feet, rather than the
    // waving hand's bounding-box centre, to hold the character still on screen.
    const scale = 112 / Math.max(1, anchor.y - rect.y);
    context.setTransform(2, 0, 0, 2, 0, 0);
    context.clearRect(0, 0, 124, 124);
    context.imageSmoothingEnabled = true; context.imageSmoothingQuality = 'high';
    context.drawImage(asset.image, rect.x, rect.y, rect.width, rect.height,
      62 - (anchor.x - rect.x) * scale, 119 - (anchor.y - rect.y) * scale, rect.width * scale, rect.height * scale);
  }, [asset, frame]);

  function greet() {
    const now = Date.now();
    if (reduced || paused || now - lastGreeting.current < 6000) return;
    lastGreeting.current = now;
    setGreeting(value => value + 1);
  }
  const playing = Boolean(asset) && !reduced && !paused && visible;
  return <span className={`xiaohang-sprite ${asset ? 'is-ready' : ''}`}
    data-frame={frame} data-playing={playing ? 'true' : 'false'}
    onPointerEnter={greet}>
    {asset ? <canvas ref={canvas} width={248} height={248} aria-hidden="true" /> : <img src="/assets/xiaohang.png" alt="" draggable={false} />}
  </span>;
}
