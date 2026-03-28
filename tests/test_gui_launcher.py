"""gui_launcher.py için birim testleri."""

from __future__ import annotations

import importlib
import sys
import types


def _load_gui_launcher(*, execute_return_code: int = 0, preflight_raises: Exception | None = None):
    """main modülünü stub'layıp gui_launcher'ı temiz import eder."""
    main_stub = types.ModuleType("main")

    state = {
        "preflight_calls": [],
        "build_calls": [],
        "execute_calls": [],
    }

    def _preflight(provider: str):
        state["preflight_calls"].append(provider)
        if preflight_raises is not None:
            raise preflight_raises

    def _build_command(mode: str, provider: str, level: str, log_level: str, extra_args: dict):
        state["build_calls"].append((mode, provider, level, log_level, dict(extra_args)))
        return ["python", "dummy.py", mode, provider, level, log_level]

    def _execute_command(cmd):
        state["execute_calls"].append(list(cmd))
        return execute_return_code

    main_stub.preflight = _preflight
    main_stub.build_command = _build_command
    main_stub.execute_command = _execute_command

    previous_main = sys.modules.get("main")
    sys.modules["main"] = main_stub
    sys.modules.pop("gui_launcher", None)
    module = importlib.import_module("gui_launcher")
    if previous_main is not None:
        sys.modules["main"] = previous_main
    else:
        sys.modules.pop("main", None)
    return module, state


class TestConstants:
    def test_default_log_level_is_info(self):
        mod, _ = _load_gui_launcher()
        assert mod.DEFAULT_LOG_LEVEL == "info"

    def test_default_web_args_keys(self):
        mod, _ = _load_gui_launcher()
        assert "host" in mod.DEFAULT_WEB_ARGS
        assert "port" in mod.DEFAULT_WEB_ARGS

    def test_default_web_args_values(self):
        mod, _ = _load_gui_launcher()
        assert mod.DEFAULT_WEB_ARGS["host"] == "0.0.0.0"
        assert mod.DEFAULT_WEB_ARGS["port"] == "7860"


class TestNormalizeSelection:
    def test_normalize_selection_trims_and_lowercases(self):
        mod, _ = _load_gui_launcher()
        result = mod._normalize_selection(" WEB ", " OLLAMA ", " FULL ", " DEBUG ")

        assert result == {
            "mode": "web",
            "provider": "ollama",
            "level": "full",
            "log_level": "debug",
        }

    def test_invalid_mode_raises(self):
        mod, _ = _load_gui_launcher()
        try:
            mod._normalize_selection("desktop", "ollama", "full", "info")
            assert False, "ValueError bekleniyordu"
        except ValueError as exc:
            assert "Geçersiz mode" in str(exc)

    def test_invalid_provider_raises(self):
        mod, _ = _load_gui_launcher()
        try:
            mod._normalize_selection("cli", "gpt4", "full", "info")
            assert False, "ValueError bekleniyordu"
        except ValueError as exc:
            assert "Geçersiz provider" in str(exc)

    def test_invalid_level_raises(self):
        mod, _ = _load_gui_launcher()
        try:
            mod._normalize_selection("cli", "ollama", "superuser", "info")
            assert False, "ValueError bekleniyordu"
        except ValueError as exc:
            assert "Geçersiz level" in str(exc)

    def test_invalid_log_level_raises(self):
        mod, _ = _load_gui_launcher()
        try:
            mod._normalize_selection("cli", "ollama", "full", "verbose")
            assert False, "ValueError bekleniyordu"
        except ValueError as exc:
            assert "Geçersiz log_level" in str(exc)

    def test_all_valid_providers_accepted(self):
        mod, _ = _load_gui_launcher()
        for provider in ("ollama", "gemini", "openai", "anthropic"):
            result = mod._normalize_selection("cli", provider, "full", "info")
            assert result["provider"] == provider

    def test_all_valid_levels_accepted(self):
        mod, _ = _load_gui_launcher()
        for level in ("restricted", "sandbox", "full"):
            result = mod._normalize_selection("cli", "ollama", level, "info")
            assert result["level"] == level


