/** 产品目录、模型目录与模型状态接口。 */
import type {
  ProductCatalog,
  ModelCatalogResponse,
  ModelStatusResponse,
} from '../types';
import { getJSON } from './client';

export function loadProductCatalog(): Promise<ProductCatalog> {
  return getJSON<ProductCatalog>('/api/product_catalog');
}

export function loadModelCatalog(): Promise<ModelCatalogResponse> {
  return getJSON<ModelCatalogResponse>('/api/models');
}

export function checkModelStatus(
  provider: string,
  name: string,
  id: string,
): Promise<ModelStatusResponse> {
  const query = new URLSearchParams({
    model_provider: provider,
    model_name: name,
    model_id: id || '',
  });
  return getJSON<ModelStatusResponse>(`/api/llm/status?${query.toString()}`);
}
