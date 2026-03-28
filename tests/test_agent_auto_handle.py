"""
agent/auto_handle.py için birim testleri.
AutoHandle.handle ve yardımcı metodları kapsar.
Tüm manager bağımlılıkları MagicMock ile stub'lanır.
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_auto_handle():
    """AutoHandle örneği için gerekli tüm stub'ları oluşturup döndürür."""
    # Manager stub'ları
    code = MagicMock()
    code.list_directory.return_value = (True, "dizin içeriği")
    code.read_file.return_value = (True, "dosya içeriği\nsatır2\nsatır3")
    code.audit_project.return_value = "denetim raporu"
    code.validate_python_syntax.return_value = (True, "Sözdizimi geçerli")
    code.validate_json.return_value = (True, "JSON geçerli")
    code.security = MagicMock()
    code.security.status_report.return_value = "güvenlik raporu"

    health = MagicMock()
    health.full_report.return_value = "sistem sağlığı raporu"
    health.optimize_gpu_memory.return_value = "GPU optimize edildi"

    github = MagicMock()
    github.is_available.return_value = True
    github.list_commits.return_value = (True, "commit listesi")
    github.get_repo_info.return_value = (True, "repo bilgisi")
    github.list_files.return_value = (True, "dosya listesi")
    github.read_remote_file.return_value = (True, "uzak dosya içeriği")
    github.list_pull_requests.return_value = (True, "PR listesi")
    github.get_pull_request.return_value = (True, "PR detayı")
    github.get_pr_files.return_value = (True, "PR dosyaları")

    memory = MagicMock()
    memory.get_last_file.return_value = None
    memory.set_last_file.return_value = None
    memory.clear.return_value = None

    web = MagicMock()
    web.search = AsyncMock(return_value=(True, "arama sonuçları"))
    web.fetch_url = AsyncMock(return_value=(True, "URL içeriği"))
    web.search_docs = AsyncMock(return_value=(True, "dokümantasyon"))
    web.search_stackoverflow = AsyncMock(return_value=(True, "SO sonuçları"))

    pkg = MagicMock()
    pkg.pypi_info = AsyncMock(return_value=(True, "pypi bilgisi"))
    pkg.pypi_compare = AsyncMock(return_value=(True, "pypi karşılaştırma"))
    pkg.npm_info = AsyncMock(return_value=(True, "npm bilgisi"))
    pkg.github_releases = AsyncMock(return_value=(True, "releases"))

    docs = MagicMock()
    docs.search.return_value = (True, "belge arama sonucu")
    docs.list_documents.return_value = "belge listesi"
    docs.add_document_from_url = AsyncMock(return_value=(True, "belge eklendi"))

    # Modül stub'larını hazırla
    for mod_path in (
        "managers", "managers.code_manager", "managers.system_health",
        "managers.github_manager", "managers.web_search", "managers.package_info",
        "core", "core.memory", "core.rag",
    ):
        if mod_path not in sys.modules:
            sys.modules[mod_path] = types.ModuleType(mod_path)

    sys.modules["managers.code_manager"].CodeManager = MagicMock
    sys.modules["managers.system_health"].SystemHealthManager = MagicMock
    sys.modules["managers.github_manager"].GitHubManager = MagicMock
    sys.modules["managers.web_search"].WebSearchManager = MagicMock
    sys.modules["managers.package_info"].PackageInfoManager = MagicMock
    sys.modules["core.memory"].ConversationMemory = MagicMock
    sys.modules["core.rag"].DocumentStore = MagicMock

    sys.modules.pop("agent.auto_handle", None)
    from agent.auto_handle import AutoHandle

    handler = AutoHandle(
        code=code,
        health=health,
        github=github,
        memory=memory,
        web=web,
        pkg=pkg,
        docs=docs,
    )
    return handler, code, health, github, memory, web, pkg, docs


class TestAutoHandleLongInput:
    @pytest.mark.asyncio
    async def test_too_long_input_not_handled(self):
        handler, *_ = _make_auto_handle()
        long_text = "a" * 2001
        handled, response = await handler.handle(long_text)
        assert handled is False
        assert response == ""


