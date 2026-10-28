import { notifyAdminAccessFailure } from '../../../shared/auth/adminAccess';

export interface PlatformAuthConfig {
  enabled: boolean;
  app_id: number | null;
  platform_base_url: string;
  public_url: string | null;
}

export interface AuthSettingsResponse {
  settings: PlatformAuthConfig;
  active: PlatformAuthConfig | null;
  presets: Record<'intranet' | 'external', Omit<PlatformAuthConfig, 'enabled'>>;
  version: number;
  can_edit: boolean;
  requires_restart: boolean;
}

export class AuthSettingsApiError extends Error {
  constructor(message: string, public readonly status: number) { super(message); this.name = 'AuthSettingsApiError'; }
}

async function request(settings: PlatformAuthConfig | undefined, version: number | undefined, signal: AbortSignal, admin: boolean): Promise<AuthSettingsResponse> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (signal.aborted) controller.abort(); else signal.addEventListener('abort', cancel, { once: true });
  let timedOut = false;
  const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 20000);
  try {
    const response = await fetch(admin ? '/admin/api/settings/auth' : '/api/settings/auth', {
      method: settings ? 'PUT' : 'GET', signal: controller.signal, credentials: 'same-origin', cache: 'no-store',
      headers: { 'X-Credential-Settings': '1', ...(settings ? { 'Content-Type': 'application/json' } : {}) },
      ...(settings ? { body: JSON.stringify({ ...settings, expected_version: version }) } : {}),
    });
    const data = await response.json().catch(reason => { if (controller.signal.aborted) throw reason; return null; });
    if (!response.ok) {
      notifyAdminAccessFailure(response.status, data);
      throw new AuthSettingsApiError(data?.error || `登录配置请求失败（HTTP ${response.status}），请重试。`, response.status);
    }
    return data as AuthSettingsResponse;
  } catch (reason) {
    if (timedOut) throw new AuthSettingsApiError(settings ? '请求超时，保存结果尚未确认。请核对最新配置后重试。' : '读取登录配置超时，请重试。', 408);
    if (reason instanceof TypeError) throw new AuthSettingsApiError('无法连接配置服务，请检查连接后重试。', 0);
    throw reason;
  } finally {
    window.clearTimeout(timeout); signal.removeEventListener('abort', cancel);
  }
}

export function getAuthSettings(signal: AbortSignal, admin = false): Promise<AuthSettingsResponse> {
  return request(undefined, undefined, signal, admin);
}

export function saveAuthSettings(settings: PlatformAuthConfig, version: number, signal: AbortSignal, admin = false): Promise<AuthSettingsResponse> {
  return request(settings, version, signal, admin);
}
