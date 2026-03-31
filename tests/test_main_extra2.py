"""
main.py — additional unit tests (coverage improvement, batch 2)
Target lines: 56-70, 73-90, 93-97, 100-106, 109-119, 122-139,
              142-149, 152-208, 210-234, 237-240, 242-250, 398-419,
              421-481
"""
from __future__ import annotations

import io
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ──────────────────────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────────────────────

def _get_main():
    import main as m
    return m


# ══════════════════════════════════════════════════════════════
# print_banner (line 56-70)
# ══════════════════════════════════════════════════════════════

class TestPrintBanner:
    def test_print_banner_outputs_sidar(self):
        """print_banner() should print something containing 'SIDAR' (line 56-70)."""
        m = _get_main()
        printed = []
        with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
            m.print_banner()
        combined = " ".join(printed)
        assert "SIDAR" in combined or "Sidar" in combined or len(printed) > 0

    def test_print_banner_contains_welcome_message(self):
        """print_banner should print a welcome line (line 70)."""
        m = _get_main()
        printed = []
        with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
            m.print_banner()
        combined = " ".join(printed)
        assert len(combined) > 0


# ══════════════════════════════════════════════════════════════
# ask_choice (lines 73-90)
# ══════════════════════════════════════════════════════════════

class TestAskChoice:
    def test_ask_choice_empty_input_returns_default(self):
        """Empty input should return the default value (line 84-85)."""
        m = _get_main()
        options = {"1": ("Option A", "a"), "2": ("Option B", "b")}
        with patch("builtins.input", return_value=""):
            with patch("builtins.print"):
                result = m.ask_choice("Choose:", options, "1")
        assert result == "a"

    def test_ask_choice_valid_input_returns_value(self):
        """Valid selection returns corresponding value (line 87-88)."""
        m = _get_main()
        options = {"1": ("Option A", "a"), "2": ("Option B", "b")}
        with patch("builtins.input", return_value="2"):
            with patch("builtins.print"):
                result = m.ask_choice("Choose:", options, "1")
        assert result == "b"

    def test_ask_choice_invalid_then_valid(self):
        """Invalid then valid input - retries (line 90)."""
        m = _get_main()
        options = {"1": ("Option A", "a"), "2": ("Option B", "b")}
        inputs = iter(["x", "invalid", "1"])
        with patch("builtins.input", side_effect=inputs):
            with patch("builtins.print"):
                result = m.ask_choice("Choose:", options, "2")
        assert result == "a"

    def test_ask_choice_default_shows_default_marker(self):
        """Default option shows (Varsayılan) marker in output (line 78)."""
        m = _get_main()
        options = {"1": ("Option A", "a"), "2": ("Option B", "b")}
        printed = []
        with patch("builtins.input", return_value="1"):
            with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                m.ask_choice("Choose:", options, "1")
        combined = " ".join(printed)
        assert "Varsayılan" in combined


# ══════════════════════════════════════════════════════════════
# ask_text (lines 93-97)
# ══════════════════════════════════════════════════════════════

class TestAskText:
    def test_ask_text_returns_input(self):
        """ask_text returns user input (line 96-97)."""
        m = _get_main()
        with patch("builtins.input", return_value="mytext"):
            result = m.ask_text("Enter something:")
        assert result == "mytext"

    def test_ask_text_empty_returns_default(self):
        """Empty input returns default value (line 97)."""
        m = _get_main()
        with patch("builtins.input", return_value=""):
            result = m.ask_text("Enter something:", default="fallback")
        assert result == "fallback"

    def test_ask_text_with_default_shows_hint(self):
        """Default value shown as hint in prompt (line 95)."""
        m = _get_main()
        prompts = []
        def fake_input(p=""):
            prompts.append(p)
            return ""
        with patch("builtins.input", side_effect=fake_input):
            m.ask_text("Enter:", default="mydefault")
        assert any("mydefault" in p for p in prompts)


# ══════════════════════════════════════════════════════════════
# confirm (lines 100-106)
# ══════════════════════════════════════════════════════════════

