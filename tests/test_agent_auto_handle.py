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


class TestAutoHandleEarlyExitBranches:
    @pytest.mark.parametrize(
        "method_name, command_text, expected_response",
        [
            ("_try_github_list_files", "github dosyaları listele", "dosya-list-branch"),
            ("_try_github_read", "github'dan README oku", "uzak-okuma-branch"),
        ],
    )
    def test_handle_stops_on_github_branch(self, method_name, command_text, expected_response, monkeypatch):
        if "pydantic" not in sys.modules:
            pydantic_stub = types.ModuleType("pydantic")
            pydantic_stub.BaseModel = object
            pydantic_stub.Field = lambda *a, **k: None
            pydantic_stub.ValidationError = Exception
            sys.modules["pydantic"] = pydantic_stub

        handler, *_ = _make_auto_handle()

        monkeypatch.setattr(handler, "_try_clear_memory", AsyncMock(return_value=(False, "")))
        monkeypatch.setattr(handler, "_try_audit", AsyncMock(return_value=(False, "")))
        monkeypatch.setattr(handler, "_try_health", AsyncMock(return_value=(False, "")))
        monkeypatch.setattr(handler, "_try_gpu_optimize", AsyncMock(return_value=(False, "")))
        monkeypatch.setattr(handler, "_try_github_commits", lambda *_: (False, ""))
        monkeypatch.setattr(handler, "_try_github_info", lambda *_: (False, ""))

        if method_name == "_try_github_list_files":
            monkeypatch.setattr(handler, "_try_github_list_files", lambda *_: (True, expected_response))
            monkeypatch.setattr(handler, "_try_github_read", lambda *_: (_ for _ in ()).throw(AssertionError("read branch should not run")))
        else:
            monkeypatch.setattr(handler, "_try_github_list_files", lambda *_: (False, ""))
            monkeypatch.setattr(handler, "_try_github_read", lambda *_: (True, expected_response))
            monkeypatch.setattr(handler, "_try_github_list_prs", lambda *_: (_ for _ in ()).throw(AssertionError("list_prs branch should not run")))

        handled, response = asyncio.run(handler.handle(command_text))
        assert handled is True
        assert response == expected_response


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

    def test_pr_detail_with_missing_number_is_not_auto_handled(self):
        handler, *_ = _make_auto_handle()
        handled, response = asyncio.run(handler.handle("PR detayını göster"))
        assert handled is True
        assert "PR listesi" in response

    def test_pr_detail_when_service_returns_error_is_prefixed(self):
        handler, _, _, github, *_ = _make_auto_handle()
        github.get_pull_request.return_value = (False, "404 not found")
        handled, response = asyncio.run(handler.handle("PR #42 detayı"))
        assert handled is True
        assert response == "404 not found"


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

    @pytest.mark.asyncio
    async def test_health_timeout_returns_warning_message(self, monkeypatch):
        handler, *_ = _make_auto_handle()

        async def _raise_timeout(*_args, **_kwargs):
            raise asyncio.TimeoutError()

        monkeypatch.setattr(handler, "_run_blocking", _raise_timeout)
        handled, response = await handler.handle("sistem sağlık raporu")
        assert handled is True
        assert "zaman aşımı" in response.lower()


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


class TestAutoHandleParametrizedBranches:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "command_text,expected_substring",
        [
            (".status", "sistem sağlığı"),
            (".health", "sistem sağlığı"),
            (".clear", "temizlendi"),
            (".audit", "denetim"),
            (".gpu", "gpu"),
        ],
    )
    async def test_dot_commands_with_single_parametrized_test(self, command_text, expected_substring):
        handler, *_ = _make_auto_handle()

        handled, response = await handler.handle(command_text)

        assert handled is True
        assert expected_substring in response.lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "text",
        [
            "dosyayı oku ardından düzenle",
            "önce test yaz sonra çalıştır",
            "1) build al 2) deploy et",
            "first run tests then open report",
            "step 1: lint step 2: test",
            "planı yap ve ardından uygula",
        ],
    )
    async def test_multi_step_inputs_are_not_auto_handled(self, text):
        handler, *_ = _make_auto_handle()

        handled, response = await handler.handle(text)

        assert handled is False
        assert response == ""


