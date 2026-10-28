"""Coverage is explicit evidence against actual exact-version DOCX anchors."""
import pytest
from docx import Document
from jonhon_taskbook.review_document import document_projection
from src.service.rd_platform.store import RdError

@pytest.fixture
def evidence_doc(tmp_path):
    d=Document();d.add_heading('保密属性',level=1);d.add_paragraph('本项目经客户确认按公开资料办理，依据客户分类单CX-01。')
    path=tmp_path/'coverage.docx';d.save(path)
    return document_projection(path,revision_id='r1')

def test_fifteen_classes_and_titles_do_not_satisfy_coverage(evidence_doc):
    from src.service.rd_platform.taskbook_coverage import check_taskbook_coverage,load_mapping
    mapping=load_mapping();result=check_taskbook_coverage({'id':'pkg','source_refs':[]},{'id':'r1','sha256':evidence_doc['sha256']},evidence_doc,mapping,[])
    assert len(result['findings'])==15
    assert result['blocking_count']==15
    assert next(x for x in result['findings'] if x['section_key']=='confidentiality')['status']=='pending'
    assert next(x for x in result['findings'] if x['section_key']=='budget')['status']=='missing'

def test_human_evidence_requires_actual_body_anchor_and_known_source(evidence_doc):
    from src.service.rd_platform.taskbook_coverage import check_taskbook_coverage,load_mapping
    package={'id':'pkg','source_refs':[{'source_id':'src','version':1}],'requirement_ids':['R1']}
    revision={'id':'r1','sha256':evidence_doc['sha256']}
    decision={'section_key':'confidentiality','status':'evidenced','output_anchor':evidence_doc['blocks'][0]['id'],'evidence_ref':'src@1','requirement_ref':'R1','reason':'已核对客户分类单','checked_by':'engineer'}
    with pytest.raises(RdError,match='标题'):
        check_taskbook_coverage(package,revision,evidence_doc,load_mapping(),[decision])
    decision['output_anchor']=evidence_doc['blocks'][1]['id']
    result=check_taskbook_coverage(package,revision,evidence_doc,load_mapping(),[decision])
    assert next(x for x in result['findings'] if x['section_key']=='confidentiality')['status']=='evidenced'
    decision['evidence_ref']='foreign@1'
    with pytest.raises(RdError,match='依据'):
        check_taskbook_coverage(package,revision,evidence_doc,load_mapping(),[decision])

def test_old_revision_and_unapproved_not_applicable_refused(evidence_doc):
    from src.service.rd_platform.taskbook_coverage import check_taskbook_coverage,load_mapping
    with pytest.raises(RdError,match='修订'):
        check_taskbook_coverage({'id':'pkg','source_refs':[]},{'id':'r2','sha256':'different'},evidence_doc,load_mapping(),[])
    decision={'section_key':'budget','status':'not_applicable','reason':'无预算'}
    with pytest.raises(RdError,match='依据|确认'):
        check_taskbook_coverage({'id':'pkg','source_refs':[]},{'id':'r1','sha256':evidence_doc['sha256']},evidence_doc,load_mapping(),[decision])
