/** 生成条件检查——从原 SPA collectReadinessIssues 原样迁移。 */
import type { ProductType, ModelItem, TemplateEditPlan } from '../types';

export interface FormState {
  productType: string;
  productDomain: string;
  developmentProcess: string;
  coverPhase: string;
  productSeries: string;
  organizationScope: string;
  templateInstruction: string;
  templateEditConfirmed: boolean;
}

export interface ReadinessDeps {
  productCatalog: ProductType[];
  modelCatalog: ModelItem[];
  selectedModelKey: string;
  selectedModelReady: boolean | null;
  backendHealthReady: boolean | null;
  backendReadyForGeneration: boolean | null;
  localDefaultsReady: boolean;
  filesTech: File | null;
  filesSpec: File | null;
  templateEditPlan: TemplateEditPlan | null;
}

export interface ReadinessDetail {
  hasProduct: boolean;
  productEnabled: boolean;
  hasDomain: boolean;
  hasProcess: boolean;
  hasPhase: boolean;
  hasSeries: boolean;
  hasScope: boolean;
  hasModel: boolean;
  hasPairFiles: boolean;
  useLocalDefaults: boolean;
  templatePlanOk: boolean;
  templateConfirmOk: boolean;
  backendOk: boolean;
}

export interface ReadinessResult {
  ready: boolean;
  issues: string[];
  useLocalDefaults: boolean;
  detail: ReadinessDetail;
}

export function collectReadinessIssues(
  form: FormState,
  deps: ReadinessDeps,
): ReadinessResult {
  const issues: string[] = [];
  const product = deps.productCatalog.find((item) => item.value === form.productType);
  const selectedModel = deps.modelCatalog.find(
    (item) =>
      `${item.provider}|${item.name}|${item.id}` ===
      `${selectedModelKeyParts(deps.selectedModelKey).provider}|${selectedModelKeyParts(deps.selectedModelKey).name}|${selectedModelKeyParts(deps.selectedModelKey).id}`,
  );
  const hasUploadedFile = !!deps.filesTech || !!deps.filesSpec;
  const hasPairFiles = !!deps.filesTech && !!deps.filesSpec;
  const useLocalDefaults = deps.localDefaultsReady && !hasUploadedFile;
  const editReady =
    !form.templateInstruction ||
    (deps.templateEditPlan && form.templateEditConfirmed);

  if (!form.productType) issues.push('请选择产品类型');
  if (form.productType && product?.enabled === false) issues.push('该产品类型当前模板未就绪');
  if (!form.productDomain) issues.push('请选择质量管理体系分类');
  if (!form.developmentProcess) issues.push('请选择研制流程分类');
  if (!form.coverPhase) issues.push('请选择封面研制阶段（F/C/S/D）');
  if (!form.productSeries) issues.push('请填写产品系列');
  if (!form.organizationScope) issues.push('请选择产品归属范围');
  if (!selectedModel) issues.push('请选择语义路由模型');
  if (!hasPairFiles && !useLocalDefaults) issues.push('请上传需求文件和产品规范，或使用本机内置样例');
  if (form.templateInstruction && !deps.templateEditPlan) issues.push('模板提示词已填写，但尚未预览章节变更');
  if (form.templateInstruction && deps.templateEditPlan && !form.templateEditConfirmed)
    issues.push('请确认模板章节变更后再生成');
  if (selectedModel && deps.selectedModelReady === false) issues.push('当前所选模型尚未配置调用凭据');
  else if (deps.backendHealthReady === false) issues.push('后台当前不可生成，请先处理模型连接或受控目录问题');
  if (!editReady) issues.push('模板章节变更尚未确认');

  const ready = issues.length === 0;
  return {
    ready,
    issues,
    useLocalDefaults,
    detail: {
      hasProduct: !!form.productType,
      productEnabled: product?.enabled !== false,
      hasDomain: !!form.productDomain,
      hasProcess: !!form.developmentProcess,
      hasPhase: !!form.coverPhase,
      hasSeries: !!form.productSeries,
      hasScope: !!form.organizationScope,
      hasModel: !!selectedModel,
      hasPairFiles,
      useLocalDefaults,
      templatePlanOk: !form.templateInstruction || !!deps.templateEditPlan,
      templateConfirmOk: !form.templateInstruction || form.templateEditConfirmed,
      backendOk: deps.backendReadyForGeneration !== false,
    },
  };
}

/** 将 "provider|name|id" 格式的 select value 拆回字段。 */
function selectedModelKeyParts(key: string): { provider: string; name: string; id: string } {
  if (!key) return { provider: '', name: '', id: '' };
  const parts = key.split('|');
  return {
    provider: parts[0] ? decodeURIComponent(parts[0]) : '',
    name: parts[1] ? decodeURIComponent(parts[1]) : '',
    id: parts[2] ? decodeURIComponent(parts[2]) : '',
  };
}
