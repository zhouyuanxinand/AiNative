import { Button, Tag } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { rdCatalogResource, RdApiError } from './api';
import { FlowGraphEditor } from './FlowGraphEditor';
import { teamConfigurationIssue } from './TeamConfiguration';
import { messageOf, statusTitle } from './presentation';
import type { Action, FlowGraph, ResourceSummary } from './types';
import './actionTemplateDetail.css';

type Member = { resource_id: string; resource_version: number | string };
type Detail = ResourceSummary & { configuration: Record<string, unknown> };
const keyOf = (id: string, version: number | string) => `${id}@${version}`;
const emptyGraph: FlowGraph = { nodes: [], edges: [] };
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const contractText = (value: unknown) => typeof value === 'string' ? value : record(value) ? String(value.title ?? value.name ?? value.description ?? '未提供说明') : '未提供说明';

/** A fixed resource view. Names enrich the display only; the stored graph stays unchanged. */
export function ActionTemplateDetail({ id, version, actions, onBack, onStructure }: {
  id: string; version: string; actions: Action[]; onBack: () => void;
  onStructure?: (id: string, version: string, count: number) => void;
}) {
  const [detail, setDetail] = useState<Detail | null>(null), [memberDetails, setMemberDetails] = useState<Record<string, ResourceSummary>>({});
  const [loading, setLoading] = useState(true), [error, setError] = useState(''), [restricted, setRestricted] = useState(false), [revision, setRevision] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    setDetail(null); setMemberDetails({}); setLoading(true); setError(''); setRestricted(false);
    void (async () => {
      const resource = await rdCatalogResource(id, version, controller.signal) as ResourceSummary & { configuration?: unknown };
      if (resource.id !== id || String(resource.version) !== version) throw new Error('返回的动作版本与所选版本不一致，请重新读取。');
      if (!record(resource.configuration)) throw new Error('该固定版本未提供可展示的动作配置。');
      // Catalog projections use null for optional absent fields. Normalize only this view.
      const configuration = {
        ...resource.configuration,
        members: resource.configuration.members ?? [],
        inputs: resource.configuration.inputs ?? [],
        outputs: resource.configuration.outputs ?? [],
        execution_graph: resource.configuration.execution_graph ?? emptyGraph,
      };
      const issue = teamConfigurationIssue(configuration);
      if (issue) throw new Error(`该固定版本的执行图暂时无法展示：${issue}`);
      const members = configuration.members as Member[];
      const graph = configuration.execution_graph as FlowGraph;
      const refs = new Map(members.map(member => [keyOf(member.resource_id, member.resource_version), member]));
      for (const node of graph.nodes) if (node.resource_id && node.resource_version !== undefined) refs.set(keyOf(node.resource_id, node.resource_version), { resource_id: node.resource_id, resource_version: node.resource_version });
      const entries = await Promise.allSettled([...refs.values()].map(async member => {
        const item = await rdCatalogResource(member.resource_id, member.resource_version, controller.signal);
        if (item.id !== member.resource_id || String(item.version) !== String(member.resource_version)) throw new Error('成员版本不一致');
        return [keyOf(member.resource_id, member.resource_version), item] as const;
      }));
      if (controller.signal.aborted) return;
      setDetail({ ...resource, configuration });
      setMemberDetails(Object.fromEntries(entries.flatMap(entry => entry.status === 'fulfilled' ? [entry.value] : [])));
      onStructure?.(id, version, graph.nodes.length);
    })().catch(reason => {
      if (controller.signal.aborted) return;
      setError(messageOf(reason)); setRestricted(reason instanceof RdApiError && [401, 403, 404].includes(reason.status));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [id, version, revision, onStructure]);
  useEffect(() => { if (!loading) heading.current?.focus({ preventScroll: true }); }, [loading]);
  const members = (detail?.configuration.members ?? []) as Member[];
  const fixedName = (resourceId: string, fixedVersion: string | number | undefined) => {
    if (fixedVersion === undefined) return '';
    const registered = actions.find(action => action.id === resourceId && String(action.version) === String(fixedVersion));
    return memberDetails[keyOf(resourceId, fixedVersion)]?.name?.trim() || registered?.title?.trim() || registered?.name?.trim() || '';
  };
  const storedGraph = (detail?.configuration.execution_graph ?? emptyGraph) as FlowGraph;
  const graph = useMemo<FlowGraph>(() => ({ ...storedGraph, nodes: storedGraph.nodes.map((node, index) => {
    const resourceId = node.resource_id ?? node.action_id;
    const fixedVersion = node.resource_version ?? node.action_version ?? members.find(member => member.resource_id === resourceId)?.resource_version;
    return { ...node, title: node.title?.trim() || (resourceId ? fixedName(resourceId, fixedVersion) : '') || `执行步骤 ${index + 1}` };
  }) }), [storedGraph, memberDetails, actions]);
  const unnamed = graph.nodes.some((node, index) => node.title === `执行步骤 ${index + 1}`);
  const retry = () => setRevision(value => value + 1);
  return <section className="rd-action-detail" aria-label="动作模板完整画布">
    <div className="rd-action-detail-back"><Button autoInsertSpace={false} type="link" htmlType="button" className="rd-link-button" aria-label="返回动作模板" onClick={onBack}>← <span>返回动作模板</span></Button><span>固定版本 V{version}</span></div>
    <header className="rd-action-detail-heading"><div><span className="rd-eyebrow">动作模板</span><h2 ref={heading} tabIndex={-1}>{detail?.name || '动作模板详情'}</h2>{detail && <p>{detail.description || '查看当前固定版本的执行步骤与前后依赖。'}</p>}</div><Button autoInsertSpace={false} htmlType="button" className="rd-button" disabled={loading} onClick={retry}>{loading ? '读取中…' : '刷新固定版本'}</Button></header>
    {loading && <div className="rd-action-detail-state" role="status">正在读取所选固定版本与步骤名称…</div>}
    {error && <div className="rd-action-detail-state rd-error" role="alert"><strong>{restricted ? '当前无法访问此动作版本' : '动作模板读取失败'}</strong><p>{error}</p><Button autoInsertSpace={false} htmlType="button" className="rd-button" onClick={retry}>重试读取动作模板</Button></div>}
    {detail && !loading && <>
      <div className="rd-action-detail-facts"><Tag className={`rd-badge ${detail.status ?? ''}`}>{statusTitle(detail.status)}</Tag><span>{graph.nodes.length === 1 ? '单动作封装 · 1 个执行步骤' : graph.nodes.length ? `多步骤编排 · ${graph.nodes.length} 个执行步骤` : '尚无执行图'}</span><span>{members.length} 个固定成员</span><span>{detail.executable ? '已接入执行能力' : '尚未接入执行能力'}</span></div>
      {graph.nodes.length ? <FlowGraphEditor key={keyOf(id, version)} graph={graph} readOnly allowRoutes={false} emptyRoleLabel="执行步骤" choices={members.map(member => ({ id: member.resource_id, version: member.resource_version, title: fixedName(member.resource_id, member.resource_version) || '固定成员', kind: 'resource' as const }))} onChange={() => {}} /> : <div className="rd-action-detail-state">该固定版本没有执行图，未补造执行节点。</div>}
      {unnamed && <p className="rd-action-name-notice" role="status">部分步骤名称暂未取得，仍按原图展示。<Button autoInsertSpace={false} type="link" htmlType="button" className="rd-link-button" onClick={retry}>重试读取步骤名称</Button></p>}
      <details className="rd-disclosure rd-action-contract"><summary>固定成员与输入输出</summary><div className="rd-action-contract-columns"><section><h3>固定成员</h3>{members.length ? <ul>{members.map((member, index) => <li key={`${keyOf(member.resource_id, member.resource_version)}-${index}`}><strong>{fixedName(member.resource_id, member.resource_version) || '名称暂未取得'}</strong><span>V{member.resource_version}</span><code>{member.resource_id}</code></li>)}</ul> : <p>此版本未列出固定成员。</p>}</section>{(['inputs', 'outputs'] as const).map(field => <section key={field}><h3>{field === 'inputs' ? '输入' : '输出'}</h3>{Array.isArray(detail.configuration[field]) && detail.configuration[field].length ? <ul>{(detail.configuration[field] as unknown[]).map((item, index) => <li key={index}>{contractText(item)}</li>)}</ul> : <p>未提供说明。</p>}</section>)}</div></details>
    </>}
  </section>;
}
