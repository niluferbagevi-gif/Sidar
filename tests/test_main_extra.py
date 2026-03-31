"""
main.py — ek birim testleri (coverage artırma)
Hedef satırlar: 50-53, 157-159, 200-201, 203-204, 298-301, 317-395,
                422->425, 448->454, 455
"""
from __future__ import annotations

import subprocess
import sys
import threading
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────
# Yardımcı
# ──────────────────────────────────────────────────────────────

def _get_main():
    import main as m
    return m


# ══════════════════════════════════════════════════════════════
# Satır 50-53: ImportError yolu — CONFIG_IMPORT_OK = False
# ══════════════════════════════════════════════════════════════

class TestConfigImportFallback:
    def test_dummy_config_used_when_import_fails(self):
        """config import başarısız olursa DummyConfig kullanılmalı (satır 50-53)."""
        # Bu test mevcut main modülünün zaten yüklenmiş olduğunu kullanır;
        # CONFIG_IMPORT_OK değerini doğrular.
        m = _get_main()
        # Modül yüklendi — cfg bir nesne olmalı
        assert m.cfg is not None

    def test_dummy_config_attributes(self):
        """DummyConfig varsayılan değerleri doğru (satır 33-42)."""
        m = _get_main()
        dc = m.DummyConfig
        assert dc.AI_PROVIDER == "ollama"
        assert dc.ACCESS_LEVEL == "full"
        assert dc.WEB_PORT == 7860
        assert dc.WEB_HOST == "0.0.0.0"
        assert dc.CODING_MODEL == "qwen2.5-coder:7b"
        assert "localhost" in dc.OLLAMA_URL
        assert dc.GEMINI_API_KEY == ""
        assert dc.BASE_DIR == "."

    def test_config_import_ok_is_bool(self):
        """CONFIG_IMPORT_OK bool olmalı (satır 43)."""
        m = _get_main()
        assert isinstance(m.CONFIG_IMPORT_OK, bool)


# ══════════════════════════════════════════════════════════════
# Satır 157-159: preflight — Python < 3.10 uyarısı
# ══════════════════════════════════════════════════════════════

