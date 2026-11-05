import { CaseClarifications } from './CaseClarifications';
import { CaseComparisons } from './CaseComparisons';
import { CaseHandover } from './CaseHandover';
import type { Project, ResearchCase } from './types';
import type { CommandRunner } from './WorkpackagePanel';

export function CaseRecords(props: { kind: 'clarifications' | 'comparisons' | 'delivery' | 'reuse'; project: Project; researchCase: ResearchCase; busy: boolean; error: string; command: CommandRunner; onDirtyChange: (dirty: boolean) => void; focusRequest?: { requirementId: string } }) {
  if (props.kind === 'clarifications') return <CaseClarifications {...props} />;
  if (props.kind === 'comparisons') return <CaseComparisons {...props} />;
  return <CaseHandover {...props} kind={props.kind} />;
}
