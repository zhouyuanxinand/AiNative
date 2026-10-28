"""Fifteen business content classes mapped to one immutable ReviewStore revision.

Matches locate candidates only. Evidence is a human adoption with a real body
anchor and fixed project source; this module never rewrites document content.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
from .store import RdError,_id,_now

def load_mapping():
    return json.loads((Path(__file__).parent/'resources'/'taskbook_section_mapping.json').read_text(encoding='utf-8-sig'))

def _blocks(items):
    for block in items:
        yield block
        for row in block.get('rows',[]):
            for cell in row.get('cells',[]):yield from _blocks(cell.get('blocks',[]))

def _text(block):
    return block.get('text','') or ' '.join(_text(child) for row in block.get('rows',[]) for cell in row.get('cells',[]) for child in cell.get('blocks',[]))

def _body(block):
    text=_text(block).strip()
    return bool(not block.get('heading_level') and len(text)>=3 and not re.fullmatch(r'[.。…\s_—Xx＊*]+',text))

def check_taskbook_coverage(package,revision,review_document,mapping,decisions):
    revision_id=revision.get('id') or revision.get('revision_id')
    if review_document.get('revision_id')!=revision_id or review_document.get('sha256')!=revision.get('sha256'):
        raise RdError(409,'覆盖核验必须对应同一修订及文件哈希')
    if not isinstance(decisions,list) or len(decisions)>15:raise RdError(422,'覆盖处置必须为十五类内容以内的列表')
    blocks=list(_blocks(review_document.get('blocks',[])));by_id={b['id']:b for b in blocks}
    by_key={s['section_key']:s for s in mapping['sections']}
    chosen={}
    sources={s['source_id']+'@'+str(s['version']) for s in package.get('source_refs',[])}
    requirements=set(package.get('requirement_ids',[]))
    for decision in decisions:
        key=decision.get('section_key')
        if key not in by_key or key in chosen:raise RdError(422,'覆盖内容类别无效或重复')
        status=decision.get('status')
        if status not in {'evidenced','not_applicable'}:raise RdError(422,'人工覆盖处置须选择有依据或不适用')
        if not decision.get('checked_by') or not isinstance(decision.get('reason'),str) or not decision['reason'].strip():
            raise RdError(422,'采用或不适用须填写核对依据及确认人')
        if decision.get('evidence_ref') not in sources:raise RdError(422,'覆盖依据必须引用固定输入包中的资料版本')
        if decision.get('requirement_ref') and decision['requirement_ref'] not in requirements:raise RdError(422,'覆盖要求引用不属于采用的需求基线')
        anchor=decision.get('output_anchor')
        if status=='evidenced' and (anchor not in by_id or not _body(by_id[anchor])):
            raise RdError(422,'有依据须定位实际正文或表格，标题和占位文字不能作为核验内容')
        if anchor and anchor not in by_id:raise RdError(422,'文档位置不属于本次修订')
        chosen[key]=decision
    findings=[]
    for section in mapping['sections']:
        candidates=[b['id'] for b in blocks if any(alias in _text(b) for alias in section['aliases'])]
        decision=chosen.get(section['section_key'])
        findings.append({'section_key':section['section_key'],'label':section['label'],'group':section['group'],
                         'status':decision['status'] if decision else 'pending' if candidates else 'missing',
                         'output_anchor':decision.get('output_anchor') if decision else None,'candidate_anchors':candidates,
                         'evidence_ref':decision.get('evidence_ref') if decision else None,'requirement_ref':decision.get('requirement_ref') if decision else None,
                         'finding':decision['reason'] if decision else '已定位候选内容，须核对固定来源后采用' if candidates else '未定位内容或依据，请补充资料并修订',
                         'checked_by':decision['checked_by'] if decision else None})
    return {'id':_id(),'revision_id':revision_id,'document_sha256':revision['sha256'],'package_id':package['id'],'mapping_version':mapping['version'],
            'findings':findings,'blocking_count':sum(f['status'] not in {'evidenced','not_applicable'} for f in findings),'created_at':_now()}
