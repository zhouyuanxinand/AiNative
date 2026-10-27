import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  activateTemplateVersion, loadTemplateVersions, templateDownloadUrl,
  uploadTemplateVersion, versionDownloadUrl,
} from '../../api/templates';
import type { TemplateItem, TemplateVersion, TemplateVersionHistory } from '../../types';
import './templates.css';

function dateLabel(value?: string) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '初始模板';
}

const statusLabels = {
  active: '使用中', historical: '历史版本', ready: '待启用', invalid: '校验未通过',
};

export function TemplateDirectory({ directory, error, loading, onRefresh }: {
  directory: TemplateItem[]; error: string; loading: boolean; onRefresh: () => void;
}) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<TemplateItem | null>(null);
  const filtered = directory.filter(item =>
    [item.product_type, item.product_domain, item.filename].join(' ').toLowerCase().includes(query.trim().toLowerCase()));

  if (selected) {
    return <TemplateVersionEditor item={selected} onClose={() => setSelected(null)} onChanged={onRefresh} />;
  }
  return (
    <div className="template-manager">
      <p className="template-intro">为指定产品更换 Word 模板。校验通过后启用，后续生成立即使用新版本；可随时恢复历史版本。</p>
      <div className="template-toolbar">
        <label htmlFor="template-search">查找模板
          <input id="template-search" type="search" placeholder="输入产品类型、体系或文件名"
            value={query} onChange={event => setQuery(event.target.value)} />
        </label>
        <span>{filtered.length} 项模板</span>
        <button className="template-button" type="button" onClick={onRefresh} disabled={loading}>刷新目录</button>
      </div>
      {error ? <p className="template-error" role="alert">目录读取失败：{error}</p>
        : loading && !directory.length ? <p className="management-status" role="status">正在加载模板目录…</p>
        : !filtered.length ? <p className="management-status">没有找到匹配的模板，请调整搜索词。</p>
        : <ul className="template-catalog-list" aria-label="已启用模板目录">
          {filtered.map(item => <li key={item.product_type_id + '/' + item.product_domain_id}>
            <div className="template-product">
              <strong>{item.product_type}</strong><span>{item.product_domain}</span>
            </div>
            <div className="template-file-info">
              <span className="template-filename">{item.filename}</span>
              <span>版本 {item.version} · {dateLabel(item.updated_at)}</span>
            </div>
            <div className="template-actions">
              <a className="template-link" href={templateDownloadUrl(item)}>下载模板</a>
              <button className="template-button primary" type="button"
                aria-label={'更换 ' + item.product_type + ' ' + item.product_domain + ' 模板'}
                onClick={() => setSelected(item)}>更换模板</button>
            </div>
          </li>)}
        </ul>}
    </div>
  );
}

