import { useCallback, useEffect, useRef, useState } from 'react';
import { commandRdProject } from '../../rd/api/rd';
import { getTaskbookWorkspace, getTaskbookDraft, saveTaskbookDraft, taskbookMutation, type NativeWorkspace, type NativeInputForm } from '../api/workspace';

export const emptyNativeForm = (): NativeInputForm => ({ source_refs: [], parameters: { product_type: '', product_domain: '', development_process: '全新', product_series: '', organization_scope: 'non_central_research', cover_phase: 'F', use_llm: true, fail_on_regression: false }, model_selection: { provider: '', name: '', id: '' } });
export function useTaskbookWorkspace(projectId: string, taskId: string) {
  const [mutating, setMutating] = useState(false); const mutationLock = useRef(false);
  const [workspace, setWorkspace] = useState<NativeWorkspace | null>(null), [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true);
  const [form, setForm] = useState<NativeInputForm>(emptyNativeForm), [operations, setOperations] = useState<Record<string, unknown>[]>([]), [savedStamp, setSavedStamp] = useState(''), [saveError, setSaveError] = useState<unknown>(null), [saving, setSaving] = useState(false);
  const actorRole = useRef('');
  const packageScope = useRef<string | null>(null);
  const draftRevision = useRef(0), alive = useRef(true), initialized = useRef(false), savingRef = useRef(false);
  const stamp = JSON.stringify([form, operations]);
  const refresh = useCallback(async () => {
    let data: NativeWorkspace;
    try { data = await getTaskbookWorkspace(projectId, taskId); } catch (reason) { if (alive.current) { setError(reason); if (reason instanceof Error && 'status' in reason && [401,403,404].includes(Number(reason.status))) setWorkspace(null); } throw reason; }
    if (!alive.current) return;
    if (actorRole.current && actorRole.current !== data.project.role) initialized.current = false; actorRole.current = data.project.role;
    setWorkspace(data); setError(null);
    if (!initialized.current) {
      const pack = data.packages.find(item => item.id === data.work_unit.input_package_id);
      const fields = data.draft?.form?.parameters ? data.draft.form : pack ? { source_refs: pack.source_refs.map(ref => ({ source_id: ref.source_id, version: ref.version })), parameters: pack.raw_parameters, model_selection: pack.model_selection } : emptyNativeForm();
      const pending = data.draft?.pending_operations || [];
      setForm(fields); setOperations(pending); setSavedStamp(JSON.stringify([fields, pending])); draftRevision.current = data.draft?.draft_revision || 0; initialized.current = true; packageScope.current = data.work_unit.input_package_id || null;
    } else if (packageScope.current !== (data.work_unit.input_package_id || null)) {
      packageScope.current = data.work_unit.input_package_id || null; draftRevision.current = data.draft?.draft_revision || 0; setSavedStamp(''); setSaveError(null);
    }
  }, [projectId, taskId]);
  useEffect(() => { alive.current = true; setLoading(true); void refresh().catch(setError).finally(() => alive.current && setLoading(false)); return () => { alive.current = false; }; }, [refresh]);
  const save = useCallback(async () => {
    if (savingRef.current) throw new Error('草稿正在保存，请稍后继续。');
    savingRef.current = true; setSaving(true); setSaveError(null);
    try {
      const result = await saveTaskbookDraft(projectId, taskId, { expected_draft_revision: draftRevision.current, input_package_id: workspace?.work_unit.input_package_id || null, form, pending_operations: operations });
      if (!alive.current) return;
      draftRevision.current = result.draft_revision; setSavedStamp(stamp);
    } catch (reason) { if (alive.current) setSaveError(reason); throw reason; }
    finally { savingRef.current = false; if (alive.current) setSaving(false); }
  }, [projectId, taskId, workspace?.work_unit.input_package_id, form, operations, stamp]);
  const mutate = useCallback(async (action: string, payload: Record<string, unknown>, key: string) => { if (!workspace) return; if (mutationLock.current) throw new Error('另一项任务操作正在处理，请等待结果后重试。'); mutationLock.current = true; setMutating(true); try { await taskbookMutation(projectId, taskId, action, { ...payload, expected_version: workspace.project.version }, key); await refresh(); } finally { mutationLock.current = false; setMutating(false); } }, [projectId, taskId, workspace, refresh]);
  const command = useCallback(async (action: string, payload: Record<string, unknown>, key: string) => { if (!workspace) return; if (mutationLock.current) throw new Error('另一项任务操作正在处理，请等待结果后重试。'); mutationLock.current = true; setMutating(true); try { await commandRdProject(projectId, action, payload, workspace.project.version, key); await refresh(); } finally { mutationLock.current = false; setMutating(false); } }, [projectId, workspace, refresh]);
  const compareDraft = useCallback(() => getTaskbookDraft(projectId, taskId, workspace?.work_unit.input_package_id), [projectId, taskId, workspace?.work_unit.input_package_id]);
  const saveMergedDraft = useCallback(async (remoteRevision: number) => { draftRevision.current = remoteRevision; await save(); }, [save]);
  const dirty = initialized.current && stamp !== savedStamp;
  return { mutating, compareDraft, saveMergedDraft, workspace, error, loading, form, setForm, operations, setOperations, dirty, save, saveError, saving, refresh, mutate, command };
}
export type TaskbookWorkspaceController = ReturnType<typeof useTaskbookWorkspace>;
