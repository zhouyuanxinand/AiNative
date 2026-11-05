import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined, args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const errors = [];
try {
  for (const mode of ['webgl','no-webgl','portrait']) {
    const page = await browser.newPage({viewport:{width:390,height:700}, reducedMotion:'reduce'});
    page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(mode=>{
      const original = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function(type,...args) {
        if(type.startsWith('webgl') && mode !== 'webgl') return null;
        const ctx = original.call(this,type,...args);
        if(type==='webgl' && ctx) window.pilotContext = ctx;
        return ctx;
      };
    }, mode);
    if (mode==='portrait') await page.route('**/assets/xiaohang-3d.json',route=>route.abort());
    await page.route('**/api/rd/assistant/weather',route=>route.fulfill({json:{status:'unavailable'}}));
    await page.goto(`${process.env.BASE_URL || 'http://127.0.0.1:18370'}/tests/fixtures/xiaohang-companion.html`);
    const sprite = page.locator('.xiaohang-sprite'), box = await sprite.boundingBox();
    if (mode==='portrait') {
      await page.waitForFunction(()=>document.querySelector('.xiaohang-sprite img')?.naturalWidth>0);
      assert.equal(await sprite.getAttribute('data-renderer'),'portrait');
    } else {
      await page.waitForFunction(kind=>document.querySelector('.xiaohang-sprite')?.dataset.renderer===kind,mode==='webgl'?'webgl':'atlas');
      const inspect = () => sprite.locator('canvas').first().evaluate(canvas=>{
        const pixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
        let solid=0, top=canvas.height, bottom=0;
        for(let i=3;i<pixels.length;i+=4) if(pixels[i]>180) {
          const y=Math.floor((i-3)/4/canvas.width); top=Math.min(top,y);bottom=Math.max(bottom,y);solid++;
        }
        return {solid,top,bottom};
      });
      const before = await inspect();
      assert(before.solid>5500 && before.bottom-before.top>185,'a full pilot is visible in the canvas');
      assert.equal(await sprite.getAttribute('data-playing'),'false','reduced-motion still shows the model');
      if (mode==='webgl') {
        await page.evaluate(()=>window.pilotContext.getExtension('WEBGL_lose_context').loseContext());
        await page.waitForFunction(()=>document.querySelector('.xiaohang-sprite')?.dataset.renderer==='atlas');
        const after = await inspect();
        assert(after.solid>5500 && Math.abs(after.bottom-before.bottom)<5,'context loss preserves the feet and the character');
      }
    }
    assert.deepEqual(await sprite.boundingBox(),box,'switching renderers never changes the hit box');
    await page.close();
  }
  assert.deepEqual(errors,[]);
  console.log('Verified: 3D pilot, context recovery, software atlas, static portrait and reduced motion.');
} finally {await browser.close();}
