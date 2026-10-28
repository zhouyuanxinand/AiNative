/** 结果卡片——摘要 + 下载按钮 + 警告 + 门禁面板。 */
import { useTaskbook } from '../../hooks/useTaskbook';
import { escapeHtml } from '../../../../shared/lib/dom';
import { IndicatorReviewPanel } from './IndicatorReviewPanel';
import { GenerationFeedback } from '../../../feedback/components/GenerationFeedback';
import { readRdContext } from '../../model/rdGeneration';

export function ResultCard() {
  const { jobResult, resultBlocked, currentJid } = useTaskbook();
  let projectContext = null;
  try { projectContext = readRdContext(window.location.search); } catch { /* The context banner explains malformed links. */ }
  const reviewQuery = projectContext ? `?${new URLSearchParams({ rd_project: projectContext.project_id, rd_task: projectContext.task_id })}` : '';
  // 旧版会在终态事件未带完整 result 时保留结果卡和下载入口；
  // 不应因为某个 SSE 字段缺失而让整个结果栏变空。
  const result = jobResult || {};
  const meta = result.meta || {};
  const stats = meta.stats || {};
  const scopeLabel = meta.organization_scope === 'central_research' ? '中央研究院产品' : '非中央研究院产品';
  const warns = result.warnings || [];
  const imageWarns = warns.filter((w) => String(w).includes('图片'));
  const otherWarns = warns.filter((w) => !String(w).includes('图片'));

  // 门禁面板
  const gateCandidates = [
    meta.gate_result,
    meta.configured_qa_gate,
    meta.semantic_integrity_gate,
    meta.delivery_gate_result,
  ].filter(Boolean);
  const firstFailedGate = gateCandidates.find(
    (g) => g && (g.passed === false || g.deliverable === false),
  );
  const gate = firstFailedGate || meta.gate_result || gateCandidates[0] || null;
  const allGatesPassed = !resultBlocked && gateCandidates.every(
    (g) => g && g.passed !== false && g.deliverable !== false,
  );

  return (
    <div className="card result-wrap" id="result-card">
      <h2>
        <span className="section-kicker" id="result-kicker">
          {resultBlocked ? 'BLOCKED' : projectContext ? 'DRAFT' : 'DELIVERED'}
        </span>
        <span id="result-title">
          {resultBlocked ? '已生成复核件（未通过交付门禁）' : '生成完成'}
        </span>
      </h2>
      {projectContext && <p>此文件为研发任务工作稿。文档检查通过后，请返回项目登记固定成果并送交独立审签；工程批准结果以项目审签记录为准。</p>}
      {currentJid && !projectContext && <GenerationFeedback jid={currentJid} />}
      <div className="result-summary" id="result-summary">
        <SummaryItem label="识别产品" value={meta.product_type || '-'} />
        <SummaryItem
          label="使用配置"
          value={`${meta.selected_product_type_label || '-'} / ${meta.product_domain_label || '-'} / ${meta.development_process || '-'} / ${meta.product_series || '未填系列'} / ${scopeLabel} / ${meta.profile || '-'}`}
        />
        <SummaryItem label="输出文件" value={meta.output_name || '-'} />
        <SummaryItem label="保存位置" value={meta.saved_path || '浏览器下载未落地时，可直接去这里取'} />
        <SummaryItem
          label="图片 / 媒体"
          value={`${stats.drawing_count ?? '-'} 张图片引用 / ${stats.media_count ?? '-'} 个媒体文件`}
        />
        <SummaryItem
          label="QA / LLM"
          value={`${meta.qa_ok === null ? '-' : meta.qa_ok ? 'QA通过' : 'QA阻断'} / ${meta.llm_model || (meta.use_llm ? '模型已启用' : '模型未启用')}`}
        />
        <SummaryItem label="图片决策" value={`${meta.image_warning_count || 0} 条图片筛选提示`} />
        <SummaryItem
          label="清理统计"
          value={`删段 ${stats.para_deleted ?? 0} / 红字 ${stats.red_cleared ?? 0} / 高亮 ${stats.hl_cleared ?? 0}`}
        />
      </div>
      <div className="result-grid">
        {currentJid && <a className="btn-dl btn-docx" id="btn-review" href={`/review/${encodeURIComponent(currentJid)}${reviewQuery}`}>
          <svg className="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 4h7v16H4zM14 4h6v16h-6M7 8h1M7 12h1M17 8h1M17 12h1" /></svg>
          打开审阅模式
        </a>}
        <a
          className="btn-dl btn-docx"
          id="btn-docx"
          href={currentJid ? `/api/download/${encodeURIComponent(currentJid)}` : '#'}
          download
        >
          <svg className="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M6 3h9l3 3v15H6z" />
            <path d="M14 3v4h4M9 12h6M9 16h6" />
          </svg>
          {resultBlocked ? '下载未通过文件（仅供复核）' : '下载研制任务书 (.docx)'}
        </a>
        <a
          className="btn-dl btn-html"
          id="btn-html"
          href={currentJid ? `/api/report/${encodeURIComponent(currentJid)}` : '#'}
          target="_blank"
          rel="noopener"
        >
          <svg className="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M4 5h16v14H4z" />
            <path d="M8 9h8M8 13h5" />
          </svg>
          查看质量报告 (HTML)
        </a>
        <a
          className="btn-dl btn-html"
          id="btn-report-download"
          href={currentJid ? `/api/report/${encodeURIComponent(currentJid)}/download` : '#'}
          download
        >
          <svg className="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 4v11M8 11l4 4 4-4M5 20h14" />
          </svg>
          下载质量报告 (HTML)
        </a>
      </div>

      {/* 图片警告 */}
      {imageWarns.length > 0 && (
        <div className="warns-box" id="image-warns-box">
          {imageWarns.map((w, i) => (
            <div key={i} className="warn-item image-decision">
              🖼 {w}
            </div>
          ))}
        </div>
      )}

      {/* 其他警告 */}
      {otherWarns.length > 0 && (
        <div className="warns-box" id="warns-box">
          {otherWarns.map((w, i) => (
            <div key={i} className="warn-item">
              ⚠ {w}
            </div>
          ))}
        </div>
      )}

      {currentJid && <IndicatorReviewPanel key={currentJid} jid={currentJid} />}
      {currentJid && meta.source_review_required && <section className="indicator-review" aria-label="输入文档识别复核">
        <h3>输入文档待复核</h3>
        <p>转换或 OCR 内容需逐页核对。下载原件、识别文本与原页证据，核对或修正后上传 DOCX 重新生成。</p>
        {Object.entries(meta.input_normalization || {}).filter(([, value]) => value.evidence_path).map(([role]) => <p key={role}><a href={`/api/input_evidence/${encodeURIComponent(currentJid)}/${role}`}>下载{role === 'tech' ? '需求文件' : '产品规范'}识别证据（ZIP）</a></p>)}
      </section>}

      {/* 门禁面板 */}
      {gate && gate.passed !== null && (
        <GatePanel gate={gate} allPassed={allGatesPassed} blocked={resultBlocked} />
      )}

      <div className="result-reset">
        <button
          onClick={() => window.dispatchEvent(new CustomEvent('taskbook:reset'))}
          className="btn-progress-reset"
        >
          <svg className="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M4 12a8 8 0 1 0 2.3-5.7" />
            <path d="M4 5v5h5" />
          </svg>
          重新开始
        </button>
      </div>
    </div>
  );
}

