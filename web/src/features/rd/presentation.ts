import type { ContextKey, ProjectContext, ResearchCase, Source, StageId } from './types';

export const STAGES: Array<{ id: StageId; title: string; short: string; description: string }> = [
  { id: 'input', title: '资料输入与需求澄清', short: '资料输入', description: '归集来源文件、澄清六项业务参数，保留尚未解析的空值。' },
  { id: 'requirements', title: '需求确认', short: '需求确认', description: '记录可追溯的需求，由实际负责人确认需求和证据。' },
  { id: 'selection', title: '选型决策', short: '选型决策', description: '依据需求和选型证据，决定直接选用、改型或新研。' },
  { id: 'planning', title: '直接选用／改型／新研', short: '分类决定落实', description: '按产品研制分类开展阶段工作；任务书编制策略独立记录。' },
  { id: 'design', title: '方案与零配件设计', short: '方案设计', description: '归集方案及零配件设计资料，以实际工程决定推进。' },
  { id: 'verification', title: '验证及审签', short: '验证审签', description: '上传验证和审签依据，记录真实决定；系统不会代替专业审签。' },
  { id: 'delivery', title: '交付与反馈', short: '交付反馈', description: '归集交付成果和反馈依据，再记录阶段决定。' },
  { id: 'knowledge', title: '知识治理与再次复用', short: '知识治理', description: '核对可复用成果和知识治理证据，发布仍由实际治理流程负责。' },
];
export const CONTEXT_FIELDS: Array<{ key: ContextKey; label: string; placeholder: string }> = [
  { key: 'product_type', label: '产品类型', placeholder: '例如：连接器' },
  { key: 'product_domain', label: '质量管理体系分类', placeholder: '按来源资料填写' },
  { key: 'development_process', label: '研制流程', placeholder: '例如：全新 / 改型I' },
  { key: 'cover_phase', label: '封面阶段', placeholder: '例如：F / C / S / D' },
  { key: 'product_series', label: '产品系列', placeholder: '按来源资料填写' },
  { key: 'organization_scope', label: '组织范围', placeholder: '例如：non_central_research' },
];
export const EMPTY_CONTEXT: ProjectContext = { product_type: '', product_domain: '', development_process: '', cover_phase: '', product_series: '', organization_scope: '' };
export const ROUTES = { direct: '直接选用', modification: '改型', new: '新研' };
export const COMPOSITION_ROUTES: Record<string, string> = { direct: '直接使用现有模板', adapt: '适配现有模板', new: '新建任务书模板' };
export const routeTitle = (axis: string, value: string) => (axis === 'product' ? ROUTES[value as keyof typeof ROUTES] : COMPOSITION_ROUTES[value]) ?? value;
export const isCurrentSource = (source: Source, selection: ResearchCase['source_selection']) => source.role === 'reference' || selection?.[source.role] === source.id;
export const STATUS: Record<string, string> = { validated: '验证通过', reviewed: '已审核', candidate: '候选', rolled_back: '已回退', draft: '草稿', submitted: '已提交', pending: '待执行', running: '执行中', completed: '已完成', blocked: '已阻塞', failed: '执行失败', cancelled: '已取消', published: '已发布', retired: '已停用', approved: '已通过', rejected: '未通过' };
export const stageTitle = (id: string) => STAGES.find(stage => stage.id === id)?.title ?? id;
export const statusTitle = (value?: string) => value ? STATUS[value] ?? value : '待执行';
export const formatTime = (value?: string) => value && !Number.isNaN(new Date(value).getTime()) ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '—';
export const formatSize = (value: number) => value >= 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(value / 1024)} KB`;
export const messageOf = (error: unknown) => error instanceof Error ? error.message : '操作未完成，请重试。';
export const readable = (value: unknown): string => typeof value === 'string' ? value : JSON.stringify(value, null, 2) ?? '—';
