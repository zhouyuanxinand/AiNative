/** 帮助浮层组件——从原 SPA #help-popover + help-trigger 迁移。 */
import { useEffect, useRef } from 'react';
import { useTaskbook } from '../../hooks/useTaskbook';

export function HelpPopover() {
  const { helpOpen, setHelpOpen } = useTaskbook();
  const popoverRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!helpOpen) return;
    const onResize = () => positionPopover();
    window.addEventListener('resize', onResize);
    const onClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        popoverRef.current &&
        !popoverRef.current.contains(target) &&
        triggerRef.current &&
        !triggerRef.current.contains(target)
      ) {
        setHelpOpen(false);
      }
    };
    document.addEventListener('click', onClickOutside);
    positionPopover();
    return () => {
      window.removeEventListener('resize', onResize);
      document.removeEventListener('click', onClickOutside);
    };
  }, [helpOpen, setHelpOpen]);

  function positionPopover() {
    const trigger = triggerRef.current;
    const popover = popoverRef.current;
    if (!trigger || !popover || !helpOpen) return;
    const rect = trigger.getBoundingClientRect();
    const margin = 16;
    const width = Math.min(360, window.innerWidth - margin * 2);
    const left = Math.max(margin, Math.min(rect.right + 12, window.innerWidth - width - margin));
    const top = Math.max(
      margin,
      Math.min(rect.top - popover.offsetHeight - 12, window.innerHeight - popover.offsetHeight - margin),
    );
    popover.style.width = `${width}px`;
    popover.style.left = `${left}px`;
    popover.style.right = 'auto';
    popover.style.top = `${top}px`;
  }

  return (
    <>
      <button
        ref={triggerRef}
        className="help-trigger"
        type="button"
        onClick={() => setHelpOpen(!helpOpen)}
        aria-label="查看受控生成策略与规则"
        title="查看受控生成策略与规则"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M9.8 9a2.4 2.4 0 1 1 3.9 1.9c-1.1.8-1.7 1.2-1.7 2.5M12 17h.01" />
        </svg>
      </button>
      {helpOpen && (
        <div ref={popoverRef} className="help-popover open">
          <div className="side-title">受控生成策略</div>
          <div className="policy-list">
            <div className="policy-item">
              <div className="policy-no">01</div>
              <div>
                <strong>语义识别</strong>
                <p>不依赖章节号与来源顺序，换文档仍可路由。</p>
              </div>
            </div>
            <div className="policy-item">
              <div className="policy-no">02</div>
              <div>
                <strong>原文搬运</strong>
                <p>段落、表格、图片和图题作为连续内容块复制。</p>
              </div>
            </div>
            <div className="policy-item">
              <div className="policy-no">03</div>
              <div>
                <strong>模板受控</strong>
                <p>产品类型一对一匹配后台模板，用户无需上传。</p>
              </div>
            </div>
            <div className="policy-item">
              <div className="policy-no">04</div>
              <div>
                <strong>质量门禁</strong>
                <p>指标一致性、版式、污染词和证据链必须通过。</p>
              </div>
            </div>
          </div>
          <div className="taxonomy">
            <div className="taxonomy-label">7-14 规则主类</div>
            <div className="taxonomy-tags">
              <span>来源和功能</span>
              <span>使用环境</span>
              <span>安装形式</span>
              <span>产品组成</span>
              <span>技术指标</span>
              <span>外形尺寸</span>
              <span>安装尺寸</span>
              <span>接口尺寸</span>
              <span>可靠性</span>
              <span>维修性</span>
              <span>测试性</span>
              <span>工艺</span>
              <span>其他要求</span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
