from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pathlib import Path

if importlib.util.find_spec("httpx") is None and "httpx" not in sys.modules:
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.AsyncClient = type("AsyncClient", (), {})
    sys.modules["httpx"] = fake_httpx

if "redis.asyncio" not in sys.modules:
    fake_redis_asyncio = types.ModuleType("redis.asyncio")

    class Redis:
        @classmethod
        def from_url(cls, *_args, **_kwargs):
            return cls()

    fake_redis_asyncio.Redis = Redis
    fake_redis = types.ModuleType("redis")
    fake_redis.asyncio = fake_redis_asyncio
    sys.modules["redis"] = fake_redis
    sys.modules["redis.asyncio"] = fake_redis_asyncio

for _mod_name, _class_name in [
    ("managers.web_search", "WebSearchManager"),
    ("managers.package_info", "PackageInfoManager"),
    ("core.rag", "DocumentStore"),
    ("core.memory", "ConversationMemory"),
]:
    _mod = types.ModuleType(_mod_name)
    _mod.__dict__[_class_name] = type(_class_name, (), {})
    sys.modules.setdefault(_mod_name, _mod)

_pydantic_spec = None
if "pydantic" not in sys.modules:
    _pydantic_spec = importlib.util.find_spec("pydantic")
if _pydantic_spec is None and "pydantic" not in sys.modules:
    fake_pydantic = types.ModuleType("pydantic")
    fake_pydantic.BaseModel = object
    fake_pydantic.Field = lambda *a, **k: None
    fake_pydantic.ValidationError = Exception
    sys.modules["pydantic"] = fake_pydantic

_jwt_spec = None
if "jwt" not in sys.modules:
    _jwt_spec = importlib.util.find_spec("jwt")
if _jwt_spec is None and "jwt" not in sys.modules:
    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWTError = Exception
    fake_jwt.encode = lambda payload, *_args, **_kwargs: f"token:{payload.get('sub', '')}"
    fake_jwt.decode = lambda *_args, **_kwargs: {"sub": "stub"}
    sys.modules["jwt"] = fake_jwt

from agent.auto_handle import AutoHandle
from agent.swarm import SwarmOrchestrator
from agent import sidar_agent


def _load_role_module(module_name: str):
    role_path = Path(__file__).resolve().parents[1] / "agent" / "roles" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"tests_{module_name}", role_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_COVERAGE_MOD = _load_role_module("coverage_agent")
_POYRAZ_MOD = _load_role_module("poyraz_agent")
CoverageAgent = _COVERAGE_MOD.CoverageAgent
PoyrazAgent = _POYRAZ_MOD.PoyrazAgent


def test_poyraz_plan_service_operations_normalizes_items_and_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)

    payload = SimpleNamespace(
        campaign_name="Lansman",
        service_name="Catering",
        audience="Kurumsal",
        menu_plan={"ana yemek": ["Kebap", None, " "]},
        vendor_assignments={"chef": " Ahmet ", "host": " "},
        timeline=["T-7", 5, ""],
        notes=" kritik hazırlık ",
        persist_checklist=True,
        tenant_id="tenant-a",
        checklist_title="Operasyon",
        owner_user_id="owner-1",
        campaign_id=12,
    )

    checklist = SimpleNamespace(id=77, title="Operasyon", status="planned")

    class _Db:
        async def add_operation_checklist(self, **kwargs):
            self.kwargs = kwargs
            return checklist

    db = _Db()

    async def _fake_ensure_db():
        return db

    monkeypatch.setattr(_POYRAZ_MOD, "parse_tool_argument", lambda *_args, **_kwargs: payload)
    agent._ensure_db = _fake_ensure_db

    raw = asyncio.run(agent._tool_plan_service_operations("{}"))
    parsed = json.loads(raw)

    items = parsed["service_plan"]["items"]
    assert any(item["type"] == "menu_plan" for item in items)
    assert any(item["type"] == "vendor_assignment" for item in items)
    assert any(item["type"] == "timeline" and item["entry"] == "5" for item in items)
    assert parsed["service_plan"]["checklist"]["id"] == 77


