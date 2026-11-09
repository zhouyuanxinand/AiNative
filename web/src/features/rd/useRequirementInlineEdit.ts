import { useRef, useState } from 'react';
import { isCurrentSource } from './presentation';
import type { Requirement, ResearchCase } from './types';
import type { CommandRunner } from './WorkpackagePanel';

interface EditableRequirement { title: string; content: string; source_ids: string[] }
interface RowEdit extends EditableRequirement { id: string; revision: number; inputRevision: ResearchCase['input_revision']; original: EditableRequirement }
const revision = (row: Requirement) => row.revision ?? row.version ?? 1;
const fingerprint = (row: EditableRequirement) => JSON.stringify([row.title.trim(), row.content.trim(), [...row.source_ids].sort()]);

/** A record revision is separate from adopting a specification or clarification. */
export function useRequirementInlineEdit(rc: ResearchCase, command: CommandRunner, disabled: boolean) {
  const [draft, setDraft] = useState<RowEdit | null>(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const savingLock = useRef(false);
  const dirty = !!draft && fingerprint(draft) !== fingerprint(draft.original);
  const current = rc.requirements.find(row => row.id === draft?.id);
  const stale = !!draft && (!current || revision(current) !== draft.revision || rc.input_revision !== draft.inputRevision);
  const hasInvalidSource = !!draft && (!draft.source_ids.length || draft.source_ids.some(id => {
    const source = rc.sources.find(item => item.id === id);
    return !source || !isCurrentSource(source, rc.source_selection);
  }));

  function begin(row: Requirement) {
    if (disabled || draft) return;
    const original = { title: row.title, content: row.content, source_ids: [...row.source_ids] };
    setDraft({ ...original, id: row.id, revision: revision(row), inputRevision: rc.input_revision, original });
    setError('');
  }
  function change(fields: Partial<EditableRequirement>) {
    if (disabled || savingLock.current) return;
    setDraft(previous => previous ? { ...previous, ...fields } : null);
    setError('');
  }
  function cancel() {
    if (savingLock.current) return;
    setDraft(null); setError('');
  }
  async function save() {
    if (!draft || disabled || savingLock.current || !dirty || stale) return;
    if (!draft.title.trim() || !draft.content.trim() || hasInvalidSource) {
      setError('请填写标题、内容，并关联当前输入文件。'); return;
    }
    savingLock.current = true; setSaving(true); setError('');
    try {
      const succeeded = await command('save_requirement', {
        id: draft.id, title: draft.title.trim(), content: draft.content.trim(), source_ids: draft.source_ids,
      }, () => { setDraft(null); setError(''); });
      if (!succeeded) setError('保存未成功，修改已保留。请检查页面提示后重试。');
    } catch {
      setError('保存未成功，修改已保留，请重试。');
    } finally { savingLock.current = false; setSaving(false); }
  }
  return { draft, dirty, saving, stale, hasInvalidSource, begin, change, cancel, save,
    error: stale ? '这条需求或输入已更新，请先复制修改内容，取消编辑后重新核对。' : error };
}
