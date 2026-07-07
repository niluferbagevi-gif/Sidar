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