function TemplateVersionEditor({ item, onClose, onChanged }: {
  item: TemplateItem; onClose: () => void; onChanged: () => void;
}) {
  const [data, setData] = useState<TemplateVersionHistory | null>(null);
  const [candidate, setCandidate] = useState<TemplateVersion | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reload, setReload] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const form = useRef<HTMLFormElement>(null);

  useEffect(() => { heading.current?.focus(); }, []);
  useEffect(() => {
    let active = true;
    setError('');
    loadTemplateVersions(item.product_type_id, item.product_domain_id)
      .then(result => { if (active) setData(result); })
      .catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [item.product_type_id, item.product_domain_id, reload]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = new FormData(event.currentTarget);
    body.set('product_type', item.product_type_id);
    body.set('product_domain', item.product_domain_id);
    body.set('actor', 'web-user');
    setBusy('upload');
    setError('');
    setNotice('');
    setCandidate(null);
    try {
      const result = await uploadTemplateVersion(body);
      setCandidate(result.version);
      setData(previous => ({
        current: result.current,
        versions: [result.version, ...(previous?.versions || [])],
      }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy('');
    }
  }

  async function activate(version: TemplateVersion) {
    if (!data) return;
    setBusy(version.id);
    setError('');
    setNotice('');
    try {
      const result = await activateTemplateVersion(version.id, data.current.revision);
      setData(result);
      setCandidate(null);
      form.current?.reset();
      setNotice('版本 ' + version.version + ' 已启用，后续生成将使用此模板。');
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy('');
    }
  }

  const current = data?.current || item;
  return (
    <div className="template-manager">
      <div className="template-editor-head">
        <div>
          <h3 ref={heading} tabIndex={-1}>{item.product_type} / {item.product_domain}</h3>
          <p>当前版本：{current.version} · {current.filename}</p>
        </div>
        <button type="button" className="template-button" disabled={!!busy} onClick={onClose}>返回模板列表</button>
      </div>
      <p className="template-intro">支持 DOCX、DOC。上传后检查章节与指标表，保留本产品的生成规则。启用仅影响此产品及体系，历史任务保持原样。</p>
      {error && <div className="template-error" role="alert">{error}
        <button type="button" className="template-link" onClick={() => setReload(value => value + 1)} disabled={!!busy}>刷新版本信息</button>
      </div>}
      {notice && <p className="template-success" role="status">{notice}</p>}
      {!data && !error && <p role="status">正在读取版本记录…</p>}
      <form ref={form} className="template-upload-form" onSubmit={upload} aria-label="上传替换模板">
        <label className="template-upload-file">新模板文件
          <input name="template" type="file" accept=".docx,.doc" required disabled={!!busy || !data} />
        </label>
        <label>版本名称（选填）
          <input name="version" type="text" maxLength={80} placeholder="如 A版修订；留空使用上传时间" disabled={!!busy} />
        </label>
        <label className="template-update-note">更新说明（选填）
          <input name="note" type="text" maxLength={500} placeholder="说明本次调整，便于后续查找" disabled={!!busy} />
        </label>
        <div className="template-upload-actions">
          <button className="template-button primary" type="submit" disabled={!!busy || !data}>
            {busy === 'upload' ? '正在上传并校验…' : '上传并校验'}
          </button>
          <a className="template-link" href={templateDownloadUrl(current)}>下载当前模板</a>
        </div>
      </form>
      {candidate && <section className="template-validation" aria-labelledby="template-validation-title">
        <h4 id="template-validation-title">{candidate.validation.passed ? '模板校验通过' : '模板需要调整'}</h4>
        <p>{candidate.filename} · 版本 {candidate.version}</p>
        <p>识别到 {candidate.validation.heading_count} 个章节、{candidate.validation.table_count} 张表格。</p>
        {candidate.validation.problems.length > 0 && <ul className="template-error">
          {candidate.validation.problems.map(problem => <li key={problem}>{problem}</li>)}
        </ul>}
        {candidate.warnings.map(warning => <p className="template-conversion-note" key={warning}>{warning}</p>)}
        <details><summary>查看章节变化</summary>
          <p>新增：{candidate.validation.headings_added.join('、') || '无'}</p>
          <p>移除或改名：{candidate.validation.headings_removed.join('、') || '无'}</p>
        </details>
        <div className="template-actions">
          <a className="template-link" href={versionDownloadUrl(candidate.id)}>下载新模板核对</a>
          <button className="template-button primary" type="button"
            disabled={!!busy || !candidate.validation.passed} onClick={() => activate(candidate)}>
            {busy === candidate.id ? '正在启用…' : '启用此版本'}
          </button>
        </div>
        {!candidate.validation.passed && <p>请补齐上述章节或表格后重新上传，当前使用的模板不受影响。</p>}
      </section>}
      <section className="template-history" aria-labelledby="template-history-title">
        <h4 id="template-history-title">版本记录</h4>
        {!data?.versions.length ? <p className="management-status">首次更换时会自动保存当前模板，之后可在这里恢复。</p>
          : <ul>{data.versions.map(version => <li key={version.id}>
            <div className="template-version-heading">
              <strong>{version.version}</strong>
              <span className={'template-version-state ' + version.status}>{statusLabels[version.status]}</span>
            </div>
            <p className="template-filename">{version.filename}</p>
            <p>{dateLabel(version.created_at)}{version.note ? ' · ' + version.note : ''}</p>
            <div className="template-actions">
              <a className="template-link" href={versionDownloadUrl(version.id)}>下载</a>
              {version.status === 'historical' && <button type="button" className="template-button" disabled={!!busy}
                onClick={() => activate(version)}>{busy === version.id ? '正在恢复…' : '恢复此版本'}</button>}
              {['ready', 'invalid'].includes(version.status) && <button type="button" className="template-button" disabled={!!busy}
                onClick={() => setCandidate(version)}>查看校验结果</button>}
            </div>
          </li>)}</ul>}
      </section>
    </div>
  );
}
