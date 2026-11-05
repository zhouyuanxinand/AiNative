import { PlatformButton } from '../../components/ui/PlatformButton';
import { useEffect, useRef, useState } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { useApplicationLeaveGuard } from '../../hooks/useApplicationLeaveGuard';
import { makeRequestKey, RdApiError, rdGovernanceSession, rdDerivations, rdDerivation, rdDerivationAction, rdDeriveTemplate, rdTemplateRules, rdTemplateRuleSave, rdTemplateRuleReview, rdTemplateRulePublish } from './api';
import { messageOf, readable, statusTitle, isCurrentSource } from './presentation';
import type { GovernanceSession, Project } from './types';
import './flowDesigner.css';
import './derivationExperience.css';
const asObject = (value: unknown): Record<string, unknown> => value && typeof value === 'object' ? value as Record<string,unknown> : {};
const idOf = (item: Record<string, unknown>) => String(item.id ?? item.candidate_id ?? '');
const targetOf = (item: Record<string, unknown>) => asObject(item.target ?? asObject(item.derivation).target);
const EMPTY_DRAFT = {
  baselineProduct: '', baselineDomain: '', targetProduct: '', targetLabel: '', targetDomain: '', targetDomainLabel: '', targetVersion: '1',
  evidence: '{"indicators":[],"methods":[],"criteria":[]}', operations: '[]', reason: '',
  profile: null as File | null, mapping: null as File | null, pages: [] as File[], caseId: '', sourceIds: [] as string[],
};
type DraftSnapshot = typeof EMPTY_DRAFT;
function sameDraftValue(left: DraftSnapshot[keyof DraftSnapshot], right: DraftSnapshot[keyof DraftSnapshot]) {
  return Array.isArray(left) && Array.isArray(right) ? left.length === right.length && left.every((item, index) => item === right[index]) : left === right;
}
export function TemplateDerivationPanel({ projects }: { projects: Project[] }) {
  const [access, setAccess] = useState<GovernanceSession | null>(null), [items,setItems] = useState<Array<Record<string,unknown>>>([]), [rules,setRules] = useState<Array<Record<string,unknown>>>([]);
  const [selected,setSelected] = useState<Record<string,unknown> | null>(null), [ruleId,setRuleId] = useState(''), [caseId,setCaseId] = useState('');
  const [target,setTarget] = useState({ product_type:'',product_label:'',domain:'',domain_label:'',version:'1' });
  const [baseline,setBaseline] = useState({ product_type:'',domain:'' });
  const [evidence,setEvidence] = useState('{"indicators":[],"methods":[],"criteria":[]}'), [operations,setOperations] = useState('[]'), [reason,setReason] = useState('');
  const [profile,setProfile] = useState<File | null>(null), [mapping,setMapping] = useState<File | null>(null), [pages,setPages] = useState<File[]>([]);
  const [sourceIds,setSourceIds] = useState<string[]>([]), [loading,setLoading] = useState(true), [busy,setBusy] = useState(false), [error,setError] = useState(''), [notice,setNotice] = useState('');
  const [revision,setRevision] = useState(0), [page,setPage] = useState(1), [rulePage,setRulePage] = useState(1), [total,setTotal] = useState(0), [ruleTotal,setRuleTotal] = useState(0);
  const [confirm,setConfirm] = useState<'review'|'reject'|'publish'|'rollback'|'rule-review'|'rule-publish'|null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [savedSnapshot, setSavedSnapshot] = useState<DraftSnapshot>(EMPTY_DRAFT);
  const snapshot: DraftSnapshot = {
    baselineProduct: baseline.product_type, baselineDomain: baseline.domain,
    targetProduct: target.product_type, targetLabel: target.product_label, targetDomain: target.domain, targetDomainLabel: target.domain_label, targetVersion: target.version,
    evidence, operations, reason, profile, mapping, pages, caseId, sourceIds,
  };
  const epoch = useRef(0), pending = useRef(false), retry = useRef({ fingerprint:'',key:'' });
  const contexts = projects.flatMap(project => project.cases.map(researchCase => ({ project,researchCase })));
  const context = contexts.find(item => item.researchCase.id === caseId);
  const currentSources = context?.researchCase.sources.filter(source => isCurrentSource(source, context.researchCase.source_selection)) ?? [];
  const binding = selected ? asObject(selected.project_binding) : {};
  const bound = Object.keys(binding).length > 0;
  const contextMatchesBinding = !!context && (!bound || binding.project_id === context.project.id && binding.case_id === context.researchCase.id && binding.input_revision === context.researchCase.input_revision);
  useEffect(() => {
    if (!selected?.project_binding || !sameDraftValue(caseId, savedSnapshot.caseId) || !sameDraftValue(sourceIds, savedSnapshot.sourceIds)) return;
    const current = asObject(selected.project_binding);
    const nextCaseId = typeof current.case_id === 'string' ? current.case_id : caseId;
    const nextSourceIds = Array.isArray(current.source_ids) ? current.source_ids.filter((id): id is string => typeof id === 'string') : sourceIds;
    setCaseId(nextCaseId); setSourceIds(nextSourceIds);
    setSavedSnapshot(previous => ({ ...previous, caseId: nextCaseId, sourceIds: nextSourceIds }));
  }, [selected?.candidate_id, selected?.id, selected?.project_binding]);
  const rule = rules.find(item => idOf(item) === ruleId);
  const dirty = (Object.keys(snapshot) as Array<keyof DraftSnapshot>).some(key => !sameDraftValue(snapshot[key], savedSnapshot[key]));
  useApplicationLeaveGuard({ dirty, busyMessage: busy ? '模板治理正在办理，请等待实际回执。' : undefined });
  function deny() { epoch.current++; setAccess(null); setItems([]); setRules([]); setSelected(null); setRuleId(''); setProfile(null); setMapping(null); setPages([]); setEvidence('{"indicators":[],"methods":[],"criteria":[]}'); setOperations('[]'); setReason(''); setTarget({ product_type:'',product_label:'',domain:'',domain_label:'',version:'1' }); setBaseline({product_type:'',domain:''}); setCaseId(''); setSourceIds([]); setConfirm(null); setFieldErrors({}); setSavedSnapshot(EMPTY_DRAFT); }
  function focusField(id: string) {
    const field = document.getElementById(id);
    for (let parent = field?.parentElement; parent; parent = parent.parentElement) if (parent instanceof HTMLDetailsElement) parent.open = true;
    requestAnimationFrame(() => { field?.focus(); field?.scrollIntoView({ block: 'center', behavior: 'auto' }); });
  }
  function invalid(fields: Record<string, string>, message: string) {
    setFieldErrors(fields); setError(message); focusField(Object.keys(fields)[0]);
  }
  function clearField(id: string) { setFieldErrors(current => { if (!current[id]) return current; const next = { ...current }; delete next[id]; return next; }); }
  const fieldHelp = (id: string) => fieldErrors[id] ? <small id={`${id}-error`} className="rd-error">{fieldErrors[id]}</small> : null;
  const fieldProps = (id: string) => ({ 'aria-invalid': !!fieldErrors[id], 'aria-describedby': fieldErrors[id] ? `${id}-error` : undefined });
  useEffect(() => { const controller = new AbortController(), currentEpoch=epoch.current; setLoading(true); setError(''); void (async()=>{ const session=await rdGovernanceSession(controller.signal); if(controller.signal.aborted || currentEpoch!==epoch.current)return; setAccess(session); if(!session.can_prepare_templates && !session.can_review_templates && !session.can_publish_templates){setItems([]);setRules([]);return;} const [candidates,ruleList]=await Promise.all([rdDerivations(controller.signal,page),rdTemplateRules(controller.signal,rulePage)]); if(controller.signal.aborted || currentEpoch!==epoch.current)return;setItems(candidates.items);setRules(ruleList.items);setTotal(candidates.total ?? candidates.items.length);setRuleTotal(ruleList.total ?? ruleList.items.length);setPage(value=>Math.min(value,Math.max(1,Math.ceil((candidates.total ?? candidates.items.length)/5))));setRulePage(value=>Math.min(value,Math.max(1,Math.ceil((ruleList.total ?? ruleList.items.length)/5)))); })().catch(reason=>{if(controller.signal.aborted || currentEpoch!==epoch.current)return;if(reason instanceof RdApiError && [401,403].includes(reason.status))deny();setError(messageOf(reason));}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});return()=>controller.abort();},[revision,page,rulePage]);
  async function perform(fingerprint: string, request: (key: string)=>Promise<Record<string,unknown>>, message:string, savedFields: Partial<DraftSnapshot> = {}) { if(pending.current)return;pending.current=true;setBusy(true);setError('');const currentEpoch=epoch.current;if(retry.current.fingerprint!==fingerprint)retry.current={fingerprint,key:makeRequestKey()};try{const result=await request(retry.current.key);if(currentEpoch!==epoch.current)return;setNotice(message);setConfirm(null);if(result.candidate_id){const refreshed=await rdDerivation(String(result.candidate_id));if(currentEpoch!==epoch.current)return;setSelected(refreshed);}else if(result.applicability && result.id){setRuleId(String(result.id));}setSavedSnapshot(previous => ({ ...previous, ...savedFields }));retry.current={fingerprint:'',key:''};setRevision(value=>value+1);}catch(reason){if(currentEpoch!==epoch.current)return;if(reason instanceof RdApiError && [401,403].includes(reason.status))deny();setError(messageOf(reason));}finally{pending.current=false;setBusy(false);} }
  function prepareRule() {
    const fields: Record<string, string> = {};
    if (!target.product_type) fields['rd-target-product_type'] = '请填写目标产品标识。';
    if (!target.domain) fields['rd-target-domain'] = '请填写目标领域标识。';
    if (!reason.trim()) fields['rd-governance-reason'] = '请填写本次变更依据。';
    if (!profile) fields['rd-target-profile'] = '请上传目标 Profile（YAML）。';
    if (!mapping) fields['rd-target-mapping'] = '请上传目标 mapping（YAML）。';
    if (Object.keys(fields).length || !profile || !mapping) { invalid(fields, '请补全差异规则所需字段。'); return; }
    try { const ops = JSON.parse(operations); if (!Array.isArray(ops)) throw new Error(); const payload = { target: { product_type: target.product_type, domain: target.domain }, operations: ops, reason }; const form = new FormData(); form.set('payload', JSON.stringify(payload)); form.set('target_profile', profile); form.set('target_mapping', mapping); setFieldErrors({}); void perform(JSON.stringify(payload)+profile.name+profile.size+mapping.name+mapping.size, key => rdTemplateRuleSave(form, key), '差异规则草稿已保存。审核与发布需分别办理。', { targetProduct: snapshot.targetProduct, targetDomain: snapshot.targetDomain, operations, reason, profile, mapping }); }
    catch { invalid({ 'rd-target-operations': '结构差异操作必须是 JSON 数组，请检查括号和字段格式。' }, '请检查结构差异操作。'); }
  }
  function derive() {
    const fields: Record<string, string> = {};
    if (!context) fields['rd-derivation-case'] = '请选择所属项目案例。';
    if (!sourceIds.length) fields['rd-derivation-sources'] = '请至少选择一份当前实际来源。';
    if (!baseline.product_type) fields['rd-baseline-product'] = '请填写基线产品标识。';
    if (!baseline.domain) fields['rd-baseline-domain'] = '请填写基线领域标识。';
    for (const key of Object.keys(target) as Array<keyof typeof target>) if (!target[key].trim()) fields[`rd-target-${key}`] = '请填写此目标信息。';
    if (!rule) fields['rd-derivation-rule'] = '请选择固定差异规则。';
    if (Object.keys(fields).length || !context) { invalid(fields, '请补全候选所需的基线、目标、案例与实际来源。'); return; }
    try { const professional = JSON.parse(evidence); if (!professional || typeof professional !== 'object') throw new Error(); const payload = { baseline_product_type: baseline.product_type, baseline_domain: baseline.domain, target, project_id: context.project.id, case_id: context.researchCase.id, source_ids: sourceIds, rule_id: ruleId, professional_evidence: professional }; setFieldErrors({}); void perform(JSON.stringify(payload), key => rdDeriveTemplate(payload, key), '目标派生已返回。请核对资产和阻塞原因；候选不等于已发布模板。', { baselineProduct: snapshot.baselineProduct, baselineDomain: snapshot.baselineDomain, targetProduct: snapshot.targetProduct, targetLabel: snapshot.targetLabel, targetDomain: snapshot.targetDomain, targetDomainLabel: snapshot.targetDomainLabel, targetVersion: snapshot.targetVersion, evidence, caseId, sourceIds }); }
    catch { invalid({ 'rd-professional-evidence': '专业依据必须包含 indicators、methods、criteria 引用数组，请检查 JSON 格式。' }, '请检查目标专业依据。'); }
  }
  function action(actionName:string){if(!selected)return;let payload:Record<string,unknown>|FormData={};if(actionName==='bind-project'){if(!context || !sourceIds.length){setError('请选择案例与当前实际来源后固定候选输入。');return;}payload={project_id:context.project.id,case_id:context.researchCase.id,source_ids:sourceIds,expected_input_revision:context.researchCase.input_revision,expected_manifest_digest:asObject(selected.asset_manifest).digest};}if(actionName==='regression'){if(!context){setError('请选择有权限的项目案例作为实际回归输入。');return;}payload={project_id:context.project.id,case_id:context.researchCase.id,expected_input_revision:context.researchCase.input_revision};}if(actionName==='visual-review'){if(!pages.length || !reason.trim()){setError('请上传真实版式检查页并填写核验说明。');return;}const form=new FormData();pages.forEach(file=>form.append('pages',file));form.set('expected_asset_digest',String(selected.asset_digest ?? ''));form.set('conclusion','passed');form.set('reason',reason);payload=form;}if(['review','reject'].includes(actionName))payload={approved:actionName==='review',reason,expected_manifest_digest:asObject(selected.asset_manifest).digest ?? selected.asset_digest};if(actionName==='publish')payload={expected_target_digest:selected.target_digest};if(actionName==='rollback')payload={reason};const savedFields: Partial<DraftSnapshot> = actionName === 'bind-project' ? { caseId, sourceIds } : actionName === 'visual-review' ? { reason, pages } : ['review','reject','rollback'].includes(actionName) ? { reason } : {};const fingerprint=JSON.stringify({id:idOf(selected),action:actionName,payload:payload instanceof FormData ? {asset:selected.asset_digest,reason,pages:pages.map(file=>[file.name,file.size,file.lastModified])}:payload});void perform(fingerprint,key=>rdDerivationAction(idOf(selected),actionName==='reject'?'review':actionName,payload,key),`已收到${{'bind-project':'候选来源绑定',regression:'实际回归','visual-review':'版式核验',review:'独立审核',reject:'退回',publish:'目标发布',rollback:'目标回退'}[actionName]}回执，请核对状态。`, savedFields);}
  async function detail(id:string){if(pending.current)return;setBusy(true);const currentEpoch=epoch.current;try{const result=await rdDerivation(id);if(currentEpoch===epoch.current)setSelected(result);}catch(reason){if(reason instanceof RdApiError && [401,403].includes(reason.status))deny();setError(messageOf(reason));}finally{setBusy(false);} }
  const blockers = Array.isArray(asObject(selected?.validation).blockers) ? asObject(selected?.validation).blockers as unknown[] : [];
  const deriveHint = !rule ? '请先选择已发布的差异规则。' : rule.status !== 'published' ? '当前差异规则尚未发布，请完成规则审核与发布后再派生。' : !context ? '请选择项目案例，使用实际上传来源。' : !sourceIds.length ? '请至少选择一份当前实际来源。' : '基线、目标与专业依据填写完成后，可派生候选。';
  const reasonHint = reason.trim() ? '办理时使用下方填写的依据；提交前请核对。' : '填写办理依据后可审核、退回或回退。';
  return <section className="rd-section rd-derivation-experience" aria-label="目标模板派生与独立治理">
    <div className="rd-section-head"><div><h3>目标模板派生与独立治理</h3><p>先选择候选核对待办；准备新目标时，再填写基线、来源与差异规则。</p></div><PlatformButton type="button" className="rd-button" disabled={busy || loading} onClick={() => setRevision(value => value + 1)}>刷新治理记录</PlatformButton></div>
    {loading && <p className="rd-loading" role="status">正在读取治理权限与候选…</p>}
    {busy && <p className="rd-notice" role="status">正在办理，请等待实际回执。</p>}
    {error && <p className="rd-error rd-banner" role="alert">{error} 填写内容保留；权限失效时受限资料已清除。</p>}
    {notice && <p className="rd-success rd-banner" role="status">{notice}</p>}
    {access && !access.can_prepare_templates && !access.can_review_templates && !access.can_publish_templates && <p className="rd-notice">当前账号无模板治理权限。普通项目可直接采用已发布固定版，无需再次审批。</p>}
    {access && (access.can_prepare_templates || access.can_review_templates || access.can_publish_templates) && <>
      <section className="rd-derivation-candidates" aria-label="目标候选与资产">
        <div className="rd-section-head"><h4>目标候选与资产</h4><span className="rd-badge">{total} 项</span></div>
        {!items.length && !loading && <p className="rd-empty-inline">尚无可读取的派生候选。{access.can_prepare_templates ? '可在下方展开“准备新候选”。' : '候选准备后，可在此核对并办理。'}</p>}
        <div className="rd-derivation-candidate-list">{items.map(item => <PlatformButton key={idOf(item)} type="button" className="rd-button" disabled={busy} aria-pressed={idOf(selected ?? {}) === idOf(item)} onClick={() => void detail(idOf(item))}>{String(targetOf(item).product_label ?? idOf(item))} · {statusTitle(String(item.status ?? 'candidate'))}</PlatformButton>)}</div>
        <div className="rd-designer-toolbar"><span>{total} 项 · 第 {page}/{Math.max(1, Math.ceil(total / 5))} 页</span><PlatformButton type="button" className="rd-button compact" disabled={busy || page <= 1} onClick={() => setPage(value => value - 1)}>上一页</PlatformButton><PlatformButton type="button" className="rd-button compact" disabled={busy || page >= Math.ceil(total / 5)} onClick={() => setPage(value => value + 1)}>下一页</PlatformButton></div>
        {!selected && !!items.length && <p className="rd-muted">选择候选，查看当前阻塞原因与可办理操作。</p>}
        {selected && <div className="rd-derivation-selected">
          <div className="rd-section-head"><h4>{String(targetOf(selected).product_label ?? idOf(selected))}</h4><span className="rd-badge">{statusTitle(String(selected.status ?? 'candidate'))}</span></div>
          <p className="rd-muted">{selected.publish_ready === true ? '已满足候选发布条件，仍需发布回执。' : '发布条件以服务端核验为准；请先核对实际验证记录。'}</p>
          {!!blockers.length && <div className="rd-notice"><strong>待处理事项</strong><ul>{blockers.map((item, index) => <li key={index}>{typeof item === 'string' ? item : String(asObject(item).message ?? asObject(item).reason ?? readable(item))}</li>)}</ul></div>}
          {access.can_prepare_templates && <section className="rd-derivation-operation" aria-label="候选来源绑定">
            <h5>来源绑定与实际回归</h5>
            {bound ? <p className="rd-muted">已固定案例 {context && context.researchCase.id === binding.case_id ? context.researchCase.title : String(binding.case_id)} · 输入修订 {String(binding.input_revision)}。回归必须使用同一固定输入。</p> : <p id="rd-candidate-binding-help" className="rd-notice">此历史导入候选尚未绑定实际项目来源。请先选择案例与当前来源，再固定绑定。</p>}
            {bound && !contextMatchesBinding && <p className="rd-notice">当前案例或输入修订与候选绑定不同，不能开始回归。</p>}
            <div className="rd-inline-actions">
              {!bound && <PlatformButton type="button" className="rd-button" disabled={busy || !context || !sourceIds.length} aria-describedby="rd-candidate-binding-help" onClick={() => action('bind-project')}>固定所选案例与来源</PlatformButton>}
              <PlatformButton type="button" className="rd-button" disabled={busy || !bound || !contextMatchesBinding} aria-describedby="rd-candidate-regression-help" onClick={() => action('regression')}>运行实际回归</PlatformButton>
              <PlatformButton type="button" className="rd-link-button" disabled={busy} onClick={() => focusField('rd-derivation-case')}>选择案例与来源</PlatformButton>
            </div>
            <p id="rd-candidate-regression-help" className="rd-muted">{!bound ? '请先固定候选的案例与来源，再开始回归。' : !contextMatchesBinding ? '请核对绑定案例及输入修订。' : '将使用候选固定输入进行实际回归。'}</p>
          </section>}
          {access.can_review_templates && <section className="rd-derivation-operation" aria-label="版式核验">
            <h5>版式核验</h5>
            <div className="rd-field"><label htmlFor="rd-review-pages">真实版式检查页</label><input id="rd-review-pages" type="file" multiple accept="image/png,image/jpeg" disabled={busy} onChange={event => setPages(Array.from(event.target.files ?? []))} /></div>
            <PlatformButton type="button" className="rd-button" disabled={busy || !pages.length || !reason.trim()} aria-describedby="rd-visual-review-help" onClick={() => action('visual-review')}>登记版式核验通过</PlatformButton>
            <p id="rd-visual-review-help" className="rd-muted">{!pages.length ? '请上传真实检查页（PNG / JPG），并填写核验依据。' : !reason.trim() ? '检查页已选择，请填写核验依据。' : `已选择 ${pages.length} 张检查页；本次登记使用填写的依据。`}</p>
          </section>}
          {(access.can_review_templates || access.can_publish_templates) && <section className="rd-derivation-operation" aria-label="候选审核与发布">
            <h5>审核与发布</h5>
            <p id="rd-candidate-reason-help" className="rd-muted">{reasonHint}</p>
            <div className="rd-designer-toolbar">
              {access.can_review_templates && <><PlatformButton type="button" className="rd-button" disabled={busy || !reason.trim()} aria-describedby="rd-candidate-reason-help" onClick={() => setConfirm('review')}>独立审核候选</PlatformButton><PlatformButton type="button" className="rd-button" disabled={busy || !reason.trim()} aria-describedby="rd-candidate-reason-help" onClick={() => setConfirm('reject')}>退回候选</PlatformButton></>}
              {access.can_publish_templates && <><PlatformButton type="button" className="rd-button primary" disabled={busy} onClick={() => setConfirm('publish')}>发布目标固定版</PlatformButton><PlatformButton type="button" className="rd-button danger" disabled={busy || !reason.trim()} aria-describedby="rd-candidate-reason-help" onClick={() => setConfirm('rollback')}>回退此目标发布</PlatformButton></>}
              <PlatformButton type="button" className="rd-link-button" disabled={busy} onClick={() => focusField('rd-governance-reason')}>填写办理依据</PlatformButton>
            </div>
          </section>}
          <details className="rd-disclosure"><summary>适用目标、差异与验证结果</summary><pre className="rd-designer-diff">{readable({ target: targetOf(selected), baseline: selected.baseline, derivation: selected.derivation, validation: selected.validation, regression: selected.regression, review: selected.review })}</pre></details>
          <details className="rd-disclosure"><summary>DOCX / Profile / mapping / 规则 / 来源资产摘要</summary><pre className="rd-designer-diff">{readable({ asset_manifest: selected.asset_manifest, asset_digest: selected.asset_digest, target_digest: selected.target_digest })}</pre></details>
        </div>}
      </section>
      <div className="rd-field rd-derivation-reason"><label htmlFor="rd-governance-reason">变更 / 核验 / 审核依据</label><textarea id="rd-governance-reason" className="resize-none" rows={3} value={reason} disabled={busy} {...fieldProps('rd-governance-reason')} onChange={event => { setReason(event.target.value); clearField('rd-governance-reason'); }} /><small>供本次规则变更、版式核验、独立审核或回退使用。提交前请核对依据与当前对象一致。</small>{fieldHelp('rd-governance-reason')}</div>
      <section className="rd-derivation-rules" aria-label="受控差异规则">
        <div className="rd-section-head"><h4>受控差异规则</h4><span className="rd-muted">审核与发布分别办理</span></div>
        <div className="rd-field"><label id="rd-derivation-rule-label">固定差异规则</label><StyledSelect id="rd-derivation-rule" aria-labelledby="rd-derivation-rule-label" aria-describedby={fieldErrors['rd-derivation-rule'] ? 'rd-derivation-rule-error' : undefined} invalid={!!fieldErrors['rd-derivation-rule']} value={ruleId} disabled={busy} onChange={value => { setRuleId(value); clearField('rd-derivation-rule'); }} options={[{ value: '', label: '选择目标差异规则' }, ...rules.map(item => ({ value: idOf(item), label: `${idOf(item)} · V${item.version} · ${statusTitle(String(item.status))}` }))]} />{fieldHelp('rd-derivation-rule')}</div>
        <div className="rd-designer-toolbar" aria-label="差异规则分页"><span>{ruleTotal} 项 · 第 {rulePage}/{Math.max(1, Math.ceil(ruleTotal / 5))} 页</span><PlatformButton type="button" className="rd-button compact" disabled={busy || loading || rulePage <= 1} onClick={() => { setRuleId(''); setRulePage(value => value - 1); }}>上一页规则</PlatformButton><PlatformButton type="button" className="rd-button compact" disabled={busy || loading || rulePage >= Math.ceil(ruleTotal / 5)} onClick={() => { setRuleId(''); setRulePage(value => value + 1); }}>下一页规则</PlatformButton></div>
        {rule && <><details className="rd-disclosure"><summary>差异规则完整记录</summary><pre className="rd-designer-diff">{readable(rule)}</pre></details><div className="rd-designer-toolbar">{access.can_review_templates && <PlatformButton type="button" className="rd-button" disabled={busy || !reason.trim()} aria-describedby={!reason.trim() ? 'rd-rule-reason-help' : undefined} onClick={() => setConfirm('rule-review')}>独立审核此规则</PlatformButton>}{access.can_publish_templates && <PlatformButton type="button" className="rd-button" disabled={busy} onClick={() => setConfirm('rule-publish')}>发布已审核规则</PlatformButton>}{access.can_review_templates && !reason.trim() && <PlatformButton type="button" className="rd-link-button" disabled={busy} onClick={() => focusField('rd-governance-reason')}>填写办理依据</PlatformButton>}</div>{access.can_review_templates && !reason.trim() && <p id="rd-rule-reason-help" className="rd-muted">请先填写审核依据，再办理此规则的独立审核。</p>}</>}
      </section>
      {access.can_prepare_templates && <>
        <details className="rd-derivation-task"><summary><strong>准备新候选</strong><span>基线、目标与实际来源 · 已选 {sourceIds.length} 份来源</span></summary>
          <div className="rd-derivation-task-body">
            <p className="rd-muted">复用受控结构，目标专业指标、方法与判据仍须有实际来源。候选不等于已发布模板。</p>
            <div className="rd-field"><label id="rd-derivation-case-label">来源与实际回归案例</label><StyledSelect id="rd-derivation-case" aria-labelledby="rd-derivation-case-label" aria-describedby={fieldErrors['rd-derivation-case'] ? 'rd-derivation-case-error' : undefined} invalid={!!fieldErrors['rd-derivation-case']} value={caseId} disabled={busy} onChange={id => { setCaseId(id); setSourceIds([]); clearField('rd-derivation-case'); }} options={[{ value: '', label: '选择有权限的项目案例' }, ...contexts.map(item => ({ value: item.researchCase.id, label: `${item.project.title} / ${item.researchCase.title}` }))]} />{fieldHelp('rd-derivation-case')}</div>
            <fieldset id="rd-derivation-sources" tabIndex={-1} disabled={busy} {...fieldProps('rd-derivation-sources')}><legend>实际来源固定版</legend>
              {currentSources.map(source => <div key={source.id} className="rd-derivation-source"><label className="rd-dependency-option"><input type="checkbox" checked={sourceIds.includes(source.id)} onChange={event => { setSourceIds(current => event.target.checked ? [...current, source.id] : current.filter(id => id !== source.id)); clearField('rd-derivation-sources'); }} />{source.name} · V{source.version}</label><details className="rd-disclosure"><summary>来源标识与摘要</summary><code>{source.id} · {source.sha256}</code></details></div>)}
              {!currentSources.length && <p className="rd-muted">{!context ? '请先选择案例，再选择其实际上传资料。' : '此案例没有当前可用来源，请先在项目中上传或确认资料。'}</p>}{fieldHelp('rd-derivation-sources')}
            </fieldset>
            <h5>基线与目标</h5>
            <div className="rd-derivation-grid">
              <div className="rd-field"><label htmlFor="rd-baseline-product">基线产品标识</label><input id="rd-baseline-product" value={baseline.product_type} disabled={busy} {...fieldProps('rd-baseline-product')} onChange={event => { setBaseline({ ...baseline, product_type: event.target.value }); clearField('rd-baseline-product'); }} />{fieldHelp('rd-baseline-product')}</div>
              <div className="rd-field"><label htmlFor="rd-baseline-domain">基线领域标识</label><input id="rd-baseline-domain" value={baseline.domain} disabled={busy} {...fieldProps('rd-baseline-domain')} onChange={event => { setBaseline({ ...baseline, domain: event.target.value }); clearField('rd-baseline-domain'); }} />{fieldHelp('rd-baseline-domain')}</div>
              {(Object.keys(target) as Array<keyof typeof target>).map(key => <div className="rd-field" key={key}><label htmlFor={`rd-target-${key}`}>{{ product_type: '目标产品标识', product_label: '目标产品名称', domain: '目标领域标识', domain_label: '目标领域名称', version: '目标资产版本' }[key]}</label><input id={`rd-target-${key}`} value={target[key]} disabled={busy} {...fieldProps(`rd-target-${key}`)} onChange={event => { setTarget({ ...target, [key]: event.target.value }); clearField(`rd-target-${key}`); }} />{fieldHelp(`rd-target-${key}`)}</div>)}
            </div>
            <div className="rd-field"><label htmlFor="rd-professional-evidence">目标专业依据（指标 / 方法 / 判据）</label><textarea id="rd-professional-evidence" className="resize-none rd-code-input" rows={8} value={evidence} disabled={busy} {...fieldProps('rd-professional-evidence')} onChange={event => { setEvidence(event.target.value); clearField('rd-professional-evidence'); }} /><small>每条引用包含 source_id、version、sha256、location、quote；原文必须来自所选固定来源。结构复用不代表工程认可。</small>{fieldHelp('rd-professional-evidence')}</div>
            <p id="rd-derive-help" className="rd-notice">{deriveHint}</p><div className="rd-inline-actions"><PlatformButton type="button" className="rd-button primary" disabled={busy || !rule || rule.status !== 'published'} aria-describedby="rd-derive-help" onClick={derive}>派生完整目标候选</PlatformButton><PlatformButton type="button" className="rd-link-button" disabled={busy} onClick={() => focusField('rd-derivation-rule')}>选择差异规则</PlatformButton></div>
          </div>
        </details>
        <details className="rd-derivation-task"><summary><strong>维护差异规则</strong><span>上传目标配置、保存草稿 · 审核与发布分别办理</span></summary>
          <div className="rd-derivation-task-body">
            <p className="rd-muted">本次规则目标：{target.product_type || '产品标识未填写'} / {target.domain || '领域标识未填写'}。</p><PlatformButton type="button" className="rd-link-button" disabled={busy} onClick={() => focusField('rd-target-product_type')}>填写目标产品与领域</PlatformButton>
            <div className="rd-derivation-grid">
              <div className="rd-field"><label htmlFor="rd-target-profile">目标 Profile（YAML）</label><input id="rd-target-profile" type="file" accept=".yaml,.yml" disabled={busy} {...fieldProps('rd-target-profile')} onChange={event => { setProfile(event.target.files?.[0] ?? null); clearField('rd-target-profile'); }} />{fieldHelp('rd-target-profile')}<details className="rd-disclosure"><summary>Profile 填写要求</summary><p>目标 Profile 需明确禁用继承的指标词表（indicator_sources：workbook=false、reference_families=[]），并为指标、方法、判据分别设置专业引用合同的标签或章节选择器。规则审核固定上传文件摘要。</p></details></div>
              <div className="rd-field"><label htmlFor="rd-target-mapping">目标 mapping（YAML）</label><input id="rd-target-mapping" type="file" accept=".yaml,.yml" disabled={busy} {...fieldProps('rd-target-mapping')} onChange={event => { setMapping(event.target.files?.[0] ?? null); clearField('rd-target-mapping'); }} />{fieldHelp('rd-target-mapping')}</div>
              <div className="rd-field rd-derivation-full"><label htmlFor="rd-target-operations">结构差异操作（JSON 数组）</label><textarea id="rd-target-operations" className="resize-none rd-code-input" rows={5} value={operations} disabled={busy} {...fieldProps('rd-target-operations')} onChange={event => { setOperations(event.target.value); clearField('rd-target-operations'); }} /><small>操作按现有模板大纲编辑合同校验；上传文件由服务端计算摘要，不能自报批准。</small>{fieldHelp('rd-target-operations')}</div>
            </div>
            <p className="rd-muted">保存只生成规则草稿，使用上方填写的目标与变更依据。</p><PlatformButton type="button" className="rd-button" disabled={busy} onClick={prepareRule}>保存差异规则草稿</PlatformButton>
          </div>
        </details>
      </>}
    </>}
    {confirm && <FeedbackConfirmDialog title={{review:'独立审核目标候选',reject:'退回目标候选',publish:'发布目标固定版',rollback:'回退此目标发布','rule-review':'独立审核差异规则','rule-publish':'发布差异规则'}[confirm]} confirm={{review:'审核通过',reject:'退回候选',publish:'发布目标模板',rollback:'回退目标绑定','rule-review':'审核规则','rule-publish':'发布规则'}[confirm]} danger={confirm==='rollback'||confirm==='reject'} pending={busy} error={error} onCancel={()=>setConfirm(null)} onConfirm={()=>{if(confirm==='rule-review' && rule){const payload={approved:true,reason,expected_digest:rule.digest};void perform(JSON.stringify({id:ruleId,...payload}),key=>rdTemplateRuleReview(ruleId,payload,key),'差异规则审核回执已保存，尚未发布。', { reason });}else if(confirm==='rule-publish' && rule){const payload={expected_digest:rule.digest};void perform(JSON.stringify({id:ruleId,...payload}),key=>rdTemplateRulePublish(ruleId,payload,key),'差异规则发布回执已保存。');}else action(confirm);}}><p>服务端独立核验治理资格、固定资产摘要、来源和实际验证证据。发布不替代项目采用；回退只恢复此目标绑定。</p></FeedbackConfirmDialog>}
  </section>;
}

