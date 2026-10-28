/** 历史任务网格——展示 /api/history 返回的任务列表。 */
import { useTaskbook } from '../../hooks/useTaskbook';
import type { HistoryItem } from '../../model/types';

export function HistoryGrid() {
  const { history } = useTaskbook();

  return (
    <div className="card history-wrap" id="history-card">
      <h2>
        <span className="section-kicker">HISTORY</span>当前服务最近任务
      </h2>
      <p className="section-sub">
        这里只显示当前服务实例生成的结果，旧发布版本任务仍保留在后台审计记录中。
      </p>
      <div className="history-grid" id="history-grid">
        {history.length === 0 ? (
          <div className="hist-empty">暂无历史任务，首次生成后将在此显示。</div>
        ) : (
          history.map((item, i) => <HistoryCard key={item.jid || i} item={item} />)
        )}
      </div>
    </div>
  );
}

function HistoryCard({ item }: { item: HistoryItem }) {
  const qa = item.qa_ok === null ? '-' : item.qa_ok ? '通过' : '阻断';
  const delivery =
    item.delivery_status === 'approved'
      ? '通过'
      : item.delivery_status === 'blocked'
        ? '阻断'
        : item.delivery_status || '-';
  const canReuse = Boolean(
    item.product_type_id || item.product_domain_id || item.development_process,
  );

  const applyPreset = (autoPrecheck: boolean) =>
    window.dispatchEvent(
      new CustomEvent('taskbook:apply-history', { detail: { item, autoPrecheck } }),
    );

  return (
    <div className="hist-item">
      <div className="hist-title">
        {item.created_at || '-'} / {item.status}
      </div>
      <div className="hist-val">
        产品：{item.product || '-'}
        <br />
        配置：{item.profile || '-'}
        <br />
        交付：{delivery}
        <br />
        基础 QA：{qa}
        <br />
        图片：{Number(item.drawing_count || 0)} / 媒体：{Number(item.media_count || 0)}
        <br />
        图片决策：{Number(item.image_warning_count || 0)} 条提示
        <br />
        输出：{item.output_name || '-'}
        {item.error && <><br />失败原因：{item.error}</>}
        {item.saved_path ? <br /> : null}
        {item.saved_path ? `保存：${item.saved_path}` : null}
        {item.jid && (item.status === 'done' || item.status === 'blocked') ? (
          <>
            <br />
            <a href={`/review/${encodeURIComponent(item.jid)}`}>审阅与修订</a> /{' '}
            <a href={`/api/download/${encodeURIComponent(item.jid)}`}>下载文档</a> /{' '}
            <a href={`/api/report/${encodeURIComponent(item.jid)}`} target="_blank" rel="noopener">
              查看报告
            </a>
          </>
        ) : null}
      </div>
      {canReuse && (
        <div className="hist-actions">
          <button className="hist-btn" type="button" onClick={() => applyPreset(false)}>
            复用本次参数
          </button>
          <button className="hist-btn" type="button" onClick={() => applyPreset(true)}>
            复用并预检
          </button>
        </div>
      )}
    </div>
  );
}
