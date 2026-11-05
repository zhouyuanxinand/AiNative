import { PlatformButton } from '../../components/ui/PlatformButton';
import { businessApprovalGate, businessExecutableNodes, insertBusinessAction } from './businessGraph';
import { Fragment, useEffect, useId, useRef, useState, type PointerEvent, type ReactNode } from 'react';
import { StyledSelect } from '../../components/ui/StyledSelect';
import { autoLayoutOperations } from './flowDraftReducer';
import { makeRequestKey } from './api';
import { routeFlowEdge } from './flowEdgeGeometry';
import type { BusinessWorkflowTemplate, FlowGraph, FlowNode, FlowOperation } from './types';
import './flowDesigner.css';

export interface FlowChoice { id: string; version: string | number; title: string; kind?: 'action' | 'resource' }
type Point = { x: number; y: number };
type NodeDrag = { kind: 'node'; id: string; start: Point; position: Point; scroll: Point; next: Point; zoom: number; element: HTMLButtonElement; pointerId: number };
type PanDrag = { kind: 'pan'; start: Point; position: Point; element: HTMLDivElement; pointerId: number };
type LinkDrag = { kind: 'link'; source: string; start: Point; element: HTMLButtonElement; pointerId: number };
const newId = () => `n-${makeRequestKey()}`;
const NODE_WIDTH = 210, NODE_HEIGHT = 108;
const CANVAS_INSET = 24;
const REQUIRED_BUSINESS_NODES = new Set(['input', 'confirm_requirements', 'comparison', 'selection_decision', 'rd_start', 'taskbook', 'taskbook_scope', 'scheme', 'detail', 'integration', 'verification', 'delivery']);
const nodeTitle = (node: FlowNode) => node.title || '未命名节点';
const storedPosition = (node: FlowNode, index: number): Point => node.position ?? { x: 24 + index % 3 * 270, y: 24 + Math.floor(index / 3) * 160 };

