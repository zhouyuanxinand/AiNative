/** 预检卡片——展示后端返回的预检结果。 */
import { useTaskbook } from '../../hooks/useTaskbook';
import { escapeHtml } from '../../../../shared/lib/dom';
import type { PrecheckFile } from '../../model/types';

export function PrecheckCard() {
  const { precheck } = useTaskbook();
  if (!precheck) return null;

  const filesData = precheck.files || {};
  const items: [string, PrecheckFile | null | undefined][] = [
    ['技术要求预检', filesData.tech],
    ['产品规范预检', filesData.spec],
    ['内置模板预检', filesData.tpl],
    [
      '业务选择',
      precheck.selection
        ? {
            message: `${precheck.selection.product_type} / ${precheck.selection.product_domain} / 模板：${precheck.selection.template}`,
            ok: true,
          }
        : null,
    ],
    ['文件一致性', precheck.consistency],
    ['建议产品', precheck.suggestion],
  ];

  return (
    <div className="card precheck-wrap" id="precheck-card">
      <h2>
        <span className="section-kicker">PRECHECK</span>上传预检
      </h2>
      <div className="precheck-grid" id="precheck-grid">
        {items.map(([title, item]) => {
          if (!item) return null;
          const ok = item.ok !== false;
          const details: string[] = [item.message || item.product || ''];
          if (item.profile) details.push('建议配置：' + item.profile);
          if (item.tokens) details.push('命中信号：' + item.tokens.join(' / '));
          if (item.name) details.push('文件：' + item.name);
          if (item.score !== undefined) details.push('匹配分：' + item.score);
          return (
            <div key={title} className="pre-item">
              <div className="pre-title">
                {escapeHtml(title)}
                {title !== '建议产品' && (
                  <span className={ok ? 'badge-ok' : 'badge-warn'}>{ok ? '正常' : '警告'}</span>
                )}
              </div>
              <div
                className="pre-val"
                dangerouslySetInnerHTML={{ __html: details.map(escapeHtml).join('<br>') }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
