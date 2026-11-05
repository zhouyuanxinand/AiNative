"""Governed business workflows, independent of Workspace capability graphs."""
from copy import deepcopy
import json

from . import catalog
from .store import RdError, _actor, _id, _json, _now, _text
from .designer import digest, topological

MANDATORY = {'selection': ('input', 'confirm_requirements', 'comparison', 'selection_decision', 'rd_start'),
             'project': ('input', 'confirm_requirements', 'comparison', 'selection_decision', 'rd_start', 'taskbook'),
             'research': ('taskbook', 'taskbook_scope', 'scheme', 'detail', 'integration', 'verification', 'delivery')}
GATES = {'confirm_requirements': 'requirements', 'selection_decision': 'selection', 'rd_start': 'rd_start',
         'taskbook_scope': 'taskbook_scope', 'verification': 'verification', 'delivery': 'delivery'}
LABELS = {'input': '资料受理', 'confirm_requirements': '需求确认', 'comparison': '成熟产品比对', 'selection_decision': '选型决定',
          'rd_start': '研发启动依据', 'taskbook': '研制任务书策划', 'taskbook_scope': '任务书范围批准',
          'scheme': '方案设计', 'detail': '详细设计', 'integration': '整合', 'verification': '验证与审签', 'delivery': '交付接收'}


