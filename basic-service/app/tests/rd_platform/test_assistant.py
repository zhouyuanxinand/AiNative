"""Read-only case guidance, durable conversations and the real model seam."""
import importlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from jonhon_taskbook import llm_client
from jonhon_taskbook.usage_context import model_user_id_var
from service.rd_platform.store import Store

REAL_CHAT = llm_client.chat


def setup_case(tmp_path, actor="oa-user", model=False):
    store = Store(tmp_path / "rd.sqlite3", tmp_path / "assets")
    project = store.create_project(actor, "任务书真实案例")
    project = store.command(actor, project["id"], project["version"], "case", "create_case",
                            {"scenario_id": "taskbook", "title": "当前案例"})
    cid = project["cases"][0]["id"]
    if model:
        project = store.command(actor, project["id"], project["version"], "model", "save_context",
                                {"case_id": cid, "context": {}, "model_selection": {
                                    "provider": "smartvision", "name": "chosen-model", "id": "model-1"}})
    return store, project, cid


def assistant(store):
    return importlib.import_module("service.rd_platform.assistant").CaseAssistant(store)


@pytest.fixture(autouse=True)
def prevent_network(monkeypatch):
    monkeypatch.setattr(llm_client, "get_model_status", lambda *a: {"configured": False})
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: pytest.fail("unexpected model invocation"))


def change_members(store, pid, members):
    with sqlite3.connect(store.path) as db:
        project = json.loads(db.execute("SELECT payload FROM projects WHERE id=?", (pid,)).fetchone()[0])
        project["members"] = members
        db.execute("UPDATE projects SET payload=? WHERE id=?", (json.dumps(project), pid))


def test_unconfigured_guidance_is_durable_and_does_not_mutate_business(tmp_path):
    store, project, cid = setup_case(tmp_path)
    before = store.get_project("oa-user", project["id"])
    reply = assistant(store).ask("oa-user", project["id"], cid, "现在该做什么", "turn-1")
    assert reply["reply"]["mode"] == "local_guidance"
    assert "办理指引，尚未调用模型" in reply["reply"]["content"]
    assert "资料" in reply["reply"]["content"]
    assert len(reply["suggestions"]) <= 3
    assert store.get_project("oa-user", project["id"]) == before
    restored = assistant(Store(store.path, store.asset_root)).get("oa-user", project["id"], cid)
    assert [m["role"] for m in restored["messages"]] == ["user", "assistant"]
    assert restored["context"]["project_version"] == before["version"]


def test_actor_project_and_case_isolation_and_permission_rechecked(tmp_path):
    store, project, cid = setup_case(tmp_path)
    change_members(store, project["id"], ["colleague"])
    service = assistant(store)
    service.ask("oa-user", project["id"], cid, "我的指引", "same")
    assert service.get("colleague", project["id"], cid)["messages"] == []
    service.ask("colleague", project["id"], cid, "同事指引", "same")
    change_members(store, project["id"], [])
    for operation in (lambda: service.get("colleague", project["id"], cid),
                      lambda: service.ask("colleague", project["id"], cid, "同事指引", "same"),
                      lambda: service.get("oa-user", project["id"], "another-case")):
        with pytest.raises(Exception) as error:
            operation()
        assert error.value.status == 404
    other = store.create_project("oa-user", "另一项目")
    with pytest.raises(Exception) as error:
        service.get("oa-user", other["id"], cid)
    assert error.value.status == 404


