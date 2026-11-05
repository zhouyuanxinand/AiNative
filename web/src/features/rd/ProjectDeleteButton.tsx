import { DeleteOutlined } from '@ant-design/icons';
import { Button, Tooltip } from 'antd';
import type { Project } from './types';

export function ProjectDeleteButton({ project, disabled, onRequest }: { project: Project; disabled?: boolean; onRequest: (project: Project) => void }) {
  if (project.can_delete !== true) return null;
  const reason = project.delete_blocked_reason;
  return <Tooltip title={reason || '删除项目'}><span className="rd-project-delete-anchor"><Button type="text" danger className="rd-project-delete" icon={<DeleteOutlined />} aria-label={`删除项目“${project.title}”`} disabled={disabled || !!reason} onClick={event => { event.stopPropagation(); onRequest(project); }} /></span></Tooltip>;
}