function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="summary-item">
      <div className="summary-label">{label}</div>
      <div className="summary-value">{value}</div>
    </div>
  );
}

function GatePanel({
  gate,
  allPassed,
  blocked,
}: {
  gate: NonNullable<NonNullable<import('../../model/types').JobMeta>['gate_result']>;
  allPassed: boolean;
  blocked: boolean;
}) {
  if (allPassed) {
    return (
      <div
        id="gate-panel"
        style={{
          display: 'block',
          marginTop: 12,
          background: 'var(--color-success-bg)',
          border: '1px solid var(--color-success-border)',
          borderRadius: 10,
          padding: '12px 16px',
          fontSize: 13,
          color: 'var(--color-success)',
        }}
      >
        ✅ 全部门禁通过
      </div>
    );
  }
  const cats = gate.categories || {};
  const catColors: Record<string, string> = {
    '模板/污染': 'var(--red)',
    '图题/图片': 'var(--orange)',
    表格结构: '#531dab',
    关键内容: 'var(--blue)',
    '格式/变更': '#874d00',
  };
  const total = Math.max(
    Object.values(cats).reduce((s, v) => s + v.length, 0),
    blocked ? 1 : 0,
  );
  const warnHtml = (gate.warnings || [])
    .map((w) => `<li style="font-size:12px;color:var(--muted);padding:2px 0">${escapeHtml(w)}</li>`)
    .join('');
  let rows = '';
  for (const [cat, items] of Object.entries(cats)) {
    const color = catColors[cat] || 'var(--muted)';
    items.forEach((item) => {
      rows += `<tr><td style="padding:5px 8px;white-space:nowrap"><span style="display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;font-weight:600;background:var(--color-error-bg);color:${color};border:1px solid ${color}">${escapeHtml(cat)}</span></td><td style="padding:5px 8px;font-size:13px">${escapeHtml(item)}</td></tr>`;
    });
  }
  return (
    <div
      id="gate-panel"
      style={{ display: 'block', marginTop: 12 }}
      dangerouslySetInnerHTML={{
        __html: `<div style="background:var(--solid);border:1px solid var(--color-error-border);border-left:4px solid var(--red);border-radius:10px;padding:14px 16px"><div style="font-weight:600;font-size:14px;color:var(--red);margin-bottom:10px">❌ 门禁未通过（${total} 项阻断）</div><table style="width:100%;border-collapse:collapse">${rows}</table>${warnHtml ? `<ul style="margin-top:8px;padding-left:18px">${warnHtml}</ul>` : ''}</div>`,
      }}
    />
  );
}
