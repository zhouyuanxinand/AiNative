/** 模板管理与规则中心接口。 */
import type {
  RulesSummary,
  TemplateItem,
  TemplateCandidate,
  TemplateEditPlan,
  CapabilitiesResponse,
} from '../types';
import { getJSON, postForm } from './client';

export function loadRulesSummary(): Promise<RulesSummary> {
  return getJSON<RulesSummary>('/api/rules/summary');
}

export function loadTemplateDirectory(): Promise<TemplateItem[]> {
  return getJSON<TemplateItem[]>('/api/templates');
}

export function loadTemplateCandidates(): Promise<TemplateCandidate[]> {
  return getJSON<TemplateCandidate[]>('/api/templates/candidates');
}

export function loadCapabilities(): Promise<CapabilitiesResponse> {
  return getJSON<CapabilitiesResponse>('/api/capabilities');
}

export function postCandidateAction(
  candidateId: string,
  action: string,
  fields: Record<string, string | boolean>,
): Promise<Record<string, unknown>> {
  const body = new FormData();
  Object.entries(fields).forEach(([key, value]) => body.append(key, String(value)));
  return postForm(`/api/templates/candidates/${encodeURIComponent(candidateId)}/${action}`, body);
}

export function onboardTemplate(fd: FormData): Promise<Record<string, unknown>> {
  return postForm('/api/templates/onboard', fd);
}

export function previewTemplateEdit(fd: FormData): Promise<TemplateEditPlan> {
  return postForm('/api/template_edit/preview', fd);
}
