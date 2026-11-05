import { Button, Card } from 'antd';
import { useMemo } from 'react';
import { formatTime } from './presentation';
import { projectCaseCardModel } from './projectCaseCardModel';
import type { CaseSurface } from './scenarioManifest';
import type { Catalog, Project } from './types';

export function PlatformHome({ onStart, projects, catalog, canCreate, catalogLoading, catalogError, loading, error, onRefresh, onOpenProject, onOpenCase, onOpenProjects }: {
  onStart: () => void;
  projects: Project[];
  catalog: Catalog | null;
  canCreate: boolean;
  catalogLoading: boolean;
  catalogError: string;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  onOpenProject: (id: string) => void;
  onOpenCase: (projectId: string, caseId: string, target?: CaseSurface) => void;
  onOpenProjects: () => void;
}) {
  const projectFacts = useMemo(() => projects.map(project => ({ project,
    flows: project.cases.map(researchCase => ({ researchCase, model: projectCaseCardModel(project, researchCase) })),
  })), [projects]);
  const recentProjects = useMemo(() => [...projectFacts].sort((left, right) =>
    (Date.parse(right.project.updated_at ?? right.project.created_at ?? '') || 0) - (Date.parse(left.project.updated_at ?? left.project.created_at ?? '') || 0),
  ).slice(0, 5), [projectFacts]);
  const attention = useMemo(() => projectFacts.flatMap(({ project, flows }) =>
    flows.filter(({ model }) => !!model.attention).map(flow => ({ project, ...flow })),
  ), [projectFacts]);

  return <div className="rd-platform-home rd-daily-workbench">
    <header className="rd-home-intro"><h1>我的工作</h1><Button type="primary" htmlType="button" className="rd-button primary" disabled={!canCreate} onClick={onStart}><span aria-hidden="true">＋</span>新建项目</Button></header>
    {catalogLoading ? <p className="rd-home-start-note" role="status">正在读取流程模板…</p> : !catalogError && !catalog?.project_workflow_templates?.some(item => item.status === 'published') && <p className="rd-home-start-note">暂无已发布流程模板，请在流程管理中查看与发布。</p>}
    <div className="rd-home-work-grid">
      <Card className="rd-home-continue rd-home-panel" role="region" aria-labelledby="rd-home-continue-title" styles={{ body: { padding: 0 } }}>
        <div className="rd-home-section-heading"><h2 id="rd-home-continue-title">最近项目</h2><div><Button type="link" htmlType="button" className="rd-link-button" disabled={loading} onClick={onRefresh}>{loading ? '读取中…' : '刷新'}</Button><Button type="link" htmlType="button" className="rd-link-button" onClick={onOpenProjects}>全部项目 <span aria-hidden="true">→</span></Button></div></div>
        {error && <div className="rd-error rd-home-read-error" role="alert"><p>{error}</p><p>{projects.length ? '当前显示上次读取的项目记录。' : '项目数据尚未取得，请重试读取。'}</p><Button type="link" htmlType="button" className="rd-link-button" onClick={onRefresh}>重新读取</Button></div>}
        {loading && <p className="rd-loading rd-home-read-status" role="status">{projects.length ? '正在刷新项目，已读取记录继续保留。' : '正在读取项目…'}</p>}
        {recentProjects.length > 0 && <div className="rd-home-project-table"><table role="table" aria-label="最近项目与当前工作"><thead role="rowgroup"><tr role="row"><th scope="col">项目 / 业务流程</th><th scope="col">当前工作</th><th scope="col">最近更新</th><th scope="col">操作</th></tr></thead><tbody role="rowgroup">{recentProjects.map(({ project, flows }) => {
          const current = flows.find(({ model }) => !model.completed) ?? flows[0];
          const researchCase = current?.researchCase;
          const recordedAt = project.updated_at ?? project.created_at;
          const validTime = recordedAt && Number.isFinite(Date.parse(recordedAt));
          return <tr key={project.id} role="row">
            <td role="cell"><button type="button" className="rd-home-project-name" onClick={() => onOpenProject(project.id)}>{project.title}</button>{current && <p>{current.researchCase.title !== project.title ? current.researchCase.title : current.model.templateTitle}</p>}</td>
            <td role="cell"><span className="rd-home-cell-label" aria-hidden="true">当前工作</span>{current ? <span className={`rd-home-stage ${current.model.completed ? 'completed' : ''}`}>{current.model.stepTitle}</span> : <span className="rd-muted">待选择流程模板</span>}</td>
            <td role="cell"><span className="rd-home-cell-label" aria-hidden="true">最近更新</span>{validTime ? <time dateTime={recordedAt}>{formatTime(recordedAt)}</time> : <span className="rd-muted">未记录</span>}</td>
            <td role="cell"><Button type="link" htmlType="button" className="rd-link-button" onClick={() => researchCase ? onOpenCase(project.id, researchCase.id) : onOpenProject(project.id)}>{current?.model.actionLabel ?? '进入项目'}</Button></td>
          </tr>;
        })}</tbody></table></div>}
        {!loading && !error && !projects.length && <div className="rd-home-list-empty"><h3>暂无项目记录</h3><p>新建项目后开始办理。</p></div>}
      </Card>
      <Card className="rd-home-attention rd-home-panel" role="region" aria-labelledby="rd-home-attention-title" styles={{ body: { padding: 0 } }}>
        <div className="rd-home-section-heading"><h2 id="rd-home-attention-title">需关注</h2></div>
        {attention.length ? <><p className="rd-home-attention-caption">{attention.length} 个流程{error || loading ? ' · 上次读取记录' : ''}</p><div className="rd-attention-list">{attention.slice(0, 5).map(({ project, researchCase, model }) => <button type="button" key={`${project.id}-${researchCase.id}`} onClick={() => onOpenCase(project.id, researchCase.id, 'workpackages')}><span className={`rd-attention-mark ${model.status}`} aria-hidden="true" /><div><strong>{researchCase.title}</strong><small>{project.title}</small><span className={`rd-home-attention-state ${model.status}`}>{model.attention}</span></div><span className="rd-attention-open" aria-hidden="true">→</span></button>)}</div>{attention.length > 5 && <p className="rd-home-attention-more"><Button type="link" htmlType="button" className="rd-link-button" onClick={onOpenProjects}>查看其余 {attention.length - 5} 个流程 →</Button></p>}</> : <div className="rd-home-attention-empty"><p>{loading ? '正在核对项目状态…' : error ? '项目状态尚未取得，请重试读取。' : '暂无待处理事项。'}</p></div>}
      </Card>
    </div>
  </div>;
}
