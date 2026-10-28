"""Baseline-bound route decisions and conservative project responsibility facts."""
from __future__ import annotations

import copy


COMMAND_FIELDS = {
    'record_selection': {'route', 'selected_product', 'rationale', 'evidence_ref', 'suitability', 'supply_status'},
    'record_delivery': {'selection_id', 'outcome', 'recipient', 'reference', 'note'},
}
ROUTE_LABELS = {'undecided': '待选型决定', 'direct': '直接选用', 'modification': '改型研制', 'new': '全新研制'}
STAGE_LABELS = {
    'requirements': '需求澄清与基线确认', 'selection': '选型与路线决定',
    'selection_pending': '选型资料待核实', 'delivery_ready': '直接选用待交接',
    'delivery_blocked': '直接选用交接受阻', 'delivered': '直接选用已交接',
    'development_pending': '研发启动与任务书准入', 'development': '任务书编制与工程核对',
    'review': '任务书工程审签', 'publication': '批准任务书待发布计划',
    'execution': '计划交接与研发协作', 'needs_revalidation': '路线与输入待复核',
}
def current_selection(doc):
    decisions = doc.get('selection_decisions', [])
    return decisions[-1] if decisions else None


def draft_changed(doc):
    baseline = next((b for b in doc['baselines'] if b['id'] == doc['project']['current_baseline_id']), None)
    return bool(baseline and baseline['requirements'] != doc['requirements'])


def require_current_baseline(doc):
    from .store import RdError
    baseline = doc['project']['current_baseline_id']
    if not baseline:
        raise RdError(409, '请先确认需求基线')
    if draft_changed(doc):
        raise RdError(409, '需求草稿已变化，请先确认新基线并复核选型')
    return baseline


def require_development_route(doc, native_route):
    """Legacy admissions stay usable until an explicit route decision exists."""
    from .store import RdError
    selection = current_selection(doc)
    if selection is None:
        return
    baseline = require_current_baseline(doc)
    route = 'modification' if native_route == 'modified' else native_route
    if selection['baseline_id'] != baseline:
        raise RdError(409, '选型决定须先按当前需求基线重新复核')
    if selection['route'] == 'direct' or selection['route'] != route:
        raise RdError(409, '研发准入路线须与当前选型决定一致；直接选用不创建研制任务书')


def apply_journey_command(doc, actor, action, payload):
    from .store import RdError, _id, _now, _text
    baseline = require_current_baseline(doc)
    common = {'id': _id(), 'baseline_id': baseline, 'created_by': actor['user_id'], 'created_at': _now()}
    if action == 'record_selection':
        route = payload.get('route')
        if route not in ('direct', 'modification', 'new'):
            raise RdError(422, '选型路线不正确')
        if payload.get('suitability') not in ('pending', 'confirmed') or payload.get('supply_status') not in ('pending', 'confirmed'):
            raise RdError(422, '适配性和供货状态须为待核实或已确认')
        values = {key: _text(payload.get(key), label, required=required) for key, label, required in (
            ('selected_product', '选用产品', route != 'new'), ('rationale', '选型依据说明', True), ('evidence_ref', '选型资料引用', False))}
        if payload['suitability'] == 'confirmed' and not values['evidence_ref']:
            raise RdError(422, '确认适配性须填写真实选型资料引用；资料缺失时请登记待核实')
        doc['selection_decisions'].append({**common, **values, 'route': route, 'suitability': payload['suitability'], 'supply_status': payload['supply_status']})
        return
    selection = current_selection(doc)
    if not selection or payload.get('selection_id') != selection['id']:
        raise RdError(409, '交接必须引用当前选型决定')
    if selection['baseline_id'] != baseline or selection['route'] != 'direct':
        raise RdError(409, '只有当前基线的直接选用路线可登记交接')
    outcome = payload.get('outcome')
    if outcome not in ('blocked', 'accepted'):
        raise RdError(422, '交接结果不正确')
    if outcome == 'accepted' and (selection['suitability'] != 'confirmed' or selection['supply_status'] != 'confirmed' or not selection['evidence_ref']):
        raise RdError(409, '适配性、供货状态和选型资料确认后才能接受交接')
    values = {key: _text(payload.get(key), label, required=required) for key, label, required in (
        ('recipient', '交接接收方', True), ('reference', '交接凭据', outcome == 'accepted'), ('note', '交接说明', outcome == 'blocked'))}
    doc['delivery_records'].append({**common, **values, 'selection_id': selection['id'], 'outcome': outcome})


