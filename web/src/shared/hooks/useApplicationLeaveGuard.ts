import { useEffect, useRef } from 'react';

interface LeaveState { dirty: boolean; busyMessage?: string }
const guards = new Set<() => LeaveState>();
let confirmedLogoutNavigation = false;

/** Shared by the page-unload warning and the application's explicit logout action. */
export function useApplicationLeaveGuard(state: LeaveState) {
  const current = useRef(state);
  current.current = state;
  useEffect(() => {
    const read = () => current.current;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (confirmedLogoutNavigation || (!current.current.dirty && !current.current.busyMessage)) return;
      event.preventDefault();
      event.returnValue = '';
    };
    guards.add(read);
    window.addEventListener('beforeunload', beforeUnload);
    return () => { guards.delete(read); window.removeEventListener('beforeunload', beforeUnload); };
  }, []);
}

export function applicationLeaveState(): LeaveState {
  const states = Array.from(guards, read => read());
  return { dirty: states.some(state => state.dirty), busyMessage: states.find(state => state.busyMessage)?.busyMessage };
}

/** Call only after a confirmed logout succeeds, immediately before leaving the page. */
export function navigateAfterLogout() {
  navigateAfterConfirmedLeave('/logged-out');
}

/** Use only after the application has confirmed discarding the current input. */
export function navigateAfterConfirmedLeave(destination = window.location.href) {
  confirmedLogoutNavigation = true;
  try { window.location.assign(destination); }
  catch (reason) { confirmedLogoutNavigation = false; throw reason; }
}