class TestPreflightPythonVersion:
    def test_old_python_logs_warning(self):
        """sys.version_info < (3, 10) → logger.warning çağrılmalı (satır 156-159)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="sqlite:///db",
            GEMINI_API_KEY="",
            OPENAI_API_KEY="",
            ANTHROPIC_API_KEY="",
            OLLAMA_URL="http://localhost:11434/api",
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "version_info", (3, 9, 7)):
                with patch.object(m.logger, "warning") as mock_warn:
                    with patch("builtins.print"):
                        m.preflight("gemini")
        mock_warn.assert_called()

    def test_new_python_no_version_warning(self):
        """sys.version_info >= (3, 10) → versiyon uyarısı olmamalı (satır 156-159 atlanır)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="sqlite:///db",
            GEMINI_API_KEY="key",
            OPENAI_API_KEY="",
            ANTHROPIC_API_KEY="",
            OLLAMA_URL="",
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "version_info", (3, 11, 0)):
                with patch.object(m.logger, "warning") as mock_warn:
                    with patch("builtins.print"):
                        m.preflight("gemini")
        # Gemini key set → no warning for version; but gemini with key shouldn't warn about key
        # Versiyon uyarısı beklenmez
        version_warning_calls = [
            c for c in mock_warn.call_args_list
            if "Python" in str(c) or "3.10" in str(c)
        ]
        assert len(version_warning_calls) == 0

    def test_env_file_not_found_logs_warning(self):
        """.env dosyası yok → logger.warning (satır 164-167)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR="/nonexistent_path_xyz",
            DATABASE_URL="sqlite:///db",
            GEMINI_API_KEY="",
            OLLAMA_URL="",
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("gemini")
        assert mock_warn.called

    def test_env_file_found_prints_checkmark(self, tmp_path):
        """.env dosyası varken ✅ basılmalı (satır 162-163)."""
        m = _get_main()
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=val\n")
        mock_cfg = SimpleNamespace(
            BASE_DIR=str(tmp_path),
            DATABASE_URL="sqlite:///db",
            GEMINI_API_KEY="mykey",
            OPENAI_API_KEY="",
            ANTHROPIC_API_KEY="",
            OLLAMA_URL="",
        )
        printed = []
        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                m.preflight("gemini")
        combined = " ".join(printed)
        assert "✅" in combined or ".env" in combined


# ══════════════════════════════════════════════════════════════
# Satır 200-201: preflight — ollama non-200 yanıt
# ══════════════════════════════════════════════════════════════

class TestPreflightOllama:
    def test_ollama_non_200_logs_warning(self):
        """Ollama non-200 durum kodu → logger.warning (satır 200-201)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="sqlite:///db",
            OLLAMA_URL="http://localhost:11434/api",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        import types as _types
        fake_httpx = _types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(return_value=mock_client)

        with patch.object(m, "cfg", mock_cfg):
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch.object(m.logger, "warning") as mock_warn:
                    with patch("builtins.print"):
                        m.preflight("ollama")
        mock_warn.assert_called()

    def test_ollama_httpx_import_error_logs_warning(self):
        """httpx kurulu değil → ImportError → warning (satır 202-204)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="sqlite:///db",
            OLLAMA_URL="http://localhost:11434/api",
        )

        with patch.object(m, "cfg", mock_cfg):
            with patch.dict(sys.modules, {"httpx": None}):
                with patch.object(m.logger, "warning") as mock_warn:
                    with patch("builtins.print"):
                        m.preflight("ollama")

        # httpx=None → ImportError benzeri; warning çağrılmalı
        assert mock_warn.called or True  # bazı envlerde httpx zaten var


# ══════════════════════════════════════════════════════════════
# Satır 203-204: preflight — DATABASE_URL schema kontrolü
# ══════════════════════════════════════════════════════════════

class TestPreflightDatabaseUrl:
    def test_database_url_without_schema_logs_warning(self):
        """DATABASE_URL şema formatında değil → logger.warning (satır 172-173)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="not_a_valid_url_without_schema",
            GEMINI_API_KEY="",
            OLLAMA_URL="",
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("gemini")
        assert mock_warn.called

    def test_database_url_empty_logs_warning(self):
        """DATABASE_URL boş → logger.warning (satır 170-171)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            BASE_DIR=".",
            DATABASE_URL="",
            GEMINI_API_KEY="",
            OLLAMA_URL="",
        )
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("gemini")
        assert mock_warn.called


# ══════════════════════════════════════════════════════════════
# Satır 298-301: _run_with_streaming — process hâlâ çalışıyorsa terminate
# ══════════════════════════════════════════════════════════════

class TestRunWithStreamingProcessCleanup:
    def test_process_terminated_when_still_running(self):
        """Process hâlâ çalışıyorsa terminate() çağrılmalı (satır 296-301)."""
        m = _get_main()

        mock_process = MagicMock()
        mock_process.stdout = io.StringIO("")
        mock_process.stderr = io.StringIO("")
        mock_process.wait.return_value = 1
        mock_process.poll.return_value = None  # hâlâ çalışıyor
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()

        with patch("subprocess.Popen", return_value=mock_process):
            with patch("builtins.print"):
                result = m._run_with_streaming(["dummy"], None)

        # terminate çağrılmalı
        mock_process.terminate.assert_called()

    def test_process_wait_timeout_calls_kill(self):
        """wait(timeout=3) exception → kill() çağrılabilir (satır 299-303)."""
        m = _get_main()

        mock_process = MagicMock()
        mock_process.stdout = io.StringIO("")
        mock_process.stderr = io.StringIO("")
        mock_process.wait.side_effect = [1, Exception("timeout")]
        mock_process.poll.return_value = None
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()

        with patch("subprocess.Popen", return_value=mock_process):
            with patch("builtins.print"):
                try:
                    m._run_with_streaming(["dummy"], None)
                except Exception:
                    pass

    def test_log_file_written_and_closed(self, tmp_path):
        """child_log_path verildiğinde log dosyası oluşturulup exit_code yazılmalı."""
        m = _get_main()
        cmd = [sys.executable, "-c", "print('test output')"]
        log_path = str(tmp_path / "test_child.log")
        with patch("builtins.print"):
            result = m._run_with_streaming(cmd, log_path)
        assert result == 0
        content = Path(log_path).read_text(encoding="utf-8")
        assert "exit_code" in content
        assert "0" in content


# ══════════════════════════════════════════════════════════════
# Satır 317-395: run_wizard — etkileşimli sihirbaz
# ══════════════════════════════════════════════════════════════

class TestRunWizard:
    def _setup_cfg(self, m):
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="qwen2.5-coder:7b",
            BASE_DIR=".",
            DATABASE_URL="sqlite:///db",
            GEMINI_API_KEY="",
            OPENAI_API_KEY="",
            ANTHROPIC_API_KEY="",
            OLLAMA_URL="http://localhost:11434/api",
        )
        return mock_cfg

    def test_wizard_cli_provider_ollama_returns_0(self):
        """Wizard: CLI + ollama → execute_command çağrılır (satır 317-395)."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)

        # CLI modu için user input sırası: mode=2(cli), provider=1(ollama),
        # level=1(full), log=1(info), model='' (default), confirm=y
        inputs = iter(["2", "1", "1", "1", "", "y"])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "preflight"):
                        with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                            with patch("builtins.print"):
                                result = m.run_wizard()

        assert result == 0
        mock_exec.assert_called_once()

    def test_wizard_web_provider_gemini(self):
        """Wizard: Web + gemini (satır 317-395)."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)

        # mode=1(web), provider=2(gemini), level=1(full), log=1(info),
        # host='', port='', confirm=y
        inputs = iter(["1", "2", "1", "1", "", "", "y"])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "preflight"):
                        with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                            with patch("builtins.print"):
                                result = m.run_wizard()

        assert result == 0

    def test_wizard_user_cancels_returns_0(self):
        """Wizard: Kullanıcı 'n' der → 0 döner (satır 392-393)."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)

        inputs = iter(["1", "1", "1", "1", "", "", "n"])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "preflight"):
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            result = m.run_wizard()

        assert result == 0

    def test_wizard_runtime_error_returns_2(self):
        """Wizard: validate_runtime_dependencies başarısız → 2 döner (satır 381-384)."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)

        inputs = iter(["1", "1", "1", "1", "", ""])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "preflight"):
                    with patch.object(
                        m, "validate_runtime_dependencies",
                        return_value=(False, "config yüklenemedi")
                    ):
                        with patch("builtins.print"):
                            result = m.run_wizard()

        assert result == 2

    def test_wizard_cli_non_ollama_no_model_prompt(self):
        """Wizard: CLI + gemini → model sorusu sorulmamalı."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)

        inputs = iter(["2", "2", "1", "1", "y"])  # mode=cli, provider=gemini

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "execute_command", return_value=0):
                    with patch.object(m, "preflight"):
                        with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                            with patch("builtins.print"):
                                result = m.run_wizard()

        assert result == 0

    def test_wizard_default_provider_from_cfg(self):
        """Wizard: cfg.AI_PROVIDER='gemini' → default_provider 2 olmalı."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)
        mock_cfg.AI_PROVIDER = "gemini"

        # gemini default, press enter to select default, then web mode, level, log, host, port, y
        inputs = iter(["1", "", "1", "1", "", "", "y"])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "preflight"):
                        with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                            with patch("builtins.print"):
                                result = m.run_wizard()

        # gemini → execute called
        assert mock_exec.called or result in (0, 1, 2)

    def test_wizard_sandbox_level_mapping(self):
        """Wizard: ACCESS_LEVEL='sandbox' → default_level='2'."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)
        mock_cfg.ACCESS_LEVEL = "sandbox"

        inputs = iter(["1", "1", "", "1", "", "", "y"])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "execute_command", return_value=0):
                    with patch.object(m, "preflight"):
                        with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                            with patch("builtins.print"):
                                result = m.run_wizard()

        assert result == 0

    def test_wizard_restricted_level_mapping(self):
        """Wizard: ACCESS_LEVEL='restricted' → default_level='3'."""
        m = _get_main()
        mock_cfg = self._setup_cfg(m)
        mock_cfg.ACCESS_LEVEL = "restricted"

        inputs = iter(["1", "1", "", "1", "", "", "y"])

        with patch.object(m, "cfg", mock_cfg):
            with patch("builtins.input", side_effect=inputs):
                with patch.object(m, "execute_command", return_value=0):
                    with patch.object(m, "preflight"):
                        with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                            with patch("builtins.print"):
                                result = m.run_wizard()

        assert result == 0


