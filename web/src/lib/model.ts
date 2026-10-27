/** 模型选择工具——与原 SPA modelSelectionKey/getSelectedModel 逻辑一致。 */
import type { ModelItem } from '../types';

export function modelSelectionKey(item: { provider?: string; name?: string; id?: string } | null): string {
  if (!item) return '';
  return [item.provider || '', item.name || '', item.id || '']
    .map((value) => encodeURIComponent(value))
    .join('|');
}

/** 在模型目录中按 select value 查找。 */
export function findModelBySelectValue(
  catalog: ModelItem[],
  selectValue: string,
): ModelItem | null {
  return catalog.find((item) => modelSelectionKey(item) === selectValue) || null;
}

/** 将选中的模型信息追加到 FormData。 */
export function appendModelSelection(
  fd: FormData,
  selected: ModelItem | null,
): boolean {
  if (!selected) return false;
  fd.append('model_provider', selected.provider);
  fd.append('model_name', selected.name);
  if (selected.id) fd.append('model_id', selected.id);
  return true;
}
