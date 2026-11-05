import type { Clarification } from './types';

/** Adoption creates a new requirement and input revision; the question retains its original versions. */
export function isCurrentClarification(record: Clarification, inputRevision?: number, requirementRevision?: number): boolean {
  const version = record.status === 'adopted' ? record.adoption : record;
  return !record.invalidated_at && !!version && inputRevision != null && requirementRevision != null
    && version.input_revision === inputRevision && version.requirement_revision === requirementRevision;
}
