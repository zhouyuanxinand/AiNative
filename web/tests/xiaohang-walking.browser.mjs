import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const output = process.env.SCREENSHOT_DIR || '../runtime/xiaohang-walking';
await mkdir(output, { recursive: true });
const errors = [], unexpectedApi = [], checks = [];

function hitBoxes(buttons) {
  return buttons.map(button => {
    const { x, y, width, height } = button.getBoundingClientRect();
    return [x, y, width, height];
  });
}

// Measure the visible shoe sole, rather than the bounding box of its transparent canvas.
function sampleWalk(sprites, { duration, before }) {
  function sole(canvas) {
    const { width, height } = canvas;
    const pixels = canvas.getContext('2d').getImageData(0, 0, width, height).data;
    for (let y = height - 1; y >= 0; y--) {
      let sumX = 0, count = 0;
      for (let x = 0; x < width; x++) if (pixels[(y * width + x) * 4 + 3] > 40) { sumX += x; count++; }
      if (count) return { x: (sumX / count + 0.5) * canvas.clientWidth / width, y: (y + 0.5) * canvas.clientHeight / height };
    }
    throw new Error('Walking shoe has no visible pixels');
  }
  function relativeSoleY(canvas, point) {
    const style = getComputedStyle(canvas);
    if (style.visibility === 'hidden' || Number(style.opacity) < 0.15) return null;
    const [ox, oy] = style.transformOrigin.split(' ').map(parseFloat);
    const matrix = new DOMMatrixReadOnly(style.transform === 'none' ? undefined : style.transform);
    return new DOMPoint(point.x - ox, point.y - oy).matrixTransform(matrix).y + oy - point.y;
  }
  return sprites.map((sprite, index) => {
    const body = sprite.querySelector('.xiaohang-sprite-motion'), button = sprite.closest('button');
    const legs = ['left', 'right'].map(side => sprite.querySelector(`canvas.xiaohang-step-leg.is-${side}`));
    if (legs.some(leg => !leg)) throw new Error('Both walking shoes must be visible');
    const soles = legs.map(sole), animations = sprite.getAnimations({ subtree: true });
    const bodyDuration = body.getAnimations()[0]?.effect.getTiming().duration;
    animations.forEach(animation => animation.pause());
    const states = [], width = sprite.getBoundingClientRect().width;
    for (let step = 0; step <= 40; step++) {
      const progress = step / 40;
      animations.forEach(animation => { animation.currentTime = duration * progress; });
      const root = sprite.getBoundingClientRect(), moving = body.getBoundingClientRect(), hit = button.getBoundingClientRect();
      const position = (moving.left + moving.width / 2 - root.left - root.width / 2) / width;
      const feet = legs.map((leg, legIndex) => {
        const y = relativeSoleY(leg, soles[legIndex]);
        return y === null ? null : y / width;
      });
      if ([hit.x, hit.y, hit.width, hit.height].some((value, axis) => value !== before[index][axis])) {
        throw new Error(`Walking moved the ${width}px launcher hit box`);
      }
      states.push({ progress, position, feet });
    }
    const visible = states.filter(state => state.feet.every(y => y !== null));
    if (!visible.length) throw new Error('No walking phase displays both shoes');
    const best = visible.reduce((a, b) => Math.abs(a.feet[0] - a.feet[1]) + Math.abs(a.position) >
      Math.abs(b.feet[0] - b.feet[1]) + Math.abs(b.position) ? a : b);
    animations.forEach(animation => { animation.currentTime = duration * best.progress; });
    return { width, bodyDuration, states };
  });
}

