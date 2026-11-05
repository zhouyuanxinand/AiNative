"""Explicit new-policy authoring steps for business lifecycle fixtures."""


def adopt_plan(store, project, workpackage_id, actor='owner'):
    def command(name, data):
        nonlocal project
        project = store.command(actor, project['id'], project['version'],
            f"fixture-{project['version']}-{name}", name, {'case_id': project['cases'][0]['id'], **data})
    command('create_flow_draft', {'workpackage_id': workpackage_id})
    draft = project['cases'][0]['flow_drafts'][-1]
    command('validate_flow_draft', {'draft_id': draft['id']})
    command('prepare_execution_bundle', {'draft_id': draft['id']})
    candidate = project['cases'][0]['execution_candidates'][-1]
    command('adopt_execution_bundle', {'candidate_id': candidate['id'], 'candidate_digest': candidate['digest']})
    return project