class WorkflowTemplates:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        with self.store._transaction() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS workflow_template_versions(
                id TEXT,version TEXT,payload TEXT NOT NULL,PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS workflow_template_heads(id TEXT PRIMARY KEY,version TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workflow_template_publications(
                id TEXT,version TEXT,status TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS workflow_template_receipts(actor TEXT,key TEXT,fingerprint TEXT,response TEXT,PRIMARY KEY(actor,key));
                CREATE TABLE IF NOT EXISTS workflow_template_audit(id TEXT PRIMARY KEY,payload TEXT NOT NULL);''')
            for category, seeds in (('selection', catalog.SELECTION_WORKFLOW_TEMPLATES), ('research', catalog.RESEARCH_WORKFLOW_TEMPLATES),
                                    ('project', catalog.PROJECT_WORKFLOW_TEMPLATES)):
                for seed in seeds:
                    ids = MANDATORY[category]
                    graph = {'nodes': [{'id': nid, 'title': LABELS[nid], 'role': '项目负责人' if nid in GATES else '研发工程师',
                        'deliverables': [LABELS[nid] + '记录'], 'position': {'x': i * 240, 'y': 0},
                        **({'action_resource': {'resource_id': 'taskbook-authoring-team', 'resource_version': 1}} if nid == 'taskbook' else {}),
                        **({'workpackage_definition_id': 'taskbook'} if nid == 'taskbook' else {}),
                        **({'gate': GATES[nid]} if nid in GATES else {})} for i, nid in enumerate(ids)],
                        'edges': [{'id': 'edge-' + a + '-' + b, 'source': a, 'target': b} for a, b in zip(ids, ids[1:])]}
                    if category == 'project':
                        next(n for n in graph['nodes'] if n['id'] == 'taskbook').update(
                            title='研制任务书生成', deliverables=['受控研制任务书', '质量校验结果'])
                    value = {**deepcopy(seed), 'category': category, 'graph': graph, 'actor': 'system-bootstrap', 'created_at': _now()}
                    value.pop('status', None)
                    value['digest'] = digest(value)
                    db.execute('INSERT OR IGNORE INTO workflow_template_versions VALUES(?,?,?)', (seed['id'], seed['version'], _json(value)))
                    db.execute('INSERT OR IGNORE INTO workflow_template_heads VALUES(?,?)', (seed['id'], seed['version']))
                    db.execute('INSERT OR IGNORE INTO workflow_template_publications VALUES(?,?,?,1)', (seed['id'], seed['version'], 'published'))

    @staticmethod
    def _permission(permissions, name):
        if not isinstance(permissions, dict) or permissions.get(name) is not True:
            raise RdError(403, '当前主体没有业务流程模板治理权限。')

    def _detail(self, db, rid, version=None, management=False):
        from .designer import _identifier
        _identifier(rid, '业务模板ID')
        if version is not None and (not isinstance(version, str) or not 1 <= len(version) <= 10 or not version.isascii() or not version.isdecimal() or int(version) < 1):
            raise RdError(422, '业务模板固定版本须为正整数字符串。')
        if version is None:
            if not management:
                rows = db.execute('SELECT v.version,v.payload FROM workflow_template_versions v JOIN workflow_template_publications p ON v.id=p.id AND v.version=p.version WHERE v.id=? AND p.status=? ORDER BY CAST(v.version AS INTEGER) DESC', (rid, 'published')).fetchall()
                version = next((r['version'] for r in rows if self._references_available(db, json.loads(r['payload']))), None)
            else:
                row = db.execute('SELECT version FROM workflow_template_heads WHERE id=?', (rid,)).fetchone()
                version = row[0] if row else None
            if version is None:
                raise RdError(404, '业务流程模板不存在或没有获准发布版。')
        row = db.execute('SELECT v.payload,p.status,p.revision FROM workflow_template_versions v JOIN workflow_template_publications p ON v.id=p.id AND v.version=p.version WHERE v.id=? AND v.version=?', (rid, version)).fetchone()
        if row is None or (not management and row['status'] != 'published'):
            raise RdError(404, '业务流程模板固定版不存在或未发布。')
        result = json.loads(row[0])
        if not management and not self._references_available(db, result):
            raise RdError(404, '业务流程模板包含未授权动作。')
        result.update(status=row['status'], publication_revision=row['revision'])
        result['head_version'] = db.execute('SELECT version FROM workflow_template_heads WHERE id=?', (rid,)).fetchone()[0]
        result['available_versions'] = [r['version'] for r in db.execute('SELECT v.version,v.payload FROM workflow_template_versions v JOIN workflow_template_publications p ON v.id=p.id AND v.version=p.version WHERE v.id=? AND (? OR p.status=?) ORDER BY CAST(v.version AS INTEGER) DESC', (rid, int(management), 'published'))
            if management or self._references_available(db, json.loads(r['payload']))]
        if not management:
            result['head_version'] = result['available_versions'][0]
        checked = db.execute("SELECT payload FROM workflow_template_audit WHERE json_extract(payload,'$.template_id')=? AND json_extract(payload,'$.version')=? AND json_type(payload,'$.validation')='object' ORDER BY rowid DESC LIMIT 1", (rid, version)).fetchone()
        if checked:
            result['validation'] = json.loads(checked[0])['validation']
        return result

    def _references_available(self, db, value):
        return all(not node.get('action_resource') or self.store.workspace.root_available(
            node['action_resource']['resource_id'], node['action_resource']['resource_version'], db=db)
            for node in value['graph']['nodes'])

    def detail(self, actor, rid, version=None, permissions=None, *, management=False):
        _actor(actor)
        if management:
            if not isinstance(permissions, dict) or not any(permissions.get(k) is True for k in ('can_edit_workflows', 'can_publish_workflows')):
                raise RdError(403, '当前主体没有业务流程模板治理权限。')
        with self.store._connection() as db:
            return self._detail(db, rid, version, management)

    def list(self, actor, permissions=None, *, category=None, q='', page=1, page_size=5, management=False):
        _actor(actor)
        if category is not None and category not in MANDATORY:
            raise RdError(422, '业务流程模板分类无效。')
        if management and (not isinstance(permissions, dict) or not any(permissions.get(k) is True for k in ('can_edit_workflows', 'can_publish_workflows'))):
            raise RdError(403, '当前主体没有业务流程模板治理权限。')
        with self.store._connection() as db:
            items = []
            for row in db.execute('SELECT id FROM workflow_template_heads ORDER BY id'):
                try:
                    value = self._detail(db, row[0], management=management)
                except RdError as error:
                    if error.status == 404 and not management:
                        continue
                    raise
                if category is None or value['category'] == category:
                    items.append(value)
        return self.store.workspace._page(items, q=q, page=page, page_size=page_size)

    def _validate_graph(self, db, category, graph, *, publication=True):
        if not isinstance(graph, dict) or set(graph) != {'nodes', 'edges'} or not isinstance(graph['nodes'], list) or not 1 <= len(graph['nodes']) <= 64 or not isinstance(graph['edges'], list) or len(graph['edges']) > 512:
            raise RdError(422, '流程应包含 1 至 64 个节点及不超过 512 条连线。')
        from .designer import _identifier, position_value
        nodes, ids = [], set()
        for n in graph['nodes']:
            if not isinstance(n, dict) or set(n) - {'id', 'title', 'role', 'deliverables', 'position', 'gate', 'action_resource', 'workpackage_definition_id'}:
                raise RdError(422, '业务图不接受任意表达式、循环或并行调度。')
            nid = _identifier(n.get('id'))
            if nid in ids:
                raise RdError(422, '业务节点ID重复。')
            ids.add(nid)
            value = {'id': nid, 'title': _text(n.get('title'), '业务节点名称', 200, publication),
                'role': _text(n.get('role'), '业务责任', 200, publication), 'deliverables': deepcopy(n.get('deliverables', [])),
                'position': position_value(n.get('position', {'x': 0, 'y': 0}))}
            if not isinstance(value['deliverables'], list) or len(value['deliverables']) > 100 or any(not isinstance(v, str) or len(v) > 500 for v in value['deliverables']):
                raise RdError(422, '业务交付物须为文本列表。')
            if nid in GATES:
                if n.get('gate') != GATES[nid]:
                    raise RdError(422, '不能删除或改变必需业务关口。')
                value['gate'] = GATES[nid]
            elif 'gate' in n:
                raise RdError(422, '新增业务关口需注册政策，不能由图声明批准。')
            if 'action_resource' in n:
                if nid in GATES:
                    raise RdError(422, '业务决定关口不能绑定技术执行来代替批准，请使用独立动作节点。')
                ref = n['action_resource']
                if not isinstance(ref, dict) or set(ref) != {'resource_id', 'resource_version'} or not isinstance(ref.get('resource_id'), str) or type(ref.get('resource_version')) is not int or ref['resource_version'] < 1:
                    raise RdError(422, '业务动作引用须为获准固定专家团。')
                _identifier(ref['resource_id'], '动作标识')
                resource = self.store._resource(db, ref['resource_id'], ref['resource_version'])
                if resource['kind'] != 'team' or not resource.get('executable'):
                    raise RdError(422, '业务动作须引用可执行专家团。')
                if publication and not self.store.workspace.capability_available(ref['resource_id'], ref['resource_version'], db=db):
                    raise RdError(422, '业务动作固定版本当前未获准使用，请重新选择后校验。')
                if publication and self.store.workspace._grant(db, ref['resource_id'], ref['resource_version']).get('dependency_only'):
                    raise RdError(422, '依赖专用资源不能成为业务动作根。')
                value['action_resource'] = deepcopy(ref)
                scope = n.get('workpackage_definition_id', 'input_check' if category == 'selection' else 'taskbook')
                if scope != ('input_check' if category == 'selection' else 'taskbook'):
                    raise RdError(422, '当前业务模板尚未绑定该阶段或工作包执行范围。')
                value['workpackage_definition_id'] = scope
                if publication:
                    steps, _ = self.store.designer.expand(db, ref['resource_id'], ref['resource_version'], 'validate')
                    if nid == 'taskbook':
                        self.store._validate_plan(db, 'taskbook', steps, '2', allow_duplicate_required=True)
                    elif any(s['action_id'] not in ({'consistency'} if category == 'selection' else set(catalog.ACTION_TITLES)) for s in steps):
                        raise RdError(422, '选型资料检查只能绑定实际一致性检查能力。')
            nodes.append(value)
        edges = []
        edge_ids = set()
        for e in graph['edges']:
            if not isinstance(e, dict) or set(e) - {'id', 'source', 'target'}:
                raise RdError(422, '业务连线无效。')
            edge = {'id': _identifier(e.get('id') or _id()), 'source': _identifier(e.get('source')), 'target': _identifier(e.get('target'))}
            if edge['id'] in edge_ids:
                raise RdError(422, '业务连线ID重复。')
            if edge['source'] not in ids or edge['target'] not in ids:
                from .designer import invalid
                raise invalid('连线引用的节点不存在，请删除该连线或恢复节点。', edge_id=edge['id'])
            edge_ids.add(edge['id'])
            edges.append(edge)
        result = {'nodes': nodes, 'edges': edges}
        if not publication:
            return result
        missing = [nid for nid in MANDATORY[category] if nid not in ids]
        if missing:
            from .designer import invalid
            raise invalid('流程缺少必需节点：' + '、'.join(LABELS[nid] for nid in missing), node_id=missing[0])
        _, deps = topological(result)
        ancestor_cache = {}
        def ancestors(nid):
            if nid in ancestor_cache:
                return ancestor_cache[nid]
            values = set(deps[nid])
            for dep in deps[nid]:
                values.update(ancestors(dep))
            ancestor_cache[nid] = values
            return values
        for a, b in zip(MANDATORY[category], MANDATORY[category][1:]):
            if a not in ancestors(b):
                from .designer import invalid
                raise invalid(f'“{LABELS[b]}”需要在“{LABELS[a]}”之后办理，请补齐前置连线。', node_id=b)
        gate = {'research': 'taskbook_scope', 'selection': 'selection_decision', 'project': 'taskbook'}[category]
        before_gate = ancestors(gate)
        for node in nodes:
            if node.get('action_resource') and node['id'] not in before_gate and not (category == 'project' and node['id'] == gate):
                raise RdError(422, '该可执行节点位于尚无受托执行合同的后续业务阶段，不能发布为已绑定动作。')
            if category == 'project':
                if node['id'] != gate and node['id'] not in before_gate:
                    raise RdError(422, '项目流程必须止于研制任务书生成，不能包含下游或无关联节点。')
                if node['id'] not in MANDATORY[category] and not node.get('action_resource'):
                    raise RdError(422, '项目流程新增节点须绑定已有可执行动作。')
                if node.get('action_resource') and 'rd_start' not in ancestors(node['id']):
                    raise RdError(422, '任务书执行动作必须在研发启动依据之后办理。')
        if category in {'research', 'project'} and not next(n for n in nodes if n['id'] == 'taskbook').get('action_resource'):
            raise RdError(422, '任务书业务节点必须固定完整任务书专家团。')
        if any(n.get('action_resource') for n in nodes):
            from .designer import default_graph
            definition_id, version = ('input_check', '1') if category == 'selection' else ('taskbook', '2')
            package = {'definition_id': definition_id, 'definition_version': version,
                'title': '业务动作合同校验', 'nodes': catalog.default_nodes(definition_id, version)}
            # Publication and project preparation use the same actual compiler.
            execution_graph = default_graph(package, {'category': category, 'graph': result})
            self.store.designer.compile(db, execution_graph, definition_id, version)
        return result

    def _validation_result(self, db, payload):
        errors = []
        try:
            category = payload.get('category')
            if category not in MANDATORY:
                raise RdError(422, '请选择项目流程、选型流程或研发流程。')
            if category == 'research' and payload.get('product_route') not in {'modification', 'new'}:
                raise RdError(422, '研发流程须选择适用的改型或全新研发路线。')
            if 'title' in payload:
                _text(payload['title'], '流程模板名称', 200, True)
            self._validate_graph(db, category, payload.get('graph'))
        except RdError as error:
            errors.append({'code': 'invalid_workflow', 'message': str(error.detail),
                **{field: getattr(error, field) for field in ('node_id', 'edge_id') if getattr(error, field, None)}})
        return {'valid': not errors, 'errors': errors, 'warnings': [],
                'graph_digest': digest(payload.get('graph')), 'checked_at': _now()}

    def validate(self, actor, permissions, payload):
        """Preview validates configuration only: no draft, event, or execution is created."""
        _actor(actor)
        if not isinstance(permissions, dict) or not any(permissions.get(k) is True for k in ('can_edit_workflows', 'can_publish_workflows')):
            raise RdError(403, '当前主体没有流程模板校验权限。')
        if not isinstance(payload, dict) or set(payload) - {'id', 'version', 'category', 'title', 'product_route', 'graph'}:
            raise RdError(422, '流程校验仅接受模板配置，不接受执行代码或身份设置。')
        with self.store._connection() as db:
            return self._validation_result(db, payload)

    def history(self, actor, rid, permissions=None, *, management=False, page=1, page_size=5):
        actor = _actor(actor)
        if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 50:
            raise RdError(422, '历史分页参数无效。')
        if management and (not isinstance(permissions, dict) or not any(permissions.get(k) is True for k in ('can_edit_workflows', 'can_publish_workflows'))):
            raise RdError(403, '当前主体没有流程模板历史管理权限。')
        with self.store._connection() as db:
            current = self._detail(db, rid, management=management)
            versions = current['available_versions']
            visible_versions = versions[(page - 1) * page_size:page * page_size]
            items = [self._detail(db, rid, version, management=management) for version in visible_versions]
            events = [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM workflow_template_audit WHERE json_extract(payload,'$.template_id')=? ORDER BY rowid DESC", (rid,))]
            events = [item for item in events if item['version'] in visible_versions]
            usages = []
            for row in db.execute('SELECT payload FROM projects ORDER BY rowid DESC'):
                project = json.loads(row[0])
                if project.get('deleted_at') or (actor != project['owner_id'] and actor not in project.get('members', [])):
                    continue
                for case in project.get('cases', []):
                    prefix = {'project_id': project['id'], 'project_title': project['title'],
                              'case_id': case['id'], 'case_title': case['title']}
                    for adoption in case.get('workflow_template_adoptions', []):
                        if adoption.get('template_id') != rid or adoption.get('template_version') not in visible_versions:
                            continue
                        active = case.get('workflow_templates', {}).get(adoption['category'], {})
                        usages.append({**prefix, 'reference_type': 'adoption', 'adoption_id': adoption['id'],
                            'template_version': adoption['template_version'], 'template_digest': adoption['template_digest'],
                            'current': active.get('id') == adoption['id'], 'actor': adoption['actor'],
                            'adopted_at': adoption['created_at']})
                    for package in case.get('workpackages', []):
                        snapshot = package.get('snapshot') or {}
                        binding = snapshot.get('taskbook_binding') or {}
                        fixed = binding.get('workflow') or {}
                        if fixed.get('id') == rid and fixed.get('version') in visible_versions:
                            usages.append({**prefix, 'reference_type': 'run', 'workpackage_id': package['id'],
                                'run_id': package.get('run_id'), 'template_version': fixed['version'],
                                'template_digest': fixed['digest'], 'current': False,
                                'adopted_at': snapshot.get('submitted_at')})
            return {'items': items, 'events': events, 'usages': usages, 'total': len(versions),
                    'page': page, 'page_size': page_size, 'total_pages': max(1, (len(versions) + page_size - 1) // page_size)}

    def _baseline(self, db, payload, current, rid, category):
        ref = payload.get('based_on')
        if ref is None and current:
            old = self._detail(db, rid, str(current), True)
            ref = {field: old[field] for field in ('id', 'version', 'digest')}
        if ref is None:
            return None
        if not isinstance(ref, dict) or set(ref) != {'id', 'version', 'digest'}:
            raise RdError(422, '来源版本须指定模板、固定版本和内容摘要。')
        base = self._detail(db, ref['id'], ref['version'], True)
        if base['digest'] != ref['digest']:
            raise RdError(409, '来源模板摘要不匹配，请重新读取历史版本。')
        if base['category'] != category:
            raise RdError(422, '来源模板与新草稿的流程分类不一致。')
        return deepcopy(ref)

    def save(self, actor, permissions, payload, key):
        actor = _actor(actor)
        if not isinstance(payload, dict) or set(payload) - {'id', 'operation', 'expected_version', 'version',
                'expected_state_revision', 'category', 'title', 'product_route', 'graph', 'change_note', 'based_on'}:
            raise RdError(422, '业务流程模板命令无效。')
        op = payload.get('operation', 'save')
        if op not in {'save', 'validate', 'publish', 'retire'}:
            raise RdError(422, '业务流程模板操作无效。')
        if op == 'validate':
            if not isinstance(permissions, dict) or not any(permissions.get(k) is True for k in ('can_edit_workflows', 'can_publish_workflows')):
                raise RdError(403, '当前主体没有流程模板校验权限。')
        else:
            self._permission(permissions, 'can_edit_workflows' if op == 'save' else 'can_publish_workflows')
        key = _text(key, 'Idempotency-Key', 200, True)
        fingerprint = digest(payload)
        with self.store._transaction() as db:
            receipt = db.execute('SELECT fingerprint,response FROM workflow_template_receipts WHERE actor=? AND key=?', (actor, key)).fetchone()
            if receipt:
                if receipt[0] != fingerprint:
                    raise RdError(409, '同一幂等键已用于其他模板命令。')
                return json.loads(receipt[1])
            from .designer import _identifier
            rid = _identifier(payload.get('id') or _id(), '模板ID')
            head = db.execute('SELECT version FROM workflow_template_heads WHERE id=?', (rid,)).fetchone()
            current = int(head[0]) if head else 0
            if type(payload.get('expected_version')) is not int or payload['expected_version'] != current:
                raise RdError(409, '业务流程模板内容版本已更新。')
            note = _text(payload.get('change_note', ''), '修改说明', 2000)
            before_status, validation = None, None
            if op == 'save':
                category = payload.get('category')
                if category not in MANDATORY:
                    raise RdError(422, '模板分类须为project、selection或research。')
                old = self._detail(db, rid, str(current), True) if current else None
                if old and old['category'] != category:
                    raise RdError(422, '模板分类不能随版本改变。')
                route = payload.get('product_route')
                if category == 'research' and route not in {'modification', 'new'}:
                    raise RdError(422, '研发模板只适用于改型或新研路线。')
                version = str(current + 1)
                graph = self._validate_graph(db, category, payload.get('graph'), publication=False)
                baseline = self._baseline(db, payload, current, rid, category)
                value = {'id': rid, 'version': version, 'category': category,
                    'title': _text(payload.get('title'), '业务流程模板名称', 200, True),
                    'graph': graph, 'change_note': note,
                    'actor': actor, 'created_at': _now(), 'product_route': route if category == 'research' else None,
                    'nodes': [n['id'] for n in graph['nodes']]}
                if baseline:
                    value['based_on'] = baseline
                value['digest'] = digest(value)
                db.execute('INSERT INTO workflow_template_versions VALUES(?,?,?)', (rid, version, _json(value)))
                db.execute('INSERT INTO workflow_template_heads VALUES(?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version', (rid, version))
                db.execute('INSERT INTO workflow_template_publications VALUES(?,?,?,1)', (rid, version, 'draft'))
            else:
                version = str(payload.get('version', current))
                fixed = self._detail(db, rid, version, True)
                if type(payload.get('expected_state_revision')) is not int or payload['expected_state_revision'] != fixed['publication_revision']:
                    raise RdError(409, '模板发布状态修订已更新。')
                before_status = fixed['status']
                if op == 'publish' and before_status != 'draft':
                    raise RdError(409, '仅草稿版本可以发布；已停用版本请基于历史建立新草稿。')
                if op == 'retire' and before_status != 'published':
                    raise RdError(409, '仅已发布版本可以停用。')
                if op == 'validate':
                    validation = self._validation_result(db, fixed)
                elif op == 'publish':
                    validation = self._validation_result(db, fixed)
                    if not validation['valid']:
                        raise RdError(422, '发布校验未通过：' + '；'.join(item['message'] for item in validation['errors']))
                if op != 'validate':
                    db.execute('UPDATE workflow_template_publications SET status=?,revision=revision+1 WHERE id=? AND version=?', ('published' if op == 'publish' else 'retired', rid, version))
            response = self._detail(db, rid, version, True)
            if validation:
                response['validation'] = validation
            audit = {'id': _id(), 'actor': actor, 'operation': op, 'template_id': rid, 'version': version,
                     'digest': response['digest'], 'created_at': _now(), 'change_note': note,
                     'before_status': before_status, 'status': response['status'], 'state_revision': response['publication_revision']}
            if validation:
                audit['validation'] = validation
            db.execute('INSERT INTO workflow_template_audit VALUES(?,?)', (audit['id'], _json(audit)))
            db.execute('INSERT INTO workflow_template_receipts VALUES(?,?,?,?)', (actor, key, fingerprint, _json(response)))
            return response

    @staticmethod
    def _record_adoption(case, fixed, actor):
        category = fixed['category']
        previous = case.setdefault('workflow_templates', {}).get(category)
        adoption = {'id': _id(), 'template_id': fixed['id'], 'template_version': fixed['version'],
            'template_digest': fixed['digest'], 'title': fixed['title'], 'category': category,
            'input_revision': case['input_revision'], 'graph': deepcopy(fixed['graph']),
            'previous_adoption_id': previous.get('id') if previous else None, 'actor': actor, 'created_at': _now()}
        case.setdefault('workflow_template_adoptions', []).append(adoption)
        case['workflow_templates'][category] = deepcopy(adoption)
        return adoption

    def start_project(self, db, project, case, reference, actor):
        if actor != project['owner_id']:
            raise RdError(403, '项目流程由项目负责人选择并启动。')
        if not isinstance(reference, dict) or set(reference) != {'id', 'version', 'digest'}:
            raise RdError(422, '请选择已发布流程的固定标识、版本和摘要。')
        if reference['version'] is None:
            raise RdError(422, '项目流程须明确指定固定版本，不能隐式采用最新版。')
        fixed = self._detail(db, reference['id'], reference['version'])
        if fixed['category'] != 'project':
            raise RdError(422, '新建项目须选择已发布项目流程，不能采用阶段流程代替。')
        if fixed['digest'] != reference['digest']:
            raise RdError(409, '流程模板固定摘要已变化，请重新读取后选择。')
        self._validate_graph(db, 'project', fixed['graph'])
        self.store.workspace.require_definition('taskbook', '2', db=db, workflow=fixed)
        return self._record_adoption(case, fixed, actor)

    @staticmethod
    def fixed_project(case):
        adoption = case.get('workflow_templates', {}).get('project')
        if not adoption:
            return None
        return {'id': adoption['template_id'], 'version': adoption['template_version'],
            'digest': adoption['template_digest'], 'title': adoption['title'], 'category': 'project',
            'graph': deepcopy(adoption['graph']), 'nodes': [node['id'] for node in adoption['graph']['nodes']]}

    def adopt(self, db, project, case, data, actor):
        if actor != project['owner_id']:
            raise RdError(403, '业务流程模板采用由项目负责人办理。')
        fixed = self._detail(db, data.get('template_id'), data.get('template_version'))
        if data.get('template_digest') != fixed['digest']:
            raise RdError(409, '业务模板固定摘要不匹配。')
        if fixed['category'] == 'project' or case.get('workflow_templates', {}).get('project'):
            raise RdError(422, '项目流程须在创建时固定，不能通过阶段模板采用替换已启动的流程。')
        self._validate_graph(db, fixed['category'], fixed['graph'])
        category = fixed['category']
        if category == 'research':
            route = (case.get('product_route') or {}).get('value')
            if route not in {'modification', 'new'} or route != fixed.get('product_route'):
                raise RdError(422, '研发模板与有效产品路线不匹配；直接选用不创建研发包。')
            from .lifecycle import LifecyclePolicy
            if LifecyclePolicy.resolve(case).version == 'v2':
                self.store.lifecycle.execution_refs(case)
        elif case['stage'] not in {'input', 'requirements', 'selection'}:
            raise RdError(422, '选型流程仅在选型事项办理期间采用。')
        adoption = self._record_adoption(case, fixed, actor)
        binding = case.get('taskbook_binding')
        if category == 'research' and binding and any((binding.get('workflow') or {}).get(key) != fixed[key] for key in ('id', 'version', 'digest')):
            self.store._stale_taskbook_binding(case, '已采用研发业务流程变化，请重新固定任务书文档与业务流程绑定。')
        return {'workflow_adoption_id': adoption['id']}

    @staticmethod
    def _template_ref(value):
        value = value or {}
        return (value.get('template_id', value.get('id')), value.get('template_version', value.get('version')),
                value.get('template_digest', value.get('digest')))

    def project_projection(self, case):
        # A template's current view comes from fixed evidence, never a similarly
        # named historical package or a successful-looking boolean.
        lifecycle = case.get('business_lifecycle', {})
        current_input = case['input_revision']
        candidates = {c['id']: c for c in case.get('execution_candidates', [])}
        binding = case.get('taskbook_binding') or {}
        def current(row):
            return row.get('input_revision') == current_input and not row.get('invalidated_at')
        decisions = {d['id']: d for d in case.get('decisions', []) if current(d) and d.get('verdict') == 'approved'}
        baselines = {b['id']: b for b in case.get('requirement_baselines', []) if current(b)}
        activations = {a['id']: a for a in case.get('rd_activations', []) if current(a) and a.get('status') == 'active'}
        for category, adoption in case.get('workflow_templates', {}).items():
            states, execution_refs, runs = {}, {}, {}
            fixed_ref = self._template_ref(adoption)
            # A project graph is selected before its sources exist. Its version
            # remains fixed while each gate and run is checked against current inputs.
            adoption_current = category == 'project' or adoption['input_revision'] == current_input
            binding_current = binding.get('status') == 'current' and binding.get('input_revision') == current_input and self._template_ref(binding.get('workflow')) == fixed_ref
            packages = sorted(case.get('workpackages', []), key=lambda p: ((p.get('snapshot') or {}).get('submitted_at', ''), p.get('run_id') or ''))
            for package in packages:
                snapshot = package.get('snapshot') or {}
                candidate_ref = snapshot.get('execution_candidate') or {}
                candidate = candidates.get(candidate_ref.get('id'))
                if not adoption_current or not package.get('run_id') or not candidate:
                    continue
                if (candidate_ref.get('digest') != candidate.get('digest') or candidate.get('workpackage_id') != package['id']
                    or candidate.get('input_revision') != current_input or snapshot.get('input_revision') != current_input
                    or self._template_ref(candidate.get('business_template')) != fixed_ref
                    or not self.store._same_inputs(snapshot, case)):
                    continue
                fixed_binding = snapshot.get('taskbook_binding') or {}
                if fixed_binding and (not binding_current or fixed_binding.get('id') != binding.get('id')
                                      or fixed_binding.get('fingerprint') != binding.get('fingerprint')):
                    continue
                by_id = {n['id']: n for n in package['nodes']}
                grouped = {}
                for item in snapshot.get('execution_mapping', []):
                    step = by_id.get(item.get('step_instance_id'))
                    if step and item.get('run_id') == package['run_id'] and step.get('business_node_id') == item.get('business_node_id'):
                        grouped.setdefault(item['business_node_id'], []).append(step)
                for nid, steps in grouped.items():
                    statuses = {n['status'] for n in steps}
                    if statuses == {'completed'}:
                        state = 'completed'
                    elif package['status'] in {'failed', 'blocked', 'cancelled'}:
                        state = package['status']
                    else:
                        state = next((v for v in ('failed', 'blocked', 'cancelled', 'running', 'submitted') if v in statuses), 'pending')
                    runs[nid] = state
                    execution_refs[nid] = {'run_id': package['run_id'], 'workpackage_id': package['id'],
                        'candidate_id': candidate['id'], 'candidate_digest': candidate['digest'],
                        'step_instance_ids': [n['id'] for n in steps]}
            engineering = self.store.records._current_engineering(case, binding) if binding_current else {}
            chain = [nid for nid in binding.get('workflow', {}).get('nodes', []) if nid in {'scheme', 'detail', 'integration'}]
            for node in adoption['graph']['nodes']:
                nid, gate = node['id'], node.get('gate')
                if node.get('action_resource') and not gate:
                    states[nid] = runs.get(nid, 'pending')
                elif gate in {'requirements', 'selection', 'rd_start', 'taskbook_scope'}:
                    valid = False
                    if adoption_current:
                        if gate == 'requirements':
                            valid = lifecycle.get('current_requirement_baseline_id') in baselines
                        elif gate == 'selection':
                            valid = decisions.get(lifecycle.get('current_selection_decision_id'), {}).get('kind') == 'selection'
                        elif gate == 'rd_start':
                            activation = activations.get(lifecycle.get('current_activation_id'), {})
                            valid = (lifecycle.get('rd_activation_state') == 'active' and bool(activation)
                                and activation.get('selection_decision_id') == lifecycle.get('current_selection_decision_id')
                                and decisions.get(activation.get('selection_decision_id'), {}).get('kind') == 'selection'
                                and activation.get('requirement_baseline_id') == lifecycle.get('current_requirement_baseline_id')
                                and activation.get('requirement_baseline_id') in baselines)
                        else:
                            valid = binding_current and decisions.get(lifecycle.get('current_taskbook_scope_decision_id'), {}).get('kind') == 'taskbook_scope'
                    states[nid] = 'completed' if valid else 'pending_decision'
                elif gate in {'verification', 'delivery'}:
                    valid = adoption_current and binding_current and any(d.get('stage') == gate for d in decisions.values())
                    states[nid] = 'completed' if valid else 'pending_decision'
                elif nid in engineering:
                    record = engineering[nid]
                    prior = chain[:chain.index(nid)] if nid in chain else []
                    valid_prior = all(p in engineering and engineering[p].get('verdict') == 'approved' for p in prior)
                    expected = [engineering[p]['id'] for p in prior if p in engineering]
                    states[nid] = ('completed' if record['verdict'] == 'approved' else 'rejected') if adoption_current and valid_prior and record.get('prerequisite_record_ids') == expected else 'pending'
                elif category == 'project' and nid == 'input':
                    roles = {source['role'] for source in self.store._active_sources(case)}
                    states[nid] = 'completed' if {'tech', 'spec'} <= roles else 'pending'
                elif category == 'project' and nid == 'comparison':
                    try:
                        for axis in ('product', 'composition'):
                            route = case.get(axis + '_route') or {}
                            self.store.records.route_binding(case, axis, route.get('value'), route.get('comparison_id'))
                        states[nid] = 'completed'
                    except RdError:
                        states[nid] = 'pending'
                else:
                    states[nid] = 'pending'
            adoption['node_states'] = states
            adoption['node_execution_refs'] = execution_refs
            adoption['stale'] = not adoption_current
            if category == 'project':
                self._project_workflow_status(case, adoption, states, execution_refs, binding_current)

    def _project_workflow_status(self, case, adoption, states, execution_refs, binding_current):
        state = {'status': 'pending', 'template_id': adoption['template_id'],
            'template_version': adoption['template_version'], 'template_digest': adoption['template_digest'],
            'terminal_node_id': 'taskbook'}
        execution = execution_refs.get('taskbook')
        if execution:
            state['execution_ref'] = deepcopy(execution)
            terminal = states['taskbook']
            state['status'] = 'running' if terminal in {'running', 'submitted'} else terminal
            if terminal == 'completed':
                try:
                    package = self.store._package(case, execution['workpackage_id'])
                    checks = [node for node in package['nodes'] if node['action_id'] == 'verify']
                    if not checks or any(node.get('result', {}).get('delivery_approved') is not True for node in checks):
                        raise RdError(422, '当前任务书尚未通过全部质量校验。')
                    self.store.reviews._taskbook_snapshot(case, package['id'])
                    if not all(value == 'completed' for value in states.values()):
                        raise RdError(422, '流程尚有未完成的当前业务依据或动作。')
                except (RdError, OSError) as error:
                    states['taskbook'] = state['status'] = 'blocked'
                    state['reason'] = str(error)
        else:
            fixed_ref = self._template_ref(adoption)
            previous = [package for package in case['workpackages']
                if self._template_ref((package.get('snapshot') or {}).get('taskbook_binding', {}).get('workflow')) == fixed_ref]
            if previous and (not binding_current or any((package.get('snapshot') or {}).get('input_revision') != case['input_revision'] for package in previous)):
                state.update(status='stale', reason='已保留历史运行；当前输入或任务书绑定已变化，需重新固定并执行。')
            elif (case.get('product_route') or {}).get('value') == 'direct':
                state.update(status='blocked', reason='当前选型为直接选用，不创建研发任务书工作包。')
        adoption['terminal_status'] = state['status']
        case['project_workflow_status'] = state
