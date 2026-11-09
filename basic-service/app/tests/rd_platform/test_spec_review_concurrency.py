"""Batched specification calls overlap without mixing evidence or requirement rows."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from threading import Barrier, Event, Lock
import time

import pytest

from jonhon_taskbook import llm_client
from jonhon_taskbook.usage_context import model_user_id_var
from service.rd_platform import requirement_recommendations as review
from service.rd_platform.store import RdError
from test_requirement_spec_recommendations import case, install_model


def many_requirements(case, count=69):
    case['requirements'] = [{'id': f'r{i}', 'revision': i + 1, 'title': f'指标{i}',
                             'content': f'指标{i}：待澄清。'} for i in range(count)]


def missing_response(payload):
    return {'items': [{'requirement_id': row['requirement_id'], 'status': 'not_found', 'evidence': []}
                      for row in reversed(payload['requirements'])]}


def test_batches_overlap_with_a_bound_and_reassemble_out_of_order_rows(case, tmp_path, monkeypatch):
    many_requirements(case)
    before = deepcopy(case)
    install_model(monkeypatch, {})
    gate, second_finished, lock = Barrier(3, timeout=2), Event(), Lock()
    calls, finished = [], []
    active = peak = 0

    def chat(system, payload, **kwargs):
        nonlocal active, peak
        data = json.loads(payload)
        first = int(data['requirements'][0]['requirement_id'][1:])
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append(data)
        try:
            if first < 45:
                gate.wait()
            if first == 0:
                assert second_finished.wait(2), 'another batch must finish before the first'
            result = missing_response(data)
            with lock:
                finished.append(first)
            if first == 15:
                second_finished.set()
            return result
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(llm_client, 'chat_json', chat)
    result = review.propose(case, tmp_path / 'analysis', 'local:test')
    assert peak == 3
    assert sorted(len(call['requirements']) for call in calls) == [9, 15, 15, 15, 15]
    assert finished.index(15) < finished.index(0)
    assert [(row['requirement_id'], row['requirement_revision']) for row in result['items']] == [
        (row['id'], row['revision']) for row in case['requirements']]
    assert all(call['specification'] == calls[0]['specification'] for call in calls)
    assert case == before


def test_all_batches_share_one_deadline_and_bounded_transport_attempts(case, tmp_path, monkeypatch):
    many_requirements(case, 31)
    install_model(monkeypatch, {})
    options = []

    def chat(system, payload, **kwargs):
        options.append(kwargs)
        return missing_response(json.loads(payload))

    monkeypatch.setattr(llm_client, 'chat_json', chat)
    started = time.monotonic()
    review.propose(case, tmp_path / 'analysis', 'local:test')
    assert len(options) == 3
    assert len({option['deadline'] for option in options}) == 1
    assert started < options[0]['deadline'] <= started + 240
    assert all(option['timeout_seconds'] == 120 and option['retries'] == 2 for option in options)


def test_model_and_usage_identity_follow_each_request_into_batch_workers(case, tmp_path, monkeypatch):
    many_requirements(case, 31)
    real_scope = llm_client.model_scope
    install_model(monkeypatch, {})
    monkeypatch.setattr(llm_client, 'model_scope', lambda *args: real_scope(*args, resolve=False))
    gate, lock = Barrier(6, timeout=3), Lock()
    seen = []

    def chat(system, payload, **kwargs):
        data = json.loads(payload)
        selection = llm_client._model_selection.get()
        identity = (model_user_id_var.get(), selection.provider, selection.model, selection.model_id)
        gate.wait()
        with lock:
            seen.append(identity)
        return missing_response(data)

    monkeypatch.setattr(llm_client, 'chat_json', chat)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = []
        for index in range(2):
            snapshot = deepcopy(case)
            snapshot['model_selection'] = {'provider': 'smartvision', 'name': f'model-{index}', 'id': str(index)}
            pending.append(pool.submit(review.propose, snapshot, tmp_path / str(index), f'user-{index}'))
        for future in pending:
            assert len(future.result()['items']) == 31
    assert sorted(seen) == sorted([(f'user-{i}', 'smartvision', f'model-{i}', str(i)) for i in range(2) for _ in range(3)])
    assert model_user_id_var.get() == ''


@pytest.mark.parametrize('failure', ['transport', 'duplicate_id'])
def test_failed_batch_stops_later_dispatch_without_modifying_input(case, tmp_path, monkeypatch, failure):
    many_requirements(case)
    before = deepcopy(case)
    install_model(monkeypatch, {})
    gate, lock, started = Barrier(3, timeout=2), Lock(), []

    def chat(system, payload, **kwargs):
        data = json.loads(payload)
        first = int(data['requirements'][0]['requirement_id'][1:])
        with lock:
            started.append(first)
        gate.wait()
        if first == 0:
            if failure == 'transport':
                raise TimeoutError('model service')
            result = missing_response(data)
            result['items'][0] = deepcopy(result['items'][1])
            return result
        # These calls are already in flight when the first batch fails.
        time.sleep(0.1)
        return missing_response(data)

    monkeypatch.setattr(llm_client, 'chat_json', chat)
    with pytest.raises(RdError) as error:
        review.propose(case, tmp_path / 'analysis', 'local:test')
    assert error.value.status == (502 if failure == 'transport' else 422)
    assert sorted(started) == [0, 15, 30]
    assert case == before
