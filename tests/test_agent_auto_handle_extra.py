"""
agent/auto_handle.py için ek kapsama testleri.
Eksik satırları (timeout, error, edge-case) hedefler.
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_auto_handle(cfg=None):
    code = MagicMock()
    code.list_directory.return_value = (True, "dizin içeriği")
    code.read_file.return_value = (True, "dosya içeriği\nsatır2")
    code.audit_project.return_value = "denetim raporu"
    code.validate_python_syntax.return_value = (True, "Sözdizimi geçerli")
    code.validate_json.return_value = (True, "JSON geçerli")
    code.security = MagicMock()
    code.security.status_report.return_value = "güvenlik raporu"

    health = MagicMock()
    health.full_report.return_value = "sağlık raporu"
    health.optimize_gpu_memory.return_value = "GPU temizlendi"

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

    # Stub pydantic so agent/__init__.py can import sidar_agent without it installed
    if "pydantic" not in sys.modules:
        pydantic_mod = types.ModuleType("pydantic")
        pydantic_mod.BaseModel = MagicMock
        pydantic_mod.Field = MagicMock
        pydantic_mod.ValidationError = type("ValidationError", (Exception,), {})
        sys.modules["pydantic"] = pydantic_mod

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
        cfg=cfg,
    )
    return handler, code, health, github, memory, web, pkg, docs


# ── _try_dot_command extra branches ──────────────────────────────────────────

class TestDotCommandExtraBranches:
    def test_dot_audit_handled(self):
        async def _run():
            handler, code, *_ = _make_auto_handle()
            code.audit_project.return_value = "denetim tamam"
            handled, response = await handler.handle(".audit")
            assert handled is True

        def test_dot_gpu_handled(self):
            async def _run():
                handler, _, health, *_ = _make_auto_handle()
                handled, response = await handler.handle(".gpu")
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_dot_command_unknown_returns_false(self):
            async def _run():
                handler, *_ = _make_auto_handle()
                # .xyz is not a known dot command
                handled, response = await handler.handle(".xyz")
                assert handled is False
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_dot_command_no_match_returns_false(self):
            async def _run():
                handler, *_ = _make_auto_handle()
                r = await handler._try_dot_command("normal text", "normal text")
                assert r == (False, "")
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _try_health timeout and error ─────────────────────────────────────────────

        asyncio.run(_run())
class TestTryHealthErrors:
    def test_health_timeout(self):
        async def _run():
            handler, *_ = _make_auto_handle()
            handler._run_blocking = AsyncMock(side_effect=asyncio.TimeoutError())
            handled, response = await handler._try_health("sistem sağlık raporu")
            assert handled is True
            assert "zaman aşımı" in response.lower()

        def test_health_generic_exception(self):
            async def _run():
                handler, *_ = _make_auto_handle()
                handler._run_blocking = AsyncMock(side_effect=RuntimeError("test hata"))
                handled, response = await handler._try_health("sistem sağlık raporu")
                assert handled is True
                assert "hata" in response.lower() or "alınamadı" in response.lower()
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_health_no_health_manager(self):
            async def _run():
                handler, _, health, *_ = _make_auto_handle()
                handler.health = None
                handled, response = await handler._try_health("sistem sağlık raporu")
                assert handled is True
                assert "başlatılamadı" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _try_gpu_optimize timeout and error ─────────────────────────────────────

        asyncio.run(_run())
class TestTryGpuErrors:
    def test_gpu_timeout(self):
        async def _run():
            handler, *_ = _make_auto_handle()
            handler._run_blocking = AsyncMock(side_effect=asyncio.TimeoutError())
            handled, response = await handler._try_gpu_optimize("vram temizle")
            assert handled is True
            assert "zaman aşımı" in response.lower()

        def test_gpu_generic_error(self):
            async def _run():
                handler, *_ = _make_auto_handle()
                handler._run_blocking = AsyncMock(side_effect=OSError("gpu hata"))
                handled, response = await handler._try_gpu_optimize("gpu optimize")
                assert handled is True
                assert "başarısız" in response.lower() or "hata" in response.lower()
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_gpu_no_health_manager(self):
            async def _run():
                handler, _, health, *_ = _make_auto_handle()
                handler.health = None
                handled, response = await handler._try_gpu_optimize(".gpu")
                assert handled is True
                assert "başlatılamadı" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _try_audit timeout and error ─────────────────────────────────────────────

        asyncio.run(_run())
class TestTryAuditErrors:
    def test_audit_generic_error(self):
        async def _run():
            handler, *_ = _make_auto_handle()
            handler._run_blocking = AsyncMock(side_effect=RuntimeError("audit hatası"))
            handled, response = await handler._try_audit("denetle")
            assert handled is True
            assert "hata" in response.lower()

        def test_audit_no_match_returns_false(self):
            async def _run():
                handler, *_ = _make_auto_handle()
                handled, response = await handler._try_audit("merhaba dünya")
                assert handled is False
                assert response == ""
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _try_read_file error path ─────────────────────────────────────────────────

        asyncio.run(_run())
class TestTryReadFileErrors:
    def test_read_file_error(self):
        async def _run():
            handler, code, *_ = _make_auto_handle()
            code.read_file.return_value = (False, "dosya bulunamadı")
            handled, response = await handler.handle('dosyayı oku "missing.py"')
            assert handled is True
            assert "✗" in response

        def test_read_file_uses_memory_last_file(self):
            async def _run():
                handler, code, _, _, memory, *_ = _make_auto_handle()
                memory.get_last_file.return_value = "cached.py"
                code.read_file.return_value = (True, "cached content")
                handled, response = await handler.handle("dosyayı oku")
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_read_file_cat_keyword(self):
            async def _run():
                handler, code, *_ = _make_auto_handle()
                code.read_file.return_value = (True, "file content here")
                handled, response = await handler.handle('cat "main.py"')
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _try_validate_file edge cases ────────────────────────────────────────────

        asyncio.run(_run())
class TestTryValidateFile:
    def test_validate_json_file(self):
        async def _run():
            handler, code, *_ = _make_auto_handle()
            code.read_file.return_value = (True, '{"key": "value"}')
            code.validate_json.return_value = (True, "JSON geçerli")
            handled, response = await handler.handle('sözdizimi doğrula "config.json"')
            assert handled is True
            assert "✓" in response

        def test_validate_unsupported_extension(self):
            async def _run():
                handler, code, *_ = _make_auto_handle()
                code.read_file.return_value = (True, "content")
                handled, response = await handler.handle('sözdizimi doğrula "file.txt"')
                assert handled is True
                assert "desteklenmiyor" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_validate_read_error(self):
            async def _run():
                handler, code, *_ = _make_auto_handle()
                code.read_file.return_value = (False, "okunamadı")
                handled, response = await handler.handle('sözdizimi doğrula "bad.py"')
                assert handled is True
                assert "okunamadı" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_validate_no_path_returns_warning(self):
            async def _run():
                handler, *_ = _make_auto_handle()
                handled, response = await handler.handle("sözdizimi doğrula")
                assert handled is True
                assert "⚠" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_validate_python_fail(self):
            async def _run():
                handler, code, *_ = _make_auto_handle()
                code.read_file.return_value = (True, "def broken(")
                code.validate_python_syntax.return_value = (False, "SyntaxError")
                handled, response = await handler.handle('sözdizimi doğrula "script.py"')
                assert handled is True
                assert "✗" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _try_github_read error path ───────────────────────────────────────────────

        asyncio.run(_run())
class TestTryGithubReadErrors:
    def test_github_read_no_path(self):
        async def _run():
            handler, _, _, github, *_ = _make_auto_handle()
            handled, response = await handler.handle("github oku")
            assert handled is True
            assert "⚠" in response

        def test_github_read_unavailable(self):
            async def _run():
                handler, _, _, github, *_ = _make_auto_handle()
                github.is_available.return_value = False
                handled, response = await handler.handle('github oku "README.md"')
                assert handled is True
                assert "token" in response.lower() or "ayarlanmamış" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_github_read_error_response(self):
            async def _run():
                handler, _, _, github, *_ = _make_auto_handle()
                github.read_remote_file.return_value = (False, "erişim reddedildi")
                handled, response = await handler.handle('github oku "README.md"')
                assert handled is True
                assert "✗" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _try_github_list_prs various states ──────────────────────────────────────

        asyncio.run(_run())
class TestTryGithubListPrs:
    def test_pr_list_closed_state(self):
        async def _run():
            handler, _, _, github, *_ = _make_auto_handle()
            handled, response = await handler.handle("kapalı PR listele")
            assert handled is True

        def test_pr_list_all_state(self):
            async def _run():
                handler, _, _, github, *_ = _make_auto_handle()
                handled, response = await handler.handle("tüm pull request listele")
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_pr_list_unavailable(self):
            async def _run():
                handler, _, _, github, *_ = _make_auto_handle()
                github.is_available.return_value = False
                handled, response = await handler.handle("PR listele")
                assert handled is True
                assert "token" in response.lower() or "ayarlanmamış" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_pr_get_files(self):
            async def _run():
                handler, _, _, github, *_ = _make_auto_handle()
                github.get_pr_files.return_value = (True, "PR dosya listesi")
                handled, response = await handler.handle("PR #7 dosyaları")
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_pr_get_unavailable(self):
            async def _run():
                handler, _, _, github, *_ = _make_auto_handle()
                github.is_available.return_value = False
                handled, response = await handler.handle("PR #3 detayı")
                assert handled is True
                assert "token" in response.lower() or "ayarlanmamış" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_pr_files_unavailable(self):
            async def _run():
                handler, _, _, github, *_ = _make_auto_handle()
                github.is_available.return_value = False
                handled, response = await handler.handle("PR #5 dosyaları")
                assert handled is True
                assert "token" in response.lower() or "ayarlanmamış" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _try_github_info and _try_github_list_files unavailable ─────────────────

        asyncio.run(_run())
class TestGithubInfoListUnavailable:
    def test_github_info_unavailable(self):
        async def _run():
            handler, _, _, github, *_ = _make_auto_handle()
            github.is_available.return_value = False
            handled, response = await handler.handle("github repo bilgisi")
            assert handled is True
            assert "token" in response.lower() or "ayarlanmamış" in response

        def test_github_list_files_unavailable(self):
            async def _run():
                handler, _, _, github, *_ = _make_auto_handle()
                github.is_available.return_value = False
                handled, response = await handler.handle("github repo dosyaları listele")
                assert handled is True
                assert "token" in response.lower() or "ayarlanmamış" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_github_commits_with_number(self):
            async def _run():
                handler, _, _, github, *_ = _make_auto_handle()
                handled, response = await handler.handle("5 commit listele")
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _try_clear_memory awaitable ───────────────────────────────────────────────

        asyncio.run(_run())
class TestClearMemoryAwaitable:
    def test_clear_memory_awaitable_clear(self):
        async def _run():
            handler, _, _, _, memory, *_ = _make_auto_handle()
            memory.clear = AsyncMock(return_value=None)
            handled, response = await handler.handle("belleği temizle")
            assert handled is True
            assert "temizlendi" in response

        def test_hafiza_sifirla(self):
            async def _run():
                handler, *_ = _make_auto_handle()
                handled, response = await handler.handle("hafızayı sıfırla")
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_konusmayi_sil(self):
            async def _run():
                handler, *_ = _make_auto_handle()
                handled, response = await handler.handle("konuşmayı sil")
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _try_web_search empty query ───────────────────────────────────────────────

        asyncio.run(_run())
class TestWebSearchEdgeCases:
    def test_web_search_empty_query(self):
        async def _run():
            handler, *_ = _make_auto_handle()
            handled, response = await handler.handle("web'de ara ")
            # Empty query: may not be handled or returns warning
            assert isinstance(handled, bool)
            assert isinstance(response, str)

        def test_fetch_url_no_url(self):
            async def _run():
                handler, *_ = _make_auto_handle()
                handled, response = await handler.handle("url oku")
                assert handled is True
                assert "⚠" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_fetch_url_with_url(self):
            async def _run():
                handler, _, _, _, _, web, *_ = _make_auto_handle()
                handled, response = await handler.handle("url oku https://example.com")
                assert handled is True
                assert "URL içeriği" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_stackoverflow_search(self):
            async def _run():
                handler, _, _, _, _, web, *_ = _make_auto_handle()
                handled, response = await handler.handle("stackoverflow: python async")
                assert handled is True
                assert "SO sonuçları" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_search_docs_with_topic(self):
            async def _run():
                handler, _, _, _, _, web, *_ = _make_auto_handle()
                handled, response = await handler.handle("docs ara fastapi routing")
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _try_pypi with version compare ───────────────────────────────────────────

        asyncio.run(_run())
class TestPypiNpmGh:
    def test_pypi_version_compare(self):
        async def _run():
            handler, _, _, _, _, _, pkg, _ = _make_auto_handle()
            handled, response = await handler.handle("pypi requests 2.31.0")
            assert handled is True
            assert "pypi karşılaştırma" in response

        def test_npm_package_info(self):
            async def _run():
                handler, _, _, _, _, _, pkg, _ = _make_auto_handle()
                handled, response = await handler.handle("npm react")
                assert handled is True
                assert "npm bilgisi" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_github_releases(self):
            async def _run():
                handler, _, _, _, _, _, pkg, _ = _make_auto_handle()
                handled, response = await handler.handle("github releases tiangolo/fastapi")
                assert handled is True
                assert "releases" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _try_docs_search mode selection ──────────────────────────────────────────

        asyncio.run(_run())
class TestDocsSearch:
    def test_docs_search_with_mode(self):
        async def _run():
            handler, _, _, _, _, _, _, docs = _make_auto_handle()
            docs.search.return_value = (True, "vektör sonuç")
            handled, response = await handler.handle("depoda ara python mode:vector")
            assert handled is True

        def test_docs_list(self):
            async def _run():
                handler, _, _, _, _, _, _, docs = _make_auto_handle()
                handled, response = await handler.handle("belge listele")
                assert handled is True
                assert "belge listesi" in response
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_docs_add_primary_form(self):
            async def _run():
                handler, _, _, _, _, _, _, docs = _make_auto_handle()
                handled, response = await handler.handle("belge ekle https://example.com/doc")
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_docs_add_secondary_form(self):
            async def _run():
                handler, _, _, _, _, _, _, docs = _make_auto_handle()
                handled, response = await handler.handle("belge depo ekle https://example.com")
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_docs_add_with_title(self):
            async def _run():
                handler, _, _, _, _, _, _, docs = _make_auto_handle()
                handled, response = await handler.handle('belge ekle https://example.com "Başlık"')
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_docs_search_awaitable(self):
            async def _run():
                import asyncio as _asyncio
                handler, _, _, _, _, _, _, docs = _make_auto_handle()
                async def fake_search(*args):
                    return (True, "async sonuç")
                docs.search.return_value = fake_search()
                handled, response = await handler.handle("depoda ara python")
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _try_security_status ─────────────────────────────────────────────────────

        asyncio.run(_run())
class TestSecurityStatus:
    def test_openclaw_keyword(self):
        async def _run():
            handler, code, *_ = _make_auto_handle()
            handled, response = await handler.handle("openclaw durumu")
            assert handled is True
            assert "güvenlik raporu" in response

        def test_erisim_seviyesi_keyword(self):
            async def _run():
                handler, code, *_ = _make_auto_handle()
                handled, response = await handler.handle("erişim seviyesi ne")
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_sandbox_mod_keyword(self):
            async def _run():
                handler, code, *_ = _make_auto_handle()
                handled, response = await handler.handle("sandbox mod kontrol")
                assert handled is True
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── Helpers ────────────────────────────────────────────────────────────────────

        asyncio.run(_run())
class TestHelpers:
    def test_extract_path_quoted(self):
        handler, *_ = _make_auto_handle()
        assert handler._extract_path('"my_file.py"') == "my_file.py"

    def test_extract_path_bare(self):
        handler, *_ = _make_auto_handle()
        result = handler._extract_path("oku main.py şimdi")
        assert result == "main.py"

    def test_extract_path_none(self):
        handler, *_ = _make_auto_handle()
        assert handler._extract_path("hiçbir yol yok burada") is None

    def test_extract_dir_path_quoted_no_extension(self):
        handler, *_ = _make_auto_handle()
        result = handler._extract_dir_path('"src/module"')
        assert result == "src/module"

    def test_extract_dir_path_explicit_dotslash(self):
        handler, *_ = _make_auto_handle()
        result = handler._extract_dir_path("listele ./src dizinini")
        assert result == "./src"

    def test_extract_dir_path_with_extension_returns_none(self):
        handler, *_ = _make_auto_handle()
        result = handler._extract_dir_path("listele ./src/main.py")
        assert result is None

    def test_extract_url_found(self):
        handler, *_ = _make_auto_handle()
        assert handler._extract_url("bak https://example.com/path") == "https://example.com/path"

    def test_extract_url_not_found(self):
        handler, *_ = _make_auto_handle()
        assert handler._extract_url("url yok") is None

    def test_cfg_timeout_applied(self):
        cfg = MagicMock()
        cfg.AUTO_HANDLE_TIMEOUT = "30"
        handler, *_ = _make_auto_handle(cfg=cfg)
        assert handler.command_timeout == 30.0

    def test_default_timeout_no_cfg(self):
        handler, *_ = _make_auto_handle()
        assert handler.command_timeout == 12.0
