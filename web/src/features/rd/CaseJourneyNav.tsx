import type { CSSProperties } from 'react';
import { Tooltip } from 'antd';
import { PlatformButton } from '../../components/ui/PlatformButton';
import { caseStepForSurface, type CaseJourneyStep } from './caseJourney';
import type { CaseSurface } from './scenarioManifest';
import type { ResearchCase } from './types';

export function CaseJourneyNav({ steps, active, completed, surface, researchCase, busy, onOpen }: {
  steps: CaseJourneyStep[]; active: CaseSurface; completed: boolean; surface?: CaseSurface;
  researchCase: ResearchCase; busy: boolean; onOpen: (target: CaseSurface) => void;
}) {
  const viewed = surface && surface !== 'current' ? caseStepForSurface(surface, researchCase) : undefined;
  return <nav className="rd-case-journey" aria-label="办理步骤">
    <ol style={{ '--journey-columns': steps.length } as CSSProperties}>
      {steps.map((step, index) => <li key={step.id} className={viewed === step.id ? 'is-viewed' : ''}>
        <Tooltip title={step.reason} trigger={['hover', 'focus']}>
          <span className="rd-journey-step-hint" tabIndex={!step.available ? 0 : undefined}
            onClick={!step.available ? event => event.currentTarget.focus() : undefined}
            aria-label={!step.available ? `${step.title}：${step.reason}` : undefined}>
            <PlatformButton className="rd-journey-step" aria-label={step.title}
              aria-current={viewed === step.id ? 'step' : undefined}
              disabled={busy || !step.available} title={step.reason}
              onClick={() => onOpen(step.target)}>
              <span className="rd-journey-number" aria-hidden="true">{index + 1}</span>
              <span className="rd-journey-label">{step.title}
                {!completed && active === step.id && <small aria-hidden="true">当前待办</small>}
              </span>
            </PlatformButton>
          </span>
        </Tooltip>
      </li>)}
    </ol>
  </nav>;
}
