import type { FeedbackIdentity, FeedbackRating, FeedbackStatus } from '../../api/feedback';

export function feedbackIdentityLabel(identity?: FeedbackIdentity): string {
  if (identity?.source === 'smartvision') return identity.verified ? '统一登录已验证' : '统一登录未验证';
  if (identity?.source === 'manual') return '本地手填（未验证）';
  return '历史未记录（未验证）';
}

export const ratingLabels: Record<FeedbackRating, string> = { good: '好', average: '一般', poor: '差' };
export const statusLabels: Record<FeedbackStatus, string> = { open: '待处理', in_progress: '处理中', resolved: '已解决' };
export const ratingOptions = Object.entries(ratingLabels).map(([value, label]) => ({ value, label }));
export const statusOptions = Object.entries(statusLabels).map(([value, label]) => ({ value, label }));
export const feedbackTime = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date);
};

export const feedbackError = (reason: unknown) => reason instanceof Error ? reason.message : '请求未完成，请重试。';

export function newFeedbackRequestId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, '0')).join('');
}
