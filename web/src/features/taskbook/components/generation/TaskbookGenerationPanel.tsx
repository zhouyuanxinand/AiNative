import { LegacyTaskbookGenerationPanel } from './LegacyTaskbookGenerationPanel';
import { TaskbookInputPanel } from '../workspace/TaskbookInputPanel';
import type { TaskbookWorkspaceController } from '../../hooks/useTaskbookWorkspace';

/** Both entry points keep their context; native mode submits a fixed input package to the same engine. */
export function TaskbookGenerationPanel({ binding }: { binding?: TaskbookWorkspaceController }) {
  return binding ? <TaskbookInputPanel controller={binding} /> : <LegacyTaskbookGenerationPanel />;
}
