import { EditOutlined } from '@ant-design/icons';
import { Button, Table, Tooltip } from 'antd';
import { useCurrentUser } from '../../hooks/useCurrentUser';
import { ProjectDeleteButton } from './ProjectDeleteButton';
import { projectCaseCardModel } from './projectCaseCardModel';
import { formatTime } from './presentation';
import type { PlatformLocation } from './platformNavigation';
import type { Project } from './types';
import './projectDirectory.css';

export function projectDirectoryFacts(project: Project) {
  const flows = project.cases.map(item => ({ id: item.id, ...projectCaseCardModel(project, item) }));
  const completed = flows.filter(item => item.completed).length;
  const attention = flows.filter(item => !item.completed && item.attention).length;
  return { flows, completed, attention, status: !flows.length ? 'empty' : completed === flows.length ? 'completed' : attention ? 'attention' : 'active' };
}

export function selectDirectoryProjects(projects: Project[], location: PlatformLocation) {
  const term = location.q.trim().toLocaleLowerCase();
  const timestamp = (project: Project) => Date.parse(project.updated_at ?? project.created_at ?? '') || 0;
  return projects.filter(project => {
    if (term && ![project.title, project.customer_name, project.product_name, project.brief, ...project.cases.map(item => item.title)].join(' ').toLocaleLowerCase().includes(term)) return false;
    const facts = projectDirectoryFacts(project);
    return !location.projectStatus || (location.projectStatus === 'active' ? facts.flows.length > facts.completed : facts.status === location.projectStatus);
  }).sort((left, right) => {
    if (location.projectSort === 'name') return left.title.localeCompare(right.title, 'zh-CN');
    return location.projectSort === 'oldest' ? timestamp(left) - timestamp(right) : timestamp(right) - timestamp(left);
  });
}

export function ProjectOwner({ project }: { project: Project & { owner_name?: string; owner_display_name?: string } }) {
  const { state } = useCurrentUser();
  const id = project.owner_id?.trim();
  const user = state.status === 'ready' && state.identity.authenticated ? state.identity.user : null;
  const currentName = user && [user.userid, `smartvision:${user.userid}`].includes(id) ? user.display_name : '';
  const name = project.owner_display_name?.trim() || project.owner_name?.trim() || currentName || (id?.startsWith('local:') ? '本地用户' : id || '未设置');
  return id && name !== id ? <Tooltip title={`账号：${id}`}><span tabIndex={0} className="rd-owner-label">{name}</span></Tooltip> : <>{name}</>;
}

export function ProjectDirectoryTable({ projects, disabled, onOpen, onContinue, onEdit, onDelete }: {
  projects: Project[]; disabled: boolean; onOpen: (id: string) => void; onContinue: (id: string, caseId: string) => void;
  onEdit: (project: Project) => void; onDelete: (project: Project) => void;
}) {
  return <div className="rd-project-table-scroll" role="region" aria-label="项目紧凑列表" tabIndex={0}>
    <Table<Project> rowKey="id" dataSource={projects} pagination={false} size="small" tableLayout="fixed" columns={[
      { title: '项目 / 客户 / 产品', key: 'project', width: '34%', render: (_, project) => <div className="rd-project-table-title"><Button type="link" onClick={() => onOpen(project.id)}>{project.title}</Button><span>{project.customer_name || '客户未填写'} · {project.product_name || '产品未填写'}</span></div> },
      { title: '办理情况', key: 'status', width: '20%', render: (_, project) => { const facts = projectDirectoryFacts(project); return <><span>{facts.flows.length ? `${facts.completed} / ${facts.flows.length} 个流程已完成` : '待建立流程'}</span>{facts.attention > 0 && <small className="rd-project-table-attention">{facts.attention} 个流程需关注</small>}</>; } },
      { title: '负责人 / 最近更新', key: 'owner', width: '25%', render: (_, project) => <><ProjectOwner project={project} /><small>{formatTime(project.updated_at)}</small></> },
      { title: '操作', key: 'actions', width: '21%', render: (_, project) => { const current = projectDirectoryFacts(project).flows.find(item => !item.completed); return <div className="rd-project-table-actions"><Button type="link" disabled={disabled} onClick={() => current ? onContinue(project.id, current.id) : onOpen(project.id)}>{current ? '继续办理' : '查看项目'}</Button><Tooltip title="编辑项目"><Button type="text" icon={<EditOutlined />} aria-label={`编辑项目：${project.title}`} disabled={disabled} onClick={() => onEdit(project)} /></Tooltip><ProjectDeleteButton project={project} disabled={disabled} onRequest={onDelete} /></div>; } },
    ]} locale={{ emptyText: '没有符合条件的项目' }} />
  </div>;
}
