import { Button, Input, type InputRef } from 'antd';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { FeedbackConfirmDialog, FeedbackDialog } from '../../components/feedback/FeedbackDialog';
import { useApplicationLeaveGuard } from '../../hooks/useApplicationLeaveGuard';
import { makeRequestKey, rdProject, rdSaveProjectProfile, RdApiError } from './api';
import { messageOf } from './presentation';
import type { Project, ProjectProfile } from './types';
import './projectEditDialog.css';

type Draft = ProjectProfile & { title: string };
interface Attempt { project: Project; data: Draft; key: string }
interface Props {
  project: Project;
  onClose: (uncertain?: boolean) => void;
  onSaved: (project: Project) => void;
  onPendingChange: (pending: boolean) => void;
  onRefresh?: (project: Project) => void;
}
const fields = ['title', 'customer_name', 'product_name', 'brief'] as const;
const valuesOf = (project: Project): Draft => ({
  title: project.title, customer_name: project.customer_name ?? '',
  product_name: project.product_name ?? '', brief: project.brief ?? '',
});
const trim = (draft: Draft): Draft => ({
  title: draft.title.trim(), customer_name: draft.customer_name.trim(),
  product_name: draft.product_name.trim(), brief: draft.brief.trim(),
});

/** Load a fresh version before editing; an uncertain write retains its original request. */
export function ProjectEditDialog({ project, onClose, onSaved, onRefresh, onPendingChange }: Props) {
  const [target, setTarget] = useState<Project | null>(null);
  const [draft, setDraft] = useState<Draft>(() => valuesOf(project));
  const [reading, setReading] = useState(true), [pending, setPending] = useState(false);
  const [error, setError] = useState(''), [titleError, setTitleError] = useState(false);
  const [conflict, setConflict] = useState(false), [denied, setDenied] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [confirmation, setConfirmation] = useState<'close' | 'refresh' | null>(null);
  const titleInput = useRef<InputRef>(null), attempt = useRef<Attempt | null>(null);
  const lock = useRef(false), alive = useRef(true), reader = useRef<AbortController>();
  const pendingCallback = useRef(onPendingChange);
  pendingCallback.current = onPendingChange;
  const next = trim(draft), original = target && valuesOf(target);
  const dirty = !!original && fields.some(field => next[field] !== original[field]);
  useApplicationLeaveGuard({
    dirty: dirty || uncertain,
    busyMessage: pending ? '项目信息正在保存，请等待结果后再离开。' : undefined,
  });

  function setWorking(value: boolean) {
    lock.current = value;
    setPending(value);
    pendingCallback.current(value);
  }

  async function readLatest() {
    if (lock.current || uncertain) return;
    reader.current?.abort();
    const controller = new AbortController();
    reader.current = controller;
    setReading(true); setError('');
    try {
      const value = await rdProject(project.id, controller.signal);
      if (controller.signal.aborted) return;
      if (value?.id !== project.id || !Number.isInteger(value.version) || !Array.isArray(value.cases)) {
        throw new Error('项目读取结果不完整，请重新读取。');
      }
      setTarget(value); setDraft(valuesOf(value)); setTitleError(false);
      setConflict(false); setDenied(false); setUncertain(false); attempt.current = null;
      onRefresh?.(value);
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(messageOf(reason));
        setDenied(reason instanceof RdApiError && [403, 404].includes(reason.status));
      }
    } finally {
      if (!controller.signal.aborted) setReading(false);
    }
  }

  useEffect(() => {
    alive.current = true;
    void readLatest();
    return () => {
      alive.current = false;
      reader.current?.abort();
      if (lock.current) pendingCallback.current(false);
    };
  }, [project.id]);

  function requestClose() {
    if (lock.current) return;
    if (dirty || uncertain) setConfirmation('close');
    else onClose();
  }

  function requestRefresh() {
    if (lock.current || reading || uncertain) return;
    if (dirty || conflict) setConfirmation('refresh');
    else void readLatest();
  }

  async function save(event?: FormEvent) {
    event?.preventDefault();
    if (!target || lock.current || reading || conflict || denied || !dirty && !uncertain) return;
    if (!next.title) {
      setTitleError(true);
      titleInput.current?.focus();
      return;
    }
    if (next.title.length > 200 || next.customer_name.length > 200 || next.product_name.length > 200 || next.brief.length > 4000) {
      setError('项目名称、客户名称和产品名称最多200字，研发目标最多4000字。');
      return;
    }
    const current = attempt.current ?? { project: target, data: next, key: makeRequestKey() };
    attempt.current = current;
    setWorking(true); setError(''); setTitleError(false);
    try {
      const value = await rdSaveProjectProfile(current.project, current.data, current.key);
      if (!alive.current) return;
      if (value?.id !== target.id || !Number.isInteger(value.version) || value.version <= current.project.version || !Array.isArray(value.cases)) {
        throw new Error('保存结果尚未确认，请重试核对本次保存。');
      }
      onSaved(value);
    } catch (reason) {
      if (!alive.current) return;
      const unknown = !(reason instanceof RdApiError) || [0, 408].includes(reason.status) || reason.status >= 500;
      setError(messageOf(reason));
      setUncertain(unknown);
      setConflict(reason instanceof RdApiError && reason.status === 409);
      setDenied(reason instanceof RdApiError && [403, 404].includes(reason.status));
      if (!unknown) attempt.current = null;
    } finally {
      if (alive.current) setWorking(false);
    }
  }

  const frozen = reading || pending || conflict || denied || uncertain;
  return <>
    <FeedbackDialog title="编辑项目" className="rd-create-dialog rd-project-edit-dialog" onCancel={requestClose}>
      <form className="rd-project-edit-form" onSubmit={event => void save(event)} noValidate aria-busy={reading || pending}>
        <div className="rd-project-edit-body">
          {reading && <p className="rd-project-edit-status" role="status">正在读取最新项目信息…</p>}
          {target && <>
            <div className="rd-project-edit-field">
              <label htmlFor="rd-edit-project-title">项目名称 <span aria-hidden="true">*</span></label>
              <Input ref={titleInput} id="rd-edit-project-title" value={draft.title} maxLength={200} disabled={frozen}
                aria-required="true" aria-invalid={titleError} aria-describedby={titleError ? 'rd-edit-project-title-error' : undefined}
                status={titleError ? 'error' : undefined}
                onChange={event => { setDraft(value => ({ ...value, title: event.target.value })); setTitleError(false); }} />
              {titleError && <p id="rd-edit-project-title-error" className="rd-project-edit-error" role="alert">请输入项目名称。</p>}
            </div>
            <div className="rd-project-edit-grid">
              <div className="rd-project-edit-field">
                <label htmlFor="rd-edit-project-customer">客户名称</label>
                <Input id="rd-edit-project-customer" value={draft.customer_name} maxLength={200} disabled={frozen}
                  onChange={event => setDraft(value => ({ ...value, customer_name: event.target.value }))} />
              </div>
              <div className="rd-project-edit-field">
                <label htmlFor="rd-edit-project-product">产品名称</label>
                <Input id="rd-edit-project-product" value={draft.product_name} maxLength={200} disabled={frozen}
                  onChange={event => setDraft(value => ({ ...value, product_name: event.target.value }))} />
              </div>
            </div>
            <div className="rd-project-edit-field">
              <label htmlFor="rd-edit-project-brief">研发目标</label>
              <Input.TextArea id="rd-edit-project-brief" value={draft.brief} maxLength={4000} rows={4} disabled={frozen}
                onChange={event => setDraft(value => ({ ...value, brief: event.target.value }))} />
            </div>
            {target.cases.length > 0 && <p className="rd-project-edit-note">修改项目信息后，相关流程将按新信息重新核对编制依据，已有历史记录保留。</p>}
          </>}
          {error && <p className="rd-project-edit-error" role="alert">{error}</p>}
          {conflict && <p className="rd-project-edit-note">项目版本已变化。填写内容已保留，请重新读取项目后再编辑。</p>}
          {uncertain && <p className="rd-project-edit-note" role="status">保存结果尚未确认。请重试核对本次保存，当前填写已保留。</p>}
          {!reading && (!target || conflict || denied) && <div><Button htmlType="button" disabled={pending || uncertain} onClick={requestRefresh}>重新读取项目</Button></div>}
        </div>
        <div className="rd-project-edit-actions">
          <Button htmlType="button" disabled={pending} onClick={requestClose}>取消</Button>
          <Button htmlType="submit" type="primary" loading={pending} disabled={!target || reading || pending || conflict || denied || !dirty && !uncertain}>
            {pending ? '正在保存…' : uncertain ? '重试保存' : '保存修改'}
          </Button>
        </div>
      </form>
    </FeedbackDialog>
    {confirmation && <FeedbackConfirmDialog title={confirmation === 'refresh' ? '重新读取项目？' : '未保存的修改'}
      confirm={confirmation === 'refresh' ? '放弃草稿并重新读取' : '放弃修改'} cancel="继续编辑"
      saveAction={confirmation === 'close' && target && !reading && !conflict && !denied ? { label: uncertain ? '重试保存并关闭' : '保存并关闭', disabled: pending, onClick: () => { setConfirmation(null); void save(); } } : undefined}
      onCancel={() => setConfirmation(null)} onConfirm={() => {
        const action = confirmation;
        setConfirmation(null);
        if (action === 'refresh') void readLatest();
        else onClose(uncertain);
      }}>
      <p>{confirmation === 'refresh' ? '重新读取会替换当前填写，请确认放弃未保存的修改。'
        : uncertain ? '保存结果尚未确认。关闭不会撤回已经提交的保存，请重新打开项目核对；当前未保存的填写将被丢弃。'
        : '当前填写尚未保存，放弃后无法恢复。'}</p>
    </FeedbackConfirmDialog>}
  </>;
}
