import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const output = process.env.SCREENSHOT_DIR || '../runtime/xiaohang-companion';
await mkdir(output, { recursive: true });
const requests = [], errors = [], checks = [];
let failChat = false, failWeather = false;
const conversations = new Map();
let activeId = null;
const detail = item => ({ ...item, messages: [...item.messages], has_more: false, next_before: null });
const summary = item => {
  const {messages, draft, ...rest} = item;
  return rest;
};
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, hasTouch:true });
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/rd/session') return route.fulfill({ json: { actor_id: 'local:test', local_mode: true } });
    if (path === '/api/rd/assistant/conversations') {
      if (route.request().method() === 'GET') return route.fulfill({json: {
        items: [...conversations.values()].map(summary), total: conversations.size, page: 1, page_size: 20, active_id: activeId,
      }});
      const id = `conversation-${conversations.size + 1}`;
      const source = conversations.get(route.request().postDataJSON().source_id);
      const item = {id, title: source?.title || '新对话', created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        source_id: source?.id || null, version: 1, draft: '', message_count: source?.message_count || 0, messages: source ? [...source.messages] : []};
      conversations.set(id,item); activeId = id;
      return route.fulfill({json:detail(item)});
    }
    const conversationPath = path.match(/^\/api\/rd\/assistant\/conversations\/([^/]+)(?:\/(messages|close))?$/);
    if (conversationPath) {
      const item = conversations.get(conversationPath[1]);
      assert(item,'conversation must exist');
      if (!conversationPath[2]) return route.fulfill({json:detail(item)});
      const body = route.request().postDataJSON();
      assert.equal(body.expected_version,item.version,'the client uses the current conversation version');
      if (conversationPath[2] === 'close') {
        item.draft = body.choice === 'keep' ? body.draft : ''; item.version += 1;
        activeId = body.choice === 'keep' ? item.id : null;
        return route.fulfill({json:{active_id:activeId}});
      }
      requests.push(body);
      if (failChat) return route.fulfill({ status: 503, json: { error: '连接暂时失败，请重试。' } });
      const long = body.message === '请展示长回复', weather = body.message.includes('天气');
      const reply = long ? {content:'先明确目标，再整理已有材料。\n\n1. 写下当前最需要解决的问题，并用一两句话描述预期结果。\n2. 收集相关资料，检查信息是否完整，再决定下一步。\n\n'+'较长的模型回复也应保持清晰可读。'.repeat(35)+'\n\n可以继续告诉我你的想法。',mode:'model',actions:[]}
        : {content:weather ? '点击按钮查看涧西天气。' : '进入项目的资料区，上传技术资料，再进行资料分析。', mode:'local_guidance',
          actions:weather ? [{id:'weather',label:'查看涧西天气'}] : [{id:'start_task',label:'开始任务'},{id:'open_projects',label:'查看项目'}]};
      const seq = item.messages.length;
      item.messages.push({id:`${item.id}-${seq+1}`,seq:seq+1,role:'user',content:body.message,created_at:new Date().toISOString()},
        {id:`${item.id}-${seq+2}`,seq:seq+2,role:'assistant',...reply,created_at:new Date().toISOString()});
      if (!seq) item.title = body.message;
      item.message_count = item.messages.length; item.version += 1; item.draft = '';
      return route.fulfill({json:detail(item)});
    }
    if (path === '/api/rd/assistant/weather') return route.fulfill({ json: failWeather ? { status: 'unavailable', location: '洛阳 · 涧西区', notice: '天气服务暂时不可用' } : { status: 'ok', location: '洛阳 · 涧西区', temperature_c: 16, condition: '多云', is_day: true, wind_speed_kmh: 8, observed_at: '2026-11-04T06:00:00Z', fetched_at: '2026-11-04T06:01:00Z', source: 'MET Norway · 预报', source_url: 'https://api.met.no/doc/Locationforecast' } });
    if (path === '/api/rd/assistant/chat') {
      const body = route.request().postDataJSON(); requests.push(body);
      if (failChat) return route.fulfill({ status: 503, json: { error: '连接暂时失败，请重试。' } });
      if (body.message === '请展示长回复') return route.fulfill({json:{content:'先明确目标，再整理已有材料。\n\n1. 写下当前最需要解决的问题，并用一两句话描述预期结果。\n2. 收集相关资料，检查信息是否完整，再决定下一步。\n\n'+'较长的模型回复也应保持清晰可读。'.repeat(35)+'\n\n可以继续告诉我你的想法。',mode:'model',actions:[]}});
      return route.fulfill({ json: { content: body.message.includes('天气') ? '点击按钮查看涧西天气。' : '进入项目的资料区，上传技术资料，再进行资料分析。', mode: 'local_guidance', actions: body.message.includes('天气') ? [{id:'weather',label:'查看涧西天气'}] : [{id:'start_task',label:'开始任务'},{id:'open_projects',label:'查看项目'}] } });
    }
    throw new Error(`Unexpected API: ${path}`);
  });
  await page.goto(`${process.env.BASE_URL || 'http://127.0.0.1:18370'}/tests/fixtures/xiaohang-companion.html`);
  const launcher = page.getByRole('button', { name: '打开小航助手', exact:true });
  await launcher.waitFor();
  await page.waitForFunction(() => document.querySelector('.xiaohang-sprite')?.getAttribute('data-playing') === 'true');
  const speech = await page.locator('.rd-floating-launcher-label').boundingBox(), figure = await page.locator('.rd-floating-figure').boundingBox();
  assert(speech.y+speech.height < figure.y && speech.x >= 0, 'greeting is a visible speech bubble above the character');
  await page.screenshot({path:join(output,'greeting-bubble.png')});
  await launcher.hover();
  const bubble = page.locator('.rd-weather-nudge');
  await bubble.waitFor();
  await bubble.hover();
  await page.waitForTimeout(350);
  assert.equal(await bubble.count(),1,'moving from the character into the weather bubble keeps it open');
  assert.equal(await bubble.getByRole('link').count(),0,'weather attribution is collapsed by default');
  await bubble.locator('summary').click();
  assert.equal(await bubble.getByRole('link',{name:'CC BY 4.0 · 已转译'}).isVisible(),true);
  await page.screenshot({path:join(output,'weather-hover-source.png')});
  await page.getByRole('button',{name:'页面操作'}).click();
  await bubble.waitFor({state:'hidden'});
  await page.keyboard.press('Tab');
  await bubble.waitFor();
  await launcher.press('Escape');
  await bubble.waitFor({state:'hidden'});
  assert.equal(await launcher.isVisible(),true,'Escape dismisses the active weather bubble before docking the character');
  checks.push('鼠标悬停与键盘聚焦查看天气、移入气泡可操作、来源默认折叠、点击空白和Escape关闭');
  await page.locator('.rd-floating-launcher-label').click();
  const input = page.getByRole('textbox', {name:'问问小航'});
  await input.waitFor();
  await page.locator('.rd-welcome-intro').waitFor();
  assert.equal(await page.locator('.rd-welcome-entry-actions').getByRole('button').count(),2,'welcome retains its two task entry points');
  const weatherButton = page.getByRole('button',{name:'查看洛阳涧西天气'}), closeButton = page.getByRole('button',{name:'收起小航助手'});
  const weatherButtonBox = await weatherButton.boundingBox(), closeButtonBox = await closeButton.boundingBox();
  assert.equal(weatherButtonBox.width,closeButtonBox.width,'header actions have matching widths');
  assert.equal(weatherButtonBox.height,closeButtonBox.height,'header actions have matching heights');
  assert(Math.abs(weatherButtonBox.y-closeButtonBox.y)<=1,'header actions share one baseline');
  await weatherButton.click();
  await page.locator('.rd-weather-overlay').waitFor();
  await page.locator('.rd-weather-overlay .rd-weather-advice').click();
  assert.equal(await page.locator('.rd-weather-overlay').count(),1,'clicking within weather does not dismiss it');
  await input.click();
  assert.equal(await page.locator('.rd-weather-overlay').count(),0,'clicking the conversation composer dismisses weather');
  assert.equal(await page.getByRole('dialog').isVisible(),true,'conversation remains open');
  await weatherButton.click();
  await page.locator('.rd-welcome-log').click({position:{x:3,y:80}});
  assert.equal(await page.locator('.rd-weather-overlay').count(),0,'clicking blank conversation space dismisses weather');
  await weatherButton.click();
  await input.press('Escape');
  assert.equal(await page.locator('.rd-weather-overlay').count(),0);
  assert.equal(await page.getByRole('dialog').isVisible(),true);
  await page.screenshot({ path:join(output, 'welcome-desktop.png') });
  await input.fill('如何上传资料？');
  await input.dispatchEvent('compositionstart');
  await input.press('Enter');
  assert.equal(requests.length, 0, 'IME enter must not send');
  await input.dispatchEvent('compositionend');
  await input.press('Enter');
  await page.getByText('进入项目的资料区，上传技术资料，再进行资料分析。',{exact:true}).waitFor();
  assert.equal(requests.length, 1);
  assert.equal(await page.locator('.rd-welcome-intro').count(),0,'welcome entry points disappear once the conversation starts');
  assert.equal(await page.locator('.rd-welcome-log').getByRole('button',{name:/开始任务|查看项目/}).count(),0,'conversation replies do not repeat task and project navigation');
  await input.fill('保留草稿');
  await page.getByRole('button',{name:'收起小航助手'}).click();
  await page.getByRole('button',{name:'保留并收起',exact:true}).click();
  await launcher.click();
  await page.waitForFunction(() => !document.querySelector('.rd-welcome-composer textarea')?.disabled);
  assert.equal(await input.inputValue(),'保留草稿');
  await input.fill('失败时保留的问题'); failChat = true;
  await page.getByRole('button',{name:'发送给小航'}).click();
  await page.getByText('连接暂时失败，请重试。',{exact:true}).waitFor();
  assert.equal(await input.inputValue(),'失败时保留的问题');
  failChat = false;
  await page.getByRole('button',{name:'重试发送'}).click();
  await page.waitForFunction(() => document.querySelectorAll('.rd-welcome-message.assistant').length === 2);
  assert.equal(await input.inputValue(),'');
  checks.push('欢迎快捷入口保留、开始对话后隐藏任务/项目按钮、IME、发送、失败保留与重试、关闭后保留会话及草稿');
  await input.fill('看看涧西天气'); await input.press('Enter');
  await page.getByRole('button',{name:'查看涧西天气',exact:true}).click();
  await page.getByText('当地预报',{exact:true}).waitFor();
  await page.screenshot({ path:join(output,'weather-desktop.png') });
  failWeather = true;
  await page.getByRole('button',{name:'刷新天气'}).click();
  await page.getByText('天气服务暂时不可用',{exact:true}).waitFor();
  assert.equal(await page.getByText('当地预报',{exact:true}).count(),0);
  failWeather = false;
  await page.getByRole('button',{name:'刷新天气'}).click();
  await page.getByText('当地预报',{exact:true}).waitFor();
  await page.getByRole('button',{name:'收起天气'}).click();
  await page.screenshot({ path:join(output,'conversation-desktop.png') });
  checks.push('天气卡片数据/来源/预报时间、失败不展示旧温度、显式刷新恢复');
  await page.getByRole('button',{name:'收起小航助手'}).click();
  await page.getByRole('button',{name:'保留并收起',exact:true}).click();
  const box = await launcher.boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2); await page.mouse.down();
  await page.mouse.move(5,300,{steps:12});
  await page.getByText('松手收起',{exact:true}).waitFor();
  assert.equal(await page.locator('.xiaohang-sprite').getAttribute('data-playing'),'false');
  await page.mouse.up();
  const dock = page.getByRole('button',{name:'唤回小航助手'});
  await dock.waitFor();
  assert.equal(await launcher.isVisible(),false);
  await page.screenshot({path:join(output,'docked-left.png')});
  await page.reload(); await dock.waitFor();
  await dock.press('Enter'); await launcher.waitFor();
  await launcher.press('Home');
  const restored = await launcher.boundingBox(); assert(restored.x>1000);
  await launcher.press('Escape'); await dock.waitFor();
  await dock.press('Home'); await launcher.waitFor();
  const rightStart = await launcher.boundingBox();
  await page.mouse.move(rightStart.x+rightStart.width/2,rightStart.y+rightStart.height/2); await page.mouse.down();
  await page.mouse.move(1435,360,{steps:8}); await page.mouse.up(); await dock.waitFor();
  assert((await dock.boundingBox()).x>1400,'right edge hides with the recall tab on the right');
  await dock.click(); await launcher.waitFor();
  assert.equal(await page.getByRole('dialog').isVisible(),false,'recall must not accidentally open chat');
  checks.push('拖边隐藏、拖动暂停、刷新保留、键盘唤回与Home复位');
  // Accelerate only the idle period; user interactions have finished.
  await page.clock.install();
  await page.clock.fastForward(420000);
  await page.locator('.rd-weather-nudge').waitFor();
  await page.screenshot({path:join(output,'weather-bubble.png')});
  await page.locator('.rd-weather-nudge summary').click();
  await page.locator('.rd-weather-nudge a').first().dispatchEvent('pointerdown', {bubbles:true});
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
  assert.equal(await page.locator('.rd-weather-nudge').count(),1,'pressing the weather source must not dismiss it before the link click');
  await page.getByRole('button',{name:'收起天气'}).click();
  await page.clock.fastForward(30000);
  assert.equal(await page.locator('.rd-weather-nudge').count(),0);
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.waitForFunction(() => document.querySelector('.xiaohang-sprite')?.getAttribute('data-playing') === 'false');
  assert.equal(await page.locator('.xiaohang-sprite').getAttribute('data-playing'),'false');
  await page.clock.fastForward(420000);
  assert.equal(await page.locator('.rd-weather-nudge').count(),0);
  await page.mouse.move(200,200);
  await launcher.hover();
  await page.clock.fastForward(500);
  await page.locator('.rd-weather-nudge').waitFor();
  assert.equal(await page.locator('.xiaohang-sprite').getAttribute('data-playing'),'false','explicit weather remains usable with reduced motion');
  await page.mouse.move(200,200);
  await page.clock.fastForward(350);
  assert.equal(await page.locator('.rd-weather-nudge').count(),0,'leaving the character and bubble dismisses the preview');
  checks.push('闲置天气低频出现/关闭冷却、减少动态效果时停动且不自动弹天气');
  await page.setViewportSize({width:390,height:700}); await launcher.click();
  await input.waitFor();
  await input.fill('请展示长回复'); await input.press('Enter');
  await page.getByText('模型回复',{exact:true}).waitFor();
  assert.equal(await page.locator('.rd-welcome-log').evaluate(element => element.scrollHeight>element.clientHeight),true,'long replies scroll inside the conversation');
  await page.screenshot({path:join(output,'conversation-mobile.png')});
  for (const viewport of [{width:320,height:600},{width:390,height:700},{width:900,height:420}]) {
    await page.setViewportSize(viewport);
    // Resize commits asynchronously; measure both controls after the panel catches up.
    await page.waitForFunction(({width,height}) => {
      const panel = document.querySelector('.rd-floating-panel')?.getBoundingClientRect();
      return panel?.width === Math.min(420, width - (width <= 600 ? 24 : 48))
        && panel?.height === Math.max(120, Math.min(560, height - 120));
    }, viewport);
    const panel = await page.getByRole('dialog').boundingBox(), send=await page.getByRole('button',{name:'发送给小航'}).boundingBox();
    assert(panel.x>=0 && panel.y>=0 && panel.x+panel.width<=viewport.width+1 && panel.y+panel.height<=viewport.height+1);
    assert(send.y>=panel.y && send.y+send.height<=panel.y+panel.height+1,'send stays reachable');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth>innerWidth),false);
  }
  await page.screenshot({path:join(output,'conversation-short.png')});
  await page.setViewportSize({width:390,height:700});
  await page.getByRole('button',{name:'收起小航助手'}).click();
  await page.getByRole('button',{name:'保留并收起',exact:true}).click();
  const touchLauncher = await launcher.boundingBox();
  await page.touchscreen.tap(touchLauncher.x+touchLauncher.width/2,touchLauncher.y+touchLauncher.height/2);
  await input.waitFor();
  assert.equal(await page.locator('.rd-weather-nudge').count(),0,'touch tap opens chat without hover-only weather');
  checks.push('320/390px窄屏与900×420短窗口无横向溢出，长回复内部滚动，发送入口可达，触屏点击正常开对话');
  assert.deepEqual(errors,[]);
  await writeFile(join(output,'receipt.json'),JSON.stringify({passed:true,checks,errors,chatRequests:requests.length},null,2));
  console.log(JSON.stringify({passed:true,checks,errors,chatRequests:requests.length,output}));
} finally {await browser.close();}
