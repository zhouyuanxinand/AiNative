"""One structured draft language and a compiler into the existing leased DAG.

The compiler resolves resources; it never dispatches them. Historical graphs and
prepared candidates are values, while adoption is a separate project fact.
"""
from __future__ import annotations

import hashlib
import math
import re
from copy import deepcopy

from . import catalog
from .store import RdError, _id, _json, _now, _text
from .workspace import content_digest

COMMANDS = frozenset({'create_flow_draft', 'apply_flow_patch', 'validate_flow_draft',
    'prepare_execution_bundle', 'adopt_execution_bundle', 'simulate_execution_bundle', 'restore_flow_revision'})
NODE_FIELDS = {'id', 'action_id', 'action_version', 'resource_id', 'resource_version', 'title', 'role',
               'deliverables', 'position', 'input_bindings', 'required', 'route', 'inputs', 'outputs', 'business_node_id'}
REQUIRED_INPUTS = {'resolve_context': (), 'template_plan': ('resolve_context',),
    'content_completion': ('resolve_context', 'template_plan'),
    'generate': ('resolve_context', 'template_plan', 'content_completion'), 'verify': ('generate', 'template_plan', 'content_completion'), 'consistency': ()}


def digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def invalid(message, *, node_id=None, edge_id=None):
    error = RdError(422, message)
    error.node_id, error.edge_id = node_id, edge_id
    return error


def _identifier(value, label='节点ID'):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise RdError(422, label + '无效。')
    return value


def position_value(value):
    if not isinstance(value, dict) or set(value) != {'x', 'y'} or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 100000 for v in value.values()):
        raise RdError(422, '节点坐标无效。')
    return deepcopy(value)


def graph_value(graph):
    if not isinstance(graph, dict) or set(graph) != {'nodes', 'edges'}:
        raise RdError(422, '图只接受nodes和edges。')
    if not isinstance(graph['nodes'], list) or not 1 <= len(graph['nodes']) <= 64 or not isinstance(graph['edges'], list) or len(graph['edges']) > 512:
        raise RdError(422, '图应含1至64个节点及不超过512条边。')
    nodes, ids = [], set()
    for raw in graph['nodes']:
        if not isinstance(raw, dict) or set(raw) - NODE_FIELDS:
            raise RdError(422, '节点包含不支持的执行结构或属性。')
        n = deepcopy(raw)
        n['id'] = _identifier(n.get('id') or _id())
        if n['id'] in ids:
            raise RdError(422, '节点ID重复。')
        ids.add(n['id'])
        if 'business_node_id' in n:
            _identifier(n['business_node_id'], '业务节点ID')
        aid = n.get('action_id')
        n['resource_id'] = _identifier(n.get('resource_id') or aid, '资源ID')
        version = n.get('resource_version', 1)
        if type(version) is not int or version < 1:
            raise RdError(422, '资源固定版本必须为正整数。')
        n['resource_version'] = version
        n['action_version'] = n.get('action_version', '1')
        for field in ('title', 'role'):
            n[field] = _text(n.get(field, catalog.ACTION_TITLES.get(aid, n['resource_id']) if field == 'title' else '执行专家'), field, 200)
        if 'deliverables' not in n:
            n['deliverables'] = []
        if not isinstance(n['deliverables'], list) or any(not isinstance(v, str) or len(v) > 200 for v in n['deliverables']):
            raise RdError(422, '交付物须为文本列表。')
        p = n.get('position', {'x': 0, 'y': 0})
        n['position'] = position_value(p)
        if not isinstance(n.get('input_bindings', {}), dict):
            raise RdError(422, '输入绑定必须为角色到生产者ID的对象。')
        n.setdefault('input_bindings', {})
        if any(k not in catalog.ACTION_TITLES or not isinstance(v, str) for k, v in n['input_bindings'].items()):
            raise RdError(422, '输入绑定只接受已注册执行角色及生产者节点ID。')
        if 'required' in n and type(n['required']) is not bool:
            raise RdError(422, 'required须为布尔值。')
        for field in ('inputs', 'outputs'):
            if field in n and (not isinstance(n[field], list) or any(not isinstance(v, str) or not v or len(v) > 200 for v in n[field])):
                raise RdError(422, '输入输出合同须为明确的文本列表。')
        nodes.append(n)
    edges, edge_ids = [], set()
    for raw in graph['edges']:
        if not isinstance(raw, dict) or set(raw) - {'id', 'source', 'target'}:
            raise RdError(422, '连线不支持表达式、循环或并行调度结构。')
        e = {'id': _identifier(raw.get('id') or _id(), '连线ID'),
             'source': _identifier(raw.get('source')), 'target': _identifier(raw.get('target'))}
        if e['id'] in edge_ids:
            raise RdError(422, '连线ID重复。')
        edge_ids.add(e['id'])
        edges.append(e)
    return {'nodes': nodes, 'edges': edges}