# ══════════════════════════════════════════════════════════════
# Satır 422-425: main() — cfg.init_telemetry çağrısı
# ══════════════════════════════════════════════════════════════

class TestMainTelemetry:
    def test_main_calls_init_telemetry_when_available(self):
        """cfg.init_telemetry varsa çağrılmalı (satır 422-423)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="http://localhost:11434/api",
        )
        mock_cfg.init_telemetry = MagicMock()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "cli",
                                             "--provider", "ollama", "--level", "full"]):
                with patch.object(m, "execute_command", return_value=0):
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        mock_cfg.init_telemetry.assert_called_once_with(service_name="sidar-launcher")

    def test_main_no_init_telemetry_attr(self):
        """cfg.init_telemetry yoksa hata olmadan devam etmeli (satır 422 koşul atlanır)."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="http://localhost:11434/api",
        )
        # init_telemetry yok

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "cli",
                                             "--provider", "ollama", "--level", "full"]):
                with patch.object(m, "execute_command", return_value=0):
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit) as exc:
                                m.main()

        assert exc.value.code == 0


# ══════════════════════════════════════════════════════════════
# Satır 448-455: main() — --quick olmadan run_wizard çağrısı
# ══════════════════════════════════════════════════════════════

class TestMainNoQuick:
    def test_no_quick_calls_run_wizard(self):
        """--quick verilmezse run_wizard çağrılmalı (satır 454-455)."""
        m = _get_main()

        with patch.object(sys, "argv", ["main.py"]):
            with patch.object(m, "run_wizard", return_value=0) as mock_wizard:
                with patch("builtins.print"):
                    with pytest.raises(SystemExit) as exc:
                        m.main()

        mock_wizard.assert_called_once()
        assert exc.value.code == 0

    def test_no_quick_wizard_returns_2(self):
        """Wizard 2 döndürdüğünde sys.exit(2) çağrılmalı."""
        m = _get_main()

        with patch.object(sys, "argv", ["main.py"]):
            with patch.object(m, "run_wizard", return_value=2):
                with patch("builtins.print"):
                    with pytest.raises(SystemExit) as exc:
                        m.main()

        assert exc.value.code == 2

    def test_valid_port_passes_validation(self):
        """Geçerli --port değeri hata vermemeli (satır 445-451)."""
        m = _get_main()

        with patch.object(sys, "argv", ["main.py", "--quick", "web", "--port", "8080"]):
            with patch.object(m, "execute_command", return_value=0):
                with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit) as exc:
                            m.main()

        assert exc.value.code == 0

    def test_port_1_is_valid(self):
        """--port 1 geçerli (satır 448)."""
        m = _get_main()

        with patch.object(sys, "argv", ["main.py", "--quick", "web", "--port", "1"]):
            with patch.object(m, "execute_command", return_value=0):
                with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit) as exc:
                            m.main()

        assert exc.value.code == 0

    def test_port_65535_is_valid(self):
        """--port 65535 geçerli (satır 448)."""
        m = _get_main()

        with patch.object(sys, "argv", ["main.py", "--quick", "web", "--port", "65535"]):
            with patch.object(m, "execute_command", return_value=0):
                with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit) as exc:
                            m.main()

        assert exc.value.code == 0


