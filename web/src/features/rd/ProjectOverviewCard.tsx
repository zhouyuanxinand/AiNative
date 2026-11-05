import { Button } from 'antd';
import { ProjectDeleteButton } from './ProjectDeleteButton';
import { projectCaseCardModel } from './projectCaseCardModel';
import { formatTime } from './presentation';
import type { Project } from './types';
import './projectOverviewCard.css';

export function ProjectOverviewCard({ project, disabled, onOpen, onContinue, onDelete }: {
  project: Project;
  disabled: boolean;
  onOpen: () => void;
  onContinue: (caseId: string) => void;
  onDelete: (project: Project) => void;
}) {
  // Include every flow in the overview, even those below the two-item preview.
  const flows = project.cases.map(researchCase => ({ researchCase, model: projectCaseCardModel(project, researchCase) }));
  const completed = flows.filter(({ model }) => model.completed).length;
  const attention = flows.filter(({ model }) => !model.completed && model.attention).length;
  const updated = formatTime(project.updated_at);
  return <article className="rd-project-entry rd-platform-project rd-project-overview-card" aria-label={project.title}>
    <header>
      <h3><button type="button" onClick={onOpen}>{project.title}</button></h3>
      <div className="rd-project-entry-actions">
        <Button type="link" htmlType="button" className="rd-link-button" onClick={onOpen}>查看项目 <span aria-hidden="true">↗</span></Button>
        <ProjectDeleteButton project={project} disabled={disabled} onRequest={onDelete} />
      </div>
    </header>
    <div className="rd-project-overview-body">
      <dl className="rd-project-overview-profile">
        <div><dt>客户</dt><dd>{project.customer_name?.trim() || '未填写'}</dd></div>
        <div><dt>产品</dt><dd>{project.product_name?.trim() || '未填写'}</dd></div>
      </dl>
      {project.brief?.trim() && <p className="rd-project-goal-preview" title={project.brief}>{project.brief}</p>}
      <dl className="rd-project-overview-counts">
        <div><dt>业务流程</dt><dd>{flows.length}</dd></div>
        <div><dt>已完成</dt><dd>{completed}</dd></div>
        <div className={attention ? 'has-attention' : undefined}><dt>需关注</dt><dd>{attention}</dd></div>
      </dl>
      <dl className="rd-project-overview-meta">
        <div><dt>项目负责人</dt><dd>{project.owner_id?.trim() || '未设置'}</dd></div>
        <div><dt>最近更新</dt><dd>{updated === '—' ? '未记录' : <time dateTime={project.updated_at}>{updated}</time>}</dd></div>
      </dl>
    </div>
    {flows.length ? <div className="rd-project-cases">{flows.slice(0, 2).map(({ researchCase, model }) =>
      <button type="button" className="rd-project-continue" key={researchCase.id} onClick={() => onContinue(researchCase.id)}>
        <div><strong>{researchCase.title}</strong><small>{model.templateTitle}{model.templateVersion && ` · V${model.templateVersion}`} · {model.completed ? '已完成' : model.stepTitle}{model.attention && <span className="rd-attention-text"> · 需关注</span>}</small></div>
        <span>{model.actionLabel} <span aria-hidden="true">→</span></span>
      </button>)}</div>
      : <div className="rd-project-no-cases"><p>尚未建立业务流程</p><Button type="link" htmlType="button" className="rd-link-button" onClick={onOpen}>进入项目选择流程模板</Button></div>}
    {flows.length > 2 && <Button type="link" htmlType="button" className="rd-link-button rd-project-show-all" onClick={onOpen}>查看全部 {flows.length} 个流程</Button>}
  </article>;
}
