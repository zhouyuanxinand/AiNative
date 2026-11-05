import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||undefined});
try {
  const page=await browser.newPage({viewport:{width:390,height:700}}), errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.clock.install({time:new Date('2026-11-04T12:00:00Z')});
  await page.clock.pauseAt(new Date('2026-11-04T12:00:01Z'));
  await page.goto(`${process.env.BASE_URL||'http://127.0.0.1:18370'}/tests/fixtures/xiaohang-greeting.html`);
  const label=page.locator('.rd-floating-launcher-label');
  await label.waitFor();
  const originalRect = await label.boundingBox();
  // Restart from an explicit enable edge so these checks use a known clock origin.
  await page.getByRole('button',{name:'暂停问候',exact:true}).click();
  assert.equal(await label.isVisible(),false);
  await page.getByRole('button',{name:'继续问候',exact:true}).click();
  // React commits the enabled greeting after the click. Keep the virtual clock
  // paused until that visible phase exists, just as on the initial mount above.
  await label.waitFor();
  await page.clock.runFor(5900); assert.equal(await label.isVisible(),true);
  await page.clock.runFor(200); assert.equal(await label.isVisible(),false);
  assert.equal(await label.evaluate(element=>getComputedStyle(element).visibility),'hidden','mobile display:block must not revive a hidden greeting');
  assert.equal(await label.getAttribute('aria-hidden'),'true');
  assert.deepEqual(await label.boundingBox(),originalRect,'hidden greeting retains its drag-measurement footprint');
  assert.equal(await label.evaluate(element=>getComputedStyle(element).pointerEvents),'none');
  await page.clock.runFor(23800); assert.equal(await label.isVisible(),false);
  await page.clock.runFor(200); assert.equal(await label.isVisible(),true);
  await page.getByRole('button',{name:'暂停问候',exact:true}).click();
  await page.clock.runFor(60000); assert.equal(await label.isVisible(),false);
  await page.getByRole('button',{name:'继续问候',exact:true}).click();
  await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'}); document.dispatchEvent(new Event('visibilitychange'));});
  await label.waitFor({state:'hidden'});
  await page.clock.runFor(60000); assert.equal(await label.isVisible(),false);
  await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'}); document.dispatchEvent(new Event('visibilitychange'));});
  await label.waitFor();
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await label.evaluate(element=>getComputedStyle(element).animationName),'none');
  await page.clock.runFor(6100); assert.equal(await label.isVisible(),false,'reduced motion still respects the show/hide rhythm');
  await page.clock.runFor(24000); assert.equal(await label.isVisible(),true);
  await page.getByRole('button',{name:'卸载问候',exact:true}).click();
  await page.clock.runFor(60000); assert.equal(await label.count(),0);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,showMs:6000,hideMs:24000,disabled:true,background:true,reducedMotion:true,unmount:true,errors}));
} finally {await browser.close();}
