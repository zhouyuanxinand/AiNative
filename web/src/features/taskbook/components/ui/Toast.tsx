/** Toast 通知组件——从原 SPA #toast 元素迁移。 */
import { useTaskbook } from '../../hooks/useTaskbook';

export function Toast() {
  const { toastMessage, toastType } = useTaskbook();
  const visible = !!toastMessage;
  return (
    <div className={`toast ${visible ? 'show' : ''} ${toastType}`.trim()}>
      {toastMessage}
    </div>
  );
}
