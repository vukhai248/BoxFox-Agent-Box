import asyncio
from pathlib import Path
import pytest
from agentbox.memory.session_store import SessionStore
from agentbox.memory.history_store import HistoryError
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import create_app
from aiohttp.test_utils import TestClient, TestServer


def test_session_store_create_load_persistence(tmp_path):
    db_file = tmp_path / "sessions.sqlite"
    store = SessionStore(db_file)

    # 1. Create session
    config = {"skills": ["browser"], "tools": ["file_read"]}
    session = store.create(config, role="orchestrator")
    sid = session["id"]
    assert sid is not None
    assert session["role"] == "orchestrator"
    assert session["config"] == config
    assert session["status"] == "idle"

    # Add events and checkpoints
    store.emit(sid, "tool_start", {"name": "file_read"})
    store.save(sid, [{"role": "user", "content": "hello"}], status="running")
    store.checkpoint(sid, [{"role": "user", "content": "hello"}], "test_checkpoint")

    events = store.events(sid)
    assert len(events) == 1
    assert events[0]["data"]["name"] == "file_read"

    loaded = store.get(sid)
    assert loaded["status"] == "running"
    assert len(loaded["messages"]) == 1

    # 2. Persistence across restarts
    store.close()

    store2 = SessionStore(db_file)
    # Restart sets running -> interrupted
    reloaded = store2.get(sid)
    assert reloaded["status"] == "interrupted"
    assert reloaded["config"] == config

    # 3. Delete session — kể từ plan longtask, `SessionStore.delete` KHÔNG còn là đường xoá:
    # xoá thẳng là bypass capsule, nên hàm luôn từ chối. Đường hợp lệ là preview → capsule
    # đã xác minh → confirm (xem test_history_store.py).
    with pytest.raises(HistoryError, match="CARRY_FORWARD"):
        store2.delete(sid)
    assert store2.get(sid)["status"] == "interrupted"
    history = store2.history
    history.critical_snapshot = lambda ids: {"decisions": [], "blockers": [], "failedChecks": [],
                                             "tasks": [], "jobs": [], "budget": {}, "plans": []}
    history.quiescence = lambda ids: True
    preview = history.deletion_preview(sid)
    assert history.delete_with_capsule(sid, operation_id=preview["operationId"],
                                       expected_revision=preview["expectedRevision"], confirm=True)["status"] == "deleted"
    with pytest.raises(KeyError):
        store2.get(sid)
    with pytest.raises(KeyError):
        store2.events(sid)
    store2.close()


def test_session_store_child_cascade_delete(tmp_path):
    db_file = tmp_path / "sessions.sqlite"
    store = SessionStore(db_file)

    parent = store.create({"skills": []}, role="orchestrator")
    child = store.create({"skills": []}, role="frontend", parent_id=parent["id"])

    store.emit(child["id"], "tool_start", {"name": "browser_use"})
    assert len(store.events(child["id"])) == 1

    # Xoá thẳng cha là bypass capsule — bị từ chối; đường hợp lệ xoá ĐỆ QUY cả cây con.
    with pytest.raises(HistoryError, match="CARRY_FORWARD"):
        store.delete(parent["id"])
    history = store.history
    history.critical_snapshot = lambda ids: {"decisions": [], "blockers": [], "failedChecks": [],
                                             "tasks": [], "jobs": [], "budget": {}, "plans": []}
    history.quiescence = lambda ids: True
    preview = history.deletion_preview(parent["id"])
    assert set(preview["sessionIds"]) == {parent["id"], child["id"]}
    history.delete_with_capsule(parent["id"], operation_id=preview["operationId"],
                                expected_revision=preview["expectedRevision"], confirm=True)

    with pytest.raises(KeyError):
        store.get(parent["id"])
    with pytest.raises(KeyError):
        store.get(child["id"])
    store.close()


