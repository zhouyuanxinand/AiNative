import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined});
const output = process.env.SCREENSHOT_DIR || '../runtime/xiaohang-aerospace';
await mkdir(output,{recursive:true});
const errors=[], checks=[];
try {
  const themes = ['float','rocket','moonwalk','orbit','stargaze','signal','dock'];
  for (const [random,gesture,duration] of [[0,'float',6000],[0.15,'rocket',6000],[0.3,'moonwalk',6500],[0.5,'orbit',6500],[0.6,'stargaze',6500],[0.8,'signal',6000],[0.99,'dock',6000]]) {
    const page = await browser.newPage({viewport:{width:800,height:650}});
    page.setDefaultTimeout(15000);
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/api/**',route=>{throw new Error(`Motion must not call an API: ${route.request().url()}`);});
    await page.addInitScript(value=>{Math.random=()=>value;},random);
    await page.clock.install();
    await page.goto(`${process.env.BASE_URL || 'http://127.0.0.1:18370'}/tests/fixtures/xiaohang-aerospace.html`);
    const sprite = page.locator('.motion-real .xiaohang-sprite');
    await page.waitForFunction(()=>document.querySelectorAll('[data-playing="true"]').length===3);
    const before = await page.getByRole('button',{name:'角色100',exact:true}).boundingBox();
    const mobileBefore = await page.getByRole('button',{name:'角色70',exact:true}).boundingBox();
    for (let i=0;i<45 && await sprite.getAttribute('data-gesture')!==gesture;i++) await page.clock.runFor(1000);
    assert.equal(await sprite.getAttribute('data-gesture'),gesture,`${gesture} starts without hover or click`);
    assert.equal(await sprite.locator('.xiaohang-flight-prop').count(),1);
    assert.deepEqual(await page.getByRole('button',{name:'角色100',exact:true}).boundingBox(),before,'visual motion must not change the click/drag rectangle');
    assert.deepEqual(await page.getByRole('button',{name:'角色70',exact:true}).boundingBox(),mobileBefore,'mobile motion keeps its click/drag rectangle');
    const durations = await sprite.evaluate(element => element.getAnimations({subtree:true}).map(animation => animation.effect.getTiming().duration));
    assert(durations.length > 1 && durations.every(value => value === duration),'character and props share the full gesture duration');
    // Freeze CSS mid-action only for a clear visual inspection; playback above ran normally.
    await page.evaluate(()=>document.getAnimations().forEach(animation=>{animation.pause(); animation.currentTime=Number(animation.effect.getTiming().duration)*0.55;}));
    await page.locator('.motion-preview').screenshot({path:join(output,`${gesture}.png`)});
    await page.getByRole('button',{name:'暂停动效',exact:true}).click();
    assert.equal(await sprite.getAttribute('data-playing'),'false');
    assert.equal(await page.locator('.xiaohang-flight-prop').count(),0,'pause removes every spacecraft/connector prop');
    await page.clock.runFor(20000);
    assert.equal(await sprite.getAttribute('data-gesture'),'idle');
    await page.getByRole('button',{name:'继续动效',exact:true}).click();
    assert.equal(await sprite.getAttribute('data-gesture'),'idle','resume begins with the quiet interval');
    for (let i=0;i<45 && !themes.includes(await sprite.getAttribute('data-gesture'));i++) await page.clock.runFor(1000);
    assert(themes.includes(await sprite.getAttribute('data-gesture')),'a themed gesture returns after the quiet interval');
    assert.notEqual(await sprite.getAttribute('data-gesture'),gesture,'resuming retains the round instead of replaying the same theme');
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.waitForFunction(()=>document.querySelectorAll('[data-playing="true"]').length===0);
    assert.equal(await page.locator('.xiaohang-flight-prop').count(),0);
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.waitForFunction(()=>document.querySelectorAll('[data-playing="true"]').length===3);
    await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'}); document.dispatchEvent(new Event('visibilitychange'));});
    await page.waitForFunction(()=>document.querySelectorAll('[data-playing="true"]').length===0);
    assert.equal(await page.locator('.xiaohang-flight-prop').count(),0);
    checks.push(`${gesture}: automatic idle, desktop/mobile geometry, synchronized duration, pause/resume rotation, reduced motion, hidden tab`);
    await page.close();
  }
  assert.deepEqual(errors,[]);
  await writeFile(join(output,'receipt.json'),JSON.stringify({passed:true,checks,errors},null,2));
  console.log(JSON.stringify({passed:true,checks,errors,output}));
} finally {await browser.close();}