def test_model_uses_fixed_real_context_actor_once_without_credentials(tmp_path, monkeypatch):
    store, project, cid = setup_case(tmp_path, model=True)
    calls = []
    monkeypatch.setattr(llm_client, "get_model_status", lambda *a: {
        "configured": True, "api_key": "never-send-secret", "endpoint": "https://private.invalid"})
    def chat(system, user, **kwargs):
        calls.append((system, user, kwargs, model_user_id_var.get()))
        assert "never-send-secret" not in user + system
        assert "private.invalid" not in user + system
        assert "当前案例" in user and cid in user
        assert "不执行" in system and "数据" in system
        assert kwargs["timeout_seconds"] == 20 and kwargs["retries"] == 0
        return "建议先补齐真实技术资料。"
    monkeypatch.setattr(llm_client, "chat", chat)
    service = assistant(store)
    first = service.ask("oa-user", project["id"], cid, "下一步", "one")
    replay = service.ask("oa-user", project["id"], cid, "下一步", "one")
    assert first["reply"] == replay["reply"]
    assert first["reply"]["mode"] == "model"
    assert len(calls) == 1 and calls[0][3] == "oa-user"
    assert model_user_id_var.get() == ""
    with pytest.raises(Exception) as error:
        service.ask("oa-user", project["id"], cid, "不同问题", "one")
    assert error.value.status == 409


def test_missing_selection_never_calls_model(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_client, "get_model_status", lambda *a: {"configured": True})
    store, project, cid = setup_case(tmp_path, model=False)
    result = assistant(store).ask("oa-user", project["id"], cid, "现在该做什么", "one")
    assert result["reply"]["mode"] == "local_guidance"


def test_configured_local_model_uses_empty_oa_identity(tmp_path, monkeypatch):
    store, project, cid = setup_case(tmp_path, actor="local:abc", model=True)
    monkeypatch.setattr(llm_client, "get_model_status", lambda *a: {"configured": True})
    calls = []
    def chat(system, user, **kwargs):
        calls.append(model_user_id_var.get())
        assert "local:abc" not in user
        return "按当前真实资料核对输入。"
    monkeypatch.setattr(llm_client, "chat", chat)
    # A caller's inherited attribution must not leak into the anonymous call.
    from jonhon_taskbook.usage_context import model_user_scope
    with model_user_scope("unrelated-oa-user"):
        result = assistant(store).ask("local:abc", project["id"], cid, "现在该做什么", "one")
        assert model_user_id_var.get() == "unrelated-oa-user"
    assert result["reply"]["mode"] == "model"
    assert "本地会话，未验证OA身份" in result["reply"]["content"]
    assert calls == [""]


def test_real_blockers_and_navigation_without_business_writes(tmp_path):
    store, project, cid = setup_case(tmp_path)
    project = store.command("oa-user", project["id"], project["version"], "pull", "pull_workpackage",
                            {"case_id": cid, "definition_id": "input_check"})
    wid = project["cases"][0]["workpackages"][0]["id"]
    project = store.command("oa-user", project["id"], project["version"], "submit", "submit_workpackage",
                            {"case_id": cid, "workpackage_id": wid})
    claim = store.claim_node()
    store.complete_node(claim, {"status": "blocked", "result": {}, "blocked_reasons": ["当前规范缺少有效来源"], "artifacts": [], "obligations": []})
    before = store.get_project("oa-user", project["id"])
    service = assistant(store)
    result = service.ask("oa-user", project["id"], cid, "哪些内容缺依据", "blockers")
    assert "当前规范缺少有效来源" in result["reply"]["content"]
    assert "产品研制分类" in result["reply"]["content"]
    for target in ("current", "sources", "requirements", "routes", "workpackages", "process", "artifacts", "history"):
        response = service.ask("oa-user", project["id"], cid, "定位", "go-" + target, target)
        assert response["navigation"] == {"target": target}
    assert store.get_project("oa-user", project["id"]) == before


