/** 系统状态卡片——展示语义模型、模板目录、后端版本。 */
import { useTaskbook } from '../../hooks/useTaskbook';

export function StatusCard() {
  const { backendHealthReady, backendHealth, productCatalog } = useTaskbook();

  const modelStatus =
    backendHealth === null
      ? '检查中…'
      : !backendHealth.llm?.configured
        ? '语义模型未连接'
        : backendHealth.runtime?.semantic_retrieval
          ? backendHealth.runtime?.semantic_rerank
            ? '语义模型已连接；Embedding 与 Rerank 已启用'
            : '语义模型已连接；Embedding 已启用'
          : '语义模型已连接；使用实时模板标题树路由';

  return (
    <div className="card" id="status-card">
      <h2>
        <span className="section-kicker">STATUS</span>系统状态
      </h2>
      <p className="section-sub">当前服务运行状态与受控生成能力。</p>
      <div className="result-summary">
        <div className="summary-item">
          <div className="summary-label">语义模型</div>
          <div className="summary-value" id="status-llm">
            {backendHealthReady === false && backendHealth === null ? '语义模型未连接' : modelStatus}
          </div>
        </div>
        <div className="summary-item">
          <div className="summary-label">模板目录</div>
          <div className="summary-value" id="status-template">
            {productCatalog.length > 0
              ? `已加载 ${productCatalog.length} 个产品类型`
              : '读取失败'}
          </div>
        </div>
        <div className="summary-item">
          <div className="summary-label">后端版本</div>
          <div className="summary-value" id="status-version">
            {backendHealth?.build_fingerprint?.pipeline_version ||
              backendHealth?.build_fingerprint?.build_id ||
              backendHealth?.runtime?.profile ||
              '-'}
          </div>
        </div>
      </div>
    </div>
  );
}