function CanvasIcon({ name }: { name: 'add' | 'edit' | 'copy' | 'delete' | 'close' | 'view' }) {
  const paths = { add: 'M12 5v14M5 12h14', edit: 'm14 5 5 5M4 20l5-1L21 7l-5-5L4 14v6Z', copy: 'M9 9h11v11H9zM4 15V4h11', delete: 'M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7', close: 'm6 6 12 12M6 18 18 6', view: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm10-3a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z' };
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}

export function FlowGraphEditor({ graph, choices, readOnly = false, disabled = false, onChange, confirmed = [], onConfirm, business = false, businessCategory = 'research', allowRoutes = true, upstreamNodes = [], emptyRoleLabel = '待配置负责角色', renderNodeDetails }: {
  graph: FlowGraph; choices: FlowChoice[]; readOnly?: boolean; disabled?: boolean; onChange: (operations: FlowOperation[]) => void;
  confirmed?: Array<{ node_id: string; field: string }>; onConfirm?: (nodeId: string, field: string) => void;
  business?: boolean; businessCategory?: BusinessWorkflowTemplate['category']; allowRoutes?: boolean;
  upstreamNodes?: Array<{ id: string; action_id: string; title: string }>;
  emptyRoleLabel?: string;
  renderNodeDetails?: (node: FlowNode) => ReactNode;
}) {
  const [selected, setSelected] = useState(''), [choice, setChoice] = useState('');
  const [linking, setLinking] = useState(false), [linkFrom, setLinkFrom] = useState('');
  const [notice, setNotice] = useState('');
  const [selectedEdge, setSelectedEdge] = useState(''), [inspectorOpen, setInspectorOpen] = useState(false), [addOpen, setAddOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(true);
  const [linkPreview, setLinkPreview] = useState<{ from: string; point: Point }>();
  const [view, setView] = useState({ left: 0, top: 0, width: 720, height: 420 });
  const [zoom, setZoom] = useState(1), [panning, setPanning] = useState(false);
  const [preview, setPreview] = useState<{ id: string; x: number; y: number }>();
  const node = selectedEdge ? undefined : graph.nodes.find(item => item.id === selected) ?? graph.nodes[0];
  const uid = useId().replaceAll(':', '');
  const viewport = useRef<HTMLDivElement>(null), inspectorTitle = useRef<HTMLHeadingElement>(null);
  const nodeElements = useRef(new Map<string, HTMLButtonElement>());
  const drag = useRef<NodeDrag | PanDrag | LinkDrag>();
  const suppressClick = useRef(false);
  const position = (item: FlowNode, index: number) => preview?.id === item.id ? preview : storedPosition(item, index);
  const rectangles = graph.nodes.map((item, index) => ({ ...position(item, index), width: NODE_WIDTH, height: NODE_HEIGHT }));
  const edgeRoutes = graph.edges.map(edge => { const from = graph.nodes.findIndex(item => item.id === edge.source), to = graph.nodes.findIndex(item => item.id === edge.target); return from < 0 || to < 0 ? null : routeFlowEdge(rectangles[from], rectangles[to], rectangles); });
  const width = Math.max(720, ...rectangles.map(rect => rect.x + rect.width + 72), ...edgeRoutes.filter(Boolean).map(route => route!.bounds.x + route!.bounds.width + 24));
  const height = Math.max(340, ...rectangles.map(rect => rect.y + rect.height + 72), ...edgeRoutes.filter(Boolean).map(route => route!.bounds.y + route!.bounds.height + 24));
  const contentBounds = [...rectangles, ...edgeRoutes.filter(Boolean).map(route => route!.bounds)];
  const contentLeft = contentBounds.length ? Math.min(...contentBounds.map(rect => rect.x)) : 0;
  const contentTop = contentBounds.length ? Math.min(...contentBounds.map(rect => rect.y)) : 0;
  const contentWidth = (contentBounds.length ? Math.max(...contentBounds.map(rect => rect.x + rect.width)) - contentLeft : NODE_WIDTH) + CANVAS_INSET * 2;
  const contentHeight = (contentBounds.length ? Math.max(...contentBounds.map(rect => rect.y + rect.height)) - contentTop : NODE_HEIGHT) + CANVAS_INSET * 2;
  const displayWidth = readOnly ? contentWidth : width + CANVAS_INSET * 2, displayHeight = readOnly ? contentHeight : height + CANVAS_INSET * 2;
  const centerOffset = { x: readOnly ? Math.max(0, (view.width - contentWidth * zoom) / 2) - contentLeft * zoom : 0, y: readOnly ? Math.max(0, (view.height - contentHeight * zoom) / 2) - contentTop * zoom : 0 };
  const graphViewKey = JSON.stringify(graph);
  const locked = readOnly || disabled;
  const protectedNode = !!node && (!!node.required || !!node.gate || business && REQUIRED_BUSINESS_NODES.has(node.id));
  const businessScope = businessExecutableNodes(graph, businessCategory);
  const bindingAllowed = !!node && !node.gate && businessScope.has(node.id);
  const definitionId = businessCategory === 'selection' ? 'input_check' : 'taskbook';
  const set = (properties: FlowOperation['properties']) => { if (node && !locked) onChange([{ op: 'set_node', node_id: node.id, properties }]); };
  const canAdd = !locked && (!business || graph.nodes.some(item => item.id === businessApprovalGate(businessCategory)));
  const edge = graph.edges.find(item => item.id === selectedEdge);
  const edgeRoute = edgeRoutes[graph.edges.findIndex(item => item.id === selectedEdge)];
  const menuPoint = node ? position(node, graph.nodes.indexOf(node)) : edgeRoute?.labelPoint;
  const menuAbove = menuPoint ? (menuPoint.y + CANVAS_INSET) * zoom + centerOffset.y - view.top - 48 : 0;
  const menuStyle = menuPoint ? { left: Math.max(8, Math.min(view.width - 190, (menuPoint.x + CANVAS_INSET) * zoom + centerOffset.x - view.left)), top: Math.max(8, Math.min(view.height - 48, node && menuAbove >= 8 ? menuAbove : (menuPoint.y + CANVAS_INSET + (node ? NODE_HEIGHT : 0)) * zoom + centerOffset.y - view.top + 8)) } : undefined;

  function syncView() { const el = viewport.current; if (el) setView({ left: el.scrollLeft, top: el.scrollTop, width: el.clientWidth, height: el.clientHeight }); }
  useEffect(() => { const el = viewport.current; if (!el) return; const observer = new ResizeObserver(syncView); observer.observe(el); syncView(); return () => observer.disconnect(); }, []);
  function inspect() { setAddOpen(false); setInspectorOpen(true); requestAnimationFrame(() => inspectorTitle.current?.focus({ preventScroll: true })); }
  function removeSelection() {
    if (locked) return;
    if (edge) { onChange([{ op: 'remove_edge', edge_id: edge.id }]); setSelectedEdge(''); setNotice('已移除连线，可撤销恢复。'); }
    else if (node && !protectedNode) { onChange([{ op: 'remove_node', node_id: node.id }]); setSelected(''); setInspectorOpen(false); setNotice('已移除节点及关联连线，可撤销恢复。'); }
    else if (node) setNotice('必需步骤或业务确认节点不能删除。');
  }
  function canvasPoint(clientX: number, clientY: number): Point { const el = viewport.current!; const box = el.getBoundingClientRect(); return { x: (clientX - box.left + el.scrollLeft) / zoom - CANVAS_INSET, y: (clientY - box.top + el.scrollTop) / zoom - CANVAS_INSET }; }
  function freePosition(start: Point): Point {
    for (let row = 0; row < graph.nodes.length + 1; row++) for (let column = 0; column < 3; column++) {
      const candidate = { x: Math.max(24, start.x + column * (NODE_WIDTH + 60)), y: Math.max(24, start.y + row * (NODE_HEIGHT + 64)) };
      if (!rectangles.some(rect => candidate.x < rect.x + rect.width + 16 && candidate.x + NODE_WIDTH + 16 > rect.x && candidate.y < rect.y + rect.height + 16 && candidate.y + NODE_HEIGHT + 16 > rect.y)) return candidate;
    }
    return { x: 24, y: height + 24 };
  }
  function beginLink(event: PointerEvent<HTMLButtonElement>, from: string) {
    event.stopPropagation(); if (locked || event.button !== 0) return;
    setSelected(from); setSelectedEdge(''); setInspectorOpen(false); setAddOpen(false); setLinking(true); setLinkFrom(from);
    drag.current = { kind: 'link', source: from, start: { x: event.clientX, y: event.clientY }, element: event.currentTarget, pointerId: event.pointerId };
    setLinkPreview({ from, point: canvasPoint(event.clientX, event.clientY) }); event.currentTarget.setPointerCapture(event.pointerId);
  }
  function finishLink(event: PointerEvent<HTMLButtonElement>) {
    const active = drag.current; if (active?.kind !== 'link') return; drag.current = undefined; setLinkPreview(undefined);
    if (active.element.hasPointerCapture(active.pointerId)) active.element.releasePointerCapture(active.pointerId);
    if (Math.hypot(event.clientX - active.start.x, event.clientY - active.start.y) < 4) { setNotice('点击目标节点完成连线，Esc 取消。'); return; }
    const destination = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-flow-node]')?.getAttribute('data-flow-node');
    if (destination) createLink(active.source, destination); else { setLinking(false); setLinkFrom(''); setNotice('未连接到节点，已取消连线。'); }
  }

  function cancelGesture() {
    const active = drag.current;
    drag.current = undefined;
    suppressClick.current = false;
    if (active?.kind === 'pan') active.element.scrollTo(active.position.x, active.position.y);
    if (active?.element.hasPointerCapture(active.pointerId)) active.element.releasePointerCapture(active.pointerId);
    setPreview(undefined); setLinkPreview(undefined); setPanning(false);
  }
  useEffect(() => {
    const cancel = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || (!drag.current && !linking && !inspectorOpen && !addOpen && !selectedEdge)) return;
      event.preventDefault(); cancelGesture(); setLinking(false); setLinkFrom(''); setInspectorOpen(false); setAddOpen(false); setSelectedEdge('');
      if (inspectorOpen && node) nodeElements.current.get(node.id)?.focus({ preventScroll: true });
    };
    window.addEventListener('keydown', cancel);
    return () => window.removeEventListener('keydown', cancel);
  }, [linking, inspectorOpen, addOpen, selectedEdge, node?.id]);
  useEffect(() => { if (locked) { cancelGesture(); setLinking(false); setLinkFrom(''); setAddOpen(false); } }, [locked]);
  function locateNode(id: string, focus = false) {
    const element = nodeElements.current.get(id), container = viewport.current;
    const index = graph.nodes.findIndex(item => item.id === id);
    if (!element || !container || index < 0) return;
    const point = storedPosition(graph.nodes[index], index);
    container.scrollTo({ left: Math.max(0, (point.x + CANVAS_INSET + NODE_WIDTH / 2) * zoom + centerOffset.x - container.clientWidth / 2), top: Math.max(0, (point.y + CANVAS_INSET + NODE_HEIGHT / 2) * zoom + centerOffset.y - container.clientHeight / 2), behavior: 'instant' });
    if (focus) element.focus({ preventScroll: true });
  }
  useEffect(() => { if (selected && !drag.current) locateNode(selected); }, [selected, graph.nodes.length]);
  function changeZoom(value: number, fit = false) {
    cancelGesture(); setLinking(false); setLinkFrom('');
    const container = viewport.current, next = Math.min(1.5, Math.max(readOnly ? .01 : .25, value));
    if (!container) return;
    const center = { x: (container.scrollLeft + container.clientWidth / 2) / zoom, y: (container.scrollTop + container.clientHeight / 2) / zoom };
    setZoom(next);
    requestAnimationFrame(() => container.scrollTo({ left: fit ? 0 : Math.max(0, center.x * next - container.clientWidth / 2), top: fit ? 0 : Math.max(0, center.y * next - container.clientHeight / 2), behavior: 'instant' }));
  }
  function fitCanvas() {
    const container = viewport.current;
    if (container) changeZoom(Math.min(1, (container.clientWidth - 16) / displayWidth, (container.clientHeight - 16) / displayHeight), true);
  }
  useEffect(() => {
    if (!readOnly || !view.width || !view.height) return;
    const frame = requestAnimationFrame(fitCanvas);
    return () => cancelAnimationFrame(frame);
  }, [readOnly, graphViewKey, view.width, view.height]);
  useEffect(() => { if (!readOnly) { setZoom(1); setContextOpen(true); } }, [readOnly]);
  function createLink(from: string, to: string) {
    if (locked || !graph.nodes.some(item => item.id === from) || !graph.nodes.some(item => item.id === to)) return;
    if (from === to) { setNotice('请选择另一个节点作为终点。'); return; }
    if (graph.edges.some(edge => edge.source === from && edge.target === to)) { setNotice('这两个节点之间已存在相同连线。'); return; }
    const seen = new Set<string>(), queue = [to];
    for (let index = 0; index < queue.length; index++) {
      const id = queue[index]; if (seen.has(id)) continue; seen.add(id);
      if (id === from) { setNotice('这条连线会形成循环。请调整先后关系后再连接。'); return; }
      queue.push(...graph.edges.filter(edge => edge.source === id).map(edge => edge.target));
    }
    onChange([{ op: 'add_edge', edge: { id: `e-${makeRequestKey()}`, source: from, target: to } }]);
    setLinking(false); setLinkFrom(''); setContextOpen(false); setNotice('连线已添加到当前草稿，保存后生效。');
  }
  function chooseNode(id: string) {
    if (suppressClick.current) { suppressClick.current = false; return; }
    setSelected(id); setSelectedEdge(''); setContextOpen(true);
    if (linking && !locked) {
      if (!linkFrom) { setLinkFrom(id); setNotice('已选择起点，请点击后续节点。'); }
      else createLink(linkFrom, id);
    }
  }
  function beginNodeDrag(event: PointerEvent<HTMLButtonElement>, item: FlowNode, point: Point) {
    if (locked || linking || event.button !== 0) return;
    event.stopPropagation(); suppressClick.current = false;
    drag.current = { kind: 'node', id: item.id, start: { x: event.clientX, y: event.clientY }, scroll: { x: viewport.current?.scrollLeft ?? 0, y: viewport.current?.scrollTop ?? 0 }, position: point, next: point, zoom, element: event.currentTarget, pointerId: event.pointerId };
    setSelected(item.id); setSelectedEdge(''); setContextOpen(true); setInspectorOpen(false); setAddOpen(false); event.currentTarget.setPointerCapture(event.pointerId);
  }
  function moveNode(event: PointerEvent<HTMLButtonElement>) {
    const active = drag.current;
    if (active?.kind !== 'node') return;
    const dx = event.clientX - active.start.x + (viewport.current?.scrollLeft ?? 0) - active.scroll.x, dy = event.clientY - active.start.y + (viewport.current?.scrollTop ?? 0) - active.scroll.y;
    if (Math.abs(dx) + Math.abs(dy) < 3 && !preview) return;
    active.next = { x: Math.max(0, Math.round(active.position.x + dx / active.zoom)), y: Math.max(0, Math.round(active.position.y + dy / active.zoom)) };
    suppressClick.current = true; setPreview({ id: active.id, ...active.next });
  }
  function endNodeDrag() {
    const active = drag.current;
    drag.current = undefined; setPreview(undefined);
    if (active?.kind === 'node' && !locked && (active.next.x !== active.position.x || active.next.y !== active.position.y)) {
      onChange([{ op: 'move_node', node_id: active.id, position: active.next }]);
    }
  }
  function add() {
    const item = choices.find((_, index) => String(index) === choice);
    if (locked || (!item && !business)) return;
    const id = newId();
    const anchor = node ? storedPosition(node, graph.nodes.indexOf(node)) : { x: view.left / zoom, y: view.top / zoom };
    const newNode: FlowNode = { id, title: item?.title ?? '新增办理节点', role: '研发工程师', deliverables: [], position: freePosition({ x: anchor.x + 30, y: anchor.y + NODE_HEIGHT + 100 }), ...(business ? item ? { action_resource: { resource_id: item.id, resource_version: item.version }, workpackage_definition_id: definitionId } : {} : item!.kind === 'resource' ? { resource_id: item!.id, resource_version: item!.version } : { action_id: item!.id, action_version: String(item!.version) }) };
    const operations = business ? insertBusinessAction(graph, businessCategory, newNode) : [{ op: 'add_node', node: newNode } as FlowOperation];
    if (!operations.length) return;
    onChange(operations); setSelected(id); setSelectedEdge(''); setAddOpen(false); setInspectorOpen(true); setNotice('节点已添加，可填写属性。');
  }
  function copyNode() {
    if (!node || locked) return;
    const point = storedPosition(node, graph.nodes.indexOf(node));
    const copy: FlowNode = { ...node, id: newId(), title: `${nodeTitle(node)}（副本）`, position: freePosition({ x: point.x + 40, y: point.y + 160 }) };
    delete copy.gate;
    if (business) delete copy.required;
    else copy.required = false;
    if ('input_bindings' in copy) copy.input_bindings = {};
    const operations = business ? insertBusinessAction(graph, businessCategory, copy) : [{ op: 'add_node', node: copy } as FlowOperation];
    if (operations.length) { onChange(operations); setSelected(copy.id); setSelectedEdge(''); setContextOpen(true); setInspectorOpen(false); }
  }
  const resourceName = (id: string | undefined) => choices.find(item => item.id === id)?.title;
  const fixedResource = node?.action_resource?.resource_id ?? node?.resource_id ?? node?.action_id;
  return <div className="rd-graph-editor is-direct-canvas" onKeyDown={event => { if ((event.key === 'Delete' || event.key === 'Backspace') && !(event.target as Element).closest('input,textarea,[contenteditable=true],[role=combobox]')) { event.preventDefault(); removeSelection(); } }}>
    <div className="rd-graph-structure">
      <div className="rd-canvas-toolbar"><div><strong>{readOnly ? '流程画布 · 只读' : '流程画布'}</strong><span>{graph.nodes.length} 个节点 · {graph.edges.length} 条连线</span></div>
        <div className="rd-graph-view-tools">{!readOnly && <button type="button" className="rd-canvas-icon primary" title="新增节点" aria-label="新增节点" disabled={!canAdd} onClick={() => { setAddOpen(value => !value); setInspectorOpen(false); }}><CanvasIcon name="add" /></button>}<PlatformButton type="button" className="rd-button compact" aria-label="缩小画布" disabled={zoom <= (readOnly ? .01 : .25)} onClick={() => changeZoom(zoom - .15)}>−</PlatformButton><span aria-live="polite">{Math.round(zoom * 100)}%</span><PlatformButton type="button" className="rd-button compact" aria-label="放大画布" disabled={zoom >= 1.5} onClick={() => changeZoom(zoom + .15)}>＋</PlatformButton><PlatformButton type="button" className="rd-button compact" onClick={fitCanvas}>适应</PlatformButton>{!readOnly && <PlatformButton type="button" className="rd-button compact" disabled={disabled || graph.nodes.length < 2} onClick={() => { const operations = autoLayoutOperations(graph); if (operations.length) onChange(operations); }}>自动排列</PlatformButton>}</div>
      </div>
      <div className="rd-canvas-stage">
      <div ref={viewport} className={`rd-graph-scroll${panning ? ' is-panning' : ''}${linking ? ' is-linking' : ''}`} tabIndex={0} aria-label="流程节点画布" aria-describedby={`${uid}-canvas-help`} onScroll={syncView}
        onKeyDown={event => { if (event.target !== event.currentTarget) return; const delta = ({ ArrowLeft: [-60, 0], ArrowRight: [60, 0], ArrowUp: [0, -60], ArrowDown: [0, 60] } as Record<string, number[]>)[event.key]; if (delta) { event.preventDefault(); event.currentTarget.scrollBy(delta[0], delta[1]); } }}
        onPointerDown={event => { if (event.button !== 0 || (event.target as Element).closest('button,[role=button]')) return; setInspectorOpen(false); setAddOpen(false); setSelectedEdge(''); setContextOpen(false); drag.current = { kind: 'pan', start: { x: event.clientX, y: event.clientY }, position: { x: event.currentTarget.scrollLeft, y: event.currentTarget.scrollTop }, element: event.currentTarget, pointerId: event.pointerId }; event.currentTarget.setPointerCapture(event.pointerId); setPanning(true); }}
        onPointerMove={event => { const active = drag.current; if (active?.kind === 'pan') event.currentTarget.scrollTo(active.position.x - (event.clientX - active.start.x), active.position.y - (event.clientY - active.start.y)); }}
        onPointerUp={() => { if (drag.current?.kind === 'pan') { drag.current = undefined; setPanning(false); } }} onPointerCancel={cancelGesture} onLostPointerCapture={() => { if (drag.current?.kind === 'pan') { drag.current = undefined; setPanning(false); } }}>
        <div className="rd-graph-size" style={{ width: Math.max(view.width, displayWidth * zoom), height: Math.max(view.height, displayHeight * zoom) }}><div className="rd-graph-plane" style={{ left: CANVAS_INSET * zoom + centerOffset.x, top: CANVAS_INSET * zoom + centerOffset.y, width, height, transform: `scale(${zoom})` }}>
          <svg className="rd-canvas-connections" width={width} height={height}><defs>{['normal','active'].map(kind => <marker key={kind} id={`arrow-${uid}-${kind}`} markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path className={kind} d="M0,1 L9,5 L0,9 Z" /></marker>)}</defs>{graph.edges.map((item, index) => {
            const route = edgeRoutes[index]; if (!route) return null;
            const active = item.id === selectedEdge || !!node && [item.source,item.target].includes(node.id);
            const selectEdge = () => { setSelectedEdge(item.id); setContextOpen(true); setInspectorOpen(false); setAddOpen(false); };
            return <g key={item.id}><path className={`rd-canvas-edge${active ? ' is-selected' : ''}${!route.clear ? ' is-obscured' : ''}`} d={route.path} markerEnd={`url(#arrow-${uid}-${active ? 'active' : 'normal'})`} aria-hidden="true" /><path className="rd-canvas-edge-hit" d={route.path} role="button" tabIndex={0} aria-label={`选择连线 ${graph.nodes.find(n => n.id === item.source)?.title || item.source} → ${graph.nodes.find(n => n.id === item.target)?.title || item.target}`} aria-pressed={selectedEdge === item.id} onPointerDown={event => event.stopPropagation()} onClick={selectEdge} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectEdge(); } }} /></g>;
          })}{linkPreview && <path className="rd-canvas-link-preview" d={(() => { const index = graph.nodes.findIndex(item => item.id === linkPreview.from); if (index < 0) return ''; const start = position(graph.nodes[index], index); return `M${start.x + NODE_WIDTH},${start.y + NODE_HEIGHT / 2} L${linkPreview.point.x},${linkPreview.point.y}`; })()} markerEnd={`url(#arrow-${uid}-active)`} />}</svg>
          {graph.nodes.map((item, index) => { const point = position(item, index); return <Fragment key={item.id}><button type="button" data-flow-node={item.id} ref={element => { if (element) nodeElements.current.set(item.id, element); else nodeElements.current.delete(item.id); }} className={`rd-graph-node${node?.id === item.id ? ' is-selected' : ''}${linkFrom === item.id ? ' is-link-source' : ''}${readOnly ? ' is-readonly' : ''}`} style={{ left: point.x, top: point.y }} aria-pressed={node?.id === item.id} aria-label={`${nodeTitle(item)}，选择节点`} title={nodeTitle(item)} onClick={() => chooseNode(item.id)} onDoubleClick={() => { setSelected(item.id); setSelectedEdge(''); inspect(); }}
            onKeyDown={event => { if (locked || !event.altKey || event.nativeEvent.isComposing) return; const delta = ({ ArrowLeft: [-10, 0], ArrowRight: [10, 0], ArrowUp: [0, -10], ArrowDown: [0, 10] } as Record<string, number[]>)[event.key]; if (delta) { event.preventDefault(); onChange([{ op: 'move_node', node_id: item.id, position: { x: Math.max(0, point.x + delta[0]), y: Math.max(0, point.y + delta[1]) } }]); } }}
            onPointerDown={event => beginNodeDrag(event, item, point)} onPointerMove={moveNode} onPointerUp={endNodeDrag} onPointerCancel={cancelGesture} onLostPointerCapture={() => { if (drag.current?.kind === 'node') cancelGesture(); }}>
            <span className="rd-graph-node-kind">{item.gate ? '业务确认' : item.required || business && REQUIRED_BUSINESS_NODES.has(item.id) ? '必需节点' : item.action_resource || item.resource_id || item.action_id ? '动作节点' : '办理节点'}</span><strong>{nodeTitle(item)}</strong><span>{item.role || emptyRoleLabel}</span>
          </button>{!readOnly && <button type="button" data-flow-node={item.id} className="rd-canvas-port" style={{ left: point.x + NODE_WIDTH - 10 / zoom, top: point.y + NODE_HEIGHT / 2 - 10 / zoom, width: 20 / zoom, height: 20 / zoom, borderWidth: 2 / zoom }} disabled={disabled} title="拖到另一个节点建立连线" aria-label={`从${nodeTitle(item)}连线`} onPointerDown={event => beginLink(event, item.id)} onPointerMove={event => { if (drag.current?.kind === 'link') setLinkPreview({ from: drag.current.source, point: canvasPoint(event.clientX, event.clientY) }); }} onPointerUp={finishLink} onPointerCancel={cancelGesture} onLostPointerCapture={() => { if (drag.current?.kind === 'link') { cancelGesture(); setLinking(false); setLinkFrom(''); } }} onClick={event => { if (event.detail === 0 && !locked) { setLinking(true); setLinkFrom(item.id); setNotice('点击目标节点完成连线，Esc 取消。'); } }} />}</Fragment>; })}
        </div></div>
      </div>
      {contextOpen && menuPoint && !panning && !preview && !linking && !addOpen && !inspectorOpen && <div className="rd-canvas-context" style={menuStyle} role="toolbar" aria-label={edge ? '连线操作' : '节点操作'} onPointerDown={event => event.stopPropagation()}>{node ? <>
        <button type="button" className="rd-canvas-icon" title={readOnly ? '查看节点' : '编辑节点'} aria-label={readOnly ? '查看节点' : '编辑节点'} onClick={inspect}><CanvasIcon name={readOnly ? 'view' : 'edit'} /></button>
        {!readOnly && <><button type="button" className="rd-canvas-icon" title="新增节点" aria-label="在画布新增节点" disabled={!canAdd} onClick={() => setAddOpen(true)}><CanvasIcon name="add" /></button><button type="button" className="rd-canvas-icon" title="复制节点" aria-label="复制节点" disabled={disabled} onClick={copyNode}><CanvasIcon name="copy" /></button><button type="button" className="rd-canvas-icon danger" title={protectedNode ? '必需节点不能删除' : '删除节点'} aria-label="删除节点" disabled={disabled || protectedNode} onClick={removeSelection}><CanvasIcon name="delete" /></button></>}
      </> : <><span>依赖连线</span>{!readOnly && <button type="button" className="rd-canvas-icon danger" title="删除连线" aria-label="删除连线" disabled={disabled} onClick={removeSelection}><CanvasIcon name="delete" /></button>}<button type="button" className="rd-canvas-icon" title="取消选择" aria-label="取消选择连线" onClick={() => setSelectedEdge('')}><CanvasIcon name="close" /></button></>}</div>}
      {addOpen && !readOnly && <div className="rd-canvas-add-panel" role="region" aria-label="新增画布节点"><header><strong>新增节点</strong><button type="button" className="rd-canvas-icon" aria-label="关闭新增节点" title="关闭" onClick={() => setAddOpen(false)}><CanvasIcon name="close" /></button></header><StyledSelect aria-label="新增节点的固定能力" value={choice} options={[{ value: '', label: business ? '普通办理节点' : '选择已有动作' }, ...choices.map((item, index) => ({ value: String(index), label: `${item.title} · V${item.version}` }))]} disabled={disabled} onChange={setChoice} />{business && <small>{businessCategory === 'project' ? '新节点接入研制任务书生成之前。' : '新节点接入业务批准之前。'}</small>}<PlatformButton type="button" className="rd-button primary" disabled={!canAdd || (!business && !choices.some((_, index) => String(index) === choice))} onClick={add}>添加节点</PlatformButton></div>}
      </div>
      <div className="rd-canvas-footer"><span id={`${uid}-canvas-help`}>{readOnly ? '双击查看 · 拖动空白处浏览' : '双击编辑 · 拖圆点连线 · 选中线可删除'}</span>{notice && <span role="status">{notice}</span>}</div>
    </div>
    {inspectorOpen && <section className="rd-graph-inspector" aria-label="节点属性"><header><h4 ref={inspectorTitle} tabIndex={-1} className="rd-graph-inspector-title">节点属性{node && ` · ${nodeTitle(node)}`}</h4><button type="button" className="rd-canvas-icon" aria-label="关闭节点属性" title="关闭" onClick={() => { setInspectorOpen(false); if (node) nodeElements.current.get(node.id)?.focus({ preventScroll: true }); }}><CanvasIcon name="close" /></button></header>{!node ? <p className="rd-muted">添加或选择一个节点。</p> : <>
      <p className="rd-muted">{fixedResource ? resourceName(fixedResource) || '已绑定固定动作，详情见高级信息。' : node.gate ? '业务确认节点，由项目中相应决定记录推进。' : '普通办理节点，记录工作责任与预期成果。'}</p>
      {renderNodeDetails?.(node)}
      <fieldset disabled={locked}>
        <div className="rd-field"><label htmlFor={`${uid}-title`}>节点标题</label><input id={`${uid}-title`} value={node.title ?? ''} onChange={event => set({ title: event.target.value })} /></div>
        <div className="rd-field"><label htmlFor={`${uid}-role`}>负责角色</label><input id={`${uid}-role`} value={node.role ?? ''} onChange={event => set({ role: event.target.value })} /></div>
        <div className="rd-field"><label htmlFor={`${uid}-deliverables`}>交付物（每行一项）</label><textarea id={`${uid}-deliverables`} className="resize-none" rows={3} value={(node.deliverables ?? []).join('\n')} onChange={event => set({ deliverables: event.target.value.split('\n') })} /></div>
        {business && <div className="rd-field"><label id={`${uid}-business-resource-label`}>办理动作</label><StyledSelect aria-labelledby={`${uid}-business-resource-label`} value={node.action_resource ? node.action_resource.resource_id + '@' + node.action_resource.resource_version : ''} disabled={locked || !bindingAllowed} onChange={value => { const team = choices.find(item => item.id + '@' + item.version === value); set({ action_resource: team ? { resource_id: team.id, resource_version: team.version } : null, workpackage_definition_id: team ? definitionId : null }); }} options={[{ value: '', label: '普通业务办理节点', disabled: node.id === 'taskbook' }, ...choices.map(item => ({ value: item.id + '@' + item.version, label: item.title + ' · V' + item.version })), ...(node.action_resource && !choices.some(item => item.id === node.action_resource!.resource_id && String(item.version) === String(node.action_resource!.resource_version)) ? [{ value: node.action_resource.resource_id + '@' + node.action_resource.resource_version, label: '历史固定动作 · V' + node.action_resource.resource_version, disabled: true }] : [])]} /><small>{bindingAllowed ? '从已有动作中选择，保留固定版本。任务书节点须保留完整编制动作。' : businessCategory === 'project' ? '业务确认节点由项目中相应决定推进，不能用自动动作替代业务批准。' : '业务确认和后续阶段仅维护配置，不能用自动动作替代业务批准。'}</small></div>}
        {!business && allowRoutes && <div className="rd-field"><label id={`${uid}-route-label`}>适用路线</label><StyledSelect aria-labelledby={`${uid}-route-label`} value={node.route ?? ''} disabled={locked} onChange={value => set({ route: value || null })} options={[{ value: '', label: '所有业务路线' }, { value: 'direct', label: '成熟产品直接选用' }, { value: 'modification', label: '改型研发' }, { value: 'new', label: '全新研发' }]} /></div>}
      </fieldset>
      {!readOnly && onConfirm && <PlatformButton type="button" className="rd-button compact" disabled={disabled} onClick={() => onConfirm(node.id, 'role')}>确认角色约束</PlatformButton>}
      {!!confirmed.length && <p className="rd-muted">已确认约束：{confirmed.filter(item => item.node_id === node.id).map(item => ({ role: '负责角色', title: '节点标题', position: '节点位置', deliverables: '交付物' }[item.field] ?? item.field)).join('、') || '无'}</p>}
      <details className="rd-disclosure rd-graph-advanced"><summary>高级信息</summary><dl><dt>节点标识</dt><dd><code>{node.id}</code></dd>{fixedResource && <><dt>固定动作</dt><dd><code>{fixedResource}</code> · V{node.action_resource?.resource_version ?? node.resource_version ?? node.action_version}</dd></>}{business && <><dt>工作包范围</dt><dd>{node.action_resource ? (node.workpackage_definition_id ?? definitionId) === 'taskbook' ? '任务书装配与校验' : '资料一致性检查' : '无自动工作包'}</dd></>}</dl>
        <fieldset disabled={locked}><div className="rd-graph-coordinates">{(['x', 'y'] as const).map(axis => { const point = storedPosition(node, graph.nodes.indexOf(node)); return <div className="rd-field" key={axis}><label htmlFor={`${uid}-${axis}`}>{axis.toUpperCase()} 坐标</label><input id={`${uid}-${axis}`} type="number" min="0" value={point[axis]} onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value)) onChange([{ op: 'move_node', node_id: node.id, position: { ...point, [axis]: Math.max(0, value) } }]); }} /></div>; })}</div>
          {!business && <details className="rd-disclosure"><summary>指定输入来源节点</summary><p className="rd-muted">相同动作出现多次时，可指定本节点使用哪一步的结果。</p>{['resolve_context', 'template_plan', 'content_completion', 'generate', 'verify', 'consistency'].map(role => <div className="rd-field" key={role}><label id={`${uid}-binding-${role}`}>{({ resolve_context: '参数核对', template_plan: '模板装配', content_completion: '内容补缺', generate: '文档生成', verify: '质量验证', consistency: '一致性检查' } as Record<string, string>)[role]}输入</label><StyledSelect aria-labelledby={`${uid}-binding-${role}`} value={String(node.input_bindings?.[role] ?? '')} disabled={locked} onChange={value => { const bindings = { ...node.input_bindings }; if (value) bindings[role] = value; else delete bindings[role]; set({ input_bindings: bindings }); }} options={[{ value: '', label: '自动匹配唯一合适的来源' }, ...graph.nodes.filter(item => item.id !== node.id).map(item => ({ value: item.id, label: nodeTitle(item) })), ...upstreamNodes.filter(item => item.action_id === role).map(item => ({ value: 'upstream:' + item.id, label: '上游成果 / ' + item.title }))]} /></div>)}</details>}
        </fieldset>
      </details>
    </>}</section>}
  </div>;
}