class TestAutoHandleMultiStep:
    @pytest.mark.asyncio
    async def test_multi_step_ardından_not_handled(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler.handle("dosyayı oku ardından düzenle")
        assert handled is False

    @pytest.mark.asyncio
    async def test_multi_step_önce_sonra_not_handled(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler.handle("önce kodu yaz sonra test et")
        assert handled is False


class TestAutoHandleDotCommands:
    @pytest.mark.asyncio
    async def test_dot_status_handled(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler.handle(".status")
        assert handled is True

    @pytest.mark.asyncio
    async def test_dot_health_handled(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler.handle(".health")
        assert handled is True

    @pytest.mark.asyncio
    async def test_dot_clear_handled(self):
        handler, _, _, _, memory, *_ = _make_auto_handle()
        handled, response = await handler.handle(".clear")
        assert handled is True
        assert "temizlendi" in response.lower()


class TestAutoHandleClearMemory:
    @pytest.mark.asyncio
    async def test_belleği_temizle(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler.handle("belleği temizle")
        assert handled is True
        assert "temizlendi" in response

    @pytest.mark.asyncio
    async def test_sohbeti_sıfırla(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler.handle("sohbeti sıfırla")
        assert handled is True


class TestAutoHandleListDirectory:
    @pytest.mark.asyncio
    async def test_dizin_listele(self):
        handler, code, *_ = _make_auto_handle()
        handled, response = await handler.handle("dizin listele")
        assert handled is True
        assert "dizin içeriği" in response

    @pytest.mark.asyncio
    async def test_ls_command(self):
        handler, code, *_ = _make_auto_handle()
        handled, response = await handler.handle("ls .")
        assert handled is True


class TestAutoHandleReadFile:
    @pytest.mark.asyncio
    async def test_dosyayı_oku(self):
        handler, code, *_ = _make_auto_handle()
        handled, response = await handler.handle('dosyayı oku "main.py"')
        assert handled is True

    @pytest.mark.asyncio
    async def test_read_file_no_path_returns_warning(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler.handle("dosyayı oku")
        assert handled is True
        assert "⚠" in response


class TestAutoHandleGitHub:
    @pytest.mark.asyncio
    async def test_son_commit_listele(self):
        handler, _, _, github, *_ = _make_auto_handle()
        handled, response = await handler.handle("son commit listele")
        assert handled is True
        assert "commit listesi" in response

    @pytest.mark.asyncio
    async def test_github_unavailable(self):
        handler, _, _, github, *_ = _make_auto_handle()
        github.is_available.return_value = False
        handled, response = await handler.handle("son commit listele")
        assert handled is True
        assert "token" in response.lower() or "ayarlanmamış" in response

    @pytest.mark.asyncio
    async def test_pr_listele(self):
        handler, _, _, github, *_ = _make_auto_handle()
        handled, response = await handler.handle("PR listele")
        assert handled is True

    @pytest.mark.asyncio
    async def test_pr_detay_numarali(self):
        handler, _, _, github, *_ = _make_auto_handle()
        handled, response = await handler.handle("PR #3 detayı")
        assert handled is True
        assert "PR detayı" in response

    @pytest.mark.asyncio
    async def test_github_repo_bilgi(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler.handle("github repo bilgi")
        assert handled is True


class TestAutoHandleWebSearch:
    @pytest.mark.asyncio
    async def test_web_arama(self):
        handler, *_, web, pkg, docs = _make_auto_handle()
        handled, response = await handler.handle("web'de ara python asyncio")
        assert handled is True
        assert "arama sonuçları" in response

    @pytest.mark.asyncio
    async def test_stackoverflow_arama(self):
        handler, *_, web, pkg, docs = _make_auto_handle()
        handled, response = await handler.handle("stackoverflow: python async")
        assert handled is True
        assert "SO sonuçları" in response


class TestAutoHandlePackageInfo:
    @pytest.mark.asyncio
    async def test_pypi_sorgu(self):
        handler, *_, web, pkg, docs = _make_auto_handle()
        handled, response = await handler.handle("pypi requests")
        assert handled is True
        assert "pypi bilgisi" in response

    @pytest.mark.asyncio
    async def test_npm_sorgu(self):
        handler, *_, web, pkg, docs = _make_auto_handle()
        handled, response = await handler.handle("npm react")
        assert handled is True
        assert "npm bilgisi" in response


class TestAutoHandleHealth:
    @pytest.mark.asyncio
    async def test_sistem_sağlık(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler.handle("sistem sağlık raporu")
        assert handled is True

    @pytest.mark.asyncio
    async def test_health_manager_none(self):
        handler, code, _, github, memory, web, pkg, docs = _make_auto_handle()
        handler.health = None
        handled, response = await handler.handle("sistem sağlık raporu")
        assert handled is True
        assert "⚠" in response


class TestAutoHandleExtractors:
    def test_extract_path_quoted(self):
        handler, *_ = _make_auto_handle()
        result = handler._extract_path('"config.py"')
        assert result == "config.py"

    def test_extract_path_extension(self):
        handler, *_ = _make_auto_handle()
        result = handler._extract_path("managers/code_manager.py dosyasını oku")
        assert "code_manager.py" in result

    def test_extract_path_no_match(self):
        handler, *_ = _make_auto_handle()
        result = handler._extract_path("sadece metin")
        assert result is None

    def test_extract_url(self):
        handler, *_ = _make_auto_handle()
        result = handler._extract_url("şu url'yi oku: https://example.com/doc")
        assert result == "https://example.com/doc"

    def test_extract_url_none(self):
        handler, *_ = _make_auto_handle()
        result = handler._extract_url("url yok bu metinde")
        assert result is None

    def test_extract_dir_path_quoted(self):
        handler, *_ = _make_auto_handle()
        result = handler._extract_dir_path('"managers"')
        assert result == "managers"

    def test_extract_dir_path_relative(self):
        handler, *_ = _make_auto_handle()
        result = handler._extract_dir_path("./agent klasörünü listele")
        assert result == "./agent"


class TestAutoHandleSecurityStatus:
    def test_openclaw_triggers_security(self):
        handler, code, *_ = _make_auto_handle()
        handled, response = handler._try_security_status("openclaw durumu")
        assert handled is True
        assert "güvenlik raporu" in response

    def test_erişim_seviyesi_triggers(self):
        handler, code, *_ = _make_auto_handle()
        handled, response = handler._try_security_status("erişim seviyesi nedir")
        assert handled is True
