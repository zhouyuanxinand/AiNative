import { useEffect, useState, type ReactNode } from 'react';
import { projectTabFromUrl, materialSectionFromUrl, type ProjectTab, type MaterialSection } from '../model/projectNavigation';
import { projectJourney, roleLabel, projectRole, workItems } from '../model/rdWorkbench';
import { RdTaskPanel } from './RdTaskPanel';
import { RdProjectPlan } from './RdProjectPlan';
import { RdArtifacts } from './RdArtifacts';
import { RdJourneyPanel } from './RdJourneyPanel';
import { memberName } from '../model/presentation';
import { type RdWorkbenchContext } from '../model/context';
import './rdJourney.css';

const tabs: {id: ProjectTab;label: string}[] = [{id:'results',label:'当前成果'},{id:'flow',label:'项目流程'},{id:'materials',label:'资料与画像'}];
const sections: {id: MaterialSection;label: string}[] = [{id:'requirements',label:'需求与基线'},{id:'sources',label:'项目资料与上下文'},{id:'members',label:'协作成员'},{id:'history',label:'办理记录'}];
export function RdProjectSurface({ context, onReload, onChange, requirements, members, history: historyContent }: {context: RdWorkbenchContext;onReload:()=>void;onChange:(detail:RdWorkbenchContext['detail'])=>void;requirements:ReactNode;members:ReactNode;history:ReactNode}) {
  const {detail, disabled} = context, {project} = detail;
  const [tab,setTab]=useState(()=>projectTabFromUrl(location.search));
  const [section,setSection]=useState(()=>materialSectionFromUrl(location.search,location.hash));
  const baseline=detail.baselines.find(item=>item.id===project.current_baseline_id);
  const journey=projectJourney(detail);
  const items=workItems([detail],detail.current_user_id);
  useEffect(()=>{
    const restore=()=>{setTab(projectTabFromUrl(location.search));setSection(materialSectionFromUrl(location.search,location.hash));};
    window.addEventListener('popstate',restore);window.addEventListener('hashchange',restore);
    return()=>{window.removeEventListener('popstate',restore);window.removeEventListener('hashchange',restore);};
  },[]);
  useEffect(()=>{const frame=requestAnimationFrame(()=>{if(location.hash){try{document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView({block:'start'});}catch{/* Invalid external fragments do not change the current view. */}}});return()=>cancelAnimationFrame(frame);},[tab,section,detail.project.id]);
  function navigate(next:ProjectTab,nextSection?:MaterialSection){const url=new URL(location.href);url.searchParams.set('tab',next);url.hash='';if(nextSection)url.searchParams.set('section',nextSection);else url.searchParams.delete('section');window.history.pushState(null,'',url);setTab(next);if(nextSection)setSection(nextSection);}
  return <>
    <div className="rd-title-row"><div><p className="rd-eyebrow">{project.code} · {roleLabel(projectRole(detail))}</p><h1>{project.name}</h1><p className="rd-muted">{project.customer} · {project.product}</p></div><div className="rd-version"><span>记录版本 v{project.version}</span><button className="feedback-button" type="button" disabled={disabled} onClick={onReload}>读取最新版本</button></div></div>
    <section className="rd-project-context" aria-label="当前项目上下文"><div><small>业务路线</small><strong>{journey.route_label}</strong></div><div><small>当前业务阶段</small><strong>{journey.stage_label}</strong></div><div><small>采用需求</small><strong>{baseline?`需求基线 B${baseline.number}`:'待确认需求'}</strong></div><div><small>项目负责人</small><strong>{memberName(detail,project.owner_id)}</strong></div></section>
    {!!journey.blockers.length && <aside className="feedback-notice rd-project-blockers" aria-label="项目待处理条件"><strong>当前待处理</strong><ul>{journey.blockers.map((item,index)=><li key={index}>{item}</li>)}</ul></aside>}
    <nav className="rd-tabs rd-primary-tabs" aria-label="项目工作区">{tabs.map(item=><button key={item.id} type="button" className={tab===item.id?'selected':''} aria-current={tab===item.id?'page':undefined} onClick={()=>navigate(item.id)}>{item.label}</button>)}</nav>
    <div hidden={tab!=='results'}>
      <section className="rd-panel"><div className="rd-record-heading"><div><h2>需要我继续的工作</h2><p className="rd-muted">从当前责任进入同一工作对象，核对有效输入、成果和下一接收方。</p></div><span className="rd-route-badge">{items.length} 项</span></div><div className="rd-project-actions">{items.slice(0,6).map(item=><a key={item.id} className="rd-project-action" href={item.href}><div><strong>{item.title}</strong><p>{item.description}</p></div><span aria-hidden="true">→</span></a>)}{!items.length&&<p className="rd-empty">当前没有分派给你的办理事项。可查看工程成果、项目流程与采用资料。</p>}</div></section>
      <RdArtifacts context={context}/>
    </div>
    <div hidden={tab!=='flow'}><RdJourneyPanel context={context}/>{(detail.project_plan?.work_units.length || detail.project_plan?.items.length || detail.project_plan?.versions.length) ? <RdProjectPlan projectId={project.id} plan={detail.project_plan}/> : journey.route !== 'direct' ? <section className="rd-panel"><h2>工作包与正式计划</h2><p className="rd-muted">完成路线与启动授权后组织任务书策划。批准的工作安排经明确发布后，会在这里形成流程与计划。</p></section> : null}<RdTaskPanel context={context} onChange={onChange}/></div>
    <div hidden={tab!=='materials'}><nav className="rd-material-tabs" aria-label="项目资料区域">{sections.map(item=><button type="button" key={item.id} className={section===item.id?'selected':''} aria-current={section===item.id?'page':undefined} onClick={()=>navigate('materials',item.id)}>{item.label}</button>)}</nav>
      <div hidden={section!=='requirements'}>{requirements}</div>
      <div hidden={section!=='sources'}><section className="rd-panel"><h2>客户与产品上下文</h2><p className="rd-muted">以下信息来自当前项目登记，与采用资料共同构成本项目的工作上下文。</p><dl className="rd-metadata"><dt>客户</dt><dd>{project.customer}</dd><dt>产品</dt><dd>{project.product}</dd><dt>业务路线</dt><dd>{journey.route_label}</dd><dt>采用需求</dt><dd>{baseline?`B${baseline.number} · ${baseline.requirements.length}项要求`:'尚未确认'}</dd></dl></section><section className="rd-panel"><h2>项目资料与来源</h2><p className="rd-muted">任务书任务内维护资料版本和固定输入包，历史引用继续保留。</p>{detail.project_sources?.length?<div className="rd-table-region" role="region" tabIndex={0} aria-label="项目来源资料"><table><thead><tr><th>资料</th><th>来源版本</th><th>资料性质</th></tr></thead><tbody>{detail.project_sources.map(item=><tr key={`${item.source_id}:${item.version}`}><td>{item.name||item.source_id}</td><td>v{item.version}</td><td>{item.provenance==='mock'?'演示资料':item.provenance==='real'?'实际登记':'项目登记'}</td></tr>)}</tbody></table></div>:<p className="rd-empty">尚未登记版本化来源资料。进入任务书任务后可上传、核对并采用输入。</p>}</section></div>
      <div hidden={section!=='members'}>{members}</div><div hidden={section!=='history'}>{historyContent}</div>
    </div>
  </>;
}
