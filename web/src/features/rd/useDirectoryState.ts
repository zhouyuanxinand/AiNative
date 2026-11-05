import { useCallback, useEffect, useRef, useState } from 'react';

/** Committed directory state lives in the URL; incomplete IME input stays in memory. */
export function useDirectoryState(prefix: string, defaults: Record<string, string> = {}) {
  const initial = useRef(defaults);
  const read = useCallback(() => {
    const params = new URLSearchParams(window.location.search);
    const value = { ...initial.current };
    for (const key of Object.keys(value)) value[key] = params.get(`${prefix}_${key}`) ?? value[key];
    const page = Number(value.page);
    value.page = String(Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1);
    return value;
  }, [prefix]);
  const [state, setState] = useState(read);
  const [input, setInput] = useState(state.q ?? '');
  const [composing, setComposing] = useState(false);
  const update = useCallback((patch: Record<string, string>, resetPage = true) => {
    setState(previous => {
      const value = { ...previous, ...(resetPage ? { page: '1' } : {}), ...patch };
      const url = new URL(window.location.href);
      for (const [key, content] of Object.entries(value)) {
        if (content) url.searchParams.set(`${prefix}_${key}`, content); else url.searchParams.delete(`${prefix}_${key}`);
      }
      window.history.replaceState(window.history.state, '', url);
      return value;
    });
  }, [prefix]);
  useEffect(() => {
    const pop = () => { const value = read(); setState(value); setInput(value.q ?? ''); };
    window.addEventListener('popstate', pop); return () => window.removeEventListener('popstate', pop);
  }, [read]);
  useEffect(() => {
    if (composing || input === (state.q ?? '')) return;
    const timer = window.setTimeout(() => update({ q: input, item: '', version: '' }), 300);
    return () => window.clearTimeout(timer);
  }, [input, composing, state.q, update]);
  const commit = (value = input) => { setInput(value); update({ q: value, item: '', version: '' }); };
  return { state, update, input, setInput, composing, setComposing, commit, page: Number(state.page) || 1 };
}