def test_pending_request_rejects_duplicate_without_holding_write_lock(tmp_path, monkeypatch):
    store, project, cid = setup_case(tmp_path, model=True)
    monkeypatch.setattr(llm_client, "get_model_status", lambda *a: {"configured": True})
    entered, release = Event(), Event()
    def chat(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return "只读建议"
    monkeypatch.setattr(llm_client, "chat", chat)
    service = assistant(store)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.ask, "oa-user", project["id"], cid, "查看", "one")
        try:
            assert entered.wait(5)
            with pytest.raises(Exception) as error:
                service.ask("oa-user", project["id"], cid, "查看", "one")
            assert error.value.status == 409
            # This real business transaction must remain available during network I/O.
            current = store.get_project("oa-user", project["id"])
            store.command("oa-user", project["id"], current["version"], "change", "save_context",
                          {"case_id": cid, "context": {"product_series": "changed"}})
        finally:
            release.set()
        response = pending.result()
    assert response["reply"]["stale"] is True
    assert response["reply"]["answered_version"] == project["version"]


def test_revoked_member_cannot_save_or_read_late_model_reply(tmp_path, monkeypatch):
    store, project, cid = setup_case(tmp_path, model=True)
    change_members(store, project["id"], ["colleague"])
    monkeypatch.setattr(llm_client, "get_model_status", lambda *a: {"configured": True})
    def chat(*args, **kwargs):
        change_members(store, project["id"], [])
        return "不得返回给已撤权人员"
    monkeypatch.setattr(llm_client, "chat", chat)
    with pytest.raises(Exception) as error:
        assistant(store).ask("colleague", project["id"], cid, "查看", "one")
    assert error.value.status == 404


def test_history_paginates_and_marks_old_revision(tmp_path):
    store, project, cid = setup_case(tmp_path)
    service = assistant(store)
    for i in range(12):
        service.ask("oa-user", project["id"], cid, "现在该做什么", str(i))
    project = store.command("oa-user", project["id"], project["version"], "change", "save_context",
                            {"case_id": cid, "context": {"product_series": "new"}})
    recent = service.get("oa-user", project["id"], cid)
    assert len(recent["messages"]) == 20 and recent["history"]["total"] == 24
    assert recent["history"]["has_more"] is True
    older = service.get("oa-user", project["id"], cid, before=recent["history"]["next_before"])
    assert len(older["messages"]) == 4 and not older["history"]["has_more"]
    assert all(m["stale"] for m in recent["messages"] + older["messages"])
    assert {m["id"] for m in recent["messages"]}.isdisjoint({m["id"] for m in older["messages"]})


def test_model_failure_and_response_redact_private_details(tmp_path, monkeypatch):
    store, project, cid = setup_case(tmp_path, model=True)
    monkeypatch.setattr(llm_client, "get_model_status", lambda *a: {"configured": True})
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("api_key=PRIVATE C:/secret/model.json")))
    failed = assistant(store).ask("oa-user", project["id"], cid, "查看", "failure")
    assert failed["reply"]["mode"] == "local_guidance"
    assert "模型调用未完成" in failed["reply"]["content"]
    assert "PRIVATE" not in json.dumps(failed) and "secret/model" not in json.dumps(failed)
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: "建议。Bearer secret-token-123；文件 C:/private/config.json；api_key=sample-secret")
    result = assistant(store).ask("oa-user", project["id"], cid, "再查看", "output")
    assert all(value not in json.dumps(result) for value in ("secret-token-123", "private/config", "sample-secret"))


def test_chat_optional_timeout_preserves_existing_default(monkeypatch):
    monkeypatch.setattr(llm_client, "chat", REAL_CHAT)
    config = llm_client.LLMConfig(provider="openai", api_key="test-only", endpoint="https://example.invalid", model="test", timeout_seconds=90)
    monkeypatch.setattr(llm_client, "_active_config", lambda: config)
    captured = []
    monkeypatch.setattr(llm_client, "_request_with_retry", lambda actual, *a, **k: captured.append(actual.timeout_seconds) or "answer")
    llm_client.chat("system", "user")
    llm_client.chat("system", "user", timeout_seconds=20)
    assert captured == [90, 20] and config.timeout_seconds == 90