try {
  for (const [gesture, random, duration] of [['march', 0.36, 4800], ['pace', 0.72, 6400]]) {
    const page = await browser.newPage({ viewport: { width: 800, height: 650 } });
    page.setDefaultTimeout(15000);
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', route => { unexpectedApi.push(new URL(route.request().url()).pathname); return route.abort(); });
    await page.addInitScript(value => { Math.random = () => value; }, random);
    await page.clock.install();
    await page.goto(`${process.env.BASE_URL || 'http://127.0.0.1:18370'}/tests/fixtures/xiaohang-aerospace.html`);
    await page.waitForFunction(() => document.querySelectorAll('[data-playing="true"]').length === 3);
    const sprites = page.locator('.motion-preview .xiaohang-sprite'), buttons = page.locator('.motion-preview button');
    const before = await buttons.evaluateAll(hitBoxes);
    assert.deepEqual(before.map(box => box[2]), [100, 70, 124]);
    for (let second = 0; second < 20 && await page.locator(`[data-gesture="${gesture}"]`).count() !== 3; second++) {
      await page.clock.runFor(1000);
    }
    assert.equal(await page.locator(`[data-gesture="${gesture}"]`).count(), 3, `${gesture} starts from idle without pointer input`);
    const samples = await sprites.evaluateAll(sampleWalk, { before, duration });
    for (const { width, bodyDuration, states } of samples) {
      assert.equal(bodyDuration, duration, `${gesture} lasts ${duration}ms at ${width}px`);
      const visible = states.filter(state => state.feet.every(y => y !== null));
      const directions = visible.map(({ feet: [left, right] }) => left - right).filter(value => Math.abs(value) > .015).map(Math.sign);
      const changes = directions.filter((value, i) => i > 0 && value !== directions[i - 1]).length;
      assert(changes >= 2, `${gesture} must visibly alternate left and right footfalls at ${width}px`);
      for (const foot of [0, 1]) {
        const y = visible.map(state => state.feet[foot]);
        assert(Math.max(...y) - Math.min(...y) > .015, `${gesture}: each shoe must lift and land at ${width}px`);
      }
      const x = states.map(state => state.position);
      if (gesture === 'march') assert(Math.max(...x.map(Math.abs)) < .08, `march stays centered at ${width}px`);
      else {
        const reverses = x.some((turn, i) => x.slice(0, i).some(start => x.slice(i + 1).some(end =>
          (turn - start > .08 && turn - end > .08) || (start - turn > .08 && end - turn > .08))));
        assert(reverses, `pace must visibly travel and return at ${width}px`);
        assert(Math.abs(x.at(-1)) < .03, `pace finishes centered at ${width}px`);
      }
    }
    await page.locator('.motion-preview').screenshot({ path: join(output, `${gesture}.png`) });
    await page.getByRole('button', { name: '暂停动效', exact: true }).click();
    await page.clock.runFor(duration + 1000);
    assert.equal(await page.locator('[data-playing="false"][data-gesture="idle"][data-frame="0"]').count(), 3);
    assert.equal(await page.locator('.xiaohang-step-leg').count(), 0, 'paused characters return to their full standing pose');
    assert.deepEqual(await buttons.evaluateAll(hitBoxes), before);
    const restored = await sprites.evaluateAll(elements => elements.every(sprite => {
      const root = sprite.getBoundingClientRect(), body = sprite.querySelector('.xiaohang-sprite-motion').getBoundingClientRect();
      return Math.abs(root.x - body.x) < .1 && Math.abs(root.y - body.y) < .1 && Math.abs(root.width - body.width) < .1;
    }));
    assert(restored, 'pause removes walking displacement at all three sizes');
    checks.push(`${gesture}: automatic idle, alternating visible shoes, ${gesture === 'march' ? 'centered steps' : 'out-and-back travel'}, fixed 100/70/124px hit targets, pause returns to standing`);
    await page.close();
  }
  assert.deepEqual(unexpectedApi, []);
  assert.deepEqual(errors, []);
  await writeFile(join(output, 'receipt.json'), JSON.stringify({ passed: true, checks, errors, unexpectedApi }, null, 2));
  console.log(JSON.stringify({ passed: true, checks, errors, unexpectedApi, output }));
} finally { await browser.close(); }
