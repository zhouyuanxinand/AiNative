import { modelSelectionKey } from '../../lib/model';
import type { ModelItem, RawModelItem } from '../../types';
import type { StyledSelectOption, StyledSelectGroup } from '../../components/ui/StyledSelect';
import type { ModelSelection } from './types';

const RECENT_LIMIT = 5;
type RecentStorage = Pick<Storage, 'getItem' | 'setItem'> | null;

export function normalizeModelSelection(item?: Partial<ModelSelection> | null): ModelSelection {
  return { provider: item?.provider || '', name: item?.name || '', id: item?.id || '' };
}

export function modelDisplayLabel(item: Partial<ModelItem>): string {
  if (!item.name && !item.provider) return '使用平台默认模型';
  const vendors: Record<string, string> = { azure: '微软 Azure', dashscope: '阿里云 DashScope', openai: 'OpenAI' };
  const vendor = item.vendor || vendors[(item.name || '').split('/')[0]] || item.provider;
  return [vendor, item.name].filter(Boolean).join(' · ');
}

export function normalizeModelCatalog(items: RawModelItem[]): ModelItem[] {
  const unique = new Map<string, ModelItem>();
  for (const item of items) {
    const model = { ...normalizeModelSelection({ ...item, name: item.name || item.model || '' }), vendor: item.vendor || '', configured: item.configured !== false };
    if (model.provider && model.name && !unique.has(modelSelectionKey(model))) unique.set(modelSelectionKey(model), model);
  }
  return [...unique.values()];
}

export function buildModelOptions(catalog: ModelItem[], current: ModelSelection, recent: ModelSelection[]): (StyledSelectOption | StyledSelectGroup)[] {
  const option = (item: ModelItem): StyledSelectOption => ({ value: modelSelectionKey(item), label: `${modelDisplayLabel(item)}${item.configured ? '' : '（未就绪）'}`, disabled: !item.configured });
  const recentKeys = new Set(recent.map(modelSelectionKey));
  const byKey = new Map(catalog.map(item => [modelSelectionKey(item), item]));
  const recentItems = [...recentKeys].map(key => byKey.get(key)).filter((item): item is ModelItem => !!item?.configured).slice(0, RECENT_LIMIT);
  const displayedKeys = new Set(recentItems.map(modelSelectionKey));
  const all = catalog.filter(item => !displayedKeys.has(modelSelectionKey(item))).map(option);
  const options: (StyledSelectOption | StyledSelectGroup)[] = [{ value: modelSelectionKey(normalizeModelSelection()), label: '使用平台默认模型' }];
  if (recentItems.length) options.push({ label: '最近使用', options: recentItems.map(option) });
  if (all.length) options.push({ label: '全部模型', options: all });
  if ((current.provider || current.name) && !byKey.has(modelSelectionKey(current))) {
    options.push({ value: modelSelectionKey(current), label: `${modelDisplayLabel(current)}（当前选择，目录未提供）`, disabled: true });
  }
  return options;
}

export function recentModelsKey(actor: string): string { return `rd:model-recents:v1:${encodeURIComponent(actor)}`; }

export function readRecentModels(storage: RecentStorage, actor: string): ModelSelection[] {
  if (!storage || !actor) return [];
  try {
    const stored: unknown = JSON.parse(storage.getItem(recentModelsKey(actor)) || '[]');
    if (!Array.isArray(stored)) return [];
    const unique = new Map<string, ModelSelection>();
    for (const item of stored) {
      if (!item || typeof item.provider !== 'string' || !item.provider || typeof item.name !== 'string' || !item.name || typeof item.id !== 'string') continue;
      const model = normalizeModelSelection(item);
      if (!unique.has(modelSelectionKey(model))) unique.set(modelSelectionKey(model), model);
      if (unique.size === RECENT_LIMIT) break;
    }
    return [...unique.values()];
  } catch { return []; }
}

/** Only call after the project confirms saving this model selection. */
export function rememberRecentModel(storage: RecentStorage, actor: string, model: ModelSelection): ModelSelection[] {
  const previous = readRecentModels(storage, actor);
  if (!actor || !model.provider || !model.name) return previous;
  const selected = normalizeModelSelection(model);
  const next = [selected, ...previous.filter(item => modelSelectionKey(item) !== modelSelectionKey(selected))].slice(0, RECENT_LIMIT);
  try { storage?.setItem(recentModelsKey(actor), JSON.stringify(next)); } catch { /* Browser history is optional; a project save remains successful. */ }
  return next;
}

export function browserRecentStorage(): RecentStorage {
  try { return window.localStorage; } catch { return null; }
}
