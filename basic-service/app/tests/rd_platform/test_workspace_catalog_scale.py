"""Directory totals describe authorized resource entries, never all resources."""
import pytest

from src.service.rd_platform.store import Store, RdError


def test_hundred_managed_fifty_authorized_filter_before_ten_pages(tmp_path):
    store = Store(tmp_path / 'db.sqlite3', tmp_path / 'assets', application_id='explicit-test-app')
    publisher = {'can_edit_resources': True, 'can_publish_resources': True}
    granter = {'can_manage_application_grants': True}
    for index in range(100):
        rid = f'entry-{index:03}'
        resource = store.workspace.save_resource('publisher', publisher,
            {'id': rid, 'kind': 'skill', 'name': rid, 'expected_version': 0, 'configuration': {}}, 'save-' + rid)
        store.workspace.save_resource('publisher', publisher,
            {'id': rid, 'version': 1, 'expected_version': 1, 'operation': 'publish',
             'expected_state_revision': resource['publication_revision'], 'expected_control_revision': resource['control_revision']}, 'publish-' + rid)
        if index % 2:
            store.workspace.set_grant('authorizer', granter,
                {'id': rid, 'version': 1, 'expected_revision': 0, 'operation': 'grant'}, 'grant-' + rid)
    assert store.workspace.management_list('publisher', publisher, q='entry')['total'] == 100
    all_ids = []
    for page in range(1, 11):
        result = store.workspace.catalog_list(page=page)
        assert result['total'] == 50 and result['total_pages'] == 10 and len(result['items']) == 5
        all_ids.extend(item['id'] for item in result['items'])
    assert len(set(all_ids)) == 50 and all(int(rid[-3:]) % 2 for rid in all_ids)
    assert store.workspace.catalog_list(q='entry-099')['total'] == 1
    assert store.workspace.catalog_list(q='entry-098')['total'] == 0
    with pytest.raises(RdError) as exc:
        store.workspace.catalog_detail('entry-098', 1)
    assert exc.value.status == 404