def digests(graph):
    semantic = {'nodes': sorted([{k: v for k, v in n.items() if k != 'position'} for n in graph['nodes']], key=lambda n: n['id']),
                'edges': sorted(graph['edges'], key=lambda e: e['id'])}
    return {'digest': digest(graph), 'semantic_digest': digest(semantic),
            'layout_digest': digest({n['id']: n['position'] for n in graph['nodes']})}


def business_template(case, definition_id):
    selected = case.get('workflow_templates', {}).get('selection' if definition_id == 'input_check' else 'research')
    selected = selected or case.get('workflow_templates', {}).get('project')
    return selected if selected and selected.get('graph') else (case.get('taskbook_binding') or {}).get('workflow')


def default_graph(package, workflow=None, team_versions=None):
    if workflow and isinstance(workflow.get('graph'), dict):
        business = workflow['graph']
        _, dependencies = topological(business)
        selected = {n['id']: n for n in business['nodes'] if n.get('action_resource') and
            n.get('workpackage_definition_id', 'input_check' if workflow.get('category') == 'selection' else 'taskbook') == package['definition_id']}
        if selected:
            instances = {nid: 'action-' + _id() for nid in selected}
            nodes = [{'id': instances[nid], 'business_node_id': nid, **deepcopy(n['action_resource']),
                'title': n['title'], 'role': n['role'], 'deliverables': deepcopy(n.get('deliverables', [])),
                'position': deepcopy(n.get('position', {'x': 0, 'y': 0})), 'required': nid == 'taskbook'} for nid, n in selected.items()]
            def nearest(nid):
                result = set()
                for dep in dependencies[nid]:
                    if dep in selected:
                        result.add(dep)
                    else:
                        result.update(nearest(dep))
                return result
            edges = [{'id': _id(), 'source': instances[dep], 'target': instances[nid]} for nid in selected for dep in nearest(nid)]
            return graph_value({'nodes': nodes, 'edges': edges})
    team_by_definition = {'taskbook': 'taskbook-authoring-team', 'input_check': 'consistency-team',
                          'context_resolve': 'context-team', 'quality_check': 'quality-team'}
    definition = catalog.definition(package['definition_id'], package['definition_version'])
    if [n['action_id'] for n in package['nodes']] == definition['required_actions']:
        return graph_value({'nodes': [{'id': 'action-' + _id(), 'resource_id': team_by_definition[package['definition_id']],
            'resource_version': (team_versions or {}).get(team_by_definition[package['definition_id']], 1),
            'title': package['title'], 'role': '研发专家团', 'deliverables': [package['title']]}], 'edges': []})
    return graph_value({'nodes': [{k: v for k, v in n.items() if k in NODE_FIELDS} for n in package['nodes']],
        'edges': [{'id': 'edge-' + dep + '-' + n['id'], 'source': dep, 'target': n['id']} for n in package['nodes'] for dep in n['depends_on']]})


def topological(graph):
    nodes = {n['id']: n for n in graph['nodes']}
    deps = {nid: set() for nid in nodes}
    for e in graph['edges']:
        if e['source'] not in nodes or e['target'] not in nodes:
            raise invalid('图包含悬空连线。', edge_id=e['id'])
        deps[e['target']].add(e['source'])
    ordered, remaining = [], set(nodes)
    while remaining:
        ready = [n['id'] for n in graph['nodes'] if n['id'] in remaining and not deps[n['id']] & remaining]
        if not ready:
            raise invalid('图包含循环。', node_id=next(iter(remaining)))
        ordered.extend(ready)
        remaining.difference_update(ready)
    return ordered, deps


