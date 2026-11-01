const paths: Record<string, string> = {
  settings: 'm9.5 3-.6 2.1-1.8 1-2.1-.5-2.5 4.3L4 11.5v2L2.5 15 5 19.3l2.1-.5 1.8 1 .6 2.2h5l.6-2.2 1.8-1 2.1.5 2.5-4.3-1.5-1.5v-2l1.5-1.6L19 5.6l-2.1.5-1.8-1-.6-2.1h-5ZM15 12.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
  home: 'm3 10 9-7 9 7M5 9v12h14V9M9 21v-7h6v7',
  projects: 'M3 7h7l2-3h8a1 1 0 0 1 1 1v14H3V7Z',
  management: 'M4 21V5h10v16M14 10h6v11M7 9h4M7 13h4M7 17h4M17 14h1M17 18h1',
  flows: 'M9 3h6v5H9zM3 16h6v5H3zM15 16h6v5h-6zM12 8v4M6 16v-4h12v4',
  knowledge: 'M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1ZM12 5v15',
  operations: 'M4 3v18h17M8 17v-5M13 17V7M18 17V4',
  system: 'M4 6h16M4 12h16M4 18h16M9 3v6M16 9v6M8 15v6',
  workspace: 'm12 3 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 16l9 5 9-5',
};
export function RdNavigationIcon({ name }: { name: string }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] ?? paths.home} /></svg>;
}
