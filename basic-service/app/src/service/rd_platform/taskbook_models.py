"""Native taskbook aggregate vocabulary and shared guards."""
from __future__ import annotations
from typing import TypedDict

COLLECTIONS = ('project_sources','development_adoptions','taskbook_work_units','taskbook_input_packages','taskbook_coverages','taskbook_wbs_drafts','taskbook_releases','plan_releases','handoffs','change_impacts','selection_decisions','delivery_records')
COMMAND_FIELDS = {
    'adopt_development': {'route','approval_ref','scope','process_template_ref','provenance','requirement_ids'},
    'create_taskbook': {'adoption_id','title','description','assignee_id','reviewer_id','due_date'},
    'advance_taskbook_stage': {'task_id','target_stage'},
    'save_wbs': {'task_id','expected_wbs_revision','source_revision_id','items'},
    'publish_plan': {'task_id','release_id'},
    'accept_handoff': {'handoff_id'},
    'resolve_change_impact': {'impact_id','decision','reason','adoption_id'},
    'reopen_taskbook': {'task_id','reason'},
}


class Stage(TypedDict):
    instance_id: str
    node_code: str
    label: str
    status: str
    started_at: str | None
    completed_at: str | None


class TaskbookWorkUnit(TypedDict):
    id: str
    task_id: str
    process_code: str
    adoption_id: str
    current_stage: str
    stages: list[Stage]
    input_package_id: str | None
    selected_run_id: str | None
    selected_revision_id: str | None
    wbs_draft_id: str | None
    release_id: str | None


def normalize(doc):
    for name in COLLECTIONS:
        doc.setdefault(name, [])
    return doc


def work_unit(doc, task_id):
    from .store import RdError
    row = next((w for w in doc['taskbook_work_units'] if w['task_id'] == task_id), None)
    if row is None:
        raise RdError(404, '该任务没有任务书工作包')
    return row


def native_validity(doc, task):
    from .store import RdError
    if any(i['status'] == 'pending' and (i.get('task_id') == task['id'] or task['id'] in i.get('downstream_task_ids',[])) for i in doc['change_impacts']):
        raise RdError(409,'关联输入变更尚未完成影响复核')
    if task.get('kind') == 'taskbook':
        w = work_unit(doc,task['id'])
        if w.get('input_package_id'):
            package = next((p for p in doc['taskbook_input_packages'] if p['id'] == w['input_package_id']),None)
            if not package or package.get('status') in {'invalid','superseded','needs_revalidation'}:
                raise RdError(409,'固定输入包需要重新确认')


def usable_run(run):
    if run.get('cancel_requested'):return False
    # A blocked generation can retain a real DOCX for manual correction. The
    # exact revision adapter proves its bytes; submission still requires new,
    # passing revision QA, coverage and WBS rather than the technical status.
    if run.get('status') in {'done','completed','succeeded','success','blocked'}:return True
    if run.get('status')=='demo_sample' and run.get('provenance')=='mock' and run.get('execution_kind')=='preloaded_document':
        from .demo import demo_mode_enabled
        return demo_mode_enabled()
    return False
