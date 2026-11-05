import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(new URL('../../../../package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('./xiaohangMotion.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } });
const module = { exports: {} };
new Function('module', 'exports', outputText)(module, module.exports);
const { createXiaohangMotion, createXiaohangGestureCycle } = module.exports;

function fixture(random = () => 0, cycle) {
  let now = 0, id = 0;
  const timers = new Map(), history = [];
  const clock = {
    now: () => now,
    setTimeout: (callback, delay) => { const key = ++id; timers.set(key, { at: now + delay, callback }); return key; },
    clearTimeout: key => timers.delete(key),
  };
  const motion = createXiaohangMotion(state => history.push({ ...state, at: now }), clock, random, cycle);
  const advance = duration => {
    const target = now + duration;
    while (true) {
      const next = [...timers.entries()].sort((left, right) => left[1].at - right[1].at)[0];
      if (!next || next[1].at > target) break;
      now = next[1].at; timers.delete(next[0]); next[1].callback();
    }
    now = target;
  };
  return { motion, timers, history, advance, state: () => history.at(-1) };
}

test('keeps the initial quiet interval and returns to quiet between brief, non-repeating gestures', () => {
  const sample = fixture();
  sample.advance(7999);
  assert.ok(sample.history.every(state => state.gesture === 'idle'));
  sample.advance(1);
  assert.equal(sample.state().gesture, 'peek');
  sample.advance(120000);
  const transitions = sample.history.filter((state, index, all) => index === 0 || state.gesture !== all[index - 1].gesture);
  const gestures = transitions.filter(state => state.gesture !== 'idle');
  assert.ok(gestures.length > 5);
  gestures.forEach((state, index) => {
    if (index) assert.notEqual(state.gesture, gestures[index - 1].gesture);
    const position = transitions.indexOf(state), quiet = transitions[position - 1], nextQuiet = transitions[position + 1];
    assert.ok(state.at - quiet.at >= 8000 && state.at - quiet.at <= 18000);
    if (nextQuiet && ['peek', 'sway', 'hop', 'wave'].includes(state.gesture)) assert.ok(nextQuiet.at - state.at <= 2000);
  });
  sample.motion.stop();
});

test('uses the full quiet interval range and can select every companion gesture', () => {
  for (const [random, expected] of [[0, 'peek'], [0.26, 'sway'], [0.36, 'march'], [0.51, 'hop'], [0.72, 'pace'], [0.99, 'wave']]) {
    const sample = fixture(() => random);
    const wait = 8000 + Math.floor(random * 10001);
    sample.advance(wait - 1);
    assert.equal(sample.state().gesture, 'idle');
    sample.advance(1);
    assert.equal(sample.state().gesture, expected);
    if (expected === 'march' || expected === 'pace') {
      const duration = expected === 'march' ? 4800 : 6400;
      assert.equal(sample.state().duration, duration);
      sample.advance(duration - 1);
      assert.equal(sample.state().gesture, expected);
      sample.advance(1);
      assert.equal(sample.state().gesture, 'idle');
    }
    sample.motion.stop();
  }
});

test('hover responds once, respects cooldown and starts a fresh quiet interval afterwards', () => {
  const sample = fixture();
  assert.equal(sample.motion.greet(), true);
  assert.equal(sample.state().gesture, 'wave');
  assert.equal(sample.motion.greet(), false);
  sample.advance(2000);
  assert.equal(sample.state().gesture, 'idle');
  assert.equal(sample.motion.greet(), false);
  sample.advance(4000);
  assert.equal(sample.motion.greet(), true);
  sample.motion.stop();
});

test('stopping during a gesture resets the pose, cancels all timers and prevents later hover', () => {
  const sample = fixture();
  sample.motion.greet();
  sample.advance(300);
  sample.motion.stop();
  assert.equal(sample.state().gesture, 'idle');
  assert.equal(sample.state().frame, 0);
  assert.equal(sample.timers.size, 0);
  const count = sample.history.length;
  sample.advance(60000);
  assert.equal(sample.history.length, count);
  assert.equal(sample.motion.greet(), false);
  assert.equal(sample.timers.size, 0);
});

