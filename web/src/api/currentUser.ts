export interface PlatformUser {
  userid: string;
  name: string;
  display_name: string;
  source: 'smartvision';
  verified: true;
}

export type CurrentUser =
  | { auth_enabled: false; authenticated: false; user: null }
  | { auth_enabled: true; authenticated: false; user: null; login_url: string }
  | { auth_enabled: true; authenticated: true; user: PlatformUser };

/** The server verifies the same-origin session; the browser never reads its cookie. */
export async function loadCurrentUser(signal: AbortSignal): Promise<CurrentUser> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (signal.aborted) controller.abort();
  else signal.addEventListener('abort', cancel, { once: true });
  let timedOut = false;
  const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 20000);
  try {
    const response = await fetch('/api/current-user', { signal: controller.signal, credentials: 'same-origin', cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data?.error || '登录身份读取失败，请重试。');
    if (data?.auth_enabled === false && data.authenticated === false && data.user === null) return data;
    if (data?.auth_enabled === true && data.authenticated === false && data.user === null) {
      return { ...data, login_url: '/auth/login' };
    }
    if (data?.auth_enabled === true && data.authenticated === true && data.user?.verified === true
      && data.user.source === 'smartvision' && typeof data.user.userid === 'string' && data.user.userid
      && typeof data.user.display_name === 'string' && data.user.display_name && typeof data.user.name === 'string') return data;
    throw new Error('登录身份信息不完整，请重试读取。');
  } catch (reason) {
    if (timedOut) throw new Error('读取登录身份超时，请重试。');
    if (reason instanceof TypeError) throw new Error('无法连接统一登录服务，请检查连接后重试。');
    throw reason;
  } finally {
    window.clearTimeout(timeout);
    signal.removeEventListener('abort', cancel);
  }
}
