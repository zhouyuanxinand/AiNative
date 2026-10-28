/** 纯 DOM/字符串工具——从原 SPA 原样迁移。 */

export function escapeHtml(value: unknown): string {
  return String(value ?? '').replace(
    /[&<>"']/g,
    (ch) =>
      ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      })[ch]!,
  );
}

export function formatFileSize(size: number): string {
  const bytes = Number(size) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

export function describeSelectedFile(file?: File | null): string {
  const extension = (file?.name?.split('.').pop() || '文件').toUpperCase();
  return `${extension} · ${formatFileSize(file?.size ?? 0)} · 已读取`;
}

export function selectedFileIdentity(file?: File | null): string {
  return [file?.name || '', Number(file?.size) || 0, Number(file?.lastModified) || 0].join(':');
}

/** 从文件路径中提取文件名（兼容 Windows 反斜杠）。 */
export function basename(path: string): string {
  return path.split('\\').pop()?.split('/').pop() || path;
}