def pending_releases(doc):
    """Only the current valid, independently approved release is publishable."""
    from .store import RdError
    from .taskbook_models import native_validity
    published = {p['release_id'] for p in doc['plan_releases']}
    result = []
    for unit in doc['taskbook_work_units']:
        release = next((r for r in doc['taskbook_releases'] if r['id'] == unit.get('release_id')), None)
        task = next((t for t in doc['tasks'] if t['id'] == unit['task_id']), None)
        if not release or not task or task['status'] != 'done' or release['id'] in published:
            continue
        if not any(r['id'] in release['review_ids'] and r['status'] == 'approved' for r in doc['reviews']):
            continue
        try:
            native_validity(doc, task)
        except RdError:
            continue
        result.append({'task_id': task['id'], 'release_id': release['id'], 'source_revision_id': release['revision_id']})
    return result


def build_journey(doc):
    selection = current_selection(doc)
    adoptions = doc['development_adoptions']
    legacy = adoptions[-1] if adoptions else None
    route = selection['route'] if selection else ('modification' if legacy and legacy['route'] == 'modified' else legacy['route'] if legacy else 'undecided')
    delivery = next((d for d in reversed(doc.get('delivery_records', [])) if selection and d['selection_id'] == selection['id']), None)
    blockers = []
    baseline = doc['project']['current_baseline_id']
    evidence_baseline = selection['baseline_id'] if selection else legacy['requirements_baseline_id'] if legacy else None
    if not selection and legacy:
        blockers.append('历史项目已登记研发路线，尚无选型决定与选型资料记录')
    stale = bool(evidence_baseline and (evidence_baseline != baseline or draft_changed(doc)))
    if stale:
        stage = 'needs_revalidation'
        blockers.append('需求输入已变化，历史选型与交接保留，须按当前基线重新复核路线')
    elif not baseline:
        stage = 'requirements'
        blockers.append('尚未确认需求基线')
    elif not selection and not legacy:
        stage = 'selection'
        blockers.append('尚未登记选型决定')
    elif selection and (selection['suitability'] != 'confirmed' or not selection['evidence_ref'] or (route == 'direct' and selection['supply_status'] != 'confirmed')):
        stage = 'selection_pending'
        if selection['suitability'] != 'confirmed': blockers.append('工程适配性待核实')
        if not selection['evidence_ref']: blockers.append('缺少选型资料引用')
        if route == 'direct' and selection['supply_status'] != 'confirmed': blockers.append('供货状态待核实')
    elif route == 'direct':
        stage = 'delivered' if delivery and delivery['outcome'] == 'accepted' else 'delivery_blocked' if delivery else 'delivery_ready'
        if stage != 'delivered': blockers.append(delivery['note'] if delivery else '尚未登记直接选用交接凭据')
    else:
        from .store import RdError
        from .taskbook_models import native_validity
        native_route = 'modified' if route == 'modification' else route
        # Native inputs retain their fixed scope across unrelated baselines.
        # Route compatibility selects the units; their own guards decide validity.
        relevant = {a['id'] for a in adoptions if a['route'] == native_route}
        units = [u for u in doc['taskbook_work_units'] if u['adoption_id'] in relevant]
        ids = {u['task_id'] for u in units}
        tasks = [t for t in doc['tasks'] if t['id'] in ids]
        native_blockers = []
        for task in tasks:
            try:
                native_validity(doc, task)
            except RdError as exc:
                if exc.detail not in native_blockers:
                    native_blockers.append(exc.detail)
        if not tasks:
            stage = 'development_pending'
            blockers.append('须完成研发启动批准并创建原生任务书工作包')
        elif native_blockers:
            stage = 'needs_revalidation'
            blockers.extend(native_blockers)
        elif any(t['status'] in {'todo', 'in_progress', 'changes_requested', 'needs_revalidation'} for t in tasks):
            stage = 'development'
        elif any(t['status'] == 'in_review' for t in tasks):
            stage = 'review'
        elif any(r['task_id'] in ids for r in pending_releases(doc)):
            stage = 'publication'
            blockers.append('已批准任务书尚待负责人发布计划')
        elif any(p['task_id'] in ids for p in doc['plan_releases']):
            stage = 'execution'
            if any(h['source_task_id'] in ids and h['status'] == 'pending' for h in doc['handoffs']):
                blockers.append('下游责任人尚待接受当前版本交接')
        else:
            stage = 'development'
            blockers.append('尚无可发布的有效批准包')
    return {'route': route, 'route_label': ROUTE_LABELS[route], 'stage': stage, 'stage_label': STAGE_LABELS[stage], 'selection': copy.deepcopy(selection), 'delivery': copy.deepcopy(delivery), 'blockers': blockers}
