"""Governance roles must not be inherited from Workspace resource publication."""
from tests.rd_platform.test_http import make_client


def test_workflow_governance_is_distinct_and_reads_are_paginated(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    actor = client.get('/api/rd/session').json()['actor_id']
    monkeypatch.setenv('JTB_RD_WORKSPACE_PUBLISHERS', actor)
    session = client.get('/api/rd/governance/session')
    assert session.status_code == 200
    assert session.json()['can_publish_workflows'] is False
    assert client.get('/api/rd/workflow-templates?management=true').status_code == 403
    public = client.get('/api/rd/workflow-templates?category=selection').json()
    assert public['total'] >= 1 and public['page_size'] == 5
    assert all(item['category'] == 'selection' for item in public['items'])
    monkeypatch.setenv('JTB_RD_WORKFLOW_PUBLISHERS', actor)
    assert client.get('/api/rd/governance/session').json()['can_publish_workflows'] is True
    assert client.get('/api/rd/workflow-templates?management=true').status_code == 200


def test_template_roles_are_separate_and_client_cannot_claim_actor(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    actor = client.get('/api/rd/session').json()['actor_id']
    monkeypatch.setenv('JTB_RD_TEMPLATE_REVIEWERS', actor)
    permissions = client.get('/api/rd/governance/session').json()
    assert permissions['can_review_templates'] is True
    assert permissions['can_publish_templates'] is False
    response = client.post('/api/rd/workflow-templates', json={'actor': 'admin'}, headers={'Idempotency-Key':'forged'})
    assert response.status_code == 403


def test_governance_requires_oa_identity_and_same_origin(tmp_path):
    assert make_client(tmp_path, auth=True).get('/api/rd/governance/session').status_code == 401
    client = make_client(tmp_path)
    response = client.post('/api/rd/workflow-templates', json={}, headers={'Sec-Fetch-Site':'cross-site','Idempotency-Key':'cross'})
    assert response.status_code == 403
