import asyncio
import sys
import types


class _FakeBaseAgent:
    def __init__(self, cfg=None, *, role_name="base"):
        self.cfg = cfg or types.SimpleNamespace()
        self.role_name = role_name


sys.modules.setdefault("agent.base_agent", types.SimpleNamespace(BaseAgent=_FakeBaseAgent))

from plugins.upload_agent import UploadAgent


def test_upload_agent_empty_prompt():
    agent = UploadAgent()
    response = asyncio.run(agent.run_task(""))
    assert response == "Boş görev alındı."


def test_upload_agent_valid_prompt():
    agent = UploadAgent()
    response = asyncio.run(agent.run_task("test.txt dosyasını yükle"))
    assert response == "UploadAgent: test.txt dosyasını yükle"
