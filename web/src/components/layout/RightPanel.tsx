/** 右侧面板——结果 / 历史 / 状态三个 tab。 */
import { useTaskbook } from '../../hooks/useTaskbook';
import { usePanelResize } from '../../hooks/usePanelResize';
import { ResultCard } from '../result/ResultCard';
import { HistoryGrid } from '../result/HistoryGrid';
import { StatusCard } from '../result/StatusCard';
import type { ReviewTab } from '../../constants';

export function RightPanel() {
  const { reviewTab, setReviewTab, showResultCard } = useTaskbook();
  const { beginResize, resetPanelWidth } = usePanelResize();

  const switchTab = (tab: ReviewTab) => setReviewTab(tab);

  return (
    <aside className="right-panel">
      <button
        className="resize-handle resize-handle-right"
        id="right-resizer"
        type="button"
        aria-label="拖动调整右侧结果栏宽度"
        title="拖动调整右侧结果栏宽度，双击恢复默认宽度"
        aria-valuemin={360}
        aria-valuemax={560}
        onPointerDown={(e) => beginResize('right', e)}
        onDoubleClick={() => resetPanelWidth('right')}
      />
      <div className="review-module">
        <div className="review-tabs" aria-label="右侧面板标签">
          <button
            className={`review-tab ${reviewTab === 'result' ? 'active' : ''}`}
            type="button"
            data-review="result"
            onClick={() => switchTab('result')}
          >
            结果
          </button>
          <button
            className={`review-tab ${reviewTab === 'history' ? 'active' : ''}`}
            type="button"
            data-review="history"
            onClick={() => switchTab('history')}
          >
            历史
          </button>
          <button
            className={`review-tab ${reviewTab === 'status' ? 'active' : ''}`}
            type="button"
            data-review="status"
            onClick={() => switchTab('status')}
          >
            状态
          </button>
        </div>
        <div className="review-body">
          <div
            className={`review-section ${reviewTab === 'result' ? 'active' : ''}`}
            data-review="result"
          >
            {showResultCard ? <ResultCard /> : <ResultEmpty />}
          </div>
          <div
            className={`review-section ${reviewTab === 'history' ? 'active' : ''}`}
            data-review="history"
          >
            <HistoryGrid />
          </div>
          <div
            className={`review-section ${reviewTab === 'status' ? 'active' : ''}`}
            data-review="status"
          >
            <StatusCard />
          </div>
        </div>
      </div>
    </aside>
  );
}

function ResultEmpty() {
  const { resultEmpty } = useTaskbook();
  if (!resultEmpty) return null;
  return (
    <div className="review-empty review-empty-state" id="result-empty">
      <div className="review-empty-visual" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 3h9l3 3v15H6z" />
          <path d="M14 3v4h4M9 12h6M9 16h4" />
        </svg>
      </div>
      <strong>尚未生成结果</strong>
      <span>完成业务选择并上传来源文件后，生成结果与质量报告将在这里展示。</span>
    </div>
  );
}