def test_expired_pending_recovers_once_and_fences_late_model_reply(tmp_path, monkeypatch):
    store, project, cid = setup_case(tmp_path, model=True)
    monkeypatch.setattr(llm_client, "get_model_status", lambda *a: {"configured": True})
    entered, release = Event(), Event()
    calls = []
    def chat(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return "不应采用的晚到模型回答"
    monkeypatch.setattr(llm_client, "chat", chat)
    service = assistant(store)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.ask, "oa-user", project["id"], cid, "查询", "one")
        try:
            assert entered.wait(5)
            monkeypatch.setattr(importlib.import_module("service.rd_platform.assistant"), "PENDING_SECONDS", 0)
            recovered = assistant(store).ask("oa-user", project["id"], cid, "查询", "one")
            assert recovered["reply"]["mode"] == "local_guidance"
            assert "恢复" in recovered["reply"]["content"]
        finally:
            release.set()
        late = pending.result()
    assert late["reply"] == recovered["reply"]
    assert len(calls) == 1 and len(late["messages"]) == 2
    assert "不应采用的晚到模型回答" not in json.dumps(late, ensure_ascii=False)


def test_query_credentials_are_redacted_in_prompt_and_persisted_history(tmp_path, monkeypatch):
    store, project, cid = setup_case(tmp_path, model=True)
    monkeypatch.setattr(llm_client, "get_model_status", lambda *a: {"configured": True})
    def chat(system, user, **kwargs):
        assert "DO-NOT-SEND" not in user
        assert "private/config" not in user
        return "只读指引"
    monkeypatch.setattr(llm_client, "chat", chat)
    result = assistant(store).ask("oa-user", project["id"], cid,
        '帮我查看 {"api_key":"DO-NOT-SEND"} C:/private/config.json', "one")
    assert result["reply"]["mode"] == "model"
    assert "DO-NOT-SEND" not in json.dumps(result)


def test_old_workpackage_blockers_are_marked_historical_after_inputs_change(tmp_path):
    store, project, cid = setup_case(tmp_path)
    project = store.command("oa-user", project["id"], project["version"], "pull", "pull_workpackage",
                            {"case_id": cid, "definition_id": "input_check"})
    wid = project["cases"][0]["workpackages"][0]["id"]
    store.command("oa-user", project["id"], project["version"], "submit", "submit_workpackage",
                  {"case_id": cid, "workpackage_id": wid})
    store.complete_node(store.claim_node(), {"status": "blocked", "result": {}, "blocked_reasons": ["旧版规范缺失"], "artifacts": [], "obligations": []})
    project = store.get_project("oa-user", project["id"])
    store.command("oa-user", project["id"], project["version"], "change", "save_context",
                  {"case_id": cid, "context": {"product_series": "new-revision"}})
    reply = assistant(store).ask("oa-user", project["id"], cid, "哪些内容缺依据", "one")["reply"]
    assert "历史输入" in reply["content"] and "旧版规范缺失" in reply["content"]


def test_local_query_returns_saved_facts_and_source_versions(tmp_path):
    store, project, cid = setup_case(tmp_path)
    project = store.add_source("oa-user", project["id"], cid, project["version"], "upload", "tech", "核对资料.txt", b"source")
    sid = project["cases"][0]["sources"][0]["id"]
    project = store.command("oa-user", project["id"], project["version"], "requirement", "save_requirement",
                            {"case_id": cid, "title": "接口尺寸", "content": "尺寸按受控条款核验", "source_ids": [sid]})
    service = assistant(store)
    requirement = service.ask("oa-user", project["id"], cid, "目前有哪些需求", "req")
    assert "接口尺寸" in requirement["reply"]["content"] and "尺寸按受控条款核验" in requirement["reply"]["content"]
    sources = service.ask("oa-user", project["id"], cid, "查看活动资料", "sources")
    assert "核对资料.txt" in sources["reply"]["content"] and "v1" in sources["reply"]["content"]
