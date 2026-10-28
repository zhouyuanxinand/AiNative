/** 顶层应用壳：协调布局、表单、预检、任务生命周期与旧版兼容行为。 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { TaskbookProvider, useTaskbook, type TaskbookForm } from '../../hooks/useTaskbook';
import { useSSE } from '../../hooks/useSSE';
import { useDraft } from '../../hooks/useDraft';
import { useApplicationLeaveGuard } from '../../../../shared/hooks/useApplicationLeaveGuard';
import { Toast } from '../ui/Toast';
import { Header } from '../layout/Header';
import { ServiceCredentialsSettings } from '../../../settings/components/ServiceCredentialsSettings';
import { PlatformPage } from '../../../rd/pages/PlatformPage';
import { RightPanel } from '../layout/RightPanel';
import { UploadCard } from './UploadCard';
import { PrecheckCard } from './PrecheckCard';
import { ProgressCard } from './ProgressCard';
import { ManagementPanel } from '../../../admin/components/ManagementPanel';
import { StandaloneRuntimeLogsPage } from '../../../admin/components/StandaloneRuntimeLogsPage';
import { TaskbookReviewPage } from '../review/TaskbookReviewPage';
import { AdminPage } from '../../../admin/components/AdminPage';
import { HelpResourcePage } from '../../../help/components/HelpResourcePage';
import { RdPage } from '../../../rd/pages/RdPage';
import { GenerationContext } from './GenerationContext';
import { loadProductCatalog, loadModelCatalog, checkModelStatus } from '../../api/catalog';
import { SERVICE_CREDENTIALS_CHANGED } from '../../../settings/api/serviceCredentials';
import {
  submitJob,
  submitLocal,
  cancelJob,
  getJobStatus,
  runPrecheck,
  runPrecheckLocal,
} from '../../api/jobs';
import { loadBackendStatus, loadHistory, checkLocalFiles } from '../../api/system';
import { previewTemplateEdit } from '../../api/templates';
import { modelSelectionKey, appendModelSelection } from '../../model/model';
import { basename } from '../../../../shared/lib/dom';
import { collectReadinessIssues } from '../../model/readiness';
import { runningJobMatchesContext } from '../../model/rdGeneration';
import './taskbookWorkspace.css';
import { AUTO_DRAFT_KEY, DRAFT_KEY, RUNNING_JOB_KEY } from '../../model/constants';
import type { HistoryItem, ModelItem, SSEMessage } from '../../model/types';

interface HistoryPresetDetail {
  item: HistoryItem;
  autoPrecheck?: boolean;
}

export function LegacyTaskbookGenerationPanel() {
  const tb = useTaskbook();
  const draft = useDraft();
  const [draftReady, setDraftReady] = useState(false);
  const [modelSettingsRevision, setModelSettingsRevision] = useState(0);
  useEffect(() => { const refreshModels = () => setModelSettingsRevision(value => value + 1); window.addEventListener(SERVICE_CREDENTIALS_CHANGED, refreshModels); return () => window.removeEventListener(SERVICE_CREDENTIALS_CHANGED, refreshModels); }, []);
  const [modelCatalogState, setModelCatalogState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading');
  const [prechecking, setPrechecking] = useState(false);

  const sseCallbacks = useRef({
    onDone: (msg: SSEMessage) => {
      const blocked = msg.result?.delivery_status === 'blocked';
      tb.setIsRunning(false);
      tb.setIsCancelled(false);
      // 与旧版 showResult 一致：即使终态事件未携带 result，结果卡也必须
      // 以占位内容和下载入口呈现，不能退化为空白面板。
      tb.setJobResult(msg.result || {});
      tb.setResultBlocked(blocked);
      tb.setResultEmpty(false);
      tb.setShowResultCard(true);
      tb.setShowProgressCard(false);
      tb.setShowUploadCard(false);
      tb.setReviewTab('result');
      tb.setCurrentStep(blocked ? 5 : 6);
      tb.setProgressPercent(100);
      draft.clearRunningJob();
      loadHistory().then((items) => tb.setHistory(items)).catch(() => {});
    },
    onBlocked: (msg: SSEMessage) => {
      tb.setIsRunning(false);
      tb.setIsCancelled(false);
      tb.setJobResult(msg.result || {});
      tb.setResultBlocked(true);
      tb.setResultEmpty(false);
      tb.setShowResultCard(true);
      tb.setShowProgressCard(false);
      tb.setShowUploadCard(false);
      tb.setReviewTab('result');
      tb.setCurrentStep(5);
      tb.setProgressPercent(100);
      draft.clearRunningJob();
      loadHistory().then((items) => tb.setHistory(items)).catch(() => {});
    },
    onError: () => {
      tb.setIsRunning(false);
      tb.setIsCancelled(true);
      tb.setShowProgressCard(true);
      tb.setReviewTab('result');
      draft.clearRunningJob();
      loadHistory().then((items) => tb.setHistory(items)).catch(() => {});
    },
    onCancelled: () => {
      tb.setIsRunning(false);
      tb.setIsCancelled(true);
      tb.setProgressLiveClass('progress-live err');
      tb.setProgressLiveText('本次任务已安全终止；可以返回重新选择产品或文件');
      draft.clearRunningJob();
      loadHistory().then((items) => tb.setHistory(items)).catch(() => {});
    },
  });

  const { listenSSE, resetSSE } = useSSE(sseCallbacks.current);

  const getSelectedModel = useCallback(
    (): ModelItem | null =>
      tb.modelCatalog.find((item) => modelSelectionKey(item) === tb.selectedModelKey) || null,
    [tb.modelCatalog, tb.selectedModelKey],
  );

  const appendSelectionFields = useCallback(
    (
      fd: FormData,
      form: TaskbookForm = tb.form,
      selectedModel: ModelItem | null = getSelectedModel(),
    ) => {
      fd.append('product_type', form.productType);
      fd.append('product_domain', form.productDomain);
      fd.append('development_process', form.developmentProcess);
      fd.append('product_series', form.productSeries.trim());
      fd.append('organization_scope', form.organizationScope);
      fd.append('cover_phase', form.coverPhase);
      appendModelSelection(fd, selectedModel);
    },
    [getSelectedModel, tb.form],
  );

  const currentReadiness = useCallback(
    () =>
      collectReadinessIssues(tb.form, {
        productCatalog: tb.productCatalog,
        modelCatalog: tb.modelCatalog,
        selectedModelKey: tb.selectedModelKey,
        selectedModelReady: tb.selectedModelReady,
        backendHealthReady: tb.backendHealthReady,
        backendReadyForGeneration: tb.backendReadyForGeneration,
        localDefaultsReady: tb.localDefaultsReady,
        filesTech: tb.files.tech,
        filesSpec: tb.files.spec,
        templateEditPlan: tb.templateEditPlan,
      }),
    [tb],
  );

  const validateBeforeRun = useCallback(() => {
    tb.setValidationSubmitted(true);
    const readiness = currentReadiness();
    if (!readiness.ready) {
      tb.showToast('生成条件未满足，请先处理提示项', 'warn');
      return false;
    }
    return true;
  }, [currentReadiness, tb]);

  const showProgress = useCallback(() => {
    tb.setShowUploadCard(false);
    tb.setShowResultCard(false);
    tb.setShowProgressCard(true);
    tb.setResultEmpty(true);
    tb.setJobResult(null);
    tb.setResultBlocked(false);
    tb.setIsRunning(true);
    tb.setJobStatus('running');
    tb.setIsCancelled(false);
    tb.setReviewTab('result');
    tb.setCurrentStep(2);
    tb.setProgressPercent(0);
    tb.setProgressLiveClass('progress-live waiting');
    tb.setProgressLiveText('正在连接受控工作流…');
  }, [tb]);

  const handleReplayStarted = useCallback((jid: string) => {
    resetSSE();
    tb.setLogs([]);
    showProgress();
    tb.setCurrentJid(jid);
    draft.persistRunningJob(jid);
    listenSSE(jid, new EventSource(`/api/stream/${encodeURIComponent(jid)}`));
  }, [draft, listenSSE, resetSSE, showProgress, tb]);

  const handleSubmitLocal = useCallback(async () => {
    if (!validateBeforeRun()) return;

    const fd = new FormData();
    fd.append('use_llm', 'true');
    appendSelectionFields(fd);
    if (tb.templateEditPlan) {
      fd.append('template_edit_plan', JSON.stringify(tb.templateEditPlan));
      fd.append('template_edit_confirmed', tb.form.templateEditConfirmed ? 'true' : 'false');
    }

    showProgress();
    try {
      const data = await submitLocal(fd);
      if (!data.jid) throw new Error('后台未返回任务编号');
      tb.setCurrentJid(data.jid);
      draft.persistRunningJob(data.jid);
      listenSSE(
        data.jid,
        new EventSource(`/api/stream/${encodeURIComponent(data.jid)}`),
      );
    } catch (error) {
      tb.addLog('❌ 提交失败：' + (error as Error).message, 'err');
      tb.setShowUploadCard(true);
      tb.setShowProgressCard(false);
      tb.setIsRunning(false);
    }
  }, [appendSelectionFields, draft, listenSSE, showProgress, tb, validateBeforeRun]);

  const handleSubmit = useCallback(async () => {
    if (!validateBeforeRun()) return;
    if (!tb.files.tech && !tb.files.spec && tb.localDefaultsReady) {
      await handleSubmitLocal();
      return;
    }
    if (!tb.files.tech || !tb.files.spec) {
      tb.addLog('请上传需求文件和产品规范，或使用已就绪的本机验收样例', 'err');
      return;
    }

    const precheckForm = new FormData();
    precheckForm.append('tech', tb.files.tech);
    precheckForm.append('spec', tb.files.spec);
    appendSelectionFields(precheckForm);
    setPrechecking(true);
    try {
      tb.setPrecheck(await runPrecheck(precheckForm));
    } catch (error) {
      tb.addLog('❌ 预检失败：' + (error as Error).message, 'err');
      return;
    } finally {
      setPrechecking(false);
    }

    const fd = new FormData();
    fd.append('tech', tb.files.tech);
    fd.append('spec', tb.files.spec);
    fd.append('use_llm', 'true');
    appendSelectionFields(fd);
    if (tb.baselineDocx) fd.append('baseline_docx', tb.baselineDocx);
    if (tb.baselineJson) fd.append('baseline_json', tb.baselineJson);
    fd.append('fail_on_regression', tb.form.failOnRegression ? 'true' : 'false');
    if (tb.templateEditPlan) {
      fd.append('template_edit_plan', JSON.stringify(tb.templateEditPlan));
      fd.append('template_edit_confirmed', tb.form.templateEditConfirmed ? 'true' : 'false');
    }

    showProgress();
    try {
      const data = await submitJob(fd);
      if (!data.jid) throw new Error('后台未返回任务编号');
      tb.setCurrentJid(data.jid);
      draft.persistRunningJob(data.jid);
      listenSSE(
        data.jid,
        new EventSource(`/api/stream/${encodeURIComponent(data.jid)}`),
      );
    } catch (error) {
      tb.addLog('❌ 提交失败：' + (error as Error).message, 'err');
      tb.setShowUploadCard(true);
      tb.setShowProgressCard(false);
      tb.setIsRunning(false);
    }
  }, [appendSelectionFields, draft, handleSubmitLocal, listenSSE, showProgress, tb, validateBeforeRun]);

  const handleCancel = useCallback(async () => {
    if (!tb.currentJid) return;
    tb.setProgressLiveText('正在安全终止；当前外部模型请求返回后会立即停止后续步骤');
    try {
      await cancelJob(tb.currentJid);
      tb.addLog('⏳ 已收到停止请求', 'warn');
    } catch (error) {
      tb.addLog('❌ 停止请求失败：' + (error as Error).message, 'err');
    }
  }, [tb]);

  const handleReset = useCallback(() => {
    // 与旧版一致：新建任务保留业务选择，只清理文件和本次任务的高级设置。
    tb.setFormField('templateInstruction', '');
    tb.setFormField('templateEditConfirmed', false);
    tb.setFormField('failOnRegression', false);
    tb.setFiles({ tech: null, spec: null });
    tb.setUploadedFiles({ tech: [], spec: [] });
    tb.setBaselineDocx(null);
    tb.setBaselineJson(null);
    tb.clearValidationTouched();
    tb.setValidationSubmitted(false);
    tb.setCurrentJid(null);
    tb.setTemplateEditPlan(null);
    tb.setTemplateEditStatus('');
    tb.setTemplatePreviewLoading(false);
    tb.setLogs([]);
    tb.setProgressPercent(0);
    tb.setProgressLiveText('正在连接受控工作流…');
    tb.setProgressLiveClass('progress-live waiting');
    tb.setIsRunning(false);
    tb.setIsCancelled(false);
    tb.setJobStatus('idle');
    tb.setPrecheck(null);
    tb.setJobResult(null);
    tb.setResultBlocked(false);
    tb.setResultEmpty(true);
    tb.setShowUploadCard(true);
    tb.setShowProgressCard(false);
    tb.setShowResultCard(false);
    tb.setCurrentStep(1);
    tb.setReviewTab('result');
    tb.setManagementKind(null);
    tb.setWorkspaceView('generate');
    resetSSE();
    draft.clearRunningJob();
    requestAnimationFrame(() => {
      const baselineDocx = document.getElementById('baseline-docx') as HTMLInputElement | null;
      const baselineJson = document.getElementById('baseline-json') as HTMLInputElement | null;
      if (baselineDocx) baselineDocx.value = '';
      if (baselineJson) baselineJson.value = '';
      document.querySelector('.main')?.scrollTo({ top: 0 });
    });
  }, [draft, resetSSE, tb]);

  const handlePreviewEdit = useCallback(async () => {
    const instruction = tb.form.templateInstruction.trim();
    tb.setFormField('templateEditConfirmed', false);
    tb.setTemplateEditPlan(null);
    if (!instruction) {
      tb.setTemplateEditStatus('未填写提示词，无需调整模板');
      return;
    }

    const fd = new FormData();
    fd.append('instruction', instruction);
    appendSelectionFields(fd);
    fd.append('allow_llm', 'true');
    tb.setTemplatePreviewLoading(true);
    tb.setTemplateEditStatus('正在解析章节指令…');
    try {
      const plan = await previewTemplateEdit(fd);
      tb.setTemplateEditPlan(plan);
      tb.setTemplateEditStatus('预览已生成，请核对并确认');
    } catch (error) {
      tb.setTemplateEditStatus('解析失败：' + (error as Error).message);
    } finally {
      tb.setTemplatePreviewLoading(false);
    }
  }, [appendSelectionFields, tb]);

  const handleApplyHistoryPreset = useCallback(
    async ({ item, autoPrecheck = false }: HistoryPresetDetail) => {
      const product = tb.productCatalog.find((entry) => entry.value === item.product_type_id);
      const productType = product?.value || tb.form.productType;
      const domain = product?.domains.some((entry) => entry.value === item.product_domain_id)
        ? item.product_domain_id || ''
        : product?.domains[0]?.value || tb.form.productDomain;
      const presetForm: TaskbookForm = {
        ...tb.form,
        productType,
        productDomain: domain,
        developmentProcess: item.development_process || tb.form.developmentProcess,
        coverPhase: item.cover_phase || tb.form.coverPhase,
        productSeries: item.product_series || '',
        organizationScope: item.organization_scope || tb.form.organizationScope,
        templateInstruction: tb.form.templateInstruction,
        templateEditConfirmed: false,
      };

      Object.entries(presetForm).forEach(([key, value]) => {
        tb.setFormField(
          key as keyof TaskbookForm,
          value as TaskbookForm[keyof TaskbookForm],
        );
      });
      tb.setTemplateEditPlan(null);
      tb.setTemplateEditStatus('');
      tb.clearValidationTouched();
      tb.setValidationSubmitted(false);
      tb.setManagementKind(null);
      tb.setWorkspaceView('generate');

      let presetModel = getSelectedModel();
      if (item.model_provider && item.model_name) {
        const key = modelSelectionKey({
          provider: item.model_provider,
          name: item.model_name,
          id: item.model_id || '',
        });
        const found = tb.modelCatalog.find((entry) => modelSelectionKey(entry) === key);
        if (found) {
          tb.setSelectedModelKey(key);
          presetModel = found;
        }
      }

      tb.showToast('已复用历史参数（请重新上传文件）', 'ok');
      if (!autoPrecheck) return;

      const fd = new FormData();
      appendSelectionFields(fd, presetForm, presetModel);
      try {
        if (tb.files.tech && tb.files.spec) {
          fd.append('tech', tb.files.tech);
          fd.append('spec', tb.files.spec);
          tb.setPrecheck(await runPrecheck(fd));
          tb.showToast('已完成历史参数预检', 'ok');
        } else if (tb.localDefaultsReady) {
          tb.setPrecheck(await runPrecheckLocal(fd));
          tb.showToast('已完成本机样例预检', 'ok');
        } else {
          tb.showToast('已复用参数，但当前无可预检文件，请先上传文件', 'warn');
        }
      } catch (error) {
        tb.addLog('❌ 预检失败：' + (error as Error).message, 'err');
        tb.showToast('历史参数预检失败', 'warn');
      }
    },
    [appendSelectionFields, getSelectedModel, tb],
  );

  // 初始化目录、状态、历史、草稿与可能仍在运行的任务。
  useEffect(() => {
    let cancelled = false;
    const storedDraft =
      draft.readStoredDraft(AUTO_DRAFT_KEY) || draft.readStoredDraft(DRAFT_KEY);
    draft.restoreDraft(false);

    loadProductCatalog()
      .then((data) => {
        if (cancelled) return;
        const catalog = data.product_types || [];
        tb.setProductCatalog(catalog);
        const savedProduct = catalog.find((item) => item.value === storedDraft?.product_type);
        const selectedProduct = savedProduct || catalog.find((item) => item.enabled !== false) || catalog[0];
        const savedDomain = selectedProduct?.domains.find(
          (item) => item.value === storedDraft?.product_domain,
        );
        tb.setFormField('productType', selectedProduct?.value || '');
        tb.setFormField(
          'productDomain',
          savedDomain?.value || selectedProduct?.domains[0]?.value || '',
        );
        setDraftReady(true);
      })
      .catch(() => {
        if (!cancelled) setDraftReady(true);
      });

    loadHistory().then((items) => !cancelled && tb.setHistory(items)).catch(() => {});

    checkLocalFiles()
      .then((items) => {
        if (cancelled) return;
        const ready = Array.isArray(items) && items.length >= 2 && items.every((item) => item.exists);
        tb.setLocalDefaultsReady(ready);
        tb.setLocalDefaultFiles(ready ? items.map((item) => basename(item.path)).join(' / ') : '');
      })
      .catch(() => {
        if (!cancelled) tb.setLocalDefaultsReady(false);
      });

    (async () => {
      try {
        const payload = JSON.parse(localStorage.getItem(RUNNING_JOB_KEY) || 'null');
        if (!payload?.jid) return;
        if (!runningJobMatchesContext(payload, window.location.search)) return;
        const data = await getJobStatus(payload.jid);
        if (cancelled) return;
        if (['done', 'blocked', 'error', 'cancelled'].includes(data.status)) {
          draft.clearRunningJob();
          return;
        }
        tb.setShowUploadCard(false);
        tb.setShowResultCard(false);
        tb.setShowProgressCard(true);
        tb.setReviewTab('result');
        tb.setIsRunning(true);
        tb.setJobStatus('running');
        tb.setIsCancelled(false);
        tb.setCurrentJid(payload.jid);
        tb.setLogs([]);
        listenSSE(
          payload.jid,
          new EventSource(`/api/stream/${encodeURIComponent(payload.jid)}`),
        );
        tb.showToast('已恢复未完成任务进度', 'ok');
      } catch {
        draft.clearRunningJob();
      }
    })();

    tb.showToast('已加载首页与工作台，建议先确认系统健康状态', 'ok');
    return () => {
      cancelled = true;
    };
    // 初始化只执行一次；后续状态由各自 effect 同步。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Refresh after credential changes and discard requests from older settings.
  useEffect(() => {
    let cancelled = false;
    const storedDraft = draft.readStoredDraft(AUTO_DRAFT_KEY) || draft.readStoredDraft(DRAFT_KEY);
    setModelCatalogState('loading');
    tb.setModelCatalog([]);
    tb.setSelectedModelKey('');
    tb.setSelectedModelReady(null);
    tb.setBackendHealthReady(null);
    loadModelCatalog()
      .then((data) => {
        if (cancelled) return;
        if (!data.success || !Array.isArray(data.models)) {
          throw new Error(data.error || '模型目录读取失败');
        }
        const models = data.models
          .map((item) => ({
            provider: String(item.provider || 'smartvision'),
            name: String(item.model || item.name || ''),
            id: String(item.id || ''),
            vendor: String(item.vendor || ''),
            configured: item.configured !== false,
          }))
          .filter((item) => item.name);
        tb.setModelCatalog(models);
        setModelCatalogState(models.length ? 'ready' : 'empty');
        const savedKey =
          storedDraft?.model_provider && storedDraft?.model_name
            ? modelSelectionKey({
                provider: storedDraft.model_provider,
                name: storedDraft.model_name,
                id: storedDraft.model_id || '',
              })
            : '';
        const preferred =
          models.find((item) => modelSelectionKey(item) === savedKey && item.configured) ||
          models.find((item) => item.configured) ||
          models[0];
        tb.setSelectedModelKey(preferred ? modelSelectionKey(preferred) : '');
      })
      .catch(() => {
        if (cancelled) return;
        tb.setModelCatalog([]);
        tb.setSelectedModelKey('');
        tb.setSelectedModelReady(false);
        setModelCatalogState('error');
      });

    loadBackendStatus()
      .then((data) => {
        if (cancelled) return;
        tb.setBackendHealth(data);
        tb.setBackendHealthReady(Boolean(data.ready_for_generation));
      })
      .catch(() => {
        if (cancelled) return;
        tb.setBackendHealth(null);
        tb.setBackendHealthReady(null);
      });

    return () => { cancelled = true; };
  }, [modelSettingsRevision]);

  // 所选模型变化时重新检查凭据，忽略已经过期的响应。
  useEffect(() => {
    let active = true;
    const selected = getSelectedModel();
    if (!selected) {
      tb.setSelectedModelReady(false);
      return;
    }
    tb.setSelectedModelReady(null);
    checkModelStatus(selected.provider, selected.name, selected.id)
      .then((data) => active && tb.setSelectedModelReady(Boolean(data.configured)))
      .catch(() => active && tb.setSelectedModelReady(null));
    return () => {
      active = false;
    };
  }, [getSelectedModel, tb.selectedModelKey, tb.modelCatalog, modelSettingsRevision]);

  // UI 模式和管理页都依赖 body 级 CSS 选择器。
  useEffect(() => {
    document.body.classList.toggle('compact-mode', tb.uiMode === 'compact');
    document.body.classList.toggle('expert-mode', tb.uiMode === 'expert');
    document.body.classList.toggle('management-page', Boolean(tb.managementKind));
    document.body.dataset.page = tb.managementKind || 'home';
  }, [tb.managementKind, tb.uiMode]);

  // 目录完成初始化后，始终使用当前 React 状态写自动草稿，避免事件闭包保存旧值。
  useEffect(() => {
    if (!draftReady) return;
    draft.saveDraft(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    draftReady,
    tb.form.productType,
    tb.form.productDomain,
    tb.form.developmentProcess,
    tb.form.coverPhase,
    tb.form.productSeries,
    tb.form.organizationScope,
    tb.form.templateInstruction,
    tb.form.failOnRegression,
    tb.selectedModelKey,
  ]);

  // 全局兼容事件只挂载一次；ref 始终指向最新闭包，避免渲染间隙丢事件。
  const eventHandlersRef = useRef({
    submit: handleSubmit,
    submitLocal: handleSubmitLocal,
    cancel: handleCancel,
    reset: handleReset,
    restoreDraft: () => draft.restoreDraft(true),
    clearDraft: () => draft.clearDraft(true),
    previewEdit: handlePreviewEdit,
    applyHistory: handleApplyHistoryPreset,
    replayStarted: handleReplayStarted,
  });
  eventHandlersRef.current = {
    submit: handleSubmit,
    submitLocal: handleSubmitLocal,
    cancel: handleCancel,
    reset: handleReset,
    restoreDraft: () => draft.restoreDraft(true),
    clearDraft: () => draft.clearDraft(true),
    previewEdit: handlePreviewEdit,
    applyHistory: handleApplyHistoryPreset,
    replayStarted: handleReplayStarted,
  };
  useApplicationLeaveGuard({ dirty: Boolean(
    tb.form.productSeries ||
      tb.form.templateInstruction ||
      tb.files.tech ||
      tb.files.spec ||
      tb.isRunning ||
      tb.currentJid,
  ), busyMessage: prechecking ? '资料正在预检，请等待完成后再退出登录。'
    : tb.templatePreviewLoading ? '章节变更正在预览，请等待完成后再退出登录。'
    : tb.isRunning ? '任务正在生成，请等待完成或取消任务后再退出登录。' : undefined });

  useEffect(() => {
    const onSubmit = () => eventHandlersRef.current.submit();
    const onSubmitLocal = () => eventHandlersRef.current.submitLocal();
    const onCancel = () => eventHandlersRef.current.cancel();
    const onReset = () => eventHandlersRef.current.reset();
    const onRestoreDraft = () => eventHandlersRef.current.restoreDraft();
    const onClearDraft = () => eventHandlersRef.current.clearDraft();
    const onPreviewEdit = () => eventHandlersRef.current.previewEdit();
    const onApplyHistory = (event: Event) =>
      eventHandlersRef.current.applyHistory(
        (event as CustomEvent<HistoryPresetDetail>).detail,
      );
    const onReplayStarted = (event: Event) => eventHandlersRef.current.replayStarted((event as CustomEvent<{ jid: string }>).detail.jid);

    window.addEventListener('taskbook:submit', onSubmit);
    window.addEventListener('taskbook:submit-local', onSubmitLocal);
    window.addEventListener('taskbook:cancel', onCancel);
    window.addEventListener('taskbook:reset', onReset);
    window.addEventListener('taskbook:restore-draft', onRestoreDraft);
    window.addEventListener('taskbook:clear-draft', onClearDraft);
    window.addEventListener('taskbook:preview-edit', onPreviewEdit);
    window.addEventListener('taskbook:apply-history', onApplyHistory);
    window.addEventListener('taskbook:replay-started', onReplayStarted);

    const onKeyDown = (event: KeyboardEvent) => {
      if (document.querySelector('dialog[open]')) return;
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        const runButton = document.getElementById('btn-run') as HTMLButtonElement | null;
        if (!runButton || runButton.disabled) return;
        event.preventDefault();
        runButton.click();
      }
    };
    document.addEventListener('keydown', onKeyDown);

    return () => {
      window.removeEventListener('taskbook:submit', onSubmit);
      window.removeEventListener('taskbook:submit-local', onSubmitLocal);
      window.removeEventListener('taskbook:cancel', onCancel);
      window.removeEventListener('taskbook:reset', onReset);
      window.removeEventListener('taskbook:restore-draft', onRestoreDraft);
      window.removeEventListener('taskbook:clear-draft', onClearDraft);
      window.removeEventListener('taskbook:preview-edit', onPreviewEdit);
      window.removeEventListener('taskbook:apply-history', onApplyHistory);
      window.removeEventListener('taskbook:replay-started', onReplayStarted);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  return (
    <div className="taskbook-workspace" id="taskbook-workspace">
      <div className="taskbook-tool-heading"><div><p>研发工具 / 受控文档编制</p><h1>研制任务书生成</h1><span>上传技术要求与产品规范，按既有受控规则生成任务书，再进入成果核验与审签。</span></div>
        <div className="taskbook-tool-actions"><button className="feedback-button" type="button" onClick={handleReset}>新建生成作业</button><ServiceCredentialsSettings onSaved={async () => { setModelSettingsRevision(value => value + 1); }} /></div></div>
      <Header />
      <div className="main">
        <GenerationContext />
        {tb.managementKind && <ManagementPanel />}
        <div className="app-shell">
          <section className="workspace">
            <div className="steps" id="steps" aria-label="生成流程状态" hidden>
              {[1, 2, 3, 4, 5, 6].map((step) => (
                <div
                  key={step}
                  id={`s${step}`}
                  className={`step ${tb.currentStep === step ? 'active' : ''} ${tb.currentStep > step ? 'done' : ''}`}
                >
                  <span className="num">{step}</span>
                  <span className="label">
                    {['业务选择', '文件预检', '语义路由', '模板装配', '质量门禁', '交付完成'][step - 1]}
                  </span>
                </div>
              ))}
            </div>
            {tb.showUploadCard && <UploadCard
              modelCatalogState={modelCatalogState}
              onRetryModelCatalog={() => setModelSettingsRevision(value => value + 1)}
            />}
            <PrecheckCard />
            <ProgressCard />
            <div className="footer-note">
              所有正文均可追溯至上传源文档；系统不会由大模型代写技术要求。
            </div>
          </section>
          <RightPanel />
        </div>
      </div>
      <Toast />
    </div>
  );
}
