/**
 * 草稿存取 hook——从原 SPA saveDraft/restoreDraft/clearDraft 原样迁移。
 * localStorage 键名完全不变。
 */
import { useCallback } from 'react';
import { useTaskbook } from './useTaskbook';
import {
  DRAFT_KEY,
  AUTO_DRAFT_KEY,
  RUNNING_JOB_KEY,
} from '../model/constants';
import type { DraftPayload } from '../model/types';
import { modelSelectionKey } from '../model/model';
import { runningJobRecord } from '../model/rdGeneration';

export function useDraft() {
  const {
    form,
    setFormField,
    selectedModelKey,
    setSelectedModelKey,
    modelCatalog,
    setTemplateEditPlan,
    showToast,
  } = useTaskbook();

  const collectDraftPayload = useCallback((): DraftPayload => {
    return {
      product_type: form.productType,
      product_domain: form.productDomain,
      development_process: form.developmentProcess,
      cover_phase: form.coverPhase,
      product_series: form.productSeries,
      organization_scope: form.organizationScope,
      // 从 selectedModelKey 反解
      model_provider: decodeKeyPart(selectedModelKey, 0),
      model_name: decodeKeyPart(selectedModelKey, 1),
      model_id: decodeKeyPart(selectedModelKey, 2),
      template_instruction: form.templateInstruction,
      fail_on_regression: form.failOnRegression,
      saved_at: new Date().toISOString(),
    };
  }, [form, selectedModelKey]);

  const readStoredDraft = useCallback((key: string): DraftPayload | null => {
    try {
      const payload = JSON.parse(localStorage.getItem(key) || 'null');
      return payload && typeof payload === 'object' ? (payload as DraftPayload) : null;
    } catch {
      return null;
    }
  }, []);

  const saveDraft = useCallback(
    (showMessage = false) => {
      const payload = collectDraftPayload();
      const targetKey = showMessage ? DRAFT_KEY : AUTO_DRAFT_KEY;
      try {
        localStorage.setItem(targetKey, JSON.stringify(payload));
        if (showMessage) {
          localStorage.setItem(AUTO_DRAFT_KEY, JSON.stringify(payload));
          showToast('已保存当前选择，可随时恢复', 'ok');
        }
      } catch {
        if (showMessage) showToast('浏览器已禁用本地存储，无法保存', 'warn');
      }
    },
    [collectDraftPayload, showToast],
  );

  const restoreDraft = useCallback(
    (showMessage = false) => {
      const payload = showMessage
        ? readStoredDraft(DRAFT_KEY)
        : readStoredDraft(AUTO_DRAFT_KEY) || readStoredDraft(DRAFT_KEY);
      if (!payload) {
        if (showMessage) showToast('没有可恢复的已保存选择', 'warn');
        return null;
      }
      setFormField('productType', payload.product_type || '');
      setFormField('productDomain', payload.product_domain || '');
      setFormField('developmentProcess', payload.development_process || '全新');
      setFormField('coverPhase', payload.cover_phase || '');
      setFormField('productSeries', payload.product_series || '');
      setFormField('organizationScope', payload.organization_scope || 'non_central_research');
      let savedModelUnavailable = false;
      let hasFallbackModel = false;
      if (payload.model_provider && payload.model_name) {
        const key = modelSelectionKey({
          provider: payload.model_provider,
          name: payload.model_name,
          id: payload.model_id || '',
        });
        const savedModel = modelCatalog.find((item) => modelSelectionKey(item) === key);
        if (savedModel) {
          setSelectedModelKey(key);
        } else {
          const currentModel = modelCatalog.find((item) => modelSelectionKey(item) === selectedModelKey);
          const fallback = (currentModel?.configured ? currentModel : null)
            || modelCatalog.find((item) => item.configured)
            || currentModel
            || modelCatalog[0];
          setSelectedModelKey(fallback ? modelSelectionKey(fallback) : '');
          savedModelUnavailable = true;
          hasFallbackModel = !!fallback;
        }
      }
      setFormField('templateInstruction', payload.template_instruction || '');
      setFormField('failOnRegression', !!payload.fail_on_regression);
      if (payload.template_instruction) setTemplateEditPlan(null);
      if (showMessage) {
        showToast(
          savedModelUnavailable
            ? hasFallbackModel
              ? '已恢复其他选择；原模型当前不可用，已选择当前目录中的模型（文件需重新上传）'
              : '已恢复其他选择；原模型当前不可用，请重新选择模型（文件需重新上传）'
            : '已恢复上次保存的选择（文件需重新上传）',
          savedModelUnavailable ? 'warn' : 'ok',
        );
      }
      return payload;
    },
    [readStoredDraft, setFormField, setSelectedModelKey, selectedModelKey, modelCatalog, setTemplateEditPlan, showToast],
  );

  const clearDraft = useCallback(
    (showMessage = false) => {
      try {
        localStorage.removeItem(DRAFT_KEY);
        localStorage.removeItem(AUTO_DRAFT_KEY);
      } catch {
        /* ignore */
      }
      if (showMessage) showToast('已清空保存记录，当前页面选择保持不变', 'ok');
    },
    [showToast],
  );

  // 运行中任务持久化
  const persistRunningJob = useCallback((jid: string) => {
    try {
      localStorage.setItem(RUNNING_JOB_KEY, JSON.stringify(runningJobRecord(jid, window.location.search)));
    } catch {
      /* ignore */
    }
  }, []);

  const clearRunningJob = useCallback(() => {
    try {
      localStorage.removeItem(RUNNING_JOB_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const updateSavedSelectionState = useCallback((): string => {
    const payload = readStoredDraft(DRAFT_KEY);
    if (!payload) return '暂无已保存选择';
    const savedAt = payload.saved_at ? new Date(payload.saved_at) : null;
    const time =
      savedAt && !Number.isNaN(savedAt.getTime())
        ? savedAt.toLocaleString('zh-CN', { hour12: false })
        : '较早时间';
    return `已保存于 ${time}，恢复操作不会包含本地文件`;
  }, [readStoredDraft]);

  return {
    saveDraft,
    restoreDraft,
    clearDraft,
    persistRunningJob,
    clearRunningJob,
    updateSavedSelectionState,
    readStoredDraft,
  };
}

function decodeKeyPart(key: string, index: number): string {
  if (!key) return '';
  const parts = key.split('|');
  const part = parts[index];
  return part ? decodeURIComponent(part) : '';
}
