/** 全局类型定义——与后端 /api 响应结构一一对应。 */

// ── 产品目录 ──────────────────────────────────────────
export interface ProductDomain {
  value: string;
  label: string;
}

export interface ProductType {
  value: string;
  label: string;
  enabled: boolean;
  configured_enabled?: boolean;
  template_label?: string;
  integration_status?: 'available' | 'configured_pending_regression' | 'missing_template';
  unavailable_reason?: string;
  domains: ProductDomain[];
}

export interface ProductCatalog {
  product_types: ProductType[];
}

// ── 模型目录 ──────────────────────────────────────────
export interface ModelItem {
  provider: string;
  name: string;
  id: string;
  vendor: string;
  configured: boolean;
}

export interface RawModelItem {
  provider?: string;
  model?: string;
  name?: string;
  id?: string;
  vendor?: string;
  configured?: boolean;
}

export interface ModelCatalogResponse {
  success: boolean;
  models: RawModelItem[];
  error?: string;
}

export interface ModelStatusResponse {
  configured: boolean;
  provider?: string;
  endpoint?: string;
  model?: string;
  source?: string;
  app_id_configured?: boolean;
  tenant_id_configured?: boolean;
  model_id_configured?: boolean;
}

// ── 任务状态 ──────────────────────────────────────────
export type JobStatus = 'pending' | 'running' | 'done' | 'blocked' | 'error' | 'cancelled' | 'cancelling';

export interface JobMeta {
  product_type?: string;
  selected_product_type_label?: string;
  product_domain?: string;
  product_domain_label?: string;
  development_process?: string;
  product_series?: string;
  organization_scope?: string;
  profile?: string;
  output_name?: string;
  saved_path?: string;
  qa_ok?: boolean | null;
  llm_model?: string;
  use_llm?: boolean;
  image_warning_count?: number;
  stats?: {
    drawing_count?: number;
    media_count?: number;
    para_deleted?: number;
    red_cleared?: number;
    hl_cleared?: number;
  };
  gate_result?: GateResult | null;
  configured_qa_gate?: GateResult | null;
  semantic_integrity_gate?: GateResult | null;
  delivery_gate_result?: GateResult | null;
  input_normalization?: Record<string, { method?: string; requires_review?: boolean; evidence_path?: string; error?: string }>;
  source_review_required?: boolean;
}

export interface GateResult {
  passed?: boolean | null;
  deliverable?: boolean | null;
  categories?: Record<string, string[]>;
  warnings?: string[];
}

export interface JobResult {
  meta?: JobMeta;
  warnings?: string[];
  error?: string;
  delivery_status?: string;
}

export interface IndicatorCandidate {
  value?: string;
  display_value?: string;
  value_kind?: string;
  qualifiers?: Record<string, string>;
  scope?: string;
  condition?: string;
  comparison_status?: string;
  comparison_note?: string;
}

export interface IndicatorDecision {
  indicator_name: string;
  manual_review_required: boolean;
  user_requirement?: string;
  reason?: string;
  status?: string;
  numeric_status?: string;
  adopted_requirement?: string;
  candidate_comparisons?: IndicatorCandidate[];
}

export interface IndicatorReview {
  jid: string;
  parent_jid?: string;
  can_clarify: boolean;
  unavailable_reason?: string;
  indicator_clarifications: Record<string, string>;
  comparison_decisions: IndicatorDecision[];
  manual_review_required: IndicatorDecision[];
}

export interface JobStatusResponse {
  status: JobStatus;
  stage?: string;
  log?: string[];
  log_count?: number;
  log_offset?: number;
  error?: string;
  result?: JobResult;
}

export type SSEDataType = 'log' | 'heartbeat' | 'done' | 'blocked' | 'error' | 'cancelled';

export interface SSEMessage {
  type: SSEDataType;
  msg?: string;
  stage?: string;
  status?: string;
  elapsed?: number;
  log_count?: number;
  jid?: string;
  result?: JobResult;
}