class TestExtraArgsForMode:
    def test_web_mode_returns_default_web_args_copy(self):
        mod, _ = _load_gui_launcher()
        args = mod._extra_args_for_mode("web")

        assert args == {"host": "0.0.0.0", "port": "7860"}
        assert args is not mod.DEFAULT_WEB_ARGS  # defensive copy

    def test_cli_mode_returns_empty_dict(self):
        mod, _ = _load_gui_launcher()
        assert mod._extra_args_for_mode("cli") == {}


class TestLaunchFromGui:
    def test_launch_success_returns_success_payload(self):
        mod, state = _load_gui_launcher(execute_return_code=0)

        result = mod.launch_from_gui("web", "ollama", "full", "info")

        assert result["status"] == "success"
        assert result["return_code"] == 0
        assert state["preflight_calls"] == ["ollama"]
        assert state["build_calls"][0][0:4] == ("web", "ollama", "full", "info")
        assert state["build_calls"][0][4] == {"host": "0.0.0.0", "port": "7860"}
        assert state["execute_calls"]

    def test_launch_nonzero_return_code_maps_to_error_payload(self):
        mod, _ = _load_gui_launcher(execute_return_code=7)

        result = mod.launch_from_gui("cli", "gemini", "restricted", "warning")

        assert result["status"] == "error"
        assert result["return_code"] == 7
        assert "hata kodu" in result["message"]

    def test_launch_handles_exceptions_and_returns_error(self):
        mod, state = _load_gui_launcher(preflight_raises=RuntimeError("preflight fail"))

        result = mod.launch_from_gui("cli", "ollama", "full", "info")

        assert result == {"status": "error", "message": "preflight fail", "return_code": 1}
        assert state["execute_calls"] == []


class TestStartSidar:
    def test_start_sidar_delegates_to_launch(self):
        mod, _ = _load_gui_launcher()

        original = mod.launch_from_gui
        try:
            mod.launch_from_gui = lambda mode, provider, level, log_level: {
                "status": "success",
                "mode": mode,
                "provider": provider,
                "level": level,
                "log_level": log_level,
            }
            payload = mod.start_sidar("web", "openai", "sandbox", "debug")
            assert payload["mode"] == "web"
            assert payload["provider"] == "openai"
            assert payload["level"] == "sandbox"
            assert payload["log_level"] == "debug"
        finally:
            mod.launch_from_gui = original


class TestStartGui:
    def test_start_gui_raises_runtime_error_when_eel_missing(self):
        mod, _ = _load_gui_launcher()

        sys.modules.pop("eel", None)
        original_import = __import__

        def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "eel":
                raise ImportError("eel yok")
            return original_import(name, globals, locals, fromlist, level)

        import builtins

        builtins_import = builtins.__import__
        builtins.__import__ = _raising_import
        try:
            try:
                mod.start_gui()
                assert False, "RuntimeError bekleniyordu"
            except RuntimeError as exc:
                assert "Eel kurulu değil" in str(exc)
        finally:
            builtins.__import__ = builtins_import

    def test_start_gui_initializes_and_starts_eel(self):
        mod, _ = _load_gui_launcher()

        calls = {"init": None, "expose": None, "start": None}
        eel_stub = types.ModuleType("eel")
        eel_stub.init = lambda path: calls.update({"init": path})
        eel_stub.expose = lambda fn: calls.update({"expose": fn})
        eel_stub.start = lambda page, **kwargs: calls.update({"start": (page, kwargs)})
        sys.modules["eel"] = eel_stub

        mod.start_gui()

        assert calls["init"] is not None
        assert calls["init"].endswith("launcher_gui")
        assert calls["expose"] is mod.start_sidar
        assert calls["start"][0] == "index.html"
        assert calls["start"][1]["size"] == (980, 680)