test('aerospace gestures alternate with familiar gestures and finish before another quiet interval', () => {
  for (const [random, expected, duration] of [[0, 'float', 6000], [0.15, 'rocket', 6000], [0.3, 'moonwalk', 6500], [0.5, 'orbit', 6500], [0.6, 'stargaze', 6500], [0.8, 'signal', 6000], [0.99, 'dock', 6000]]) {
    const sample = fixture(() => random);
    sample.advance(45000);
    const themed = sample.history.filter(state => state.gesture === expected);
    assert.ok(themed.length > 0, `${expected} occurs without a pointer interaction`);
    assert.ok(themed.every(state => state.frame >= 0 && state.frame < 16 && state.duration === duration));
    const transitions = sample.history.filter((state, index, all) => index === 0 || state.gesture !== all[index - 1].gesture);
    const firstTheme = transitions.findIndex(state => state.gesture === expected);
    assert.equal(transitions[firstTheme - 1].gesture, 'idle');
    assert.ok(transitions[firstTheme].at - transitions[firstTheme - 1].at >= 8000);
    assert.equal(transitions[firstTheme + 1].gesture, 'idle');
    assert.equal(transitions[firstTheme + 1].at - transitions[firstTheme].at, duration);
    sample.motion.stop();
    assert.equal(sample.state().gesture, 'idle');
    assert.equal(sample.timers.size, 0);
  }
});

test('random rotation exhausts each group before repeating and avoids a repeat across round boundaries', () => {
  const aerospace = ['float', 'rocket', 'moonwalk', 'orbit', 'stargaze', 'signal', 'dock'];
  const companion = ['peek', 'sway', 'march', 'hop', 'pace', 'wave'];
  for (const random of [() => 0, () => 0.5, () => 0.99]) {
    const sample = fixture(random);
    sample.advance(900000);
    const transitions = sample.history.filter((state, index, all) => state.gesture !== 'idle' && (index === 0 || state.gesture !== all[index - 1].gesture));
    transitions.forEach((state, index) => assert.equal(aerospace.includes(state.gesture), index % 2 === 1));
    for (const group of [aerospace, companion]) {
      const seen = transitions.map(state => state.gesture).filter(gesture => group.includes(gesture));
      assert.ok(seen.length >= group.length * 2);
      for (let index = 0; index + group.length <= seen.length; index += group.length) {
        assert.deepEqual([...new Set(seen.slice(index, index + group.length))].sort(), [...group].sort());
      }
      seen.forEach((gesture, index) => { if (index) assert.notEqual(gesture, seen[index - 1]); });
    }
    sample.motion.stop();
  }
});

test('pausing playback retains rotation progress without keeping timers or resuming a half-finished gesture', () => {
  const cycle = createXiaohangGestureCycle(() => 0);
  const first = fixture(() => 0, cycle);
  first.advance(17400);
  assert.equal(first.state().gesture, 'float');
  first.motion.stop();
  assert.equal(first.timers.size, 0);
  const resumed = fixture(() => 0, cycle);
  resumed.advance(7999);
  assert.equal(resumed.state().gesture, 'idle');
  resumed.advance(1);
  assert.equal(resumed.state().gesture, 'sway');
  resumed.advance(9451);
  assert.equal(resumed.state().gesture, 'rocket');
  resumed.motion.stop();
  assert.equal(resumed.timers.size, 0);
});

test('a pointer greeting counts toward the familiar round without resetting the aerospace rotation', () => {
  const sample = fixture(() => 0.99);
  assert.equal(sample.motion.greet(), true);
  sample.advance(45000);
  const gestures = sample.history.filter((state, index, all) => state.gesture !== 'idle' && (index === 0 || state.gesture !== all[index - 1].gesture));
  assert.deepEqual(gestures.map(state => state.gesture), ['wave', 'pace', 'dock']);
  sample.motion.stop();
  assert.equal(sample.timers.size, 0);
});
