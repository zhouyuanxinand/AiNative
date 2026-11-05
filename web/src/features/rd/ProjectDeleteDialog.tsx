import { Button } from 'antd';
import { useRef, useState } from 'react';
import { FeedbackConfirmDialog } from '../../components/feedback/FeedbackDialog';
import { makeRequestKey, rdDeleteProject, rdProject, RdApiError } from './api';
import { messageOf } from './presentation';
import type { Project } from './types';

export function ProjectDeleteDialog({ project, onClose, onDeleted, onRefresh, onPendingChange }: {
  project: Project; onClose: (uncertain?: boolean) => void; onDeleted: (projectId: string) => void;
  onRefresh: (project: Project) => void; onPendingChange: (pending: boolean) => void;
}) {
  const [target, setTarget] = useState(project);
  const [pending, setPending] = useState(false), [error, setError] = useState('');
  const [conflict, setConflict] = useState(false), [uncertain, setUncertain] = useState(false), [denied, setDenied] = useState(false);
  const retry = useRef(makeRequestKey());
  const lock = useRef(false);
  function setWorking(value: boolean) { lock.current = value; setPending(value); onPendingChange(value); }
  async function remove() {
    if (lock.current || conflict || denied || target.can_delete !== true || target.delete_blocked_reason) return;
    setWorking(true); setError('');
    try {
      const receipt = await rdDeleteProject(target, retry.current);
      if (receipt.ok !== true || receipt.project_id !== target.id) throw new Error('删除结果尚未确认，请重新核对项目状态。');
      onDeleted(target.id);
    } catch (reason) {
      setError(messageOf(reason));
      setConflict(reason instanceof RdApiError && reason.status === 409);
      setDenied(reason instanceof RdApiError && [403, 404].includes(reason.status));
      setUncertain(!(reason instanceof RdApiError) || [0, 408].includes(reason.status) || reason.status >= 500);
    } finally { setWorking(false); }
  }
  async function refresh() {
    if (lock.current || uncertain) return;
    setWorking(true); setError('');
    try {
      const value = await rdProject(target.id);
      setTarget(value); onRefresh(value); retry.current = makeRequestKey();
      setConflict(false); setDenied(value.can_delete !== true); setUncertain(false);
      if (value.can_delete !== true) setError('当前身份没有删除此项目的权限。');
      else if (value.delete_blocked_reason) setError(value.delete_blocked_reason);
    } catch (reason) { setError(messageOf(reason)); }
    finally { setWorking(false); }
  }
  const sources = target.cases.reduce((count, item) => count + item.sources.length, 0);
  const artifacts = target.cases.reduce((count, item) => count + item.workpackages.reduce((total, workpackage) => total + workpackage.artifacts.length, 0), 0);
  return <FeedbackConfirmDialog title="删除项目" confirm="删除项目" danger pending={pending}
    confirmDisabled={conflict || denied || target.can_delete !== true || !!target.delete_blocked_reason}
    error={error} onCancel={() => { if (!lock.current) onClose(uncertain); }} onConfirm={() => void remove()}>
    <p>确定删除项目“<strong>{target.title}</strong>”？</p>
    <p>包含 {target.cases.length} 个业务流程、{sources} 份来源资料和 {artifacts} 份成果记录。删除后，这些内容将从项目空间移除，相关入口将无法继续访问。</p>
    <p>此次为逻辑删除，来源文件与历史追溯记录保留。</p>
    {uncertain && <p className="rd-warning" role="status">请求结果尚未确认。再次点击“删除项目”会核对同一次请求，请勿重复发起其他删除。</p>}
    {conflict && <p className="rd-warning">项目状态已变化，请重新读取并核对范围后再次确认。</p>}
    {(conflict || denied) && <Button htmlType="button" disabled={pending || uncertain} onClick={() => void refresh()}>重新读取项目</Button>}
  </FeedbackConfirmDialog>;
}
