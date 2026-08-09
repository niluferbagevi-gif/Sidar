from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from web.routes import coverage_ops


def _payload(response):
    return json.loads(response.body)


def _assert_database_unavailable(response) -> None:
    assert response.status_code == 503
    assert _payload(response) == {
        "success": False,
        "error": "database_unavailable",
        "message": "Veritabanı geçici olarak kullanılamıyor.",
    }


def test_coverage_deps_raise_when_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(coverage_ops, "_deps_factory", None)

    with pytest.raises(RuntimeError, match="Coverage route dependencies are not configured"):
        coverage_ops._deps()


@pytest.mark.asyncio
async def test_coverage_tasks_returns_503_when_database_unavailable() -> None:
    async def _resolve_agent_instance():
        raise RuntimeError("database unavailable")

    coverage_ops.configure_coverage_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-a",
            resolve_agent_instance=_resolve_agent_instance,
        )
    )

    response = await coverage_ops.api_qa_coverage_tasks(_user=SimpleNamespace(id="u1"))

    _assert_database_unavailable(response)


@pytest.mark.asyncio
async def test_coverage_tasks_masks_unexpected_database_exception(caplog) -> None:
    class _DB:
        async def list_coverage_tasks(self, **_kwargs):
            raise ValueError("unexpected db serialization failure")

    async def _resolve_agent_instance():
        return SimpleNamespace(memory=SimpleNamespace(db=_DB()))

    coverage_ops.configure_coverage_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-a",
            resolve_agent_instance=_resolve_agent_instance,
        )
    )

    response = await coverage_ops.api_qa_coverage_tasks(_user=SimpleNamespace(id="u1"))

    _assert_database_unavailable(response)
    assert "Unexpected operations route failure during database_operation" in caplog.text
    assert "unexpected db serialization failure" in caplog.text


def test_decode_agent_tool_result_wraps_non_json_string_output() -> None:
    assert coverage_ops.decode_agent_tool_result("plain output") == {
        "success": True,
        "output": "plain output",
    }


def test_decode_agent_tool_result_wraps_json_list_output() -> None:
    assert coverage_ops.decode_agent_tool_result('["finding"]') == {
        "success": True,
        "output": ["finding"],
    }


def test_decode_agent_tool_result_returns_dict_passthrough() -> None:
    raw = {"success": False, "error": "bad coverage"}

    assert coverage_ops.decode_agent_tool_result(raw) is raw


def test_serialize_coverage_task_uses_safe_defaults() -> None:
    serialized = coverage_ops.serialize_coverage_task(SimpleNamespace())

    assert serialized == {
        "id": 0,
        "tenant_id": "default",
        "requester_role": "",
        "command": "",
        "status": "",
        "target_path": "",
        "suggested_test_path": "",
        "review_payload_json": "{}",
        "created_at": "",
        "updated_at": "",
    }


@pytest.mark.asyncio
async def test_coverage_get_request_user_proxy_delegates_to_configured_dependencies() -> None:
    request = object()
    user = SimpleNamespace(id="coverage-user")
    calls: list[object] = []

    async def _get_request_user(req: object) -> object:
        calls.append(req)
        return user

    coverage_ops.configure_coverage_dependencies(
        lambda: SimpleNamespace(get_request_user=_get_request_user)
    )

    assert await coverage_ops._get_request_user_proxy(request) is user
    assert calls == [request]


@pytest.mark.asyncio
async def test_resolve_operations_db_returns_agent_memory_database() -> None:
    db = object()

    async def _resolve_agent_instance():
        return SimpleNamespace(memory=SimpleNamespace(db=db))

    assert (
        await coverage_ops._resolve_operations_db(
            SimpleNamespace(resolve_agent_instance=_resolve_agent_instance)
        )
        is db
    )


@pytest.mark.asyncio
async def test_coverage_tasks_returns_serialized_success_payload() -> None:
    calls: list[dict[str, object]] = []

    class _DB:
        async def list_coverage_tasks(self, **kwargs):
            calls.append(kwargs)
            return [
                SimpleNamespace(
                    id="7",
                    tenant_id="tenant-a",
                    requester_role="qa",
                    command="generate",
                    status="done",
                    target_path="core/example.py",
                    suggested_test_path="tests/unit/test_example.py",
                    review_payload_json='{"ok": true}',
                    created_at="2026-07-08T00:00:00Z",
                    updated_at="2026-07-08T00:01:00Z",
                )
            ]

    async def _resolve_agent_instance():
        return SimpleNamespace(memory=SimpleNamespace(db=_DB()))

    coverage_ops.configure_coverage_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-a",
            resolve_agent_instance=_resolve_agent_instance,
        )
    )

    response = await coverage_ops.api_qa_coverage_tasks(
        status="done", limit=5, _user=SimpleNamespace(id="u1")
    )

    assert response.status_code == 200
    assert calls == [{"tenant_id": "tenant-a", "status": "done", "limit": 5}]
    assert _payload(response) == {
        "success": True,
        "tasks": [
            {
                "id": 7,
                "tenant_id": "tenant-a",
                "requester_role": "qa",
                "command": "generate",
                "status": "done",
                "target_path": "core/example.py",
                "suggested_test_path": "tests/unit/test_example.py",
                "review_payload_json": '{"ok": true}',
                "created_at": "2026-07-08T00:00:00Z",
                "updated_at": "2026-07-08T00:01:00Z",
            }
        ],
    }


