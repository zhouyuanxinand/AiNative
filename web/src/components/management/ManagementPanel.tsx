/** 管理面板——规则中心 / 模板目录。 */
import { useState, useEffect, type FormEvent } from 'react';
import { useTaskbook } from '../../hooks/useTaskbook';
import { RulesView } from './RulesView';
import { TemplateDirectory } from './TemplateDirectory';
import { FailureDatabaseView } from './FailureDatabaseView';
import {
  loadTemplateDirectory,
  loadTemplateCandidates,
  onboardTemplate,
  postCandidateAction,
} from '../../api/templates';
import type { TemplateItem, TemplateCandidate } from '../../types';

export function ManagementPanel() {
  const { managementKind, setManagementKind, setWorkspaceView } = useTaskbook();

  if (!managementKind) return null;

  return (
    <section className="management-panel open" id="management-panel" aria-live="polite">
      <div className="management-head">
        <h2 id="management-title">
          {managementKind === 'rules'
            ? '规则中心'
            : managementKind === 'failures'
              ? '故障数据库'
              : '模板目录'}
        </h2>
        <button
          className="management-close"
          type="button"
          onClick={() => {
            setManagementKind(null);
            setWorkspaceView('generate');
          }}
        >
          返回首页
        </button>
      </div>
      {managementKind === 'rules' && <RulesView />}
      {managementKind === 'templates' && <TemplatesView />}
      {managementKind === 'failures' && <FailureDatabaseView />}
    </section>
  );
}

function TemplatesView() {
  const [directory, setDirectory] = useState<TemplateItem[]>([]);
  const [candidates, setCandidates] = useState<TemplateCandidate[]>([]);
  const [dirError, setDirError] = useState('');
  const [candidateError, setCandidateError] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    setDirError('');
    setCandidateError('');
    setLoading(true);
    Promise.all([
      loadTemplateDirectory().catch((e) => { if (active) setDirError(e.message); }),
      loadTemplateCandidates().catch((e) => { if (active) setCandidateError(e.message); }),
    ]).then(([dir, cands]) => {
      if (!active) return;
      if (Array.isArray(dir)) setDirectory(dir);
      if (Array.isArray(cands)) setCandidates(cands);
      setLoading(false);
    });
    return () => { active = false; };
  }, [revision]);

  const refresh = () => setRevision((value) => value + 1);
  return (
    <div className="management-view active" id="management-templates">
      <TemplateDirectory directory={directory} error={dirError} loading={loading} onRefresh={refresh} />
      <details className="template-advanced">
        <summary>新增产品模板与候选审批</summary>
        <p className="management-note">更换现有产品模板可在上方直接操作。新产品类型的首次接入仍需完成规则配置、样例回归及审核。</p>
        <div className="candidate-section">
          <h3>候选模板与发布审批</h3>
          <div className="candidate-list" id="template-candidates">
            {candidateError ? <div role="alert">候选模板读取失败：{candidateError}</div>
              : candidates.length === 0 ? <div className="management-status">当前没有候选模板。</div>
              : candidates.map(c => <CandidateCard key={c.candidate_id} candidate={c} onRefresh={refresh} />)}
          </div>
        </div>
        <OnboardingBox onSubmitted={refresh} />
      </details>
    </div>
  );
}

