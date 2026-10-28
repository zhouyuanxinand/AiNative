import type { ReactNode } from 'react';

export function PlatformIcon({ kind }: { kind: string }) {
  const paths: Record<string, ReactNode> = {
    overview: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    projects: <><path d="M3 7h7l2 2h9v11H3z" /><path d="M3 7V4h7l2 3" /></>,
    requirements: <><path d="M6 3h9l3 3v15H6zM14 3v5h4M9 12h6M9 16h6" /></>,
    tasks: <><rect x="4" y="4" width="16" height="17" rx="2" /><path d="M9 2v4h6V2M8 12l2 2 5-5M8 18h8" /></>,
    artifacts: <><path d="M12 3 3 8l9 5 9-5zM3 12l9 5 9-5M3 16l9 5 9-5" /></>,
    approvals: <><path d="m4 12 5 5L20 6M4 4h8M4 21h16" /></>,
    generator: <><path d="M5 3h11l3 3v15H5zM9 8h6M9 12h3M13 15l1 2 3 1-3 1-1 2-1-2-2-1 2-1z" /></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[kind] || paths.projects}</svg>;
}
