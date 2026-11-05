type Gesture = 'idle' | 'peek' | 'sway' | 'hop' | 'wave' | 'march' | 'pace' | 'float' | 'orbit' | 'dock' | 'rocket' | 'moonwalk' | 'stargaze' | 'signal';
type ActiveGesture = Exclude<Gesture, 'idle'>;
interface Step { frame: number; delay: number }
export interface XiaohangPose { frame: number; gesture: Gesture; duration: number }
interface MotionClock {
  now: () => number;
  setTimeout: (callback: () => void, delay: number) => number;
  clearTimeout: (timer: number) => void;
}

const IDLE: Step[] = [
  { frame: 0, delay: 1500 }, { frame: 1, delay: 1600 },
  { frame: 2, delay: 75 }, { frame: 3, delay: 95 }, { frame: 2, delay: 70 },
  { frame: 1, delay: 1800 }, { frame: 0, delay: 1600 },
];
const MOTIONS: Record<ActiveGesture, Step[]> = {
  peek: [{ frame: 1, delay: 280 }, { frame: 2, delay: 75 }, { frame: 3, delay: 95 }, { frame: 2, delay: 70 }, { frame: 1, delay: 680 }],
  sway: [{ frame: 1, delay: 800 }, { frame: 0, delay: 650 }],
  hop: [{ frame: 1, delay: 170 }, { frame: 0, delay: 390 }, { frame: 1, delay: 260 }],
  march: [{ frame: 0, delay: 1920 }, { frame: 2, delay: 75 }, { frame: 3, delay: 95 }, { frame: 2, delay: 70 }, { frame: 1, delay: 2640 }],
  pace: [{ frame: 0, delay: 3000 }, { frame: 2, delay: 75 }, { frame: 3, delay: 95 }, { frame: 2, delay: 70 }, { frame: 0, delay: 3160 }],
  wave: [4, 5, 6, 7, 8, 9, 10, 9, 10, 11, 12, 13, 14, 15].map(frame => ({ frame, delay: frame >= 8 && frame <= 11 ? 130 : 100 })),
  float: [{ frame: 1, delay: 240 }, { frame: 0, delay: 4200 }, { frame: 3, delay: 180 }, { frame: 1, delay: 1380 }],
  orbit: [{ frame: 4, delay: 250 }, { frame: 6, delay: 350 }, { frame: 7, delay: 500 }, { frame: 8, delay: 3600 }, { frame: 12, delay: 550 }, { frame: 14, delay: 650 }, { frame: 0, delay: 600 }],
  dock: [{ frame: 4, delay: 350 }, { frame: 5, delay: 2200 }, { frame: 3, delay: 200 }, { frame: 5, delay: 2250 }, { frame: 14, delay: 500 }, { frame: 0, delay: 500 }],
  rocket: [{ frame: 1, delay: 350 }, { frame: 4, delay: 400 }, { frame: 7, delay: 650 }, { frame: 8, delay: 3300 }, { frame: 12, delay: 600 }, { frame: 0, delay: 700 }],
  moonwalk: [{ frame: 1, delay: 300 }, { frame: 0, delay: 2800 }, { frame: 3, delay: 180 }, { frame: 1, delay: 2700 }, { frame: 0, delay: 520 }],
  stargaze: [{ frame: 4, delay: 400 }, { frame: 6, delay: 500 }, { frame: 8, delay: 4400 }, { frame: 12, delay: 600 }, { frame: 0, delay: 600 }],
  signal: [{ frame: 4, delay: 350 }, { frame: 5, delay: 2300 }, { frame: 3, delay: 180 }, { frame: 5, delay: 2170 }, { frame: 14, delay: 500 }, { frame: 0, delay: 500 }],
};
const COMPANION_GESTURES: ActiveGesture[] = ['peek', 'sway', 'march', 'hop', 'pace', 'wave'];
const AEROSPACE_GESTURES: ActiveGesture[] = ['float', 'rocket', 'moonwalk', 'orbit', 'stargaze', 'signal', 'dock'];
export const STILL_POSE: XiaohangPose = { frame: 0, gesture: 'idle', duration: 0 };

/** Keep selection history separate from playback so pausing does not restart the rotation. */
export function createXiaohangGestureCycle(random = Math.random) {
  interface Pool { all: ActiveGesture[]; remaining: ActiveGesture[]; previous: ActiveGesture | null }
  const companion: Pool = { all: COMPANION_GESTURES, remaining: [], previous: null };
  const aerospace: Pool = { all: AEROSPACE_GESTURES, remaining: [], previous: null };
  let aerospaceNext = false;
  return {
    next(): ActiveGesture {
      const pool = aerospaceNext ? aerospace : companion;
      if (!pool.remaining.length) pool.remaining = [...pool.all];
      const choices = pool.remaining.filter(gesture => gesture !== pool.previous);
      const gesture = choices[Math.floor(random() * choices.length)];
      pool.remaining.splice(pool.remaining.indexOf(gesture), 1);
      pool.previous = gesture;
      aerospaceNext = !aerospaceNext;
      return gesture;
    },
    noteGreeting() {
      if (!companion.remaining.length) companion.remaining = [...companion.all];
      companion.remaining = companion.remaining.filter(gesture => gesture !== 'wave');
      companion.previous = 'wave';
    },
  };
}

/** Local, cancellable playback; the character never changes launcher geometry. */
export function createXiaohangMotion(
  paint: (pose: XiaohangPose) => void,
  clock: MotionClock,
  random = Math.random,
  cycle = createXiaohangGestureCycle(random),
) {
  let stopped = false, active: Gesture = 'idle';
  let frameTimer = 0, gestureTimer = 0, lastGreeting = -Infinity;

  function playFrames(steps: Step[], gesture: Gesture, complete?: () => void) {
    clock.clearTimeout(frameTimer);
    const duration = gesture === 'idle' ? 0 : steps.reduce((sum, step) => sum + step.delay, 0);
    let index = 0;
    function tick() {
      if (stopped) return;
      if (index === steps.length && complete) { complete(); return; }
      const step = steps[index++ % steps.length];
      paint({ frame: step.frame, gesture, duration });
      frameTimer = clock.setTimeout(tick, step.delay);
    }
    tick();
  }

  function quiet() {
    if (stopped) return;
    active = 'idle';
    playFrames(IDLE, active);
    gestureTimer = clock.setTimeout(() => perform(cycle.next()), 8000 + Math.floor(random() * 10001));
  }

  function perform(gesture: ActiveGesture) {
    clock.clearTimeout(gestureTimer);
    active = gesture;
    if (gesture === 'wave') lastGreeting = clock.now();
    playFrames(MOTIONS[gesture], gesture, quiet);
  }

  quiet();
  return {
    greet() {
      if (stopped || active !== 'idle' || clock.now() - lastGreeting < 6000) return false;
      cycle.noteGreeting();
      perform('wave');
      return true;
    },
    stop() {
      if (stopped) return;
      stopped = true;
      clock.clearTimeout(frameTimer);
      clock.clearTimeout(gestureTimer);
      paint(STILL_POSE);
    },
  };
}