def test_server_delete_session_endpoint(tmp_path):
    async def run():
        db_file = tmp_path / "sessions.sqlite"
        store = SessionStore(db_file)
        runtime = HarnessRuntime(store, None)
        app = create_app(runtime)

        client = TestClient(TestServer(app))
        await client.start_server()

        try:
            # Create session
            sess = store.create({"skills": [], "tools": []})
            sid = sess["id"]

            # Client DELETE cũ KHÔNG được xoá thẳng: route phải từ chối với mã
            # DELETE_REQUIRES_CARRY_FORWARD (main chốt 409 + body preview khi nối route;
            # ở tầng storage hiện trả 400 qua middleware ValueError — điều quan trọng là
            # KHÔNG có cascade im lặng và phiên vẫn còn nguyên).
            res = await client.delete(
                f"/api/agent/sessions/{sid}",
                headers={"Host": "127.0.0.1:3102", "X-BoxFox-Admin": "1", "Origin": "http://localhost:3100"}
            )
            assert res.status in (400, 409), res.status
            data = await res.json()
            assert "DELETE_REQUIRES_CARRY_FORWARD" in data.get("error", "")
            assert store.get(sid)["id"] == sid
        finally:
            await client.close()
            store.close()

    asyncio.run(run())


def test_an_unknown_session_gets_an_actionable_404(tmp_path):
    """Ảnh chụp của chủ sở hữu: chat báo đúng một chữ "Not found".

    `store.get()` ném `KeyError`, và middleware biến **mọi** `KeyError` thành
    `{'error': 'Not found'}` — người dùng không có mã lỗi, không có id phiên, không có gì
    để tra. Nay id lạ trả `SESSION_NOT_FOUND` kèm id, nên UI tự mở phiên mới được.
    """

    async def run():
        store = SessionStore(tmp_path / "sessions.db")
        runtime = HarnessRuntime(store, None)
        client = TestClient(TestServer(create_app(runtime)))
        await client.start_server()
        headers = {"Host": "127.0.0.1:3102", "X-BoxFox-Admin": "1", "Origin": "http://localhost:3100"}
        try:
            for method, path, body in (("get", "/api/agent/sessions/deadbeef", None),
                                       ("post", "/api/agent/sessions/deadbeef/turns", {"prompt": "hỏi"}),
                                       ("post", "/api/agent/sessions/deadbeef/stop", None)):
                res = await getattr(client, method)(path, headers=headers, **(body and {"json": body} or {}))
                assert res.status == 404, (path, res.status)
                data = await res.json()
                assert data["code"] == "SESSION_NOT_FOUND", data
                assert data["error"].startswith("SESSION_NOT_FOUND: session deadbeef"), data
        finally:
            await client.close()
            store.close()

    asyncio.run(run())


def test_an_internal_key_error_is_not_reported_as_not_found(tmp_path):
    """`KeyError` bên trong handler là lỗi nội bộ, không phải "không có route"."""

    async def run():
        store = SessionStore(tmp_path / "sessions.db")
        runtime = HarnessRuntime(store, None)
        app = create_app(runtime)

        async def broken(request):
            raise KeyError("config['thinkingLevel']")

        app.router.add_get('/api/agent/broken-probe', broken)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            res = await client.get("/api/agent/broken-probe",
                                   headers={"Host": "127.0.0.1:3102", "X-BoxFox-Admin": "1",
                                            "Origin": "http://localhost:3100"})
            assert res.status == 500
            data = await res.json()
            assert data["code"] == "INTERNAL_ERROR", data
            assert "thinkingLevel" in data["error"], 'thông báo phải nói khoá nào thiếu'
        finally:
            await client.close()
            store.close()

    asyncio.run(run())


def test_an_unknown_skill_is_a_404_not_an_internal_error(tmp_path):
    """`catalog.items[sid]` ném `KeyError` cho một kỹ năng không có.

    Middleware nay coi `KeyError` là lỗi nội bộ (500) — đúng cho một lỗi lập trình,
    sai cho một cái tên gõ nhầm trong URL. Tuyến này phải tự trả 404 có mã, nếu không
    bản sửa `Not found` lại biến một 404 cũ thành 500.
    """

    async def run():
        store = SessionStore(tmp_path / "sessions.db")
        runtime = HarnessRuntime(store, None)
        client = TestClient(TestServer(create_app(runtime)))
        await client.start_server()
        headers = {"Host": "127.0.0.1:3102", "X-BoxFox-Admin": "1", "Origin": "http://localhost:3100"}
        try:
            res = await client.get("/api/agent/skills/khong-co-ky-nang-nay/readiness", headers=headers)
            assert res.status == 404, res.status
            data = await res.json()
            assert data["code"] == "SKILL_NOT_FOUND", data
            assert "khong-co-ky-nang-nay" in data["error"], data
        finally:
            await client.close()
            store.close()

    asyncio.run(run())
