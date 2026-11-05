import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { XiaohangSprite } from '../../src/features/rd/assistant/XiaohangSprite';
import '../../src/styles.css';

function Fixture() {
  const [paused, setPaused] = useState(false);
  return <main style={{padding:32, maxWidth:640}}>
    <h1>小航航天动效验证</h1><p>相同人物与道具，依次为桌面100px、手机70px和124px细节。</p>
    <section className="motion-preview" style={{display:'flex', alignItems:'end', gap:64, padding:'36px 32px', background:'var(--color-bg-surface)', borderRadius:16, margin:'24px 0'}}>
      {[100,70,124].map(size => <div key={size}><button type="button" aria-label={`角色${size}`} style={{display:'block', width:size, height:size, padding:0, border:0, background:'transparent'}}>
        <div style={{width:size, height:size}} className={`motion-sample ${size===100?'motion-real':size===70?'motion-mobile':'motion-detail'}`}><XiaohangSprite paused={paused}/></div>
      </button><p style={{textAlign:'center', marginTop:16}}>{size}px</p></div>)}
    </section>
    <button type="button" onClick={() => setPaused(value => !value)}>{paused?'继续动效':'暂停动效'}</button>
    <style>{`.motion-sample .xiaohang-sprite{width:100%;height:100%}`}</style>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