function CandidateCard({
  candidate,
  onRefresh,
}: {
  candidate: TemplateCandidate;
  onRefresh: () => void;
}) {
  const [actor, setActor] = useState('');
  const [reason, setReason] = useState('');
  const [regressionPassed, setRegressionPassed] = useState(false);
  const [visualReviewPassed, setVisualReviewPassed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState('');

  const act = async (action: 'review' | 'publish' | 'rollback', approved = true) => {
    setBusy(true);
    setResult('正在提交受控操作…');
    try {
      if (action === 'review') {
        await postCandidateAction(candidate.candidate_id, action, {
          approved,
          reviewer: actor.trim(),
          reason: reason.trim(),
          regression_passed: regressionPassed,
          visual_review_passed: visualReviewPassed,
          biz_id: 'template-review',
          user_id: actor.trim(),
        });
      } else if (action === 'publish') {
        await postCandidateAction(candidate.candidate_id, action, {
          publisher: actor.trim(),
        });
      } else {
        await postCandidateAction(candidate.candidate_id, action, {
          actor: actor.trim(),
          reason: reason.trim(),
        });
      }
      setResult('操作成功，正在刷新状态…');
      onRefresh();
    } catch (error) {
      setResult(`操作失败：${(error as Error).message || '未知错误'}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="candidate-card" data-candidate-id={candidate.candidate_id}>
      <div className="candidate-head">
        <div>
          <strong>
            {candidate.product_label || candidate.product_type || '-'} / {candidate.domain_label || candidate.domain || '-'}
          </strong>
          <div className="candidate-meta">
            候选 {candidate.candidate_id} · 版本 {candidate.version || '-'} · 机器校验
            {candidate.machine_validation_passed ? '通过' : '未通过'}
          </div>
        </div>
        <span className={`candidate-badge ${candidate.status || ''}`}>
          {candidate.status || 'candidate'}
        </span>
      </div>
      <div className="candidate-controls">
        <input
          type="text"
          placeholder="审核/发布人（必填）"
          value={actor}
          onChange={(event) => setActor(event.target.value)}
        />
        <input
          type="text"
          placeholder="审核或回滚原因（必填）"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
        <div className="candidate-checks">
          <label>
            <input
              type="checkbox"
              checked={regressionPassed}
              onChange={(event) => setRegressionPassed(event.target.checked)}
            />
            真实样例回归已通过
          </label>
          <label>
            <input
              type="checkbox"
              checked={visualReviewPassed}
              onChange={(event) => setVisualReviewPassed(event.target.checked)}
            />
            整页视觉复核已通过
          </label>
        </div>
        <div className="candidate-actions">
          {!['approved', 'published', 'rolled_back'].includes(candidate.status || '') && (
            <>
              <button className="primary" type="button" disabled={busy} onClick={() => act('review', true)}>
                批准候选
              </button>
              <button className="danger" type="button" disabled={busy} onClick={() => act('review', false)}>
                拒绝候选
              </button>
            </>
          )}
          {candidate.status === 'approved' && (
            <button className="primary" type="button" disabled={busy} onClick={() => act('publish')}>
              发布到正式目录
            </button>
          )}
          {candidate.status === 'published' && (
            <button className="danger" type="button" disabled={busy} onClick={() => act('rollback')}>
              回滚该版本
            </button>
          )}
        </div>
        <div className="management-status candidate-result">{result}</div>
      </div>
    </div>
  );
}

function OnboardingBox({ onSubmitted }: { onSubmitted: () => void }) {
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setStatus('正在扫描标题树并校验槽位覆盖…');
    try {
      const data = await onboardTemplate(new FormData(event.currentTarget));
      const machine = data.machine_validation_passed ? '机器校验通过' : '机器校验未通过';
      setStatus(
        `候选 ${String(data.candidate_id || '-')} 已隔离保存：${machine}；槽位 ${String(data.slot_count ?? '-')}，待解决 ${String(data.unresolved_count ?? '-')}。必须人工审核后才能发布。`,
      );
      onSubmitted();
    } catch (error) {
      setStatus(`候选模板提交失败：${(error as Error).message || '未知错误'}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="onboarding-box">
      <h3>提交候选模板</h3>
      <p>
        上传后仅执行安全校验、标题树扫描和槽位覆盖检查，进入待审核区；不会直接修改产品目录或正式生成模板。
      </p>
      <form
        className="onboarding-form"
        id="template-onboarding-form"
        onSubmit={submit}
      >
        <label>
          产品类型 ID
          <input type="text" name="product_type" required placeholder="例如 low_frequency_connector" />
        </label>
        <label>
          产品类型名称
          <input type="text" name="product_label" required placeholder="例如 低频连接器" />
        </label>
        <label>
          领域 ID
          <input type="text" name="domain" required placeholder="例如 military" />
        </label>
        <label>
          领域名称
          <input type="text" name="domain_label" required placeholder="例如 军品" />
        </label>
        <label>
          模板版本
          <input type="text" name="version" defaultValue="1.0.0" required />
        </label>
        <label>
          业务标识 biz_id
          <input type="text" name="biz_id" defaultValue="template-onboarding" required />
        </label>
        <label>
          用户标识 user_id
          <input type="text" name="user_id" defaultValue="web-user" required />
        </label>
        <label className="wide">
          候选 DOCX
          <input type="file" name="template" accept=".docx" required />
        </label>
        <div className="onboarding-actions">
          <button className="onboarding-submit" type="submit" disabled={busy}>
            扫描并提交审核
          </button>
          <span className="onboarding-warning">候选模板不会自动发布</span>
        </div>
      </form>
      <div className="management-status" id="template-onboarding-status">{status}</div>
    </div>
  );
}