class TestAutoHandleErrorAndBranchCoverage:
    @pytest.mark.asyncio
    async def test_audit_timeout_returns_warning(self):
        handler, code, *_ = _make_auto_handle()
        code.audit_project = MagicMock(side_effect=asyncio.TimeoutError)

        handled, response = await handler.handle(".audit")

        assert handled is True
        assert "zaman aşım" in response.lower()

    @pytest.mark.asyncio
    async def test_gpu_optimize_exception_returns_warning(self):
        handler, _, health, *_ = _make_auto_handle()
        health.optimize_gpu_memory = MagicMock(side_effect=RuntimeError("gpu driver unavailable"))

        handled, response = await handler.handle(".gpu")

        assert handled is True
        assert "başarısız" in response.lower()
        assert "gpu driver unavailable" in response

    @pytest.mark.asyncio
    async def test_validate_json_success_path(self):
        handler, code, *_ = _make_auto_handle()
        code.read_file.return_value = (True, '{"ok": true}')
        code.validate_json.return_value = (True, "JSON geçerli")

        handled, response = await handler.handle('dosya doğrula "config.json"')

        assert handled is True
        assert response.startswith("✓")

    @pytest.mark.asyncio
    async def test_validate_unsupported_extension_returns_warning(self):
        handler, code, *_ = _make_auto_handle()
        code.read_file.return_value = (True, "[section]\nvalue=1")

        handled, response = await handler.handle('dosya doğrula "settings.ini"')

        assert handled is True
        assert "desteklenmiyor" in response.lower()

    @pytest.mark.asyncio
    async def test_docs_add_secondary_url_form_with_title(self):
        handler, *_, docs = _make_auto_handle()

        handled, response = await handler.handle('bu URL\'yi belge deposuna ekle: https://example.com "Örnek Başlık"')

        assert handled is True
        assert "eklendi" in response.lower()
        docs.add_document_from_url.assert_awaited_once_with("https://example.com", title="Örnek Başlık")

    @pytest.mark.asyncio
    async def test_unmatched_input_returns_not_handled(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler.handle("bu ifade hiçbir kalıpla eşleşmez")
        assert handled is False
        assert response == ""


class TestAutoHandleNegativeBranchExits:
    @pytest.mark.asyncio
    async def test_try_dot_command_returns_false_for_non_dot_text(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler._try_dot_command("status", "status")
        assert handled is False
        assert response == ""

    @pytest.mark.asyncio
    async def test_try_health_returns_false_when_pattern_not_matched(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler._try_health("selam nasılsın")
        assert handled is False
        assert response == ""

    @pytest.mark.asyncio
    async def test_try_gpu_optimize_returns_false_when_pattern_not_matched(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler._try_gpu_optimize("sadece sohbet")
        assert handled is False
        assert response == ""

    @pytest.mark.asyncio
    async def test_try_fetch_url_returns_false_when_intent_missing(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler._try_fetch_url("rastgele ifade", "rastgele ifade")
        assert handled is False
        assert response == ""

    @pytest.mark.asyncio
    async def test_try_docs_add_returns_false_without_add_intent(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler._try_docs_add(
            "doküman hakkında konuşalım",
            "doküman hakkında konuşalım",
        )
        assert handled is False
        assert response == ""

    def test_try_security_status_returns_false_when_keywords_absent(self):
        handler, *_ = _make_auto_handle()
        handled, response = handler._try_security_status("kod kalitesini artır")
        assert handled is False
        assert response == ""


class TestAutoHandleErrorBranches:
    @pytest.mark.asyncio
    async def test_audit_timeout_returns_warning(self):
        handler, code, *_ = _make_auto_handle()
        with patch.object(handler, "_run_blocking", AsyncMock(side_effect=asyncio.TimeoutError)):
            handled, response = await handler.handle("sistemi tara")
        assert handled is True
        assert "zaman aşımı" in response.lower()

    @pytest.mark.asyncio
    async def test_health_without_manager_returns_warning(self):
        handler, *_ = _make_auto_handle()
        handler.health = None
        handled, response = await handler.handle("sistem sağlık raporu")
        assert handled is True
        assert "başlatılamadı" in response.lower()

    @pytest.mark.asyncio
    async def test_gpu_optimize_exception_returns_warning(self):
        handler, *_ = _make_auto_handle()
        with patch.object(handler, "_run_blocking", AsyncMock(side_effect=RuntimeError("gpu busy"))):
            handled, response = await handler.handle("gpu optimize et")
        assert handled is True
        assert "başarısız" in response.lower()

    @pytest.mark.asyncio
    async def test_docs_add_without_url_falls_back_to_react(self):
        handler, *_ = _make_auto_handle()
        handled, response = await handler.handle("belge deposuna ekle")
        assert handled is False
        assert response == ""
