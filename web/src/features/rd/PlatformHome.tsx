import { useMemo } from 'react';
import { formatTime, stageTitle } from './presentation';
import type { Catalog, Project } from './types';

export function PlatformHome({ onStart, projects, catalog, loading, error, onRefresh, onOpenProject, onOpenCase, onOpenProjects }: {
  goal: string;
  onGoalChange: (value: string) => void;
  onStart: () => void;
  projects: Project[];
  catalog: Catalog | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  onOpenProject: (id: string) => void;
  onOpenCase: (projectId: string, caseId: string) => void;
  onOpenProjects: () => void;
}) {
  const recentProjects = useMemo(() => [...projects].sort((left, right) =>
    (Date.parse(right.updated_at ?? right.created_at ?? '') || 0) - (Date.parse(left.updated_at ?? left.created_at ?? '') || 0),
  ).slice(0, 5), [projects]);
  const attention = useMemo(() => projects.flatMap(project => project.cases.flatMap(researchCase => {
    const blocked = researchCase.workpackages.filter(item => ['blocked', 'failed'].includes(item.status));
    return blocked.map(workpackage => ({ project, researchCase, workpackage }));
  })), [projects]);
  const scenarioName = (id: string) => {
    const item = catalog?.scenarios.find(scenario => scenario.id === id);
    return item?.title ?? item?.name ?? '业务流程';
  };

  return <div className="rd-platform-home rd-daily-workbench">
    <header className="rd-home-intro"><div><h1>我的工作</h1><p>查看项目进展，继续当前工作。</p></div><button type="button" className="rd-button primary" disabled={!catalog?.scenarios.length} onClick={onStart}><span aria-hidden="true">＋</span>新建项目</button></header>
    {!catalog?.scenarios.length && <p className="rd-home-start-note">新建项目需要先取得可用业务场景，请核对页面上的目录读取状态。</p>}
    <div className="rd-home-work-grid">
      <section className="rd-home-continue rd-home-panel" aria-labelledby="rd-home-continue-title">
        <div className="rd-home-section-heading"><h2 id="rd-home-continue-title">最近项目</h2><div><button type="button" className="rd-link-button" disabled={loading} onClick={onRefresh}>{loading ? '读取中…' : '刷新'}</button><button type="button" className="rd-link-button" onClick={onOpenProjects}>全部项目 <span aria-hidden="true">→</span></button></div></div>
        {error && <div className="rd-error rd-home-read-error" role="alert"><p>{error}</p><p>{projects.length ? '当前显示上次读取的项目记录。' : '项目数据尚未取得，请重试读取。'}</p><button type="button" className="rd-link-button" onClick={onRefresh}>重新读取</button></div>}
        {loading && <p className="rd-loading rd-home-read-status" role="status">{projects.length ? '正在刷新项目，已读取记录继续保留。' : '正在读取项目…'}</p>}
        {recentProjects.length > 0 && <div className="rd-home-project-table" tabIndex={0} role="region" aria-label="最近项目与当前工作"><table><thead><tr><th scope="col">项目 / 当前工作</th><th scope="col">当前阶段</th><th scope="col">最近更新</th><th scope="col">操作</th></tr></thead><tbody>{recentProjects.map(project => {
          const researchCase = project.cases.find(item => item.status !== 'completed') ?? project.cases[0];
          const recordedAt = project.updated_at ?? project.created_at;
          const validTime = recordedAt && Number.isFinite(Date.parse(recordedAt));
          return <tr key={project.id}>
            <td><button type="button" className="rd-home-project-name" onClick={() => onOpenProject(project.id)}>{project.title}</button><p>{researchCase ? <>{scenarioName(researchCase.scenario_id)}{researchCase.title !== project.title && <> · {researchCase.title}</>}</> : '尚未建立业务流程'}</p></td>
            <td>{researchCase ? <span className={`rd-home-stage ${researchCase.status === 'completed' ? 'completed' : ''}`}>{researchCase.status === 'completed' ? '流程已完成' : stageTitle(researchCase.stage)}</span> : <span className="rd-muted">待选择场景</span>}</td>
            <td>{validTime ? <time dateTime={recordedAt}>{formatTime(recordedAt)}</time> : <span className="rd-muted">未记录</span>}</td>
            <td><button type="button" className="rd-link-button" onClick={() => researchCase ? onOpenCase(project.id, researchCase.id) : onOpenProject(project.id)}>{researchCase?.status === 'completed' ? '查看成果' : researchCase ? '继续办理' : '进入项目'}</button></td>
          </tr>;
        })}</tbody></table></div>}
        {!loading && !error && !projects.length && <div className="rd-home-list-empty"><h3>暂无项目记录</h3><p>点击“新建项目”，填写研发目标并选择业务场景后开始办理。</p></div>}
      </section>
      <section className="rd-home-attention rd-home-panel" aria-labelledby="rd-home-attention-title">
        <div className="rd-home-section-heading"><h2 id="rd-home-attention-title">需关注</h2></div>
        {attention.length ? <><p className="rd-home-attention-caption">{error || loading ? '已读取记录中的' : '当前项目中的'}受阻与失败工作包</p><div className="rd-attention-list">{attention.slice(0, 5).map(({ project, researchCase, workpackage }) => <button type="button" key={`${researchCase.id}-${workpackage.id}`} onClick={() => onOpenCase(project.id, researchCase.id)}><span className={`rd-attention-mark ${workpackage.status}`} aria-hidden="true" /><div><strong>{workpackage.title}</strong><small>{project.title}</small><span className={`rd-home-attention-state ${workpackage.status}`}>{workpackage.status === 'failed' ? '执行失败' : '执行受阻'}</span></div><span className="rd-attention-open" aria-hidden="true">→</span></button>)}</div>{attention.length > 5 && <p className="rd-home-attention-more">另有 {attention.length - 5} 项，可在项目空间查看。</p>}</> : <div className="rd-home-attention-empty"><p>{loading ? '正在核对项目状态…' : error ? '项目状态尚未取得，请重试读取。' : '暂无执行受阻或失败的工作包。'}</p></div>}
      </section>
    </div>
  </div>;
}
