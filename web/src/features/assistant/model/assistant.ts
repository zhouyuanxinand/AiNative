import type { AssistantHistory } from '../api/assistant';

/** Model replies can navigate only to existing application pages. */
export function assistantHref(href: string): string | null {
  if (!href.startsWith('/') || href.startsWith('//') || /[\\\u0000-\u0020]/.test(href)) return null;
  try {
    const parsed = new URL(href, 'https://platform.local');
    if (parsed.origin !== 'https://platform.local') return null;
    const allowed = /^\/(?:rd(?:\/[A-Za-z0-9_-]+(?:\/tasks\/[A-Za-z0-9_-]+)?)?|requirements|tasks|artifacts|approvals|taskbook|help\/(?:manual|video))?$/;
    return allowed.test(parsed.pathname) ? `${parsed.pathname}${parsed.search}${parsed.hash}` : null;
  } catch { return null; }
}
export function assistantProjectId(pathname: string): string | undefined {
  const match = /^\/rd\/([^/]+)(?:\/tasks\/[^/]+)?\/?$/.exec(pathname);
  if (!match) return undefined;
  try { return decodeURIComponent(match[1]); } catch { return undefined; }
}
/** Completed turns only; transient errors and UI metadata never become model context. */
export function assistantHistory(messages: AssistantHistory[]): AssistantHistory[] {
  return messages.slice(-12).map(message => ({ role: message.role, content: message.content.slice(0, 6000) }));
}
export function assistantEnterSubmits(event: { key: string; shiftKey: boolean; isComposing: boolean; keyCode?: number }): boolean {
  return event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229;
}

/** Keep a usable business surface beside the desktop assistant. Mobile uses its full-width drawer. */
export function assistantPanelWidth(requested: number, viewport: number): number {
  const maximum = viewport > 980 ? Math.min(640, Math.max(320, viewport - 228 - 420)) : 640;
  return Math.max(320, Math.min(maximum, Math.round(requested)));
}