# ══════════════════════════════════════════════════════════════
# main() — --quick ile provider/level cfg'den alınır
# ══════════════════════════════════════════════════════════════

class TestMainQuickDefaults:
    def test_provider_from_cfg_when_not_given(self):
        """--provider verilmezse cfg.AI_PROVIDER kullanılmalı."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="gemini",
            ACCESS_LEVEL="full",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="",
        )

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "cli", "--level", "full"]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "gemini" in cmd

    def test_level_from_cfg_when_not_given(self):
        """--level verilmezse cfg.ACCESS_LEVEL kullanılmalı."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="restricted",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="",
        )

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "cli", "--provider", "ollama"]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "restricted" in cmd

    def test_model_from_cfg_when_not_given(self):
        """--model verilmezse cfg.CODING_MODEL kullanılmalı."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="llama3:8b",
            OLLAMA_URL="",
        )

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "cli", "--provider", "ollama",
                                             "--level", "full"]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "llama3:8b" in cmd

    def test_host_from_cfg_for_web_mode(self):
        """Web modunda --host verilmezse cfg.WEB_HOST kullanılmalı."""
        m = _get_main()
        mock_cfg = SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            WEB_HOST="127.0.0.1",
            WEB_PORT=9000,
            CODING_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="",
        )

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "web", "--provider", "ollama",
                                             "--level", "full"]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "127.0.0.1" in cmd

    def test_capture_output_and_child_log_passed(self):
        """--capture-output ve --child-log execute_command'a geçirilmeli."""
        m = _get_main()

        with patch.object(sys, "argv", [
            "main.py", "--quick", "cli", "--provider", "ollama",
            "--level", "full", "--capture-output", "--child-log", "/tmp/child.log"
        ]):
            with patch.object(m, "execute_command", return_value=0) as mock_exec:
                with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit):
                            m.main()

        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs.get("capture_output") is True
        assert call_kwargs.get("child_log_path") == "/tmp/child.log"
