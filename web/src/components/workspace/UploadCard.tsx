/** 上传卡片——业务选择 + 拖拽上传 + 模型选择 + 运行按钮 + 工具栏。 */
import { useTaskbook } from '../../hooks/useTaskbook';
import { useDraft } from '../../hooks/useDraft';
import { DropZone } from './DropZone';
import { StyledSelect, type StyledSelectOption } from '../ui/StyledSelect';
import { modelSelectionKey } from '../../lib/model';
import { collectReadinessIssues } from '../../lib/readiness';
import type { TemplateEditPlan } from '../../types';

type ModelCatalogState = 'loading' | 'ready' | 'empty' | 'error';

export function UploadCard({
  modelCatalogState,
  onRetryModelCatalog,
}: {
  modelCatalogState: ModelCatalogState;
  onRetryModelCatalog: () => void;
}) {
  const {
    form,
    setFormField,
    productCatalog,
    modelCatalog,
    selectedModelKey,
    setSelectedModelKey,
    selectedModelReady,
    backendHealthReady,
    backendReadyForGeneration,
    localDefaultsReady,
    localDefaultFiles,
    files,
    uploadedFiles,
    templateEditPlan,
    setTemplateEditPlan,
    templateEditStatus,
    setTemplateEditStatus,
    templatePreviewLoading,
    baselineDocx,
    setBaselineDocx,
    baselineJson,
    setBaselineJson,
    validationTouched,
    addToValidationTouched,
    validationSubmitted,
    setValidationSubmitted,
    uiMode,
    setUIMode,
    showToast,
  } = useTaskbook();
  const { saveDraft, updateSavedSelectionState } = useDraft();

  const product = productCatalog.find((item) => item.value === form.productType);

  const productOptions: StyledSelectOption[] = productCatalog.length === 0
    ? [{ value: '', label: '正在读取产品目录…' }]
    : productCatalog.map((item) => ({
        value: item.value,
        label:
          item.enabled === false
            ? `${item.label}（${item.integration_status === 'configured_pending_regression' ? '待样例验收' : '模板待补充'}）`
            : item.configured_enabled === false
              ? `${item.label}（暂时放开）`
              : item.label,
        disabled: item.enabled === false,
        title: item.unavailable_reason || item.template_label || '',
      }));
  const domainOptions: StyledSelectOption[] = (product?.domains || []).map((domain) => ({
    value: domain.value,
    label: domain.label,
  }));
  const processOptions: StyledSelectOption[] = [
    { value: '全新', label: '全新' },
    { value: '改型I', label: '改型I' },
    { value: '改型II', label: '改型II' },
    { value: '改型III', label: '改型III' },
  ];
  const coverPhaseOptions: StyledSelectOption[] = [
    { value: '', label: '请选择 F / C / S / D' },
    { value: 'F', label: 'F' },
    { value: 'C', label: 'C' },
    { value: 'S', label: 'S' },
    { value: 'D', label: 'D' },
  ];
  const organizationOptions: StyledSelectOption[] = [
    { value: 'non_central_research', label: '非中央研究院产品' },
    { value: 'central_research', label: '中央研究院产品' },
  ];
  const modelOptions: StyledSelectOption[] = modelCatalog.length === 0
    ? [{ value: '', label: modelCatalogState === 'loading' ? '正在读取模型目录…' : '暂无可用模型' }]
    : modelCatalog.map((item) => {
        const key = modelSelectionKey(item);
        return {
          value: key,
          label: `${item.vendor ? `${item.vendor} · ` : ''}${item.name}`,
          title: item.id ? `模型 ID：${item.id}` : item.name,
        };
      });
  const uiModeOptions: StyledSelectOption[] = [
    { value: 'compact', label: '新手模式' },
    { value: 'expert', label: '专家模式' },
  ];

  // 就绪检查
  const readiness = collectReadinessIssues(form, {
    productCatalog,
    modelCatalog,
    selectedModelKey,
    selectedModelReady,
    backendHealthReady,
    backendReadyForGeneration,
    localDefaultsReady,
    filesTech: files.tech,
    filesSpec: files.spec,
    templateEditPlan,
  });

  const shouldShowInvalid = (id: string, invalid: boolean, force = false) =>
    Boolean(invalid && (force || validationSubmitted || validationTouched.has(id)));

  const d = readiness.detail;
  const fieldInvalid = (id: string, invalid: boolean) =>
    shouldShowInvalid(id, invalid) ? 'invalid-field' : '';

  const invalidateTemplatePlan = () => {
    setTemplateEditPlan(null);
    setTemplateEditStatus('');
    setFormField('templateEditConfirmed', false);
  };

  const onModelChange = (value: string) => {
    setSelectedModelKey(value);
    addToValidationTouched('llm-model');
  };

  const savedSelectionStatus = updateSavedSelectionState();

  const onRun = () => {
    setValidationSubmitted(true);
    if (!readiness.ready) {
      showToast('生成条件未满足，请先处理提示项', 'warn');
      return;
    }
    // 触发提交由 App 层处理
    window.dispatchEvent(new CustomEvent('taskbook:submit'));
  };

  return (
    <div className="card" id="upload-card" style={{ display: undefined }}>
      <h2>
        <span className="section-kicker">STEP 01</span>选择业务类型并上传来源文件
      </h2>
      <div className="business-selects">
        <label>
          产品类型<span className="required-mark" aria-hidden="true">*</span>
          <StyledSelect
            id="product-type"
            value={form.productType}
            options={productOptions}
            invalid={shouldShowInvalid('product-type', !d.hasProduct || !d.productEnabled)}
            onChange={(value) => {
              const nextProduct = productCatalog.find((item) => item.value === value);
              setFormField('productType', value);
              setFormField(
                'productDomain',
                nextProduct?.domains.some((item) => item.value === form.productDomain)
                  ? form.productDomain
                  : nextProduct?.domains[0]?.value || '',
              );
              addToValidationTouched('product-type');
              invalidateTemplatePlan();
            }}
            required
          />
        </label>
        <label>
          质量管理体系分类<span className="required-mark" aria-hidden="true">*</span>
          <StyledSelect
            id="product-domain"
            value={form.productDomain}
            options={domainOptions}
            invalid={shouldShowInvalid('product-domain', !d.hasDomain)}
            onChange={(value) => {
              setFormField('productDomain', value);
              addToValidationTouched('product-domain');
            }}
            required
          />
        </label>
        <label>
          研制流程分类<span className="required-mark" aria-hidden="true">*</span>
          <StyledSelect
            id="development-process"
            value={form.developmentProcess}
            options={processOptions}
            invalid={shouldShowInvalid('development-process', !d.hasProcess)}
            onChange={(value) => {
              setFormField('developmentProcess', value);
              addToValidationTouched('development-process');
            }}
            required
          />
        </label>
        <label>
          封面研制阶段<span className="required-mark" aria-hidden="true">*</span>
          <StyledSelect
            id="cover-phase"
            value={form.coverPhase}
            options={coverPhaseOptions}
            invalid={shouldShowInvalid('cover-phase', !d.hasPhase)}
            onChange={(value) => {
              setFormField('coverPhase', value);
              addToValidationTouched('cover-phase');
            }}
            required
          />
        </label>
        <label>
          产品系列<span className="required-mark" aria-hidden="true">*</span>
          <input
            id="product-series"
            className={fieldInvalid('product-series', !d.hasSeries)}
            maxLength={160}
            value={form.productSeries}
            onChange={(e) => {
              setFormField('productSeries', e.target.value);
            }}
            onBlur={() => addToValidationTouched('product-series')}
            placeholder="用于故障模式库精确匹配，如 ICTS-BGA472"
            required
          />
        </label>
        <label>
          产品归属范围<span className="required-mark" aria-hidden="true">*</span>
          <StyledSelect
            id="organization-scope"
            value={form.organizationScope}
            options={organizationOptions}
            invalid={shouldShowInvalid('organization-scope', !d.hasScope)}
            onChange={(value) => {
              setFormField('organizationScope', value);
              addToValidationTouched('organization-scope');
            }}
            required
          />
        </label>
        <div className="managed-tip">
          <span>模板由后台受控目录自动匹配，用户无需上传。</span>
          <span>
            <span className="template-status" id="template-status">
              {product
                ? product.enabled === false
                  ? product.unavailable_reason || '真实模板待配置'
                  : `已匹配：${product.template_label || '受控模板'}`
                : productCatalog.length
                  ? '请选择产品类型'
                  : '正在读取模板目录…'}
            </span>
            <br />
            <small className="template-status-detail" style={{ fontWeight: 600 }} />
          </span>
        </div>
      </div>
      <div className="drop-row">
        <DropZone fileKey="tech" />
        <DropZone fileKey="spec" />
      </div>

      {/* 可选模板编辑 */}
      <div className="template-editor expert-only">
        <h3>可选：用提示词调整本次任务的模板章节</h3>
        <p>只允许新增、重命名、移动或删除章节标题；系统按无编号标题树定位，先预览再确认。内置模板不会被修改，LLM 也不会生成正文。</p>
        <textarea
          id="template-edit-instruction"
          value={form.templateInstruction}
          onChange={(e) => {
            setFormField('templateInstruction', e.target.value);
            addToValidationTouched('template-edit-instruction');
            invalidateTemplatePlan();
          }}
          placeholder='示例：把"其他要求"改为"顾客补充要求"；在"需提交文件"后新增"验收资料"'
        />
        <div className="template-edit-actions">
          <button
            type="button"
            className="btn-preview"
            onClick={() => window.dispatchEvent(new CustomEvent('taskbook:preview-edit'))}
            disabled={templatePreviewLoading}
          >
            {templatePreviewLoading ? '正在解析…' : '预览章节变更'}
          </button>
          <span id="template-edit-status">{templateEditStatus}</span>
        </div>
        {templateEditPlan && (
          <>
            <div
              className="template-plan-preview"
              id="template-plan-preview"
              style={{ display: 'block', whiteSpace: 'pre-wrap' }}
            >
              {formatTemplatePlan(templateEditPlan)}
            </div>
            <label
              className="template-confirm"
              id="template-confirm-wrap"
              style={{ display: 'block' }}
            >
              <input
                type="checkbox"
                id="template-edit-confirmed"
                checked={form.templateEditConfirmed}
                onChange={(e) => setFormField('templateEditConfirmed', e.target.checked)}
              />{' '}
              我已核对以上章节变更，仅应用到本次任务副本
            </label>
          </>
        )}
      </div>

      {/* 回归基线 */}
      <div className="template-editor expert-only">
        <h3>可选：稳定版本回归基线</h3>
        <p>上传上次确认正确的 DOCX；可同时上传对应语义证据 JSON。默认只生成差异报告，勾选后差异会阻断正式交付。</p>
        <div className="template-edit-actions" style={{ flexWrap: 'wrap' }}>
          <label>
            DOCX 基线{' '}
            <input
              type="file"
              id="baseline-docx"
              accept=".docx"
              onChange={(event) => setBaselineDocx(event.target.files?.[0] || null)}
            />
            {baselineDocx && <small title={baselineDocx.name}>已选：{baselineDocx.name}</small>}
          </label>
          <label>
            证据 JSON{' '}
            <input
              type="file"
              id="baseline-json"
              accept=".json"
              onChange={(event) => setBaselineJson(event.target.files?.[0] || null)}
            />
            {baselineJson && <small title={baselineJson.name}>已选：{baselineJson.name}</small>}
          </label>
          <label>
            <input
              type="checkbox"
              id="fail-on-regression"
              checked={form.failOnRegression}
            onChange={(e) => setFormField('failOnRegression', e.target.checked)}
            />{' '}
            差异阻断交付
          </label>
        </div>
      </div>

      <div className="opts">
        <div className="model-picker">
          <label htmlFor="llm-model">语义路由模型</label>
          <StyledSelect
            id="llm-model"
            value={selectedModelKey}
            options={modelOptions}
            invalid={shouldShowInvalid('llm-model', !d.hasModel)}
            aria-label="语义路由模型"
            onChange={onModelChange}
            disabled={modelCatalog.length === 0}
          />
          <span className="model-picker-status" id="model-picker-status" role="status" aria-live="polite">
            {modelCatalogState === 'loading'
              ? '正在读取可用模型…'
              : modelCatalogState === 'error'
                ? '模型目录读取失败，请检查服务凭证和网络连接。'
                : modelCatalogState === 'empty'
                  ? '服务已返回空模型目录，请检查当前凭证可用的模型。'
              : selectedModelReady === null
                ? '正在检查模型调用配置…'
                : selectedModelReady
                  ? `已就绪 · ${modelCatalog.find((item) => modelSelectionKey(item) === selectedModelKey)?.vendor || modelCatalog.find((item) => modelSelectionKey(item) === selectedModelKey)?.provider || '当前模型'}`
                  : '调用凭据未配置'}
          </span>
          {(modelCatalogState === 'error' || modelCatalogState === 'empty') && (
            <button type="button" className="ux-btn model-picker-retry" onClick={onRetryModelCatalog}>
              重新读取模型目录
            </button>
          )}
        </div>
        <button
          className="btn-run"
          id="btn-run"
          onClick={onRun}
          disabled={!readiness.ready}
          title={readiness.ready ? '条件满足，可开始生成' : readiness.issues.join('；')}
        >
          开始受控生成
        </button>
      </div>
      <div className="ux-tools">
        <div className="ux-actions">
          <button
            type="button"
            className="ux-btn"
            id="save-selection"
            onClick={() => saveDraft(true)}
          >
            保存当前选择
          </button>
          <button
            type="button"
            className="ux-btn"
            id="restore-selection"
            onClick={() => window.dispatchEvent(new CustomEvent('taskbook:restore-draft'))}
          >
            恢复上次选择
          </button>
          <button
            type="button"
            className="ux-btn"
            id="clear-selection"
            onClick={() => window.dispatchEvent(new CustomEvent('taskbook:clear-draft'))}
          >
            清空已保存选择
          </button>
          <span className="ux-saved-status" id="saved-selection-status" role="status">
            {savedSelectionStatus}
          </span>
        </div>
        <div className="mode-wrap">
          <span className="mode-label">界面模式</span>
          <StyledSelect
            id="ui-mode"
            value={uiMode}
            options={uiModeOptions}
            aria-label="界面模式"
            onChange={(value) => {
              const mode = value === 'expert' ? 'expert' : 'compact';
              setUIMode(mode);
              showToast(mode === 'expert' ? '已切换到专家模式' : '已切换到新手模式', 'ok');
            }}
          />
        </div>
        <div className="ux-note">快捷键：Ctrl/⌘ + Enter 直接发起受控生成（满足条件时）。</div>
      </div>
      <ReadyHints ready={readiness.ready} issues={readiness.issues} useLocalDefaults={readiness.useLocalDefaults} />
      {localDefaultsReady && (
        <div className="local-bar" id="local-bar">
          <div className="local-bar-row">
            <div>
              <strong>本机验收样例已就绪</strong>
              <span id="local-files">{localDefaultFiles}</span>
            </div>
            <button className="btn-demo" onClick={() => window.dispatchEvent(new CustomEvent('taskbook:submit-local'))}>
              运行内置样例
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ReadyHints({ ready, issues, useLocalDefaults }: { ready: boolean; issues: string[]; useLocalDefaults: boolean }) {
  const { validationSubmitted, validationTouched } = useTaskbook();
  if (ready) {
    const text = useLocalDefaults
      ? '当前已满足生成条件，将使用本机内置样例文件进行受控生成。'
      : '当前已满足生成条件：可以点击"开始受控生成"。';
    return <div className="ready-hints ok" id="ready-hints">{text}</div>;
  }
  if (!validationSubmitted && validationTouched.size === 0) {
    return <div className="ready-hints" id="ready-hints">请先完成必填业务信息，并上传需求文件与产品规范。</div>;
  }
  return (
    <div className="ready-hints err" id="ready-hints">
      {issues.map((item, i) => (
        <div key={i}>
          {i + 1}. {item}
          {i < issues.length - 1 && <br />}
        </div>
      ))}
    </div>
  );
}

function formatTemplatePlan(plan: TemplateEditPlan): string {
  const titles = Object.fromEntries(
    (plan.outline_before || []).map((item) => [item.id, item.semantic_path || item.title]),
  );
  const labels: Record<string, string> = {
    rename: '重命名',
    add_before: '前置新增',
    add_after: '后置新增',
    add_child: '新增子章节',
    move_before: '移动到前面',
    move_after: '移动到后面',
    move_child: '移动为子章节',
    delete: '删除',
  };
  const lines = (plan.operations || []).map((item, index) => {
    const operation = item.operation || item.action || '';
    const target = titles[item.target_slot] || '';
    const anchor = item.anchor_slot ? titles[item.anchor_slot] || '' : '';
    const newTitle = item.new_title || item.title || '';
    const suffix = newTitle ? ` → ${newTitle}` : anchor ? ` → ${anchor}` : '';
    return `${index + 1}. ${labels[operation] || operation || '章节调整'}：${target || anchor}${suffix}`;
  });
  return `解析方式：${plan.parser === 'llm' ? 'LLM 结构规划' : '受控指令解析'}${
    lines.length ? `\n${lines.join('\n')}` : '\n未产生章节变更'
  }`;
}
