import { ArrowLeftOutlined, ArrowRightOutlined, DownloadOutlined, FileWordOutlined } from '@ant-design/icons';
import { Button, Tag } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { loadTemplateDirectory, templateDownloadUrl } from '../../api/templates';
import type { TemplateItem } from '../../types';
import { StyledSelect } from '../../components/ui/StyledSelect';
import type { useDirectoryState } from './useDirectoryState';
import './reportTemplates.css';

const PAGE_SIZE = 12;
type ProductTemplates = { id: string; name: string; templates: TemplateItem[]; domains: Map<string, { name: string; templates: TemplateItem[] }> };

function groupTemplates(templates: TemplateItem[]) {
  const products = new Map<string, ProductTemplates>();
  for (const template of templates) {
    let product = products.get(template.product_type_id);
    if (!product) {
      product = { id: template.product_type_id, name: template.product_type, templates: [], domains: new Map() };
      products.set(product.id, product);
    }
    product.templates.push(template);
    const domain = product.domains.get(template.product_domain_id) ?? { name: template.product_domain, templates: [] };
    domain.templates.push(template);
    product.domains.set(template.product_domain_id, domain);
  }
  return [...products.values()];
}

export function ReportTemplateDirectory({ directory }: { directory: ReturnType<typeof useDirectoryState> }) {
  const { state, page, update } = directory;
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const search = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const cards = useRef(new Map<string, HTMLElement>());
  const returnFocus = useRef('');
  const selectedId = state.item;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    void loadTemplateDirectory(controller.signal).then(items => {
      if (!controller.signal.aborted) setTemplates(items);
    }).catch(reason => {
      if (controller.signal.aborted) return;
      setTemplates([]); setError(reason instanceof Error ? reason.message : '模板目录暂时不可用');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision]);
  const products = useMemo(() => groupTemplates(templates), [templates]);
  const selected = products.find(product => product.id === selectedId);
  const term = state.q.trim().toLocaleLowerCase();
  const productFilter = state.product;
  const hasFilter = !!term || !!productFilter;
  // Search products after grouping, so a matching system never truncates the counts.
  const matching = products.filter(product => (!productFilter || product.id === productFilter) && (!term || product.templates.some(template =>
    [template.product_type, template.product_domain, template.filename, template.version].some(value => value.toLocaleLowerCase().includes(term)))));
  const totalPages = Math.max(1, Math.ceil(matching.length / PAGE_SIZE));
  const currentPage = Math.min(Math.max(1, page), totalPages);
  const visible = matching.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  useEffect(() => {
    if (!loading && !error && !selectedId && page !== currentPage) update({ page: String(currentPage) }, false);
  }, [loading, error, selectedId, page, currentPage, update]);
  useEffect(() => {
    if (loading || error) return;
    if (selectedId) heading.current?.focus({ preventScroll: true });
    else if (returnFocus.current) {
      cards.current.get(returnFocus.current)?.focus({ preventScroll: true });
      returnFocus.current = '';
    }
  }, [selectedId, loading, error]);
  function openProduct(product: ProductTemplates) {
    returnFocus.current = product.id;
    // Commit a pending search together with selection, avoiding a delayed reset.
    update({ item: product.id, detail: 'product', q: directory.input, page: directory.input === state.q ? String(currentPage) : '1' }, false);
  }
  function backToProducts() {
    returnFocus.current = selectedId;
    update({ item: '', detail: '' }, false);
  }
  return <div className="rd-report-directory">
    <div className="rd-flow-tools">
      <div><h2>报告模板</h2><p>按产品类型查找，再选择对应质量管理体系分类的模板。</p></div>
      <div className="rd-flow-tool-actions">
        {!selectedId && <div className="rd-report-type-filter"><label htmlFor="report-template-product">产品类型</label><StyledSelect id="report-template-product" aria-label="筛选产品类型" value={productFilter}
          disabled={loading || !!error} onChange={value => update({ product: value, q: directory.input, item: '', detail: '' })}
          options={[{ value: '', label: '全部产品类型' }, ...products.map(product => ({ value: product.id, label: product.name })),
            ...(productFilter && !products.some(product => product.id === productFilter) ? [{ value: productFilter, label: '该产品类型已不在目录中', disabled: true }] : [])]} /></div>}
        {!selectedId && <div className="rd-search"><label htmlFor="report-template-search" className="rd-visually-hidden">搜索报告模板</label>
          <input ref={search} id="report-template-search" type="search" placeholder="搜索产品、体系或模板" value={directory.input}
            onCompositionStart={() => directory.setComposing(true)}
            onCompositionEnd={event => { directory.setComposing(false); directory.setInput(event.currentTarget.value); }}
            onChange={event => directory.setInput(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing && !directory.composing) { event.preventDefault(); directory.commit(); } }} />
          {directory.input && <button type="button" aria-label="清空搜索" onClick={() => { directory.commit(''); search.current?.focus(); }}>×</button>}
        </div>}
        <Button className="rd-button" disabled={loading} onClick={() => setRevision(value => value + 1)}>{loading ? '读取中…' : '刷新目录'}</Button>
      </div>
    </div>
    {selectedId && <div className="rd-report-back"><Button type="link" className="rd-link-button" icon={<ArrowLeftOutlined aria-hidden="true" />} onClick={backToProducts}>返回产品类型</Button></div>}
    {loading ? <p className="rd-loading" role="status">正在读取报告模板…</p>
      : error ? <div className="rd-error rd-banner" role="alert"><p>报告模板读取失败：{error}</p><Button type="link" className="rd-link-button" onClick={() => setRevision(value => value + 1)}>重试读取</Button></div>
      : selectedId ? selected ? <>
        <div className="rd-report-product-heading"><h3 ref={heading} tabIndex={-1}>{selected.name}</h3><span>{selected.domains.size} 个体系分类 · {selected.templates.length} 个模板</span></div>
        <div className="rd-report-systems">{[...selected.domains].map(([id, domain]) => <section className="rd-report-system" key={id} aria-label={`${domain.name}模板`}>
          <header><h4>{domain.name}</h4><span>{domain.templates.length} 个模板</span></header>
          <ul>{domain.templates.map((template, index) => <li key={`${template.product_domain_id}/${index}`}>
            <FileWordOutlined className="rd-report-file-icon" aria-hidden="true" />
            <div className="rd-report-file"><strong>研制任务书</strong><span>{template.filename}</span></div>
            <Tag className="rd-badge">版本 {template.version}</Tag>
            <Button className="rd-button" href={templateDownloadUrl(template)} icon={<DownloadOutlined aria-hidden="true" />}>下载当前模板</Button>
          </li>)}</ul>
        </section>)}</div>
      </> : <div className="rd-management-empty"><h3 ref={heading} tabIndex={-1}>该产品暂无可用模板</h3><p>目录可能已更新，请返回产品类型重新选择。</p></div>
      : <>
        <p className="rd-report-summary" role="status">{hasFilter ? `匹配 ${matching.length} / ${products.length} 类产品` : `共 ${products.length} 类产品 · ${templates.length} 个模板`}</p>
        {visible.length ? <div className="rd-report-product-grid">{visible.map(product => <Button key={product.id} className="rd-report-product-card"
          ref={element => { if (element) cards.current.set(product.id, element); else cards.current.delete(product.id); }}
          aria-label={`查看${product.name}报告模板`} onClick={() => openProduct(product)}>
          <strong className="rd-report-product-name">{product.name}</strong>
          <span className="rd-report-domain-label">质量管理体系分类</span>
          <span className="rd-report-domain-names">{[...product.domains.values()].map(domain => domain.name).join(' / ')}</span>
          <span className="rd-report-card-bottom"><span><b>{product.templates.length}</b> 个模板</span><span className="rd-report-card-open">查看模板 <ArrowRightOutlined aria-hidden="true" /></span></span>
        </Button>)}</div> : <div className="rd-management-empty">{hasFilter ? <>没有匹配的产品类型。<Button type="link" onClick={() => { directory.setInput(''); update({ q: '', product: '', item: '', detail: '' }); }}>重置筛选</Button></> : '当前暂无报告模板。'}</div>}
        {!!matching.length && <div className="rd-flow-directory-footer"><span>显示 {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, matching.length)} / {matching.length} 类产品</span><div>
          <Button className="rd-button compact" disabled={currentPage <= 1} onClick={() => update({ page: String(currentPage - 1) }, false)}>上一页</Button>
          <span className="rd-report-page-number">第 {currentPage} / {totalPages} 页</span>
          <Button className="rd-button compact" disabled={currentPage >= totalPages} onClick={() => update({ page: String(currentPage + 1) }, false)}>下一页</Button>
        </div></div>}
      </>}
  </div>;
}
