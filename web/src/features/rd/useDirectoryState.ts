import { useCallback, useEffect, useRef, useState } from 'react';
import { DIRECTORY_HISTORY, readDirectoryLocation, updateDirectoryLocation } from './platformNavigation';

/** Committed directory state lives in the URL; incomplete IME input stays in memory. */
export function useDirectoryState(prefix: string, defaults: Record<string, string> = {}) {
  const initial = useRef(defaults);
  const read = useCallback(() => {
    return readDirectoryLocation(window.location.href, prefix, initial.current, window.history.state?.[DIRECTORY_HISTORY]);
  }, [prefix]);
  const [state, setState] = useState(read);
  const [input, setInput] = useState(state.q ?? '');
  const [composing, setComposing] = useState(false);
  const update = useCallback((patch: Record<string, string>, resetPage = true) => {
    setState(previous => {
      const value = { ...previous, ...(resetPage ? { page: '1' } : {}), ...patch };
      const result = updateDirectoryLocation(window.location.href, prefix, value, window.history.state);
      window.history.replaceState(result.state, '', result.url);
      // Other mounted directory levels and the shell see the same semantic page.
      queueMicrotask(() => window.dispatchEvent(new Event('rd:directory-location')));
      return value;
    });
  }, [prefix]);
  useEffect(() => {
    const pop = () => { const value = read(); setState(value); setInput(value.q ?? ''); };
    window.addEventListener('popstate', pop);
    window.addEventListener('rd:directory-location', pop);
    return () => { window.removeEventListener('popstate', pop); window.removeEventListener('rd:directory-location', pop); };
  }, [read]);
  useEffect(() => {
    if (composing || input === (state.q ?? '')) return;
    const timer = window.setTimeout(() => update({ q: input, item: '', version: '' }), 300);
    return () => window.clearTimeout(timer);
  }, [input, composing, state.q, update]);
  const commit = (value = input) => { setInput(value); update({ q: value, item: '', version: '' }); };
  return { state, update, input, setInput, composing, setComposing, commit, page: Number(state.page) || 1 };
}
