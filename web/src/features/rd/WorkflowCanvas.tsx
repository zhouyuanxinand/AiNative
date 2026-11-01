import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { Action, PlanNode } from './types';
import { statusTitle } from './presentation';
import { layoutWorkflow, NODE_HEIGHT, NODE_WIDTH, type PositionedNode } from './workflowLayout';
import './workflowCanvas.css';

function connector(from: PositionedNode, to: PositionedNode) {
  if (from.x === to.x) {
    const x = from.x + NODE_WIDTH / 2, y1 = from.y + NODE_HEIGHT, y2 = to.y;
    return `M${x},${y1} C${x},${(y1 + y2) / 2} ${x},${(y1 + y2) / 2} ${x},${y2 - 5}`;
  }
  const forward = to.x > from.x;
  const x1 = from.x + (forward ? NODE_WIDTH : 0), x2 = to.x + (forward ? 0 : NODE_WIDTH);
  const y1 = from.y + NODE_HEIGHT / 2, y2 = to.y + NODE_HEIGHT / 2;
  return `M${x1},${y1} C${(x1+x2)/2},${y1} ${(x1+x2)/2},${y2} ${x2 + (forward ? -5 : 5)},${y2}`;
}

export function WorkflowCanvas({ nodes, actions, selectedId, onSelectNode, title = '节点画布', definition = false }: {
  nodes: PlanNode[]; actions: Action[]; selectedId?: string; onSelectNode?: (id: string) => void; title?: string; definition?: boolean;
}) {
  const graph = useMemo(() => layoutWorkflow(nodes), [nodes]);
  const viewport = useRef<HTMLDivElement>(null);
  const marker = `workflow-arrow-${useId().replace(/:/g, '')}`;
  const [mode, setMode] = useState<'canvas' | 'list'>('canvas');
  const [size, setSize] = useState({ width: 800, height: 390 });
  const [view, setView] = useState({ x: 0, y: 0, zoom: 1 });
  const drag = useRef<{ x: number; y: number; startX: number; startY: number }>();
  const fit = () => {
    const element = viewport.current;
    const width = element?.clientWidth ?? size.width, height = element?.clientHeight ?? size.height;
    const zoom = Math.min(1, (width - 24) / graph.width, (height - 24) / graph.height);
    setView({ zoom: Math.max(.25, zoom), x: (width - graph.width * zoom) / 2, y: (height - graph.height * zoom) / 2 });
  };
  const structure = nodes.map(node => `${node.id}:${node.depends_on.join(',')}`).join('|');
  useEffect(() => {
    const element = viewport.current; if (!element) return;
    const observer = new ResizeObserver(() => setSize({ width: element.clientWidth, height: element.clientHeight }));
    observer.observe(element); return () => observer.disconnect();
  }, [mode]);
  useEffect(() => { fit(); }, [structure, mode, size.width, size.height]);
  const zoomTo = (zoom: number) => setView(current => {
    const next = Math.min(1.5, Math.max(.25, zoom));
    return { zoom: next, x: size.width / 2 - (size.width / 2 - current.x) * next / current.zoom, y: size.height / 2 - (size.height / 2 - current.y) * next / current.zoom };
  });
  const name = (id: string) => actions.find(action => action.id === id)?.title ?? actions.find(action => action.id === id)?.name ?? id;
  const status = (node: PlanNode) => definition ? '模板节点' : node.status ? statusTitle(node.status) : '待执行';
  return <section className="rd-workflow-canvas" aria-label={title}>
    <div className="rd-canvas-toolbar"><div><strong>{title}</strong><span>{nodes.length} 个节点 · {nodes.reduce((sum, node) => sum + node.depends_on.length, 0)} 条依赖</span></div><div className="rd-canvas-controls">
      <button type="button" aria-pressed={mode === 'canvas'} onClick={() => setMode('canvas')}>画布</button><button type="button" aria-pressed={mode === 'list'} onClick={() => setMode('list')}>列表</button>
      {mode === 'canvas' && <><button type="button" aria-label="缩小画布" disabled={view.zoom <= .25} onClick={() => zoomTo(view.zoom - .15)}>−</button><span className="rd-canvas-scale" aria-live="polite">{Math.round(view.zoom * 100)}%</span><button type="button" aria-label="放大画布" disabled={view.zoom >= 1.5} onClick={() => zoomTo(view.zoom + .15)}>＋</button><button type="button" onClick={fit}>适应画布</button></>}
    </div></div>
    {graph.errors.length > 0 && <p className="rd-error rd-canvas-error" role="alert">{graph.errors.join(' ')}</p>}
    {!nodes.length ? <div className="rd-management-empty">尚无计划节点。</div> : mode === 'list' || graph.errors.length ? <ol className="rd-canvas-list">{nodes.map(node => <li key={node.id}><button type="button" aria-pressed={selectedId === node.id} onClick={() => onSelectNode?.(node.id)}><strong>{name(node.action_id)}</strong><span>{node.required ? '必需' : '可选'} · {status(node)}</span><small>前置：{node.depends_on.map(id => name(nodes.find(n => n.id === id)?.action_id ?? id)).join('、') || '无'}</small></button></li>)}</ol> : <div ref={viewport} className="rd-canvas-viewport" tabIndex={0} aria-label="流程画布，可拖动空白区域平移，方向键移动视图" onKeyDown={event => {
      if (event.target !== event.currentTarget) return;
      const delta = { ArrowLeft: [60, 0], ArrowRight: [-60, 0], ArrowUp: [0, 60], ArrowDown: [0, -60] }[event.key];
      if (delta) { event.preventDefault(); setView(current => ({ ...current, x: current.x + delta[0], y: current.y + delta[1] })); }
    }} onPointerDown={event => {
      if (event.button !== 0 || (event.target as Element).closest('button')) return;
      drag.current = { x: event.clientX, y: event.clientY, startX: view.x, startY: view.y }; event.currentTarget.setPointerCapture(event.pointerId);
    }} onPointerMove={event => { const start = drag.current; if (start) setView(current => ({ ...current, x: start.startX + event.clientX - start.x, y: start.startY + event.clientY - start.y })); }} onPointerUp={() => { drag.current = undefined; }} onPointerCancel={() => { drag.current = undefined; }} onLostPointerCapture={() => { drag.current = undefined; }}>
      <div className="rd-canvas-plane" style={{ width: graph.width, height: graph.height, transform: `translate(${view.x}px,${view.y}px) scale(${view.zoom})` }}>
        <svg width={graph.width} height={graph.height} className="rd-canvas-edges" aria-hidden="true"><defs><marker id={marker} markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" /></marker></defs>{graph.positions.flatMap(to => to.node.depends_on.map(id => { const from = graph.positions.find(p => p.node.id === id); return from ? <path key={`${id}-${to.node.id}`} d={connector(from, to)} markerEnd={`url(#${marker})`} className={selectedId === to.node.id || selectedId === id ? 'is-selected' : ''} /> : null; }))}</svg>
        {graph.positions.map(({ node, x, y }, index) => <button key={node.id} type="button" className={`rd-canvas-node ${node.status ?? 'draft'}${selectedId === node.id ? ' is-selected' : ''}`} aria-pressed={selectedId === node.id} aria-label={`${name(node.action_id)}，${status(node)}`} onClick={() => onSelectNode?.(node.id)} onFocus={event => {
          const rect = event.currentTarget.getBoundingClientRect(), bounds = viewport.current?.getBoundingClientRect();
          if (bounds && (rect.left < bounds.left || rect.right > bounds.right || rect.top < bounds.top || rect.bottom > bounds.bottom)) setView(current => ({ ...current, x: size.width / 2 - (x + NODE_WIDTH / 2) * current.zoom, y: size.height / 2 - (y + NODE_HEIGHT / 2) * current.zoom }));
        }} style={{ left: x, top: y, width: NODE_WIDTH, height: NODE_HEIGHT }}><span className="rd-canvas-node-index">{String(index + 1).padStart(2, '0')}</span><strong>{name(node.action_id)}</strong><span className="rd-canvas-node-meta">{node.required ? '必需' : '可选'} · {status(node)}</span></button>)}
      </div>
    </div>}
    <div className="rd-canvas-caption"><span>连线表示前置依赖，点击节点查看详情</span><span>{definition ? '模板预览' : '节点状态来自当前计划'} · 拖动画布 / 方向键平移</span></div>
  </section>;
}
