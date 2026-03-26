import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.test_web_server_runtime import _load_web_server


@pytest.fixture
def mod():
    return _load_web_server()


def test_register_plugin_agent_from_source(mod):
    src = '''
from agent.base_agent import BaseAgent

class DemoAgent(BaseAgent):
    ROLE_NAME = "demo"

    async def run_task(self, task_prompt: str) -> str:
        return f"ok:{task_prompt}"
'''
    fake_spec = SimpleNamespace(
        capabilities=["demo", "tooling"],
        description="Demo plugin",
        version="1.2.3",
        is_builtin=False,
    )
    with patch.object(mod.AgentRegistry, "register_type", return_value=None, create=True), patch.object(mod.AgentRegistry, "get", return_value=fake_spec, create=True):
        result = mod._register_plugin_agent(
            role_name="demo_plugin",
            source_code=src,
            class_name="DemoAgent",
            capabilities=["demo", "tooling"],
            description="Demo plugin",
            version="1.2.3",
        )
    assert result["role_name"] == "demo_plugin"
    assert result["is_builtin"] is False
    assert "demo" in result["capabilities"]


def test_register_plugin_agent_endpoint_and_file_upload(mod, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    src = '''
from agent.base_agent import BaseAgent

class FileAgent(BaseAgent):
    async def run_task(self, task_prompt: str) -> str:
        return task_prompt
'''

    payload = mod._AgentPluginRegisterRequest(
        role_name="json_agent",
        source_code=src,
        class_name="FileAgent",
        capabilities=["x"],
        description="",
        version="1.0.0",
    )
    fake_spec = SimpleNamespace(
        capabilities=["x"],
        description="",
        version="1.0.0",
        is_builtin=False,
    )
    with patch.object(mod.AgentRegistry, "register_type", return_value=None, create=True), patch.object(mod.AgentRegistry, "get", return_value=fake_spec, create=True):
        resp = asyncio.run(mod.register_agent_plugin(payload, _user=object()))
    assert resp.content["success"] is True
    assert resp.content["agent"]["role_name"] == "json_agent"

    class _Upload:
        filename = "mock_file_agent.py"

        def __init__(self, data: bytes):
            self._data = data
            self.closed = False

        async def read(self):
            return self._data

        async def close(self):
            self.closed = True

    fake_upload_spec = SimpleNamespace(
        capabilities=["c1", "c2"],
        description="uploaded",
        version="2.0.0",
        is_builtin=False,
    )
    with patch.object(mod.AgentRegistry, "register_type", return_value=None, create=True), patch.object(mod.AgentRegistry, "get", return_value=fake_upload_spec, create=True):
        upload_resp = asyncio.run(
            mod.register_agent_plugin_file(
                file=_Upload(src.encode("utf-8")),
                role_name="",
                class_name="FileAgent",
                capabilities="c1,c2",
                description="uploaded",
                version="2.0.0",
                _user=object(),
            )
        )
    assert upload_resp.content["success"] is True
    assert upload_resp.content["agent"]["role_name"] == "mock_file_agent"
    assert (tmp_path / "plugins" / "mock_file_agent.py").exists()
    assert upload_resp.content["agent"]["version"] == "2.0.0"


def test_register_plugin_agent_validation_errors(mod):
    with pytest.raises(mod.HTTPException) as exc:
        mod._register_plugin_agent(
            role_name="bad role",
            source_code="",
            class_name=None,
            capabilities=[],
            description="",
            version="1.0.0",
        )
    assert exc.value.status_code == 400


def test_register_plugin_file_persists_and_imports_module(mod, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    src = b"from agent.base_agent import BaseAgent\n\nclass UploadAgent(BaseAgent):\n    async def run_task(self, task_prompt: str) -> str:\n        return task_prompt\n"

    class _Upload:
        filename = "upload_agent"

        def __init__(self, data: bytes):
            self._data = data
            self.closed = False

        async def read(self):
            return self._data

        async def close(self):
            self.closed = True

    fake_upload_spec = SimpleNamespace(
        capabilities=["c1"],
        description="uploaded",
        version="2.0.0",
        is_builtin=False,
    )
    with patch.object(mod.AgentRegistry, "register_type", return_value=None, create=True), patch.object(mod.AgentRegistry, "get", return_value=fake_upload_spec, create=True):
        upload_resp = asyncio.run(
            mod.register_agent_plugin_file(
                file=_Upload(src),
                role_name="",
                class_name="UploadAgent",
                capabilities="c1",
                description="uploaded",
                version="2.0.0",
                _user=object(),
            )
        )

    assert upload_resp.content["success"] is True
    assert (tmp_path / "plugins" / "upload_agent.py").exists()


def test_persist_and_import_plugin_file_import_error(mod, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(mod.HTTPException) as exc:
        mod._persist_and_import_plugin_file(
            "broken.py",
            b"raise RuntimeError('boom')\n",
            "sidar_uploaded_plugin_broken",
        )

    assert exc.value.status_code == 400
    assert "import edilemedi" in exc.value.detail