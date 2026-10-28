import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { loadCurrentUser, type CurrentUser } from './currentUser';

type IdentityState =
  | { status: 'loading' }
  | { status: 'ready'; identity: CurrentUser }
  | { status: 'error'; error: string };

interface CurrentUserContextValue {
  state: IdentityState;
  retry: () => void;
  requireLogin: () => void;
}

const CurrentUserContext = createContext<CurrentUserContextValue | null>(null);

export function CurrentUserProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<IdentityState>({ status: 'loading' });
  const request = useRef<AbortController>();
  const retry = useCallback(() => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setState({ status: 'loading' });
    void loadCurrentUser(controller.signal).then(identity => {
      if (!controller.signal.aborted && request.current === controller) setState({ status: 'ready', identity });
    }).catch(reason => {
      if (!controller.signal.aborted && request.current === controller) {
        setState({ status: 'error', error: reason instanceof Error ? reason.message : '登录身份读取失败，请重试。' });
      }
    });
  }, []);
  const requireLogin = useCallback(() => {
    request.current?.abort();
    setState({ status: 'ready', identity: { auth_enabled: true, authenticated: false, user: null, login_url: '/auth/login' } });
  }, []);

  useEffect(() => {
    retry();
    return () => request.current?.abort();
  }, [retry]);

  return <CurrentUserContext.Provider value={{ state, retry, requireLogin }}>{children}</CurrentUserContext.Provider>;
}

export function useCurrentUser(): CurrentUserContextValue {
  const context = useContext(CurrentUserContext);
  if (!context) throw new Error('CurrentUserProvider is required.');
  return context;
}
