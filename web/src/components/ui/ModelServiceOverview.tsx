import { Button } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { requestDefaultModel, requestServiceCredentials, type DefaultModelResponse } from '../../api/serviceCredentials';
import { ServiceCredentialsSettings, type SettingsModelProbe } from './ServiceCredentialsSettings';
import './modelServiceOverview.css';

interface EnvironmentSummary { id: string; name: string; configured: boolean; custom: boolean }
type Reading<T> = { value?: T; status: 'loading' | 'ready' | 'error' };
const timeLabel = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '时间未返回' : date.toLocaleString('zh-CN', { hour12: false });
};

/** Read-only summary; completed probe receipts live only while this page is mounted. */
export function ModelServiceOverview({ onSaved }: { onSaved: () => Promise<void> }) {
  const [environment, setEnvironment] = useState<Reading<EnvironmentSummary>>({ status: 'loading' });
  const [model, setModel] = useState<Reading<DefaultModelResponse>>({ status: 'loading' });
  const [probe, setProbe] = useState<SettingsModelProbe>();
  const request = useRef<AbortController>();

  async function refresh() {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    // Clear prior readings while checking; an earlier environment must not appear current.
    setEnvironment({ status: 'loading' });
    setModel({ status: 'loading' });
    const timeout = window.setTimeout(() => controller.abort(), 20000);
    await Promise.all([
      requestServiceCredentials(undefined, controller.signal).then(response => {
        if (request.current !== controller) return;
        const active = response.history.find(item => item.active);
        const configured = ['base_url', 'app_id', 'tenant_id', 'api_key'].every(key => !!response.effective.model[key]?.trim());
        setEnvironment({ status: 'ready', value: { id: active?.id || '', name: active?.name || '', configured,
          custom: response.overridden.includes('model') } });
      }).catch(() => { if (request.current === controller) setEnvironment({ status: 'error' }); }),
      requestDefaultModel(undefined, controller.signal).then(value => {
        if (request.current === controller) setModel({ status: 'ready', value });
      }).catch(() => { if (request.current === controller) setModel({ status: 'error' }); }),
    ]);
    window.clearTimeout(timeout);
  }

  useEffect(() => {
    void refresh();
    return () => { request.current?.abort(); request.current = undefined; };
  }, []);

  const selection = model.value?.selection;
  const sameEnvironment = environment.status === 'ready' && !!probe?.environmentId && probe.environmentId === environment.value?.id;
  const sameModel = model.status === 'ready' && !model.value?.requires_selection && !!selection && probe?.provider === selection.provider
    && probe.model === selection.name && probe.modelId === selection.id;
  const matches = !probe?.draft && sameEnvironment && sameModel;
  const failedRead = environment.status === 'error' || model.status === 'error';
  const loading = environment.status === 'loading' || model.status === 'loading';

  return <div className="model-service-overview" aria-label="模型服务摘要">
    <div><h2>模型服务</h2><p>维护模型连接，测试服务并管理已保存的凭证。</p></div>
    <dl className="model-service-readings" aria-busy={loading}>
      <div><dt>平台默认模型</dt><dd>{model.status === 'loading' ? '正在读取…' : model.status === 'error' ? '读取失败，待核对'
        : selection ? <><strong>{selection.name}{model.value?.requires_selection ? '（待确认）' : ''}</strong><small>{selection.provider}</small>
          {model.value?.requires_selection && <small>请在服务凭证设置中确认默认模型</small>}</> : '尚未选择，请在服务凭证设置中确认'}</dd></div>
      <div><dt>当前使用环境</dt><dd>{environment.status === 'loading' ? '正在读取…' : environment.status === 'error' ? '读取失败，待核对'
        : <><strong>{environment.value?.name || (environment.value?.custom ? '自定义环境（标识未返回）' : '部署默认环境')}</strong>
          <small>{environment.value?.configured ? '凭证已配置' : '凭证尚未配齐，请打开设置检查'}</small></>}</dd></div>
      <div><dt>最近一次实际测试</dt><dd>{probe ? <>
        <strong>{probe.draft ? '未保存草稿测试' : '历史测试'} · {probe.success ? '响应成功' : '响应失败'}</strong>
        <span>{probe.model}{probe.provider ? ` · ${probe.provider}` : ' · 模型身份未完整核对'}</span>
        <time dateTime={probe.checkedAt}>{timeLabel(probe.checkedAt)}</time>
        <small>本次耗时 {Math.round(probe.responseTimeMs)} 毫秒</small>
        <small>{probe.draft ? '使用未保存的填写，不代表已保存环境或默认模型的测试。'
          : loading || failedRead ? '当前配置待核对，暂不能匹配此记录。'
            : matches ? '与当前环境和默认模型匹配，仅代表当次响应。'
              : '与当前环境或默认模型未匹配，不能作为当前配置的测试记录。'}</small>
      </> : '本次打开设置页期间尚无完成的模型测试'}</dd></div>
    </dl>
    {failedRead && <div className="model-service-read-error" role="alert"><p>部分配置读取失败，请重新读取后核对；读取失败不表示尚未配置。</p>
      <Button htmlType="button" size="small" disabled={loading} onClick={() => void refresh()}>重新读取模型设置</Button></div>}
    <p className="model-service-receipt-note">测试记录仅保留在此次打开的设置页，刷新或离开后清除。历史成功不代表当前可用；打开页面不会自动测试模型。</p>
    <ServiceCredentialsSettings triggerVariant="button" onSaved={async () => { await Promise.all([refresh(), onSaved()]); }}
      onProbeResult={result => { setProbe(result); void refresh(); }} />
  </div>;
}