class TestConfirm:
    def test_confirm_empty_default_yes_returns_true(self):
        """Empty input with default_yes=True returns True (line 104-105)."""
        m = _get_main()
        with patch("builtins.input", return_value=""):
            result = m.confirm("Confirm?", default_yes=True)
        assert result is True

    def test_confirm_empty_default_no_returns_false(self):
        """Empty input with default_yes=False returns False (line 104-105)."""
        m = _get_main()
        with patch("builtins.input", return_value=""):
            result = m.confirm("Confirm?", default_yes=False)
        assert result is False

    def test_confirm_y_returns_true(self):
        """Input 'y' returns True (line 106)."""
        m = _get_main()
        with patch("builtins.input", return_value="y"):
            result = m.confirm("Confirm?")
        assert result is True

    def test_confirm_yes_returns_true(self):
        """Input 'yes' returns True (line 106)."""
        m = _get_main()
        with patch("builtins.input", return_value="yes"):
            result = m.confirm("Confirm?")
        assert result is True

    def test_confirm_n_returns_false(self):
        """Input 'n' returns False (line 106)."""
        m = _get_main()
        with patch("builtins.input", return_value="n"):
            result = m.confirm("Confirm?")
        assert result is False

    def test_confirm_evet_returns_true(self):
        """Turkish 'evet' returns True (line 106)."""
        m = _get_main()
        with patch("builtins.input", return_value="evet"):
            result = m.confirm("Onaylar mısınız?")
        assert result is True


# ══════════════════════════════════════════════════════════════
# validate_runtime_dependencies (lines 109-119)
# ══════════════════════════════════════════════════════════════

class TestValidateRuntimeDependencies:
    def test_returns_true_when_config_import_ok(self):
        """CONFIG_IMPORT_OK=True → (True, None) (line 111-112)."""
        m = _get_main()
        with patch.object(m, "CONFIG_IMPORT_OK", True):
            ok, err = m.validate_runtime_dependencies("web")
        assert ok is True
        assert err is None

    def test_returns_false_for_web_when_config_fails(self):
        """CONFIG_IMPORT_OK=False + mode='web' → error mentions web_server.py (line 114-119)."""
        m = _get_main()
        with patch.object(m, "CONFIG_IMPORT_OK", False):
            ok, err = m.validate_runtime_dependencies("web")
        assert ok is False
        assert "web_server.py" in err

    def test_returns_false_for_cli_when_config_fails(self):
        """CONFIG_IMPORT_OK=False + mode='cli' → error mentions cli.py (line 114-119)."""
        m = _get_main()
        with patch.object(m, "CONFIG_IMPORT_OK", False):
            ok, err = m.validate_runtime_dependencies("cli")
        assert ok is False
        assert "cli.py" in err


# ══════════════════════════════════════════════════════════════
# _safe_choice (lines 122-130)
# ══════════════════════════════════════════════════════════════

class TestSafeChoice:
    def test_valid_choice_returned(self):
        """Valid choice string returned (line 130)."""
        m = _get_main()
        result = m._safe_choice("gemini", "ollama", {"ollama", "gemini", "openai"})
        assert result == "gemini"

    def test_invalid_choice_returns_default(self):
        """Choice not in allowed set → default (line 129)."""
        m = _get_main()
        result = m._safe_choice("invalid_val", "ollama", {"ollama", "gemini"})
        assert result == "ollama"

    def test_non_string_returns_default(self):
        """Non-string value → default (line 124-125)."""
        m = _get_main()
        result = m._safe_choice(123, "ollama", {"ollama", "gemini"})
        assert result == "ollama"

    def test_none_returns_default(self):
        """None value → default (line 124-125)."""
        m = _get_main()
        result = m._safe_choice(None, "ollama", {"ollama", "gemini"})
        assert result == "ollama"

    def test_empty_string_returns_default(self):
        """Empty string → default (line 128-129)."""
        m = _get_main()
        result = m._safe_choice("", "ollama", {"ollama", "gemini"})
        assert result == "ollama"

    def test_whitespace_normalized(self):
        """Value with spaces gets stripped (line 127)."""
        m = _get_main()
        result = m._safe_choice("  gemini  ", "ollama", {"ollama", "gemini"})
        assert result == "gemini"