@pytest.mark.asyncio
async def test_coverage_tasks_returns_503_when_list_coverage_tasks_raises_oserror() -> None:
    class _DB:
        async def list_coverage_tasks(self, **_kwargs):
            raise OSError("connection reset")

    async def _resolve_agent_instance():
        return SimpleNamespace(memory=SimpleNamespace(db=_DB()))

    coverage_ops.configure_coverage_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-a",
            resolve_agent_instance=_resolve_agent_instance,
        )
    )

    response = await coverage_ops.api_qa_coverage_tasks(_user=SimpleNamespace(id="u1"))

    _assert_database_unavailable(response)


def test_decode_agent_tool_result_handles_empty_invalid_and_scalar_json() -> None:
    assert coverage_ops.decode_agent_tool_result("") == {"success": False, "output": ""}
    assert coverage_ops.decode_agent_tool_result("{") == {"success": True, "output": "{"}
    assert coverage_ops.decode_agent_tool_result("42") == {"success": True, "output": 42}


@pytest.mark.asyncio
async def test_coverage_analyze_returns_success_payload_and_decoded_analysis() -> None:
    events: list[dict[str, object]] = []

    class _Agent:
        async def _tool_analyze_coverage_report(self, payload: str) -> str:
            decoded = json.loads(payload)
            assert decoded == {
                "coverage_xml": "coverage.xml",
                "coveragerc": ".coveragerc",
                "coverage_output": "",
                "limit": 3,
            }
            return '{"success": true, "hotspots": ["core/example.py"]}'

    async def _emit_control_room_event(room_id: str, **kwargs) -> None:
        events.append({"room_id": room_id, **kwargs})

    async def _await_if_needed(value: object) -> object:
        return value

    coverage_ops.configure_coverage_dependencies(
        lambda: SimpleNamespace(
            await_if_needed=_await_if_needed,
            get_coverage_agent_instance=lambda: _Agent(),
            emit_control_room_event=_emit_control_room_event,
            get_user_tenant=lambda _user: "tenant-a",
        )
    )

    response = await coverage_ops.api_qa_coverage_analyze(
        coverage_ops.CoverageAnalyzeRequest(limit=3, room_id="qa:room"),
        _user=SimpleNamespace(id="u1"),
    )

    assert response.status_code == 200
    assert _payload(response) == {
        "success": True,
        "analysis": {"success": True, "hotspots": ["core/example.py"]},
        "tenant_id": "tenant-a",
    }
    assert [event["kind"] for event in events] == ["tool_call", "status"]


@pytest.mark.asyncio
async def test_coverage_generate_returns_failure_payload_when_candidate_rejected() -> None:
    class _Agent:
        async def _tool_generate_missing_tests(self, _payload: str) -> str:
            return "assert True"

        def _candidate_rejection_reason(self, candidate: str, *, finding: dict[str, object]) -> str:
            assert candidate == "assert True"
            assert finding == {"path": "core/example.py"}
            return "trivial assertion"

    async def _emit_control_room_event(*_args, **_kwargs) -> None:
        return None

    async def _await_if_needed(value: object) -> object:
        return value

    coverage_ops.configure_coverage_dependencies(
        lambda: SimpleNamespace(
            await_if_needed=_await_if_needed,
            get_coverage_agent_instance=lambda: _Agent(),
            emit_control_room_event=_emit_control_room_event,
            get_user_tenant=lambda _user: "tenant-a",
        )
    )

    response = await coverage_ops.api_qa_coverage_generate(
        coverage_ops.CoverageGenerateRequest(
            coverage_finding={"path": "core/example.py"}, room_id="qa:room"
        ),
        _user=SimpleNamespace(id="u1"),
    )

    assert response.status_code == 200
    assert _payload(response) == {
        "success": False,
        "candidate": "assert True",
        "quality_rejection_reason": "trivial assertion",
        "tenant_id": "tenant-a",
    }


@pytest.mark.asyncio
async def test_coverage_batch_returns_success_payload() -> None:
    class _Agent:
        async def run_autonomous_coverage_batch(self, **kwargs):
            assert kwargs == {
                "coverage_xml": "coverage.xml",
                "coveragerc": ".coveragerc",
                "limit": 2,
                "batch_size": 1,
                "append": False,
            }
            return {"success": True, "status": "completed", "written": ["tests/unit/test_x.py"]}

    async def _emit_control_room_event(*_args, **_kwargs) -> None:
        return None

    async def _await_if_needed(value: object) -> object:
        return value

    coverage_ops.configure_coverage_dependencies(
        lambda: SimpleNamespace(
            await_if_needed=_await_if_needed,
            get_coverage_agent_instance=lambda: _Agent(),
            emit_control_room_event=_emit_control_room_event,
            get_user_tenant=lambda _user: "tenant-a",
        )
    )

    response = await coverage_ops.api_qa_coverage_batch(
        coverage_ops.CoverageBatchRequest(limit=2, append=False),
        _user=SimpleNamespace(id="u1"),
    )

    assert response.status_code == 200
    assert _payload(response) == {
        "success": True,
        "result": {"success": True, "status": "completed", "written": ["tests/unit/test_x.py"]},
        "tenant_id": "tenant-a",
    }
