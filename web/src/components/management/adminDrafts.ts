import { useEffect, useId } from 'react';

const drafts = new Set<string>();
export const hasAdminUnsavedChanges = () => drafts.size > 0;

/** Keep drafts when switching panels, and warn before explicitly ending the administrator session. */
export function useAdminUnsavedChanges(dirty: boolean) {
  const id = useId();
  useEffect(() => {
    if (dirty) drafts.add(id); else drafts.delete(id);
    return () => { drafts.delete(id); };
  }, [dirty, id]);
}
