import { useEffect, useRef, useState } from 'react';
import {
  requestTestableModels, testModelConnection,
  type CredentialOverrides, type ModelCatalogResult, type ModelConnectionResult, type TestableModel,
} from '../../api/serviceCredentials';
import { StyledSelect } from './StyledSelect';

type ProbeTask = 'models' | 'test';
const elapsed = (value: number) => value >= 1000 ? `${(value / 1000).toFixed(2)} 秒` : `${Math.round(value)} 毫秒`;
const checkedTime = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
};
const modelKey = (model: TestableModel, index: number) => `${index}:${model.id}:${model.model}`;

export function ModelConnectionTest({ credentials, disabled }: {
  credentials: CredentialOverrides;
  disabled: boolean;
}) {
  const request = useRef<{ controller: AbortController; version: number; task: ProbeTask }>();
  const version = useRef(0);
  const [running, setRunning] = useState<ProbeTask | null>(null);
  const [catalog, setCatalog] = useState<ModelCatalogResult | null>(null);
  const [modelName, setModelName] = useState('');
  const [selection, setSelection] = useState('');
  const [result, setResult] = useState<ModelConnectionResult | null>(null);
  const [feedback, setFeedback] = useState<{ message: string; error: boolean } | null>(null);
  const models = catalog?.success ? catalog.models : [];
  const incomplete = credentials.model !== null && ['base_url', 'app_id', 'api_key', 'tenant_id']
    .some(field => !credentials.model?.[field]?.trim());

  function abort() {
    version.current += 1;
    request.current?.controller.abort();
    request.current = undefined;
  }

  useEffect(() => () => abort(), []);

  useEffect(() => {
    if (!disabled) return;
    abort();
    setRunning(null);
    setCatalog(null);
    setModelName('');
    setSelection('');
    setResult(null);
    setFeedback(null);
  }, [disabled]);

  function changeModel(name: string, selected = '') {
    if (request.current?.task === 'test') {
      abort();
      setRunning(null);
    }
    setModelName(name);
    setSelection(selected);
    setResult(null);
    setFeedback(null);
  }

  function cancel() {
    abort();
    setRunning(null);
    setFeedback({ message: '已取消本次测试。', error: false });
  }

  async function run(task: ProbeTask) {
    if (disabled || request.current || incomplete || (task === 'test' && !modelName.trim())) return;
    const controller = new AbortController();
    const currentVersion = ++version.current;
    request.current = { controller, version: currentVersion, task };
    setRunning(task);
    setResult(null);
    setFeedback(null);
    if (task === 'models') {
      setCatalog(null);
      setSelection('');
    }
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 50000);
    try {
      if (task === 'models') {
        const response = await requestTestableModels(credentials, controller.signal);
        if (version.current !== currentVersion) return;
        setCatalog(response);
        if (response.success && !modelName.trim() && response.models.length) {
          const first = response.models.findIndex(item => item.configured);
          const index = first < 0 ? 0 : first;
          setModelName(response.models[index].model);
          setSelection(modelKey(response.models[index], index));
        }
      } else {
        const name = modelName.trim();
        const chosen = models.find((item, index) => modelKey(item, index) === selection && item.model === name);
        const matches = models.filter(item => item.model === name);
        const modelId = chosen?.id || (matches.length === 1 ? matches[0].id : undefined);
        const response = await testModelConnection(credentials, name, modelId, controller.signal);
        if (version.current === currentVersion) setResult(response);
      }
    } catch (reason) {
      if (version.current !== currentVersion) return;
      setFeedback({ error: true, message: timedOut
        ? '等待服务响应超过 50 秒，已停止等待。请检查网络与服务状态后重试。'
        : reason instanceof Error && reason.name !== 'AbortError'
          ? reason.message : '测试已中止，请重试。' });
    } finally {
      window.clearTimeout(timeout);
      if (version.current === currentVersion) {
        request.current = undefined;
        setRunning(null);
      }
    }
  }

  return <section className="credentials-probe" aria-label="模型连通性与响应时间">
    <h3>模型连通性与响应时间</h3>
    <p className="credentials-probe-description">使用当前填写的凭证，测试不会保存或切换配置。</p>
    <div className="credentials-probe-catalog-action">
      <button type="button" disabled={disabled || !!running || incomplete} onClick={() => void run('models')}>
        {running === 'models' ? '正在读取…' : '读取模型列表'}
      </button>
      <span>也可直接填写完整模型名称。</span>
    </div>
    {incomplete && <p className="credentials-probe-hint">请先填写完整凭证，或恢复本组默认。</p>}
    {catalog && <p className={`credentials-probe-catalog ${catalog.success ? '' : 'credentials-probe-text-error'}`}
      role={catalog.success ? 'status' : 'alert'}>
      {catalog.success
        ? catalog.models.length ? `已读取 ${catalog.models.length} 个模型，目录响应耗时 ${elapsed(catalog.response_time_ms)}。`
          : '服务未返回可用模型，可填写完整模型名称继续测试。'
        : `模型目录读取失败：${catalog.message}`}
    </p>}
    {models.length > 0 && <div className="credentials-probe-field">
      <label id="model-test-selection-label" htmlFor="model-test-selection">选择可用模型</label>
      <StyledSelect id="model-test-selection" className="credentials-probe-select"
        value={selection} disabled={disabled || running === 'models'}
        aria-labelledby="model-test-selection-label"
        options={[
          { value: '', label: '手动填写模型名称', title: '手动填写模型名称' },
          ...models.map((item, index) => {
            const label = `${[item.vendor || item.provider, item.model].filter(Boolean).join(' · ')}${item.configured ? '' : '（未就绪）'}`;
            return { value: modelKey(item, index), label, title: label };
          }),
        ]}
        onChange={value => {
          const item = models.find((entry, index) => modelKey(entry, index) === value);
          changeModel(item?.model || '', value);
        }} />
    </div>}
    <div className="credentials-probe-field">
      <label htmlFor="model-test-name">模型名称</label>
      <input id="model-test-name" value={modelName} disabled={disabled || running === 'models'}
        autoComplete="off" autoCapitalize="none" spellCheck={false} maxLength={512}
        placeholder="填写服务支持的完整模型名称" aria-describedby="model-test-hint"
        onChange={event => changeModel(event.target.value)}
        onKeyDown={event => {
          if (event.key === 'Enter') { event.preventDefault(); void run('test'); }
        }} />
    </div>
    <p className="credentials-probe-hint" id="model-test-hint">读取列表仅检查模型目录；“测试连通性”会向所选模型发送一条简短请求。</p>
    <div className="credentials-probe-actions">
      <button className="credentials-probe-test" type="button"
        disabled={disabled || !!running || incomplete || !modelName.trim()} onClick={() => void run('test')}>
        {running === 'test' ? '正在测试…' : '测试连通性'}
      </button>
      {running && <button type="button" onClick={cancel}>取消测试</button>}
    </div>
    <div aria-live="polite" aria-atomic="true">
      {running && <p className="credentials-probe-progress" role="status">
        {running === 'models' ? '正在读取当前服务的模型目录…' : '正在等待模型响应，服务端最长等待约 45 秒…'}
      </p>}
      {feedback && <p className={`credentials-probe-feedback ${feedback.error ? 'credentials-probe-text-error' : ''}`}
        role={feedback.error ? 'alert' : 'status'}>{feedback.message}</p>}
      {result && <div className="credentials-probe-result" data-status={result.success ? 'success' : 'error'}
        role={result.success ? 'status' : 'alert'}>
        <h4>{result.success ? '模型响应正常' : '模型连接测试失败'}</h4>
        <p>{result.message}</p>
        <dl>
          <div><dt>测试模型</dt><dd>{result.model}</dd></div>
          <div><dt>{result.success ? '响应耗时' : '本次耗时'}</dt><dd>{elapsed(result.response_time_ms)}</dd></div>
          <div><dt>测试时间</dt><dd>{checkedTime(result.checked_at)}</dd></div>
        </dl>
      </div>}
    </div>
    <p className="credentials-probe-hint">响应耗时为服务端从发起模型请求到收到完整响应的时间，仅代表本次测试。</p>
  </section>;
}
