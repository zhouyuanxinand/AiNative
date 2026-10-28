interface RunIdentity { run_id?: string; id?: string }
export const nativeRunId = (run: RunIdentity) => run.run_id || run.id || '';

/** Runtime returns runs newest first; browsing history never changes adoption. */
export function displayedNativeRun<T extends RunIdentity>(runs: T[], viewedId: string, adoptedId?: string) {
  return runs.find(run => nativeRunId(run) === viewedId)
    || runs.find(run => nativeRunId(run) === adoptedId)
    || runs[0];
}
export function nextNativeRunView(runs: RunIdentity[], viewedId: string, previousNewestId: string, editorDirty: boolean) {
  const newestId = runs[0] ? nativeRunId(runs[0]) : '';
  return !editorDirty && newestId && newestId !== previousNewestId ? newestId : viewedId;
}
