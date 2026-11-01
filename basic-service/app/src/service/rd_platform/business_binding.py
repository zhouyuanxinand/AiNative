"""Fixed business choices bound to real, controlled taskbook assets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .completion import EvidenceBlocked, FIELDS, context_of, sha256, validate_sources


def business_fingerprint(binding):
    def stable(value, root=False):
        if isinstance(value, dict):
            return {key: stable(item) for key, item in value.items()
                    if key not in {'path', 'original_path', 'adopted_at', 'updated_at'}
                    and not (root and key == 'fingerprint')
                    and not key.endswith('_path')}
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value
    return hashlib.sha256(json.dumps(stable(binding, root=True), ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def document_template(context):
    from jonhon_taskbook.template_registry import resolve_template_selection
    if any(not str(context.get(field) or '').strip() for field in FIELDS):
        raise EvidenceBlocked('任务书模板绑定需要完整六参数，不使用业务默认值')
    try:
        selected = resolve_template_selection(context['product_type'], context['product_domain'])
        if selected.product_type != context['product_type'] or selected.product_domain != context['product_domain']:
            raise EvidenceBlocked('受控目录别名改变了已确认产品身份')
        assets = {}
        for kind, path in [('template', selected.template_path), ('profile', selected.profile_path),
                           ('mapping', selected.category_mapping_path)]:
            if not path or not Path(path).is_file():
                raise EvidenceBlocked('缺少受控任务书资产：' + kind)
            assets[kind] = {'path': str(Path(path).resolve()), 'sha256': sha256(path)}
        return {'product_type': selected.product_type, 'product_domain': selected.product_domain,
                'title': selected.product_type_label + ' / ' + selected.product_domain_label,
                'assets': assets, **{kind + '_sha256': item['sha256'] for kind, item in assets.items()}}
    except (ValueError, FileNotFoundError) as exc:
        if isinstance(exc, EvidenceBlocked):
            raise
        raise EvidenceBlocked('当前产品与领域缺少可用受控任务书模板资产') from exc


def verify_binding(snapshot):
    """Validate an optional legacy-compatible binding; never resolve new assets."""
    binding = snapshot.get('taskbook_binding')
    if binding is None:
        return None
    if not isinstance(binding, dict) or not binding.get('id') or binding.get('status') != 'current':
        raise EvidenceBlocked('任务书业务绑定无效或已过期')
    validate_sources(snapshot)
    if binding.get('fingerprint') != business_fingerprint(binding):
        raise EvidenceBlocked('任务书业务绑定指纹不一致')
    for key, expected in [('context', context_of(snapshot)), ('requirements_snapshot', snapshot.get('requirements', [])),
                          ('product_route', snapshot.get('product_route')), ('composition_route', snapshot.get('composition_route'))]:
        if binding.get(key) != expected:
            raise EvidenceBlocked('任务书业务选择已变化：' + key)
    source_keys = ('id', 'role', 'version', 'sha256')
    project = lambda rows: sorted([{key: row.get(key) for key in source_keys} for row in rows], key=lambda row: row['id'])
    if project(binding.get('source_snapshots', [])) != project(snapshot.get('sources', [])):
        raise EvidenceBlocked('任务书绑定资料版本与当前来源不一致')
    workflow = binding.get('workflow') or {}
    if not workflow.get('id') or not workflow.get('version') or not workflow.get('nodes'):
        raise EvidenceBlocked('任务书缺少已采用研发流程身份与节点')
    if workflow.get('product_route') != (snapshot.get('product_route') or {}).get('value'):
        raise EvidenceBlocked('研发流程不适用于已确认产品路线')
    if 'business_context' in snapshot and snapshot['business_context'] != binding.get('business_context'):
        raise EvidenceBlocked('建项业务上下文与任务书绑定不一致')
    selected = binding.get('document_template') or {}
    if any(selected.get(key) != binding['context'][key] for key in ('product_type', 'product_domain')):
        raise EvidenceBlocked('任务书文档模板与已确认产品不一致')
    for kind in ('template', 'profile', 'mapping'):
        asset = (selected.get('assets') or {}).get(kind) or {}
        path = Path(asset.get('path') or '')
        if not path.is_file() or not asset.get('sha256') or sha256(path) != asset['sha256']:
            raise EvidenceBlocked('已绑定任务书资产缺失或版本已变化：' + kind)
        if selected.get(kind + '_sha256') != asset['sha256']:
            raise EvidenceBlocked('已绑定任务书资产摘要不一致：' + kind)
    return binding
