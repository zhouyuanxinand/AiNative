import { isCurrentSource } from './presentation';
import { isUnresolvedRequirementValue, requirementActualResult } from './requirementActualResult';
import type { ResearchCase } from './types';

type Blocker = { message: string; requirementId?: string };

/** Explain client-visible blockers; the server still validates and fixes the baseline. */
export function requirementConfirmationBlockers(researchCase: ResearchCase): Blocker[] {
  const blockers: Blocker[] = [];
  const rows = new Map(researchCase.requirements.map(row => [row.id, row]));
  if (!rows.size) return [{ message: '请先采用有来源的需求，再确认需求。' }];

  // Older cases may omit an explicit selection when there is only one file per role.
  const selection = { ...researchCase.source_selection };
  for (const role of ['tech', 'spec'] as const) {
    const candidates = researchCase.sources.filter(source => source.role === role);
    if (selection[role] === undefined && candidates.length === 1) selection[role] = candidates[0].id;
    if (selection[role] !== '' && candidates.length && !candidates.some(source => source.id === selection[role])) {
      blockers.push({ message: `请先明确选择当前${role === 'tech' ? '需求文件' : '产品规范'}版本。` });
    }
  }
  const sources = researchCase.sources.filter(source => isCurrentSource(source, selection));
  const sourceIds = new Set(sources.map(source => source.id));
  for (const row of rows.values()) {
    if (!row.source_ids.length || row.source_ids.some(id => !sourceIds.has(id))) {
      blockers.push({ message: `「${row.title}」缺少有效的当前来源，请先核对资料。`, requirementId: row.id });
    }
    if ('status' in row && (row.status === 'conflict' || row.status === 'rejected')) {
      blockers.push({ message: `「${row.title}」仍有冲突或拒绝项，请先核对。`, requirementId: row.id });
    }
  }

  for (const record of researchCase.clarifications ?? []) {
    if (record.required && record.status !== 'adopted') {
      const row = rows.get(record.requirement_id);
      blockers.push({ message: row ? `「${row.title}」的必需澄清尚未采用，请先处理。` : '必需澄清尚未采用，请先处理。', requirementId: row?.id });
    }
  }

  const batch = researchCase.requirement_recommendations;
  const explicitResults = researchCase.business_lifecycle?.policy_version === 'v2';
  if (explicitResults) {
    for (const row of rows.values()) if (!requirementActualResult(researchCase, row)) {
      blockers.push({ message: `「${row.title}」尚无明确采用的实际结果，请完成规范核对或办理并采用澄清。`, requirementId: row.id });
    }
  } else if (batch) {
    const actionable = batch.items.filter(item => item.status !== 'not_found');
    const current = batch.status === 'current' && batch.input_revision === researchCase.input_revision
      && Object.keys(batch.source_hashes).length === sources.length
      && sources.every(source => batch.source_hashes[source.id] === source.sha256);
    if (actionable.length && !current) {
      blockers.push({ message: '规范建议批次或来源已变化，请先重新核对规范建议。' });
    } else for (const item of actionable) {
      const row = rows.get(item.requirement_id);
      if (!(row && requirementActualResult(researchCase, row))) {
        blockers.push({ message: `「${row?.title ?? '需求'}」的规范建议尚未处理，请填写决定或采用澄清结果。`, requirementId: row?.id });
      }
    }
  }

  for (const row of rows.values()) {
    const content = (requirementActualResult(researchCase, row)?.value ?? row.content).trim();
    if (isUnresolvedRequirementValue(content)) {
      blockers.push({ message: `「${row.title}」缺少明确采用值，请先完成需求澄清。`, requirementId: row.id });
    }
  }
  return blockers;
}
