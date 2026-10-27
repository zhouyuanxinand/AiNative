import { notifyAdminAccessFailure } from './adminAccess';
import { fetchJSON } from './client';

export type HelpResourceKind = 'video' | 'manual';

export interface HelpResource {
  id: string;
  kind: HelpResourceKind;
  title: string;
  source_type: 'file' | 'link';
  source_url: string | null;
  filename: string | null;
  size_bytes: number | null;
  media_type: string | null;
  created_at: string;
  updated_at: string;
  created_by: string;
  content_url: string | null;
  preview_type: 'video' | 'pdf' | 'document' | 'link';
  preview_url: string | null;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  try {
    return await fetchJSON<T>(url, { credentials: 'same-origin', cache: 'no-store', ...init });
  } catch (cause) {
    if (cause instanceof TypeError) throw new Error('无法连接资料服务，请检查网络后重试。');
    if (cause instanceof SyntaxError) throw new Error('资料服务返回了无法读取的内容，请稍后重试。');
    throw cause;
  }
}

export const getHelpResources = (kind: HelpResourceKind, signal?: AbortSignal) =>
  request<{ items: HelpResource[] }>(`/api/help-resources?kind=${kind}`, { signal });

function adminResource(item: HelpResource): HelpResource {
  if (item.source_type !== 'file') return item;
  // The admin session is independent of the main site's OA session.
  const adminUrl = (url: string | null) => url?.replace(/^\/api\/help-resources(?=\/|\?|$)/, '/admin/api/help-resources') ?? null;
  return { ...item, content_url: adminUrl(item.content_url), preview_url: adminUrl(item.preview_url) };
}

export async function getAdminHelpResources(kind: HelpResourceKind, signal?: AbortSignal) {
  const result = await request<{ items: HelpResource[] }>(`/admin/api/help-resources?kind=${kind}`, { signal });
  return { items: result.items.map(adminResource) };
}

export const addHelpResourceLink = (body: { kind: HelpResourceKind; title: string; source_url: string }, signal?: AbortSignal) =>
  request<{ item: HelpResource }>('/api/help-resources-admin/links', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Admin-Action': '1' }, body: JSON.stringify(body), signal,
  });

export const deleteHelpResource = (id: string, signal?: AbortSignal) =>
  request<{ ok: true }>(`/api/help-resources-admin/${encodeURIComponent(id)}`, {
    method: 'DELETE', headers: { 'X-Admin-Action': '1' }, signal,
  });

export function uploadHelpResource(body: { kind: HelpResourceKind; title: string; file: File }, options: {
  signal?: AbortSignal; onProgress?: (percent: number) => void;
} = {}): Promise<{ item: HelpResource }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    const cleanup = () => options.signal?.removeEventListener('abort', abort);
    if (options.signal?.aborted) { reject(new DOMException('上传已取消。', 'AbortError')); return; }
    xhr.open('POST', '/api/help-resources-admin/upload');
    xhr.setRequestHeader('X-Admin-Action', '1');
    xhr.responseType = 'json';
    xhr.upload.onprogress = event => {
      if (event.lengthComputable) options.onProgress?.(Math.round(event.loaded / event.total * 100));
    };
    xhr.onload = () => {
      cleanup();
      const result = xhr.response as { item?: HelpResource; error?: string } | null;
      if (xhr.status < 200 || xhr.status >= 300) {
        notifyAdminAccessFailure(xhr.status, result);
        reject(new Error(result?.error || `上传失败（HTTP ${xhr.status}），请重试。`));
      } else if (!result?.item) {
        reject(new Error('未收到资料保存结果，请刷新列表核对后重试。'));
      } else resolve({ item: adminResource(result.item) });
    };
    xhr.onerror = () => { cleanup(); reject(new Error('上传连接中断，请检查网络后重试。')); };
    xhr.onabort = () => { cleanup(); reject(new DOMException('上传已取消。', 'AbortError')); };
    options.signal?.addEventListener('abort', abort, { once: true });
    const form = new FormData();
    form.append('kind', body.kind); form.append('title', body.title); form.append('file', body.file);
    xhr.send(form);
  });
}

export function helpResourceDownloadUrl(item: HelpResource): string | null {
  if (!item.content_url) return null;
  const url = new URL(item.content_url, window.location.origin);
  url.searchParams.set('download', '1');
  return url.href;
}