def test_coverage_agent_run_task_handles_write_failure_and_record_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = CoverageAgent.__new__(CoverageAgent)
    agent.cfg = SimpleNamespace(BASE_DIR=".")
    agent.role_name = "coverage"

    class _Code:
        def run_pytest_and_collect(self, *_args, **_kwargs):
            return {
                "output": "pytest output",
                "analysis": {"summary": "1 failed", "findings": [{"target_path": "agent/swarm.py", "summary": "gap"}]},
            }

        def write_generated_test(self, *_args, **_kwargs):
            return False, "permission denied"

    agent.code = _Code()

    async def _fake_generate_test_candidate(**_kwargs):
        return "```python\ndef test_generated():\n    assert True\n```"

    async def _fake_record_task(**_kwargs):
        raise RuntimeError("db offline")

    monkeypatch.setattr(agent, "_generate_test_candidate", _fake_generate_test_candidate)
    monkeypatch.setattr(agent, "_record_task", _fake_record_task)

    payload = json.loads(asyncio.run(agent.run_task('{"command":"pytest -q"}')))

    assert payload["status"] == "write_failed"
    assert payload["success"] is False
    assert "```" not in payload["generated_test_candidate"]
    assert payload["target_path"] == "agent/swarm.py"


def test_sidar_build_context_truncates_for_local_provider_and_multi_agent_fallback() -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(
        AI_PROVIDER="ollama",
        PROJECT_NAME="Sidar",
        VERSION="1.0",
        CODING_MODEL="code",
        TEXT_MODEL="text",
        GEMINI_MODEL="gemini",
        ACCESS_LEVEL="full",
        USE_GPU=False,
        GPU_INFO="none",
        CUDA_VERSION="0",
        GITHUB_REPO="org/repo",
        LOCAL_INSTRUCTION_MAX_CHARS=1200,
        LOCAL_AGENT_CONTEXT_MAX_CHARS=1000,
    )
    agent.security = SimpleNamespace(level_name="full")
    agent.github = SimpleNamespace(is_available=lambda: False)
    agent.web = SimpleNamespace(is_available=lambda: True)
    agent.docs = SimpleNamespace(status=lambda: "ready")
    agent.code = SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 2})
    agent.memory = SimpleNamespace(get_last_file=lambda: None)
    class _Todo:
        def __len__(self) -> int:
            return 0

    agent.todo = _Todo()
    agent._load_instruction_files = lambda: "K" * 1800

    context = asyncio.run(agent._build_context())
    assert context.endswith("[Not] Bağlam yerel model için kırpıldı.")

    agent._supervisor = SimpleNamespace(run_task=AsyncMock(return_value="   "))
    warning = asyncio.run(agent._try_multi_agent("test"))
    assert "geçerli bir çıktı" in warning


@pytest.mark.parametrize(
    "text,expected_handler",
    [
        (".status", "_try_health"),
        (".clear", "_try_clear_memory"),
        (".audit", "_try_audit"),
        (".gpu", "_try_gpu_optimize"),
    ],
)
def test_auto_handle_dot_commands_route_expected_handlers(
    text: str, expected_handler: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    handler = AutoHandle(
        code=SimpleNamespace(),
        health=SimpleNamespace(),
        github=SimpleNamespace(),
        memory=SimpleNamespace(),
        web=SimpleNamespace(),
        pkg=SimpleNamespace(),
        docs=SimpleNamespace(),
        cfg=SimpleNamespace(AUTO_HANDLE_TIMEOUT=1),
    )
    for name in ("_try_health", "_try_clear_memory", "_try_audit", "_try_gpu_optimize"):
        monkeypatch.setattr(handler, name, AsyncMock(return_value=(name == expected_handler, name)))

    handled, response = asyncio.run(handler._try_dot_command(text, text.lower()))
    assert handled is True
    assert response == expected_handler


@pytest.mark.parametrize(
    "exc,expected",
    [
        (json.JSONDecodeError("bad", "{", 1), True),
        (RuntimeError("schema validation failed"), True),
        (RuntimeError("429 too many requests"), True),
        (RuntimeError("network hiccup"), False),
    ],
)
def test_swarm_should_fallback_to_supervisor_parametrized(exc: Exception, expected: bool) -> None:
    assert SwarmOrchestrator._should_fallback_to_supervisor(exc) is expected
