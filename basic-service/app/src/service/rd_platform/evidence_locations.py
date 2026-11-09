"""Read-only document coordinates for quotations already saved by the platform.

Coordinates use the same zero-based body/row convention as completion.evidence_blocks.
Unlike completion search, headings remain addressable. This reader never converts a
document or calls a model: legacy formats use the copy retained by that analysis.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


def _normal(text):
    return re.sub(r'\s+', '', text)


def _references(case):
    """Collect current displays and their retained review evidence, not arbitrary input."""
    grouped = {}

    def walk(value, analysis_id=None):
        if isinstance(value, list):
            for item in value:
                walk(item, analysis_id)
        elif isinstance(value, dict):
            aid = value.get('analysis_id', analysis_id)
            for evidence in value.get('evidence', []):
                sid, quote = evidence.get('source_id'), evidence.get('quote')
                if not isinstance(sid, str) or not isinstance(quote, str) or not _normal(quote):
                    continue
                group = grouped.setdefault((sid, quote, aid),
                    {'source_id': sid, 'quote': quote, 'analysis_id': aid, 'references': []})
                ref = {'kind': evidence.get('kind')}
                if ref not in group['references']:
                    group['references'].append(ref)
            for key, item in value.items():
                if key != 'evidence':
                    walk(item, (value.get('recommendation_batch_id') or aid) if key == 'recommendation' else aid)

    analysis = case.get('source_analysis') or {}
    walk(analysis, analysis.get('id'))
    recommendations = case.get('requirement_recommendations') or {}
    walk(recommendations, recommendations.get('id'))
    for batch in case.get('requirement_recommendations_history', []):
        walk(batch, batch.get('id'))
    walk(case.get('context_provenance', {}))
    walk(case.get('requirements', []))
    return list(grouped.values())


def _location(body_index=None, row=None, line=None):
    if line is not None:
        return {'id': f'L{line:04d}', 'label': f'第 {line} 行', 'line': line}
    result = {'id': f'B{body_index + 1:04d}', 'label': f'正文块 {body_index + 1}', 'body_index': body_index}
    if row is not None:
        result.update(id=f'{result["id"]}-R{row + 1:03d}',
                      label=f'{result["label"]} · 表格第 {row + 1} 行', row=row)
    return result


def _blocks(content, suffix):
    if suffix in {'.txt', '.md'}:
        return [(line.strip(), _location(line=index + 1))
                for index, line in enumerate(content.decode('utf-8-sig').splitlines()) if line.strip()]
    document = Document(BytesIO(content))
    result = []
    for body_index, element in enumerate(document.element.body):
        if element.tag == qn('w:p'):
            text = Paragraph(element, document).text.strip()
            if text:
                result.append((text, _location(body_index)))
        elif element.tag == qn('w:tbl'):
            for row_index, row in enumerate(Table(element, document).rows):
                values = [cell.text.strip() for cell in row.cells]
                if any(values):
                    result.append((' | '.join(values), _location(body_index, row_index)))
    return result


def _index(blocks):
    texts, locations, starts, ends = [], [], [], []
    offset = 0
    for text, location in blocks:
        normal = _normal(text)
        if not normal:
            continue
        starts.append(offset)
        offset += len(normal)
        ends.append(offset)
        texts.append(normal)
        locations.append(location)
    return ''.join(texts), locations, starts, ends


def _match(index, quote):
    text, locations, starts, ends = index
    needle = _normal(quote)
    groups = []
    offset = text.find(needle)
    while offset >= 0:
        first = bisect_right(ends, offset)
        last = bisect_left(starts, offset + len(needle))
        group = tuple(range(first, last))
        # Repeated text within the same addressed row/paragraph is one block location.
        if group not in groups:
            groups.append(group)
        offset = text.find(needle, offset + 1)
    if not groups:
        return {'status': 'not_found', 'locations': [], 'reason': '未在此版本正文中找到该摘录'}
    indices = sorted({item for group in groups for item in group})
    result = {'status': 'located' if len(groups) == 1 else 'ambiguous',
              'locations': [locations[index] for index in indices]}
    if len(groups) > 1:
        result['reason'] = '原文重复，列出全部候选位置'
    return result


def _normalized_copy(source, analysis, analysis_root):
    if not analysis or analysis.get('source_hashes', {}).get(source['id']) != source['sha256']:
        return None, '缺少与原文件一致的分析版本'
    root = analysis_root.resolve()
    folder = (root / analysis['id'] / 'normalized' / source['id'] /
              f"{source['id']}-{source['sha256'][:12]}").resolve()
    path = (folder / 'normalized.docx').resolve()
    manifest_path = (folder / 'source-evidence.json').resolve()
    if not path.is_relative_to(root) or not manifest_path.is_relative_to(root):
        return None, '转换副本位置无效'
    if not path.is_file() or not manifest_path.is_file():
        return None, '此分析未保留可定位的转换副本'
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, '转换副本记录不可读取'
    if manifest.get('source_sha256') != source['sha256'] or manifest.get('status') not in {'needs_review', 'complete'}:
        return None, '转换副本与原文件版本不一致'
    # Never follow absolute paths recorded by another deployment; the source/analysis
    # identity defines the local path. The manifest binds it to the uploaded bytes.
    try:
        content = path.read_bytes()
    except OSError:
        return None, '转换副本不可读取'
    digest = hashlib.sha256(content).hexdigest()
    if manifest.get('normalized_sha256') and manifest['normalized_sha256'] != digest:
        return None, '转换副本校验不一致'
    return (content, digest), None


def _resolve_evidence(case, analysis_root, checked_path, groups=None):
    from .store import RdError

    sources = {source['id']: source for source in [*case.get('sources', []), *case.get('deleted_sources', [])]}
    current = case.get('source_analysis') or {}
    analyses = {analysis['id']: analysis for analysis in [current, *case.get('source_analysis_history', []),
        case.get('requirement_recommendations') or {}, *case.get('requirement_recommendations_history', [])] if analysis.get('id')}
    source_errors, source_paths, indices = {}, {}, {}
    items = []
    for group in _references(case) if groups is None else groups:
        sid, quote, aid = group['source_id'], group['quote'], group['analysis_id']
        source = sources.get(sid)
        item = {'source_id': sid, 'quote': quote, 'analysis_id': aid, 'status': 'unavailable', 'locations': []}
        items.append(item)
        if sid.startswith('project_'):
            item['reason'] = '项目登记依据，不是文档正文'
            continue
        if source is None:
            item['reason'] = '引用资料不存在于此流程'
            continue
        item.update(source_name=source['name'], source_version=source['version'], source_sha256=source['sha256'],
                    source_state='deleted' if source.get('status') == 'deleted' else
                    'current' if source.get('role') == 'reference' or case.get('source_selection', {}).get(source.get('role')) == sid else 'historical')
        if all(ref.get('kind') == 'source_filename' for ref in group['references']):
            item['reason'] = '文件名依据，不是文档正文'
            continue
        if sid not in source_paths and sid not in source_errors:
            try:
                source_paths[sid] = checked_path(source)
            except RdError as exc:
                if exc.status not in {404, 409}:
                    raise
                source_errors[sid] = '原文件校验不一致' if exc.status == 409 else '原文件不存在'
        if sid in source_errors:
            item['reason'] = source_errors[sid]
            continue
        suffix = Path(source['name']).suffix.lower()
        if aid in analyses and analyses[aid].get('source_hashes', {}).get(sid) != source['sha256']:
            item['reason'] = '引用的原文件版本已变化'
            continue
        item['coordinate_space'] = 'original' if suffix in {'.docx', '.txt', '.md'} else 'normalized'
        key = (sid, None if item['coordinate_space'] == 'original' else aid)
        if key not in indices:
            content, error, normalized_sha = None, None, None
            if item['coordinate_space'] == 'original':
                try:
                    content = source_paths[sid].read_bytes()
                    if hashlib.sha256(content).hexdigest() != source['sha256']:
                        content, error = None, '原文件校验不一致'
                except OSError:
                    error = '原文件不可读取'
            else:
                normalized, error = _normalized_copy(source, analyses.get(aid), analysis_root)
                if normalized:
                    content, normalized_sha = normalized
            try:
                blocks = _blocks(content, suffix) if content is not None else []
                index = _index(blocks) if content is not None else None
            except Exception:
                blocks, index, error = [], None, '文档内容不可读取'
            indices[key] = (index, error, normalized_sha, blocks)
        index, error, normalized_sha, blocks = indices[key]
        if normalized_sha:
            item['normalized_sha256'] = normalized_sha
        if error:
            item['reason'] = error
            continue
        item.update(_match(index, quote))
    return ({'items': items, 'project_id': case.get('project_id'), 'case_id': case['id'],
             'input_revision': case.get('input_revision'), 'analysis_id': current.get('id')}, indices)


def evidence_locations(case, analysis_root, checked_path):
    return _resolve_evidence(case, analysis_root, checked_path)[0]


def _highlighted_blocks(blocks, quote):
    """Map whitespace-insensitive matches back onto real text, including block spans.

    Segments avoid leaking HTML and avoid Python/JavaScript Unicode offset differences.
    """
    offsets, text, cursor = [], [], 0
    for value, location in blocks:
        positions = [index for index, char in enumerate(value) if not char.isspace()]
        normal = ''.join(value[index] for index in positions)
        offsets.append((cursor, cursor + len(normal), positions))
        text.append(normal)
        cursor += len(normal)
    haystack, needle, matches = ''.join(text), _normal(quote), []
    start = haystack.find(needle)
    while start >= 0:
        matches.append((start, start + len(needle)))
        start = haystack.find(needle, start + 1)
    result = []
    for (value, location), (begin, end, positions) in zip(blocks, offsets):
        ranges = []
        for first, last in matches:
            left, right = max(begin, first), min(end, last)
            if left < right:
                left, right = positions[left - begin], positions[right - begin - 1] + 1
                if ranges and left <= ranges[-1][1]:
                    ranges[-1] = (ranges[-1][0], max(right, ranges[-1][1]))
                else:
                    ranges.append((left, right))
        segments, cursor = [], 0
        for left, right in ranges:
            if left > cursor:
                segments.append({'text': value[cursor:left], 'highlighted': False})
            segments.append({'text': value[left:right], 'highlighted': True})
            cursor = right
        if cursor < len(value):
            segments.append({'text': value[cursor:], 'highlighted': False})
        result.append({**location, 'text': value, 'segments': segments})
    return result


def evidence_preview(case, analysis_root, checked_path, *, source_id, quote, analysis_id,
                     source_sha256, location_id, normalized_sha256=None):
    """Preview only persisted evidence and the same checked revision as its locator."""
    from .store import RdError

    reference = next((item for item in _references(case)
                      if (item['source_id'], item['quote'], item['analysis_id']) ==
                      (source_id, quote, analysis_id)), None)
    if reference is None:
        raise RdError(404, '引用依据不存在，请刷新流程后重新打开。')
    source = next((item for item in [*case.get('sources', []), *case.get('deleted_sources', [])]
                   if item['id'] == source_id), None)
    if not source or source['sha256'] != source_sha256:
        raise RdError(409, '资料版本已变化，请刷新定位后重新打开。')
    result, documents = _resolve_evidence(case, analysis_root, checked_path, [reference])
    item = result['items'][0]
    if item['status'] not in {'located', 'ambiguous'}:
        return {**item, 'blocks': [], 'selected_location_id': None}
    if item.get('normalized_sha256') != normalized_sha256:
        raise RdError(409, '转换副本已变化，请刷新定位后重新打开。')
    if location_id not in {point['id'] for point in item['locations']}:
        raise RdError(404, '原文位置已变化，请刷新定位后重新打开。')
    key = (source_id, None if item['coordinate_space'] == 'original' else analysis_id)
    return {**item, 'blocks': _highlighted_blocks(documents[key][3], quote),
            'selected_location_id': location_id}
