import type { ProductCatalog } from '../../types';
import type { ContextKey } from './types';

/** Display labels only; no inferred business values or default classifications. */
export function contextValueLabel(key: ContextKey, value: string, catalog?: ProductCatalog | null) {
  if (!value) return '待流程确认';
  if (key === 'product_type') return catalog?.product_types.find(item => item.value === value)?.label ?? (/[\u3400-\u9fff]/.test(value) ? value : '产品分类待目录核对');
  if (key === 'product_domain') return catalog?.product_types.flatMap(item => item.domains).find(item => item.value === value)?.label ?? ({ military: '军品', civilian: '民品' }[value] ?? (/[\u3400-\u9fff]/.test(value) ? value : '质量体系待目录核对'));
  if (key === 'organization_scope') return ({ central_research: '中央研究院产品', non_central_research: '非中央研究院产品' }[value] ?? (/[\u3400-\u9fff]/.test(value) ? value : '产品归属待资料核对'));
  return value;
}