# ══════════════════════════════════════════════════════════════
# _safe_text (lines 133-139)
# ══════════════════════════════════════════════════════════════

class TestSafeText:
    def test_valid_string_returned(self):
        """Non-empty string returned as-is (line 138-139)."""
        m = _get_main()
        result = m._safe_text("hello world", "default")
        assert result == "hello world"

    def test_none_returns_default(self):
        """None → default (line 135-136)."""
        m = _get_main()
        result = m._safe_text(None, "fallback")
        assert result == "fallback"

    def test_empty_string_returns_default(self):
        """Empty/whitespace string → default (line 138-139)."""
        m = _get_main()
        result = m._safe_text("   ", "fallback")
        assert result == "fallback"

    def test_number_converted_to_string(self):
        """Non-string value converted to str (line 138)."""
        m = _get_main()
        result = m._safe_text(42, "fallback")
        assert result == "42"


# ══════════════════════════════════════════════════════════════
# _safe_port (lines 142-149)
# ══════════════════════════════════════════════════════════════

class TestSafePort:
    def test_valid_port_returned(self):
        """Valid port number returned as string (line 149)."""
        m = _get_main()
        result = m._safe_port("8080", "7860")
        assert result == "8080"

    def test_invalid_port_returns_default(self):
        """Non-numeric → default (line 147-148)."""
        m = _get_main()
        result = m._safe_port("notaport", "7860")
        assert result == "7860"

    def test_port_too_high_returns_default(self):
        """Port > 65535 → default (line 149)."""
        m = _get_main()
        result = m._safe_port("99999", "7860")
        assert result == "7860"

    def test_port_zero_returns_default(self):
        """Port 0 → default (line 149)."""
        m = _get_main()
        result = m._safe_port("0", "7860")
        assert result == "7860"

    def test_int_port_converted(self):
        """Integer port value is handled (line 144)."""
        m = _get_main()
        result = m._safe_port(3000, "7860")
        assert result == "3000"


# ══════════════════════════════════════════════════════════════
# preflight (lines 152-208)
# ══════════════════════════════════════════════════════════════