// ── 历史记录 ──────────────────────────────────────────
export interface HistoryItem {
  jid?: string;
  created_at?: string;
  status: string;
  error?: string;
  product?: string;
  profile?: string;
  qa_ok?: boolean | null;
  delivery_status?: string;
  drawing_count?: number;
  media_count?: number;
  image_warning_count?: number;
  output_name?: string;
  saved_path?: string;
  product_type_id?: string;
  product_domain_id?: string;
  development_process?: string;
  organization_scope?: string;
  cover_phase?: string;
  product_series?: string;
  model_provider?: string;
  model_name?: string;
  model_id?: string;
}

// ── 预检 ──────────────────────────────────────────────
export interface PrecheckFile {
  message?: string;
  product?: string;
  profile?: string;
  tokens?: string[];
  name?: string;
  score?: number;
  ok?: boolean;
}

export interface PrecheckResponse {
  files?: Record<string, PrecheckFile | undefined>;
  selection?: {
    product_type: string;
    product_domain: string;
    template: string;
  } | null;
  consistency?: PrecheckFile;
  suggestion?: PrecheckFile;
}

// ── 规则与模板 ────────────────────────────────────────
export interface RulesSummary {
  semantic_categories?: number;
  product_catalog?: { enabled_types?: number };
  template_onboarding?: { auto_publish?: boolean };
  chapter_numbers_are_identity?: boolean;
  source_body_generation?: boolean;
  mode?: string;
}

export interface TemplateItem {
  product_type: string;
  product_domain: string;
  product_type_id: string;
  product_domain_id: string;
  template: string;
  filename: string;
  version: string;
  version_id: string;
  updated_at: string;
  sha256: string;
  revision: string;
}

export interface TemplateVersion {
  id: string;
  product: string;
  domain: string;
  filename: string;
  version: string;
  note: string;
  actor: string;
  created_at: string;
  activated_at?: string;
  base_revision: string;
  status: 'active' | 'historical' | 'ready' | 'invalid';
  warnings: string[];
  validation: {
    passed: boolean;
    problems: string[];
    heading_count: number;
    table_count: number;
    headings_added: string[];
    headings_removed: string[];
  };
}

export interface TemplateVersionHistory {
  current: TemplateItem;
  versions: TemplateVersion[];
}

export interface TemplateCandidate {
  candidate_id: string;
  product_type?: string;
  product_label?: string;
  domain?: string;
  domain_label?: string;
  version?: string;
  status?: string;
  machine_validation_passed?: boolean;
  slot_count?: number;
  unresolved_count?: number;
}

export interface TemplateEditOperation {
  target_slot: string;
  anchor_slot?: string;
  operation?: string;
  new_title?: string;
  action?: string;
  title?: string;
}

export interface TemplateEditPlan {
  outline_before?: { id: string; title: string; semantic_path?: string }[];
  operations?: TemplateEditOperation[];
  parser?: string;
  [key: string]: unknown;
}

export interface CapabilitiesResponse {
  source_inputs?: Record<string, { status: string }>;
}

// ── 后端健康 ──────────────────────────────────────────
export interface HealthResponse {
  ready_for_generation?: boolean;
  llm?: { configured?: boolean };
  runtime?: {
    profile?: string;
    semantic_retrieval?: boolean;
    semantic_rerank?: boolean;
  };
  build_fingerprint?: {
    build_id?: string;
    pipeline_version?: string;
  };
}

// ── 本地默认 ──────────────────────────────────────────
export interface LocalDefaultItem {
  exists: boolean;
  path: string;
}

// ── 草稿 ──────────────────────────────────────────────
export interface DraftPayload {
  product_type?: string;
  product_domain?: string;
  development_process?: string;
  cover_phase?: string;
  product_series?: string;
  organization_scope?: string;
  model_provider?: string;
  model_name?: string;
  model_id?: string;
  template_instruction?: string;
  fail_on_regression?: boolean;
  saved_at?: string;
}
