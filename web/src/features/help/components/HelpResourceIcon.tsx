import type { HelpResourceKind } from '../model/helpResources';

export function HelpResourceIcon({ kind }: { kind: HelpResourceKind }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {kind === 'video' ? (
        <>
          <rect x="3" y="5" width="18" height="14" rx="3" />
          <path d="m10 9 5 3-5 3Z" />
        </>
      ) : (
        <>
          <path d="M12 6C9 4 5 4 3 5v14c2-1 6-1 9 1 3-2 7-2 9-1V5c-2-1-6-1-9 1Z" />
          <path d="M12 6v14M6 9h3M15 9h3" />
        </>
      )}
    </svg>
  );
}
