export type StageId = 'input' | 'requirements' | 'selection' | 'planning' | 'design' | 'verification' | 'delivery' | 'knowledge';
export type CaseWorkspaceView = 'current' | 'process' | 'evidence';
export type RouteId = 'direct' | 'modification' | 'new';
export type CompositionRouteId = 'direct' | 'adapt' | 'new';
export type ContextKey = 'product_type' | 'product_domain' | 'development_process' | 'cover_phase' | 'product_series' | 'organization_scope';
export type ProjectContext = Record<ContextKey, string>;
export interface ModelSelection { provider: string; name: string; id: string }
export interface SourceEvidence { source_id: string; quote: string }
export interface SourceAnalysis {
  id: string; status: 'proposed' | 'adopted' | 'stale'; input_revision: number; adopted_input_revision?: number;
  created_at: string; source_hashes: Record<string, string>; model_selection: ModelSelection;
  context: Record<ContextKey, { value: string; status: 'proposed' | 'unresolved' | 'already_confirmed'; reason: string; evidence: SourceEvidence[]; adoption_kind?: 'refresh_source_refs' }>;
  requirements: Array<{ title: string; content: string; source_ids: string[]; evidence: SourceEvidence[] }>;
  warnings: string[];
}
export interface Source { id: string; role: 'tech' | 'spec' | 'reference'; name: string; sha256: string; size: number; version: number; created_at: string }
export interface Requirement { id: string; title: string; content: string; source_ids: string[]; created_at?: string; version?: number; revision?: number; history?: unknown[] }
export interface Decision { id?: string; kind?: 'route' | 'stage' | 'selection' | 'taskbook_scope' | 'requirement_confirmation' | 'engineering_stage'; stage?: StageId; verdict?: 'approved' | 'rejected'; axis?: 'product' | 'composition'; value?: string; rationale: string; source_ids?: string[]; artifact_ids?: string[]; created_at?: string; actor_id?: string; actor?: string; input_revision?: number; invalidated_at?: string; invalidated_reason?: string; scope?: string; bundle_id?: string; bundle_digest?: string; review_mode?: string; electronic_signature?: boolean }
export interface PlanNode { id: string; action_id: string; action_version: string; depends_on: string[]; required: boolean; status?: string; result?: Record<string, unknown>; attempt?: number; started_at?: string | null; completed_at?: string | null; ended_at?: string | null }
export interface Artifact { id: string; name: string; kind?: string; sha256?: string }
export interface Workpackage { id: string; definition_id: string; title: string; stage: StageId; status: string; plan_revision: number; nodes: PlanNode[]; snapshot?: Record<string, unknown>; run_id?: string; artifacts: Artifact[]; obligations: unknown[]; blocked_reasons: unknown[]; planned_start?: string | null; planned_end?: string | null; plan_note?: string; schedule_revision?: number; schedule_history?: Array<Record<string, unknown>>; started_at?: string | null; completed_at?: string | null; ended_at?: string | null }
export interface RouteDecision { value: string; rationale: string; source_ids: string[]; actor: string; created_at: string; comparison_id?: string; comparison_revision?: number; comparison_sha256?: string }
export interface Clarification { id: string; requirement_id: string; question: string; required: boolean; status: 'open' | 'answered' | 'adopted'; revision: number; input_revision: number; requirement_revision: number; source_ids: string[]; actor: string; created_at: string; answer: string | null; answer_source_ids: string[]; answered_by?: string | null; answered_at?: string | null; adoption?: { requirement_revision: number; requirement_content: string; actor: string; created_at: string } | null; history?: unknown[]; invalidated_at?: string; invalidated_reason?: string }
export interface ComparisonRow { requirement_id: string; assessment: 'match' | 'partial' | 'gap' | 'unknown'; candidate_value: string; reason: string; source_ids: string[] }
export interface Comparison { id: string; kind: 'product' | 'document'; title: string; status: 'manual_record'; revision: number; input_revision: number; sha256: string; source_ids: string[]; rows: ComparisonRow[]; statistics: { matches: number; total: number; partial: number; gap: number; unknown: number; match_ratio: number }; history?: unknown[]; invalidated_at?: string; invalidated_reason?: string }
export interface DeliveryRecord { id: string; status: 'manual_record'; outcome: 'accepted' | 'revision_required'; recipient: string; receipt: string; feedback: string; source_ids: string[]; artifact_ids: string[]; input_revision: number; actor: string; created_at: string; electronic_signature: false }
export interface ReuseCandidate { id: string; title: string; content: string; status: 'candidate'; scope: 'case'; published: false; source_ids: string[]; artifact_ids: string[]; input_revision: number; actor: string; created_at: string }
export interface ResearchWorkflowTemplate { id: string; version: string; title: string; status: string; product_route: string; nodes: string[] }
export interface TaskbookBinding { source_ids: string[]; id: string; revision: number; input_revision: number; workflow: ResearchWorkflowTemplate; document_template: Record<string, unknown>; scope: string; rationale: string; status: string; invalidated_at?: string; invalidated_reason?: string; fingerprint: string; adopted_at: string }
export interface EngineeringRecord { prerequisite_record_ids: string[]; id: string; node_id: string; binding_id: string; input_revision: number; verdict: string; summary: string; actor?: string; created_at?: string }
export interface ResearchCase { source_analysis?: SourceAnalysis; engineering_records?: EngineeringRecord[]; taskbook_binding?: TaskbookBinding | null; taskbook_binding_history?: TaskbookBinding[]; id: string; scenario_id: string; title: string; stage: StageId; status?: string; input_revision?: number; source_selection?: Partial<Record<'tech' | 'spec', string>>; context: Partial<ProjectContext>; model_selection?: ModelSelection; context_provenance?: Record<string, { kind: string; actor?: string; created_at?: string; source_ids?: string[]; evidence?: SourceEvidence[]; reason?: string }>; product_route: RouteDecision | null; composition_route: RouteDecision | null; sources: Source[]; requirements: Requirement[]; workpackages: Workpackage[]; decisions: Decision[]; warnings?: Array<{ code: string; message: string }>; clarifications?: Clarification[]; comparisons?: Comparison[]; deliveries?: DeliveryRecord[]; reuse_candidates?: ReuseCandidate[]; reuse_disposition?: Record<string, unknown> | null }
/** Manual project descriptions; customer and product master-data integrations are not connected. */
export interface ProjectProfile { brief: string; customer_name: string; product_name: string }
export interface Project extends Partial<ProjectProfile> { id: string; title: string; version: number; owner_id: string; members: unknown[]; cases: ResearchCase[]; events: Array<Record<string, unknown>>; created_at?: string; updated_at?: string }
export interface Action { id: string; version: string; name?: string; title?: string; description?: string; optional?: boolean; required?: boolean; evidence_mode?: string; kind?: string; [key: string]: unknown }
export interface WorkpackageDefinition { id: string; name?: string; title?: string; stage?: StageId; stages?: StageId[]; allowed_stages?: StageId[]; required_actions?: string[]; optional_actions?: string[]; description?: string; nodes?: PlanNode[]; version?: string }
export interface Catalog { research_workflow_templates?: ResearchWorkflowTemplate[]; stages: Array<{ id: StageId; name?: string; title?: string; description?: string }>; scenarios: Array<{ id: string; name?: string; title?: string; description?: string; status?: 'published'; initial_stage?: StageId; context_fields?: ContextKey[] }>; actions: Action[]; workpackage_definitions: WorkpackageDefinition[] }
export interface WorkspaceResource { id: string; kind: 'agent' | 'skill' | 'team'; name: string; description: string; configuration: Record<string, unknown>; version: number | string; status?: string; execution_mode?: string; executable?: boolean }
export interface WorkspaceResponse { resources: WorkspaceResource[]; can_manage?: boolean }
export interface BusinessLifecycle {
  policy_version: 'v2' | 'legacy_v1'; selection_order_id: string | null;
  rd_activation_state: 'not_started' | 'active' | 'needs_review' | 'historical_unverified';
  rd_project_code: string | null; current_requirement_baseline_id: string | null;
  current_selection_bundle_id: string | null; current_selection_decision_id: string | null;
  current_activation_id: string | null; current_taskbook_scope_decision_id: string | null;
  review_mode: string; required_policy_ref: string; local_review_enabled: boolean; can_record_decision?: boolean; can_confirm_requirements?: boolean;
}
export interface ReviewBundle {
  id: string; kind: 'selection' | 'taskbook_scope'; digest: string; input_revision: number;
  created_at?: string; invalidated_at?: string; invalidated_reason?: string; workpackage_id?: string;
  report?: { id: string; title: string; format: string; rows?: Array<Record<string, unknown>>; statistics?: Record<string, unknown>; product_route?: Record<string, unknown>; composition_route?: Record<string, unknown>; [key: string]: unknown };
  [key: string]: unknown;
}
export interface ParameterFact {
  value: string; status: 'adopted' | 'proposed' | 'conflict' | 'unresolved';
  evidence_status: 'current' | 'stale' | 'unverified'; reason: string;
  source_refs: Array<{ source_id: string; version?: number; sha256?: string }>;
  decision_ref?: string | Record<string, unknown> | null; rule_refs?: unknown[]; candidates?: unknown[];
}
export interface ResearchCase {
  business_lifecycle?: BusinessLifecycle; review_bundles?: ReviewBundle[];
  requirement_baselines?: Array<Record<string, unknown>>; rd_activations?: Array<Record<string, unknown>>;
  parameter_facts?: Partial<Record<ContextKey, ParameterFact>>;
}
export interface Workpackage { definition_version?: string; business_node_id?: string }
export interface WorkpackageDefinition { business_node_id?: string; lifecycle_policy_version?: string }
export type AssistantTarget = 'current' | 'sources' | 'requirements' | 'routes' | 'workpackages' | 'process' | 'artifacts' | 'history';
export interface AssistantMessage { id: string; seq: number; role: 'user' | 'assistant'; content: string; mode?: 'local_guidance' | 'model'; created_at: string; input_revision: number; answered_version: number; stale: boolean }
export interface AssistantResponse { messages: AssistantMessage[]; suggestions: Array<{ id: string; label: string; target: AssistantTarget }>; context: { stage: StageId; project_version: number; input_revision?: number }; history?: { total: number; limit: number; has_more: boolean; next_before: number | null; notice?: string }; reply?: AssistantMessage; navigation?: { target: AssistantTarget } }
