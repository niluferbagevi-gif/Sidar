from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from starlette.datastructures import URL

from web.middleware import access_policy

access_policy_middleware_impl = access_policy.access_policy_middleware_impl


class _Request:
    method = "POST"
    url = URL("http://testserver/api/operations/task")
    state = SimpleNamespace(user=SimpleNamespace(id="u1", role="user", tenant_id="tenant-a"))


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: str, *_args: Any) -> None:
        self.warnings.append(message)


@pytest.mark.parametrize(
    ("path", "method", "expected"),
    [
        ("/rag/docs", "GET", ("rag", "read", "*")),
        ("/rag/docs/doc-1", "DELETE", ("rag", "write", "doc-1")),
        ("/github-prs", "POST", ("github", "write", "*")),
        ("/api/agents/register", "POST", ("agents", "register", "*")),
        ("/api/swarm/execute", "POST", ("swarm", "execute", "*")),
        ("/api/operations/tasks", "GET", ("operations", "read", "*")),
        ("/api/qa/coverage/tasks", "POST", ("coverage", "write", "*")),
        ("/admin/stats", "GET", ("admin", "manage", "*")),
        ("/ws/chat", "GET", ("swarm", "execute", "*")),
        ("/healthz", "GET", ("", "", "")),
    ],
)
def test_resolve_policy_from_request_contract(
    path: str, method: str, expected: tuple[str, str, str]
) -> None:
    request = SimpleNamespace(method=method, url=URL(f"http://testserver{path}"))

    assert access_policy.resolve_policy_from_request(request) == expected


def test_access_policy_helpers_normalize_and_serialize_records() -> None:
    assert access_policy.get_user_tenant(SimpleNamespace(tenant_id="  team-a ")) == "team-a"
    assert access_policy.get_user_tenant(SimpleNamespace(tenant_id="")) == "default"
    assert access_policy.build_audit_resource(" RAG ", "") == "rag:*"
    assert access_policy.build_audit_resource("", "doc") == ""

    policy = access_policy.serialize_policy(
        SimpleNamespace(id="7", user_id="u1", resource_type="rag", action="read")
    )
    audit = access_policy.serialize_audit_log(
        SimpleNamespace(id="8", user_id="u1", resource="rag:*", allowed=1)
    )

    assert policy["id"] == 7
    assert policy["resource_id"] == "*"
    assert policy["effect"] == "allow"
    assert audit["id"] == 8
    assert audit["allowed"] is True


@pytest.mark.asyncio
async def test_access_policy_middleware_allows_and_audits_when_checker_allows() -> None:
    audit_calls: list[dict[str, Any]] = []
    checker_calls: list[dict[str, Any]] = []

    async def _call_next(_request: _Request) -> Any:
        return SimpleNamespace(status_code=200)

    async def _check_access_policy(**kwargs: Any) -> bool:
        checker_calls.append(kwargs)
        return True

    async def _resolve_agent_instance() -> Any:
        return SimpleNamespace(
            memory=SimpleNamespace(db=SimpleNamespace(check_access_policy=_check_access_policy))
        )

    response = await access_policy_middleware_impl(
        _Request(),
        _call_next,
        resolve_policy_from_request=lambda _request: ("operations", "write", "*"),
        get_client_ip=lambda _request: "127.0.0.1",
        is_admin_user=lambda _user: False,
        schedule_access_audit_log=lambda **kwargs: audit_calls.append(kwargs),
        resolve_agent_instance=_resolve_agent_instance,
        get_user_tenant=lambda user: str(user.tenant_id),
        logger_obj=_Logger(),
    )

    assert response.status_code == 200
    assert checker_calls == [
        {
            "user_id": "u1",
            "tenant_id": "tenant-a",
            "resource_type": "operations",
            "action": "write",
            "resource_id": "*",
        }
    ]
    assert audit_calls[-1]["allowed"] is True


@pytest.mark.asyncio
async def test_access_policy_middleware_denies_and_audits_when_checker_denies() -> None:
    audit_calls: list[dict[str, Any]] = []

    async def _call_next(_request: _Request) -> Any:
        raise AssertionError("denied requests must not continue")

    async def _check_access_policy(**_kwargs: Any) -> bool:
        return False

    async def _resolve_agent_instance() -> Any:
        return SimpleNamespace(
            memory=SimpleNamespace(db=SimpleNamespace(check_access_policy=_check_access_policy))
        )

    response = await access_policy_middleware_impl(
        _Request(),
        _call_next,
        resolve_policy_from_request=lambda _request: ("operations", "write", "*"),
        get_client_ip=lambda _request: "127.0.0.1",
        is_admin_user=lambda _user: False,
        schedule_access_audit_log=lambda **kwargs: audit_calls.append(kwargs),
        resolve_agent_instance=_resolve_agent_instance,
        get_user_tenant=lambda user: str(user.tenant_id),
        logger_obj=_Logger(),
    )

    assert response.status_code == 403
    assert audit_calls[-1]["allowed"] is False