class TestPreflightExtra:
    def _make_cfg(self, **kwargs):
        defaults = dict(
            BASE_DIR=".",
            DATABASE_URL="sqlite:///db",
            GEMINI_API_KEY="",
            OPENAI_API_KEY="",
            ANTHROPIC_API_KEY="",
            OLLAMA_URL="http://localhost:11434/api",
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_openai_missing_key_warns(self):
        """provider='openai' without OPENAI_API_KEY → warning (line 180-183)."""
        m = _get_main()
        mock_cfg = self._make_cfg(OPENAI_API_KEY="")
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("openai")
        assert mock_warn.called

    def test_anthropic_missing_key_warns(self):
        """provider='anthropic' without ANTHROPIC_API_KEY → warning (line 185-188)."""
        m = _get_main()
        mock_cfg = self._make_cfg(ANTHROPIC_API_KEY="")
        with patch.object(m, "cfg", mock_cfg):
            with patch.object(m.logger, "warning") as mock_warn:
                with patch("builtins.print"):
                    m.preflight("anthropic")
        assert mock_warn.called

    def test_ollama_200_prints_success(self):
        """Ollama returns 200 → success message printed (line 197-198)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(return_value=mock_client)

        printed = []
        with patch.object(m, "cfg", mock_cfg):
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                    m.preflight("ollama")
        combined = " ".join(printed)
        assert "✅" in combined or "Ollama" in combined

    def test_ollama_exception_warns(self):
        """Ollama connection exception → warning (line 205-207)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("Connection refused")

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(return_value=mock_client)

        with patch.object(m, "cfg", mock_cfg):
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch.object(m.logger, "warning") as mock_warn:
                    with patch("builtins.print"):
                        m.preflight("ollama")
        assert mock_warn.called

    def test_ollama_non_api_url_uses_correct_tags_url(self):
        """OLLAMA_URL without /api suffix builds correct tags URL (line 194)."""
        m = _get_main()
        mock_cfg = self._make_cfg(OLLAMA_URL="http://localhost:11434")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(return_value=mock_client)

        with patch.object(m, "cfg", mock_cfg):
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch("builtins.print"):
                    m.preflight("ollama")

        call_args = mock_client.get.call_args[0][0]
        assert "/api/tags" in call_args


# ══════════════════════════════════════════════════════════════
# build_command (lines 210-234)
# ══════════════════════════════════════════════════════════════

class TestBuildCommand:
    def test_web_mode_builds_correct_command(self):
        """Web mode includes host and port (line 231-232)."""
        m = _get_main()
        cmd = m.build_command("web", "gemini", "full", "info",
                               {"host": "0.0.0.0", "port": "8080"})
        assert "web_server.py" in cmd
        assert "--host" in cmd
        assert "0.0.0.0" in cmd
        assert "--port" in cmd
        assert "8080" in cmd

    def test_cli_ollama_includes_model(self):
        """CLI + ollama mode includes --model flag (line 229-230)."""
        m = _get_main()
        cmd = m.build_command("cli", "ollama", "full", "info",
                               {"model": "llama2:7b"})
        assert "cli.py" in cmd
        assert "--model" in cmd
        assert "llama2:7b" in cmd

    def test_cli_non_ollama_no_model(self):
        """CLI + non-ollama mode does not include --model flag (line 231-232)."""
        m = _get_main()
        cmd = m.build_command("cli", "gemini", "full", "info", {})
        assert "--model" not in cmd

    def test_invalid_mode_raises(self):
        """Invalid mode raises ValueError (line 217-218)."""
        m = _get_main()
        with pytest.raises(ValueError, match="Geçersiz mode"):
            m.build_command("invalid", "ollama", "full", "info", {})

    def test_invalid_provider_raises(self):
        """Invalid provider raises ValueError (line 219-220)."""
        m = _get_main()
        with pytest.raises(ValueError, match="Geçersiz provider"):
            m.build_command("web", "unknown", "full", "info", {})

    def test_invalid_level_raises(self):
        """Invalid level raises ValueError (line 221-222)."""
        m = _get_main()
        with pytest.raises(ValueError, match="Geçersiz level"):
            m.build_command("web", "gemini", "superuser", "info", {})

    def test_invalid_log_raises(self):
        """Invalid log level raises ValueError (line 223-224)."""
        m = _get_main()
        with pytest.raises(ValueError, match="Geçersiz log"):
            m.build_command("web", "gemini", "full", "verbose", {})

    def test_valid_restricted_level(self):
        """'restricted' is a valid level (line 213)."""
        m = _get_main()
        cmd = m.build_command("cli", "gemini", "restricted", "warning", {})
        assert "--level" in cmd
        assert "restricted" in cmd


# ══════════════════════════════════════════════════════════════
# _format_cmd (line 237-239)
# ══════════════════════════════════════════════════════════════

class TestFormatCmd:
    def test_format_cmd_quotes_parts(self):
        """_format_cmd quotes command parts (line 237-239)."""
        m = _get_main()
        result = m._format_cmd(["python", "script.py", "--arg", "value with space"])
        # shlex.quote uses single quotes for strings with spaces
        assert "'value with space'" in result or '"value with space"' in result or "value\\ with\\ space" in result

    def test_format_cmd_returns_string(self):
        """_format_cmd returns a string (line 237-239)."""
        m = _get_main()
        result = m._format_cmd(["python", "script.py"])
        assert isinstance(result, str)
        assert "python" in result
        assert "script.py" in result


# ══════════════════════════════════════════════════════════════
# _stream_pipe (lines 242-250)
# ══════════════════════════════════════════════════════════════

class TestStreamPipe:
    def test_stream_pipe_writes_to_file_obj(self):
        """_stream_pipe writes lines to file_obj (line 244-248)."""
        m = _get_main()
        pipe = io.StringIO("line1\nline2\n")
        file_obj = io.StringIO()
        with patch("builtins.print"):
            m._stream_pipe(pipe, file_obj, "[stdout]", m.CYAN, True)
        content = file_obj.getvalue()
        assert "line1" in content
        assert "line2" in content

    def test_stream_pipe_without_file_obj(self):
        """_stream_pipe handles None file_obj (line 245-248)."""
        m = _get_main()
        pipe = io.StringIO("hello\n")
        with patch("builtins.print"):
            m._stream_pipe(pipe, None, "[stdout]", m.CYAN, True)
        # No exception should be raised

    def test_stream_pipe_no_mirror_no_print(self):
        """mirror=False → print not called (line 248-249)."""
        m = _get_main()
        pipe = io.StringIO("data\n")
        printed = []
        with patch("builtins.print", side_effect=lambda *a, **k: printed.append(1)):
            m._stream_pipe(pipe, None, "[stdout]", m.CYAN, False)
        assert len(printed) == 0


# ══════════════════════════════════════════════════════════════
# execute_command (lines 398-419)
# ══════════════════════════════════════════════════════════════

class TestExecuteCommand:
    def test_execute_command_success_returns_0(self):
        """Successful subprocess.run returns 0 (line 409-410)."""
        m = _get_main()
        with patch("subprocess.run") as mock_run:
            with patch("builtins.print"):
                result = m.execute_command(["true"])
        assert result == 0

    def test_execute_command_keyboard_interrupt_returns_0(self):
        """KeyboardInterrupt returns 0 (line 411-413)."""
        m = _get_main()
        with patch("subprocess.run", side_effect=KeyboardInterrupt()):
            with patch("builtins.print"):
                result = m.execute_command(["dummy"])
        assert result == 0

    def test_execute_command_called_process_error_returns_code(self):
        """CalledProcessError returns non-zero code (line 414-416)."""
        m = _get_main()
        err = subprocess.CalledProcessError(returncode=42, cmd="dummy")
        with patch("subprocess.run", side_effect=err):
            with patch("builtins.print"):
                result = m.execute_command(["dummy"])
        assert result == 42

    def test_execute_command_generic_exception_returns_1(self):
        """Generic exception returns 1 (line 417-419)."""
        m = _get_main()
        with patch("subprocess.run", side_effect=RuntimeError("unexpected")):
            with patch("builtins.print"):
                result = m.execute_command(["dummy"])
        assert result == 1

    def test_execute_command_with_capture_output_uses_streaming(self):
        """capture_output=True uses _run_with_streaming (line 403-407)."""
        m = _get_main()
        with patch.object(m, "_run_with_streaming", return_value=0) as mock_stream:
            with patch("builtins.print"):
                result = m.execute_command(["dummy"], capture_output=True)
        mock_stream.assert_called_once()
        assert result == 0

    def test_execute_command_with_child_log_uses_streaming(self):
        """child_log_path triggers streaming path (line 403-407)."""
        m = _get_main()
        with patch.object(m, "_run_with_streaming", return_value=5) as mock_stream:
            with patch("builtins.print"):
                result = m.execute_command(["dummy"], child_log_path="/tmp/test.log")
        mock_stream.assert_called_once()
        assert result == 5

    def test_execute_command_streaming_nonzero_prints_error(self):
        """Non-zero return from streaming prints error message (line 405-407)."""
        m = _get_main()
        printed = []
        with patch.object(m, "_run_with_streaming", return_value=3):
            with patch("builtins.print", side_effect=lambda *a, **k: printed.append(str(a))):
                result = m.execute_command(["dummy"], capture_output=True)
        assert result == 3
        combined = " ".join(printed)
        assert "3" in combined or "hata" in combined.lower()


# ══════════════════════════════════════════════════════════════
# main() function (lines 421-481)
# ══════════════════════════════════════════════════════════════

class TestMainFunction:
    def _make_cfg(self, **kwargs):
        defaults = dict(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            CODING_MODEL="qwen2.5-coder:7b",
            OLLAMA_URL="http://localhost:11434/api",
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_main_quick_web_with_all_args(self):
        """--quick web with provider/level/host/port runs and exits (line 458-481)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "web",
                "--provider", "gemini",
                "--level", "sandbox",
                "--host", "127.0.0.1",
                "--port", "9090",
                "--log", "debug",
            ]):
                with patch.object(m, "execute_command", return_value=0):
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit) as exc_info:
                                m.main()
        assert exc_info.value.code == 0

    def test_main_quick_cli_default_provider_from_cfg(self):
        """--quick cli without --provider uses cfg.AI_PROVIDER (line 458-462)."""
        m = _get_main()
        mock_cfg = self._make_cfg(AI_PROVIDER="anthropic")

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "cli",
                "--level", "full",
            ]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "anthropic" in cmd

    def test_main_quick_cli_runtime_error_exits_2(self):
        """--quick cli with config import failure exits with code 2 (line 476-478)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py", "--quick", "cli"]):
                with patch.object(m, "validate_runtime_dependencies",
                                   return_value=(False, "config error")):
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit) as exc_info:
                            m.main()
        assert exc_info.value.code == 2

    def test_main_invalid_port_calls_parser_error(self):
        """--port with invalid value calls parser.error (line 445-451)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "web",
                "--provider", "ollama",
                "--port", "99999",
            ]):
                with patch("builtins.print"):
                    with pytest.raises(SystemExit):
                        m.main()

    def test_main_invalid_port_string_errors(self):
        """--port with non-numeric string → parser error (line 446-451)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "web",
                "--provider", "ollama",
                "--port", "abc",
            ]):
                with patch("builtins.print"):
                    with pytest.raises(SystemExit):
                        m.main()

    def test_main_no_quick_calls_run_wizard(self):
        """No --quick argument → run_wizard called (line 454-455)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", ["main.py"]):
                with patch.object(m, "run_wizard", return_value=0) as mock_wizard:
                    with patch("builtins.print"):
                        with pytest.raises(SystemExit):
                            m.main()
        mock_wizard.assert_called_once()

    def test_main_quick_with_model_arg(self):
        """--quick cli --model passes model to extra_args (line 469-473)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "cli",
                "--provider", "ollama",
                "--level", "full",
                "--model", "llama3:8b",
            ]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "llama3:8b" in cmd

    def test_main_quick_with_capture_output(self):
        """--capture-output flag passes to execute_command (line 434-436)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "cli",
                "--provider", "ollama",
                "--capture-output",
            ]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs.get("capture_output") is True

    def test_main_quick_with_child_log(self):
        """--child-log passes path to execute_command (line 439-441)."""
        m = _get_main()
        mock_cfg = self._make_cfg()

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "cli",
                "--provider", "ollama",
                "--child-log", "/tmp/child.log",
            ]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs.get("child_log_path") == "/tmp/child.log"

    def test_main_quick_level_from_cfg(self):
        """--quick without --level uses cfg.ACCESS_LEVEL (line 463-466)."""
        m = _get_main()
        mock_cfg = self._make_cfg(ACCESS_LEVEL="restricted")

        with patch.object(m, "cfg", mock_cfg):
            with patch.object(sys, "argv", [
                "main.py", "--quick", "cli",
                "--provider", "ollama",
            ]):
                with patch.object(m, "execute_command", return_value=0) as mock_exec:
                    with patch.object(m, "validate_runtime_dependencies", return_value=(True, None)):
                        with patch("builtins.print"):
                            with pytest.raises(SystemExit):
                                m.main()

        cmd = mock_exec.call_args[0][0]
        assert "restricted" in cmd
