import { useId } from 'react';
import { Dropdown, Progress } from 'antd';
import { MoreOutlined } from '@ant-design/icons';
import { PlatformButton } from '../../components/ui/PlatformButton';
import { projectCaseCardModel } from './projectCaseCardModel';
import type { Project, ResearchCase } from './types';
import './projectCaseCard.css';

export function ProjectCaseCard({ project, researchCase, onContinue, onOpenProcess, onOpenEvidence }: {
  project: Project; researchCase: ResearchCase; onContinue: () => void; onOpenProcess: () => void; onOpenEvidence: () => void;
}) {
  const titleId = useId(), model = projectCaseCardModel(project, researchCase);
  return <article className="rd-project-case-card" aria-labelledby={titleId}>
    <header className="rd-project-case-card-heading">
      <div><p>{model.templateTitle}{model.templateVersion && <span> · V{model.templateVersion}</span>}</p><h2 id={titleId}>{researchCase.title}</h2></div>
      <span className={`rd-badge ${model.status}`}>{model.statusLabel}</span>
    </header>
    <div className="rd-project-case-card-step"><span>当前步骤</span><strong>{model.stepTitle}</strong></div>
    <div className="rd-project-case-card-progress"><p>{model.progress.label}</p>{model.progress.percent !== null && <Progress percent={model.progress.percent} showInfo={false} size="small" status={model.completed ? 'success' : 'normal'} aria-label={model.progress.label} />}</div>
    <div className={`rd-project-case-card-next${model.attention ? ' is-attention' : ''}`}><span>{model.attention ? '需要关注' : model.completed ? '成果' : '下一步'}</span><p>{model.attention || model.nextLabel}</p></div>
    <dl className="rd-project-case-card-facts">
      <div><dt>当前资料 / 需求</dt><dd>{model.sourceCount} 份资料 · {model.requirementCount} 条需求</dd></div>
      <div><dt>项目负责人</dt><dd>{model.owner}</dd></div>
      <div><dt>最近工作包截止</dt><dd>{model.deadline || '未设置'}</dd></div>
      <div><dt>当前成果 / 交付</dt><dd>{model.artifactCount} 份成果 · {model.delivery}</dd></div>
    </dl>
    <footer className="rd-project-case-card-actions">
      <PlatformButton className="rd-button primary" onClick={onContinue}>{model.actionLabel}</PlatformButton>
      <PlatformButton className="rd-link-button" onClick={onOpenProcess}>查看流程</PlatformButton>
      <Dropdown trigger={['click']} menu={{ items: [{ key: 'evidence', label: '资料依据', onClick: onOpenEvidence }] }}>
        <PlatformButton aria-label={`${researchCase.title}更多操作`} title="更多操作"><MoreOutlined /></PlatformButton>
      </Dropdown>
    </footer>
  </article>;
}
