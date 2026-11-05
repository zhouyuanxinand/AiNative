import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { useGreetingBubble } from '../../src/features/rd/assistant/useGreetingBubble';
import '../../src/styles.css';
import '../../src/features/rd/FloatingAssistant.css';

function Greeting({enabled}: {enabled:boolean}) {
  const visible = useGreetingBubble(enabled);
  return <div className="rd-floating-assistant"><button className="rd-floating-launcher" type="button" aria-label="角色">
    <span>航</span><span className="rd-floating-launcher-label" aria-hidden={!visible} data-visible={visible}>小航<span>有事问我</span></span>
  </button></div>;
}
function Fixture() {
  const [enabled,setEnabled] = useState(true), [mounted,setMounted] = useState(true);
  return <main style={{padding:32}}>
    <button type="button" onClick={()=>setEnabled(value=>!value)}>{enabled?'暂停问候':'继续问候'}</button>
    <button type="button" onClick={()=>setMounted(value=>!value)}>{mounted?'卸载问候':'挂载问候'}</button>
    {mounted&&<Greeting enabled={enabled}/>}
  </main>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