class Designer:
    COMMANDS = COMMANDS

    def __init__(self, store):
        self.store = store

    @staticmethod
    def initialize(case):
        for name in ('flow_drafts', 'execution_candidates', 'execution_adoptions', 'flow_simulations'):
            case.setdefault(name, [])

    @staticmethod
    def _find(case, name, identifier):
        item = next((v for v in case[name] if v['id'] == identifier), None)
        if item is None:
            raise RdError(404, '固定流程对象不存在。')
        return item

    def _draft(self, case, identifier):
        return self._find(case, 'flow_drafts', identifier)

    @staticmethod
    def _record(draft, actor, origin):
        draft.update(digests(draft['graph']), actor=actor, updated_at=_now())
        draft['history'].append({key: deepcopy(draft[key]) for key in ('revision', 'input_revision', 'graph', 'digest', 'semantic_digest', 'layout_digest', 'actor', 'updated_at')})
        draft['history'][-1]['origin'] = origin
        draft.pop('validation', None)

    def command(self, db, project, case, command, data, actor):
        self.initialize(case)
        if command == 'create_flow_draft':
            package = self.store._package(case, data.get('workpackage_id'))
            draft = {'id': _id(), 'workpackage_id': package['id'], 'definition_id': package['definition_id'],
                'definition_version': package['definition_version'], 'revision': 1, 'input_revision': case['input_revision'],
                'business_template': deepcopy(business_template(case, package['definition_id'])),
                'graph': graph_value(data['graph']) if 'graph' in data else default_graph(package, business_template(case, package['definition_id']), self.store.workspace.default_team_versions(db=db)),
                'history': [], 'confirmed_fields': [], 'conflicts': [], 'created_at': _now(), 'source_run_id': package.get('run_id')}
            self._record(draft, actor, 'manual')
            case['flow_drafts'].append(draft)
            # The presence of a designer draft makes downgrade through save_plan impossible.
            if package['status'] == 'draft':
                package['execution_schema_version'] = 3
            return {'draft_id': draft['id']}
        if command == 'apply_flow_patch':
            return self._patch(case, data, actor)
        if command == 'restore_flow_revision':
            old = self._draft(case, data.get('draft_id'))
            revision = next((r for r in old['history'] if r['revision'] == data.get('revision')), None)
            if revision is None:
                raise RdError(404, '草稿历史修订不存在。')
            source = self.store._package(case, old['workpackage_id'])
            # A restored proposal has its own execution target. Copying a Run's
            # mutable status or adopted result would manufacture execution facts.
            package = {k: deepcopy(source[k]) for k in ('definition_id', 'definition_version', 'required', 'title', 'stage',
                'planned_start', 'planned_end', 'plan_note', 'request_ref')}
            if 'business_node_id' in source:
                package['business_node_id'] = source['business_node_id']
            package.update(id=_id(), status='draft', execution_schema_version=3, plan_revision=1,
                schedule_revision=0, schedule_history=[], started_at=None, completed_at=None, ended_at=None,
                nodes=catalog.default_nodes(source['definition_id'], source['definition_version']), snapshot=None,
                run_id=None, artifacts=[], obligations=[], blocked_reasons=[], revision_of=source['id'], source_run_id=source.get('run_id'))
            case['workpackages'].append(package)
            new = {**deepcopy(old), 'id': _id(), 'revision': 1, 'input_revision': case['input_revision'], 'graph': deepcopy(revision['graph']),
                   'workpackage_id': package['id'], 'source_run_id': source.get('run_id'),
                   'business_template': deepcopy(business_template(case, package['definition_id'])),
                   'restored_business_template': deepcopy(old.get('business_template')),
                   'history': [], 'conflicts': [], 'restored_from': {'draft_id': old['id'], 'revision': revision['revision']}}
            self._record(new, actor, 'manual')
            case['flow_drafts'].append(new)
            return {'draft_id': new['id'], 'workpackage_id': package['id'], 'revision_of': source['id']}
        if command in {'validate_flow_draft', 'prepare_execution_bundle'}:
            draft = self._draft(case, data.get('draft_id'))
            validation, compiled, locks, mapping = self.validate(db, case, draft)
            draft['validation'] = validation
            if command == 'validate_flow_draft':
                return {'draft_id': draft['id'], 'valid': validation['valid']}
            if not validation['valid']:
                raise RdError(422, '草稿校验未通过：' + '；'.join(e['message'] for e in validation['errors']))
            previous = next((c for c in reversed(case['execution_candidates']) if c['workpackage_id'] == draft['workpackage_id']), None)
            candidate = {'id': _id(), 'schema_version': 3, 'draft_id': draft['id'], 'draft_revision': draft['revision'],
                'workpackage_id': draft['workpackage_id'], 'input_revision': case['input_revision'],
                'business_template': deepcopy(draft.get('business_template')),
                'graph': deepcopy(draft['graph']), 'semantic_digest': draft['semantic_digest'], 'layout_digest': draft['layout_digest'],
                'compiled_plan': compiled, 'resource_locks': locks, 'mapping': mapping, 'validation': validation,
                'input_digest': self.input_digest(case), 'rule_digest': self.rule_digest(),
                'upstream_reference': self.upstream_reference(case, draft),
                'diff': self.diff(previous['graph'] if previous else None, draft['graph']), 'actor': actor, 'created_at': _now()}
            candidate['digest'] = digest(candidate)
            case['execution_candidates'].append(candidate)
            return {'candidate_id': candidate['id'], 'candidate_digest': candidate['digest']}
        candidate = self._find(case, 'execution_candidates', data.get('candidate_id'))
        if command == 'simulate_execution_bundle':
            scenario = data.get('scenario', 'normal')
            if scenario not in {'normal', 'missing_input', 'rejected', 'cancelled'}:
                raise RdError(422, '未知的隔离模拟场景。')
            simulation = {'id': _id(), 'candidate_id': candidate['id'], 'scenario': scenario, 'isolated': True,
                'execution_mode': 'simulation', 'status': {'normal': 'completed', 'missing_input': 'blocked', 'rejected': 'blocked', 'cancelled': 'cancelled'}[scenario],
                'nodes': [{'id': n['id'], 'status': 'simulated' if scenario == 'normal' else scenario} for n in candidate['compiled_plan']],
                'actor': actor, 'created_at': _now()}
            case['flow_simulations'].append(simulation)
            return {'simulation_id': simulation['id']}
        if command == 'adopt_execution_bundle':
            if actor != project['owner_id']:
                raise RdError(403, '执行包采用仅由项目负责人办理。')
            if data.get('candidate_digest') != candidate['digest']:
                raise RdError(409, '候选摘要不匹配。')
            self.require_candidate(db, case, candidate)
            package = self.store._package(case, candidate['workpackage_id'])
            if package['status'] != 'draft':
                raise RdError(409, '在途或已执行工作包只读，请新建工作包修订后采用。')
            previous = package.get('execution_adoption_id')
            adoption = {'id': _id(), 'candidate_id': candidate['id'], 'candidate_digest': candidate['digest'],
                'workpackage_id': package['id'], 'previous_adoption_id': previous, 'actor': actor, 'created_at': _now()}
            case['execution_adoptions'].append(adoption)
            package.update(execution_adoption_id=adoption['id'], execution_schema_version=3,
                           nodes=deepcopy(candidate['compiled_plan']), plan_revision=package['plan_revision'] + 1)
            return {'adoption_id': adoption['id'], 'candidate_id': candidate['id']}
        raise RdError(422, '未知流程命令。')

    def _patch(self, case, data, actor):
        draft = self._draft(case, data.get('draft_id'))
        if type(data.get('expected_draft_revision')) is not int or data['expected_draft_revision'] != draft['revision'] or data.get('base_digest') != draft['digest']:
            raise RdError(409, '流程草稿已更新，请保留本地修改后重新读取。')
        origin = data.get('origin')
        ops = data.get('operations')
        if origin not in {'manual', 'assistant', 'dialogue'} or not isinstance(ops, list) or len(ops) > 256:
            raise RdError(422, '结构化修改来源或操作列表无效。')
        graph, confirmed, conflicts = deepcopy(draft['graph']), deepcopy(draft['confirmed_fields']), []
        for op in ops:
            if not isinstance(op, dict):
                raise RdError(422, '修改操作须为对象。')
            kind = op.get('op')
            node = next((n for n in graph['nodes'] if n['id'] == op.get('node_id')), None)
            if kind in {'remove_node', 'copy_node', 'set_node', 'move_node', 'confirm_field'} and node is None:
                raise RdError(404, '修改的节点不存在。')
            properties = op.get('properties', {})
            changed_fields = set(properties) if kind == 'set_node' and isinstance(properties, dict) else ({'position'} if kind == 'move_node' else {'*'})
            protected = [f for f in confirmed if f['node_id'] == op.get('node_id') and (f['field'] in changed_fields or '*' in changed_fields)]
            if origin != 'manual' and kind != 'confirm_field' and protected:
                conflicts.append({'id': _id(), 'operation': deepcopy(op), 'reason': '已确认约束须由人工明确修改。', 'confirmed_fields': protected})
                continue
            if kind == 'add_node':
                value = deepcopy(op.get('node'))
                if not isinstance(value, dict):
                    raise RdError(422, '新节点无效。')
                value.setdefault('id', _id())
                graph['nodes'].append(value)
            elif kind == 'remove_node':
                graph['nodes'].remove(node)
                graph['edges'] = [e for e in graph['edges'] if node['id'] not in (e['source'], e['target'])]
            elif kind == 'copy_node':
                copied = deepcopy(node)
                copied['id'] = _id()
                copied['position'] = {'x': node['position']['x'] + 40, 'y': node['position']['y'] + 40}
                copied['input_bindings'] = {}
                graph['nodes'].append(copied)
            elif kind == 'set_node':
                if not isinstance(properties, dict) or set(properties) - (NODE_FIELDS - {'id'}):
                    raise RdError(422, '节点属性无效。')
                node.update(deepcopy(properties))
            elif kind == 'move_node':
                node['position'] = deepcopy(op.get('position'))
            elif kind == 'add_edge':
                edge = deepcopy(op.get('edge'))
                if not isinstance(edge, dict):
                    raise RdError(422, '新连线无效。')
                edge.setdefault('id', _id())
                graph['edges'].append(edge)
            elif kind == 'remove_edge':
                if not any(e['id'] == op.get('edge_id') for e in graph['edges']):
                    raise RdError(404, '连线不存在。')
                graph['edges'] = [e for e in graph['edges'] if e['id'] != op['edge_id']]
            elif kind == 'confirm_field':
                if origin != 'manual' or op.get('field') not in NODE_FIELDS - {'id'}:
                    raise RdError(422, '只有人工可确认节点属性。')
                ref = {'node_id': node['id'], 'field': op['field']}
                if ref not in confirmed:
                    confirmed.append(ref)
            else:
                raise RdError(422, '不支持的结构化修改操作。')
        draft.update(graph=graph_value(graph), confirmed_fields=confirmed, conflicts=conflicts,
                     revision=draft['revision'] + 1, input_revision=case['input_revision'])
        self._record(draft, actor, origin)
        return {'draft_id': draft['id'], 'draft_revision': draft['revision'], 'conflicts': deepcopy(conflicts)}

    @staticmethod
    def input_digest(case):
        values = {k: case.get(k) for k in ('input_revision', 'context', 'sources', 'source_selection', 'requirements',
            'product_route', 'composition_route', 'model_selection', 'business_context', 'taskbook_binding', 'business_lifecycle', 'workflow_templates')}
        # Historical-only removal changes access to the catalog, not a candidate's inputs.
        # Reconstruct the original ordered records only for digest compatibility.
        values['sources'] = list(case.get('sources', []))
        for removed in reversed(case.get('deleted_sources', [])):
            original = {key: value for key, value in removed.items()
                        if key not in {'status', 'deleted_at', 'deleted_by', '_source_index'}}
            values['sources'].insert(removed['_source_index'], original)
        return digest(values)

    @staticmethod
    def rule_digest():
        from .store import _RULE_ROOT
        return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(_RULE_ROOT.glob('*.yaml'))})

    @staticmethod
    def diff(before, after):
        old = {n['id']: n for n in (before or {'nodes': []})['nodes']}
        new = {n['id']: n for n in after['nodes']}
        changed = [nid for nid in old.keys() & new.keys() if old[nid] != new[nid]]
        layout_only = bool(before) and digests(before)['semantic_digest'] == digests(after)['semantic_digest']
        return {'added': sorted(new.keys() - old.keys()), 'removed': sorted(old.keys() - new.keys()), 'changed': sorted(changed),
            'layout_only': layout_only, 'impact': '仅布局变化，不触发执行。' if layout_only else '影响下次采用；已提交Run保持固定。'}

    def require_candidate(self, db, case, candidate):
        value = {k: v for k, v in candidate.items() if k != 'digest'}
        if digest(value) != candidate['digest']:
            raise RdError(409, '固定候选内容摘要核验失败。')
        if candidate['input_revision'] != case['input_revision'] or candidate['input_digest'] != self.input_digest(case) or candidate['rule_digest'] != self.rule_digest():
            raise RdError(409, '候选固定输入或规则已变化，请准备新的候选。')
        for source in self.store._active_sources(case):
            self.store._checked_path(source)
        draft = self._draft(case, candidate['draft_id'])
        if candidate.get('upstream_reference') != self.upstream_reference(case, draft):
            raise RdError(409, '固定上游成果已变化，请重新准备候选。')
        if draft['revision'] != candidate['draft_revision'] or draft['semantic_digest'] != candidate['semantic_digest']:
            raise RdError(409, '草稿已有新修订，请重新准备候选。')
        for lock in candidate['resource_locks']:
            r = self.store._resource(db, lock['resource_id'], lock['resource_version'])
            if content_digest(r) != lock['content_digest'] or not self.store.workspace.capability_available(lock['resource_id'], lock['resource_version'], db=db):
                raise RdError(422, '候选资源版本或当前应用授权已失效。')
            if not lock.get('dependency_only') and self.store.workspace._grant(db, lock['resource_id'], lock['resource_version']).get('dependency_only'):
                raise RdError(422, '根资源已改为仅依赖授权，请重新准备候选。')

    def adopted_candidate(self, db, case, package):
        if not package.get('execution_adoption_id'):
            raise RdError(422, '请先保存并校验流程草稿、准备候选并明确采用后提交执行。')
        adoption = self._find(case, 'execution_adoptions', package.get('execution_adoption_id'))
        candidate = self._find(case, 'execution_candidates', adoption['candidate_id'])
        if candidate['workpackage_id'] != package['id'] or candidate['digest'] != adoption['candidate_digest']:
            raise RdError(409, '采用对象与工作包不匹配。')
        self.require_candidate(db, case, candidate)
        return candidate

    def upstream_reference(self, case, draft):
        package = self.store._package(case, draft['workpackage_id'])
        upstream = self.store._fixed_upstream(case, package)
        if not upstream:
            return None
        return {'workpackage_id': upstream['upstream_workpackage_id'], 'run_id': upstream['upstream_run_id'],
            'results_digest': digest(upstream['upstream_results']), 'bindings': deepcopy(upstream['upstream_bindings'])}

    def validate(self, db, case, draft):
        errors, plan, locks, mapping = [], [], [], []
        try:
            if draft['input_revision'] != case['input_revision']:
                raise RdError(409, '草稿输入已变化，请通过新修订核对当前输入。')
            if draft.get('conflicts'):
                raise RdError(422, '结构化建议有未解决的已确认约束冲突。')
            current_template = business_template(case, draft['definition_id'])
            if draft.get('business_template') != current_template:
                raise RdError(409, '草稿对应的业务模板已变化，请建立新的草稿并核对影响。')
            if current_template and current_template.get('category') == 'project':
                self._validate_project_actions(current_template, draft['graph'], draft['definition_id'])
            for source in self.store._active_sources(case):
                self.store._checked_path(source)
            fixed_upstream = self.store._fixed_upstream(case, self.store._package(case, draft['workpackage_id']))
            plan, locks, mapping = self.compile(db, draft['graph'], draft['definition_id'], draft['definition_version'],
                product_route=case.get('product_route'), upstream=fixed_upstream)
        except (RdError, KeyError, TypeError, ValueError, OSError) as error:
            errors.append({'code': 'invalid_graph', 'message': str(error) if isinstance(error, RdError) else '固定图、资源或来源无法核验。',
                **{key: getattr(error, key) for key in ('node_id', 'edge_id') if getattr(error, key, None)}})
        unique = {}
        for lock in locks:
            ref = (lock['resource_id'], lock['resource_version'])
            previous = unique.get(ref)
            if previous:
                lock = {**lock, 'dependency_only': lock['dependency_only'] and previous['dependency_only']}
            unique[ref] = lock
        return {'valid': not errors, 'errors': errors, 'warnings': []}, plan, list(unique.values()), mapping

    @staticmethod
    def _validate_project_actions(workflow, graph, definition_id):
        fixed = {node['id']: node for node in workflow['graph']['nodes'] if node.get('action_resource')
            and node.get('workpackage_definition_id', 'taskbook') == definition_id}
        instances = {}
        business_ids = {node['id'] for node in workflow['graph']['nodes']}
        for node in graph['nodes']:
            nid = node.get('business_node_id', node['id'])
            if nid in fixed:
                reference = fixed[nid]['action_resource']
                if node.get('route') is not None:
                    raise invalid('已发布项目流程的固定动作不能新增路线条件来跳过执行。', node_id=node['id'])
                if nid in instances or any(node.get(key) != reference[key] for key in ('resource_id', 'resource_version')):
                    raise invalid('已发布项目流程的动作与固定资源版本不能在工作包中替换。', node_id=node['id'])
                instances[nid] = node['id']
            elif nid in business_ids:
                raise invalid('技术执行节点不能冒用业务决定或资料节点的身份。', node_id=node['id'])
        if set(instances) != set(fixed):
            raise RdError(422, '工作包不能删去已发布项目流程的固定动作。')

        def ancestry(value):
            _, dependencies = topological(value)
            result = {}
            def parents(nid):
                if nid not in result:
                    result[nid] = set(dependencies[nid])
                    for parent in dependencies[nid]:
                        result[nid].update(parents(parent))
                return result[nid]
            return {nid: parents(nid) for nid in dependencies}

        business_parents, execution_parents = ancestry(workflow['graph']), ancestry(graph)
        for nid, instance in instances.items():
            for parent in set(instances) & business_parents[nid]:
                if instances[parent] not in execution_parents[instance]:
                    raise invalid('工作包不能绕过已发布项目流程动作之间的前置关系。', node_id=instance)

    def compile(self, db, graph, definition_id, definition_version, *, product_route=None, upstream=None):
        plan, locks, mapping = [], [], []
        graph = graph_value(graph)
        ordered, deps = topological(graph)
        by_id = {n['id']: n for n in graph['nodes']}
        expansions = {}
        for nid in ordered:
            n = by_id[nid]
            if not n['role']:
                raise invalid('节点必须指定执行责任角色。', node_id=nid)
            route = n.get('route')
            if route is not None:
                chosen = (product_route or {}).get('value')
                if route not in {'direct', 'modification', 'new'} or chosen not in {'direct', 'modification', 'new'}:
                    raise invalid('有限路线必须来自有效业务决定。', node_id=nid)
                if route != chosen:
                    expansions[nid] = []
                    continue
            try:
                steps, resource_locks = self.expand(db, n['resource_id'], n['resource_version'], nid)
            except RdError as error:
                error.node_id = nid
                raise
            resource = self.store._resource(db, n['resource_id'], n['resource_version'])
            if n.get('action_id') is not None and (resource['kind'] != 'skill' or n['action_id'] != resource['configuration'].get('action_id')):
                raise invalid('动作标识与固定资源的执行器绑定不匹配。', node_id=nid)
            contracts = ({'inputs': list(REQUIRED_INPUTS[steps[0]['action_id']]), 'outputs': [steps[0]['action_id']]}
                if resource['kind'] == 'skill' else {k: resource['configuration'][k] for k in ('inputs', 'outputs')})
            if any(field in n and n[field] != contracts[field] for field in ('inputs', 'outputs')):
                raise invalid('节点输入输出合同与固定资源版本不匹配。', node_id=nid)
            locks.extend(resource_locks)
            expansions[nid] = steps
            for step in steps:
                step['business_node_id'] = n.get('business_node_id', nid)
                step['action_instance_id'] = nid
                step['step_instance_id'] = step['id']
                mapping.append({k: step[k] for k in ('business_node_id', 'action_instance_id', 'step_instance_id', 'action_id')})
        for nid in ordered:
            steps = expansions[nid]
            if not steps:
                continue
            internal_ids = {s['id'] for s in steps}
            roots = [s for s in steps if not set(s['depends_on']) & internal_ids]
            upstream_dependencies = []
            def sinks(parent):
                items = expansions[parent]
                if not items:
                    return [s for dep in deps[parent] for s in sinks(dep)]
                used = {v for s in items for v in s['depends_on']}
                return [s['id'] for s in items if s['id'] not in used]
            for parent in deps[nid]:
                upstream_dependencies.extend(sinks(parent))
            for root in roots:
                root['depends_on'] = sorted(set(root['depends_on'] + upstream_dependencies))
            for role, producer in by_id[nid].get('input_bindings', {}).items():
                if producer.startswith('upstream:'):
                    for step in steps:
                        step['input_bindings'][role] = producer
                    continue
                candidates = [s['id'] for s in expansions.get(producer, []) if s['action_id'] == role]
                if producer in {s['id'] for values in expansions.values() for s in values}:
                    candidates = [producer]
                if len(candidates) != 1:
                    raise invalid('业务节点输入绑定必须明确指向唯一匹配的Skill生产者。', node_id=nid)
                for step in steps:
                    if role in REQUIRED_INPUTS[step['action_id']] or role in step.get('input_bindings', {}):
                        step['input_bindings'][role] = candidates[0]
            if len(steps) == 1:
                for role, producer in by_id[nid].get('input_bindings', {}).items():
                    candidates = [s['id'] for s in expansions.get(producer, []) if s['action_id'] == role]
                    steps[0]['input_bindings'][role] = candidates[0] if len(candidates) == 1 else producer
                steps[0].update({k: deepcopy(by_id[nid][k]) for k in ('title', 'role', 'deliverables', 'position')})
            plan.extend(steps)
        base = self.store._validate_plan(db, definition_id, plan, definition_version, allow_duplicate_required=True)
        for clean, original in zip(base, plan):
            clean.update({k: deepcopy(v) for k, v in original.items() if k not in clean})
        plan = base
        self.bind_inputs(plan, definition_id, upstream)
        return plan, locks, mapping

    def expand(self, db, rid, version, prefix, visiting=None):
        visiting = set() if visiting is None else visiting
        ref = (rid, version)
        if ref in visiting:
            raise RdError(422, '专家团依赖包含循环。')
        if not self.store.workspace.capability_available(rid, version, db=db):
            raise RdError(422, '固定资源未发布、已撤权或依赖许可失效。')
        resource = self.store._resource(db, rid, version)
        if not visiting and self.store.workspace._grant(db, rid, version).get('dependency_only'):
            raise RdError(422, '依赖专用资源不能作为独立业务节点采用。')
        lock = {'resource_id': rid, 'resource_version': version, 'content_digest': content_digest(resource), 'dependency_only': bool(visiting)}
        if resource['kind'] == 'skill':
            aid = resource['configuration'].get('action_id')
            # Only the original registered skills are bound to actual executors.
            if rid != aid or version != 1 or aid not in catalog.ACTION_TITLES or not resource.get('executable') or resource['execution_mode'] != 'local_real':
                raise RdError(422, '资源未绑定本地六个实际执行器之一。')
            return [{'id': prefix, 'action_id': aid, 'action_version': '1', 'resource_id': rid, 'resource_version': version,
                'depends_on': [], 'required': True, 'input_bindings': {}}], [lock]
        if resource['kind'] != 'team':
            raise RdError(422, 'Agent声明没有可执行Skill图，不能直接派工。')
        if resource['execution_mode'] != 'local_real' or not resource.get('executable'):
            raise RdError(422, '专家团没有已绑定的本地真实执行合同。')
        cfg = resource['configuration']
        if any(not isinstance(cfg.get(field), list) or any(not isinstance(v, str) or not v for v in cfg[field]) for field in ('inputs', 'outputs')):
            raise RdError(422, '专家团须声明输入和输出合同。')
        internal = self.store.workspace.validate_team_graph(db, resource)
        order, deps = topological(internal)
        members = set(self.store.workspace._members(resource))
        if {(n['resource_id'], n['resource_version']) for n in internal['nodes']} != members:
            raise RdError(422, '专家团执行图与固定成员引用不一致。')
        visiting.add(ref)
        expanded, locks, by_local = [], [lock], {}
        for n in internal['nodes']:
            steps, childlocks = self.expand(db, n['resource_id'], n['resource_version'], prefix + '__' + n['id'], visiting)
            if len(steps) != 1:
                raise RdError(422, '当前专家团内部图只支持直接绑定Skill，嵌套专家团请先展开。')
            step = steps[0]
            step['depends_on'] = [prefix + '__' + dep for dep in deps[n['id']]]
            step['input_bindings'] = {role: prefix + '__' + producer for role, producer in n.get('input_bindings', {}).items()}
            by_local[n['id']] = step
            locks.extend(childlocks)
        visiting.remove(ref)
        expanded = [by_local[nid] for nid in order]
        # These references are derived from the immutable team's own DAG before
        # combining instances, so another team with the same role cannot win.
        self.bind_inputs(expanded, 'input_check')
        return expanded, locks

    @staticmethod
    def bind_inputs(plan, definition_id, upstream=None):
        by_id = {n['id']: n for n in plan}
        upstream_nodes = {n['id']: n for n in (upstream or {}).get('upstream_nodes', [])}
        def ancestors(nid):
            result = set(by_id[nid]['depends_on'])
            for dep in by_id[nid]['depends_on']:
                result.update(ancestors(dep))
            return result
        for n in plan:
            bindings = n.setdefault('input_bindings', {})
            available = ancestors(n['id'])
            for role, producer in bindings.items():
                if producer.startswith('upstream:'):
                    fixed = upstream_nodes.get(producer.removeprefix('upstream:'))
                    if not fixed or fixed['action_id'] != role:
                        raise invalid('上游输入必须引用同案固定成果中的明确匹配生产者。', node_id=n['id'])
                    continue
                if producer not in available or by_id[producer]['action_id'] != role:
                    raise invalid('输入绑定的生产者必须是前置且输出角色匹配的节点。', node_id=n['id'])
            for role in REQUIRED_INPUTS[n['action_id']]:
                choices = [nid for nid in available if by_id[nid]['action_id'] == role]
                if not choices:
                    choices = ['upstream:' + nid for nid, fixed in upstream_nodes.items() if fixed['action_id'] == role]
                if role not in bindings:
                    if len(choices) == 1:
                        bindings[role] = choices[0]
                    elif not choices and definition_id in {'quality_check', 'context_resolve', 'input_check'}:
                        continue  # Existing executor supports fixed upstream or source inputs.
                    else:
                        raise invalid('缺少明确输入生产者绑定：' + n['id'] + '/' + role, node_id=n['id'])
            # Optional executor reads also receive only unique ancestor roles.
            for role in catalog.ACTION_TITLES:
                choices = [nid for nid in available if by_id[nid]['action_id'] == role]
                if len(choices) == 1:
                    bindings.setdefault(role, choices[0])
