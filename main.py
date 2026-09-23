"""Sidar Project - Ultimate Launcher.

=================================
Görsel olarak zenginleştirilmiş etkileşimli menüler ile
argparse tabanlı, ön kontrollü (preflight) akıllı başlatıcı.
Kullanım: python main.py
Hızlı Kullanım: python main.py --quick web --provider ollama --level full

Not (isimlendirme): Bu dosya ajan REPL'i değildir -- yalnızca sihirbaz/preflight
akışını çalıştırıp sonuçta `build_command()`/`execute_command()` ile `cli.py`
(CLI REPL) veya `web_server.py`'yi alt süreçte başlatır. Gerçek ajan giriş
noktası `cli.py`'dir; `python cli.py` ile bu sihirbazı hiç atlayarak doğrudan
çalıştırılabilir. Bkz. `docs/module-notes/main.py.md`/`cli.py.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl as fcntl  # explicit legacy module export (tests patch main.fcntl)
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from core.utils.trusted_subprocess import run_trusted_command
from launcher import cli_args as launcher_cli_args
from launcher import doctor as launcher_doctor
from launcher import env_reload as launcher_env_reload
from launcher import preflight as launcher_preflight
from launcher import process as launcher_process
from launcher import selection as launcher_selection
from launcher import session as launcher_session
from launcher import ui as launcher_ui
from launcher import wizard as launcher_wizard

LAUNCHER_SESSION_FILENAME = ".sidar_session.json"
LAUNCHER_SESSION_VERSION = 1
MAX_AUTOFIX_RETRIES = 3


# Terminal Renkleri (ANSI)
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


# Config yükleme denemesi (Eğer dosya yoksa varsayılan değerler oluşturulur)
class DummyConfig:
    AI_PROVIDER = "ollama"
    ACCESS_LEVEL = "full"
    # Varsayılan olarak yalnız loopback'e bağlan; harici erişim WEB_HOST env
    # değişkeni veya CLI --host argümanıyla bilinçli şekilde açılır.
    WEB_HOST = "127.0.0.1"
    WEB_PORT = 7860
    CODING_MODEL = "qwen2.5-coder:7b"
    GEMINI_API_KEY = ""
    OLLAMA_URL = "http://localhost:11434/api"
    BASE_DIR = "."

    def initialize_directories(self) -> None:
        """Gerçek Config ile arayüz uyumluluğu için no-op."""
        return None


CONFIG_IMPORT_OK = True
logger = logging.getLogger(__name__)
_LAST_DOCTOR_AUTO_FIX_REVALIDATION: Any | None = None
_DOCTOR_APPLY_ALL_APPROVED: bool | None = None
_LAUNCHER_DOCTOR_AUTO_FIX_YES = False
BASE_DIR = str(Path(__file__).resolve().parent)


class LauncherError(Exception):
    """Base error for typed launcher diagnostics."""


class ConfigReloadError(LauncherError):
    """Raised when launcher-side config reload cannot complete."""


class DoctorCheckError(LauncherError):
    """Raised when a Doctor check or auto-fix step cannot complete."""


class LauncherEventLoopError(LauncherError):
    """Raised when the launcher cannot safely run an async coroutine."""


class LauncherEventLoopManager:
    """Centralize synchronous launcher access to async coroutines.

    main.py is mostly synchronous.  New async call sites should use this manager
    instead of scattering direct ``asyncio.Runner`` calls, so nested loop errors
    surface as a typed launcher diagnostic.
    """

    def run(self, coro: Any) -> Any:
        """Run one coroutine from a synchronous launcher context."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            with asyncio.Runner() as runner:
                return runner.run(coro)
        raise LauncherEventLoopError(
            "LauncherEventLoopManager.run() cannot be called from an active event loop; "
            "await the coroutine in the caller instead."
        )


_EVENT_LOOP_MANAGER = LauncherEventLoopManager()

try:
    import config as config_module

    Config = config_module.Config
    cfg: Any = Config()
    if hasattr(cfg, "initialize_directories"):
        cfg.initialize_directories()
except (ImportError, AttributeError):
    config_module = cast(Any, None)
    CONFIG_IMPORT_OK = False
    print(f"{YELLOW}⚠ config.py bulunamadı veya geçersiz, varsayılan ayarlar kullanılıyor.{RESET}")
    cfg = DummyConfig()

BASE_DIR = str(getattr(cfg, "BASE_DIR", BASE_DIR))


def print_banner() -> None:
    """Etkileşimli menü için renkli karşılama ekranı."""
    launcher_ui.print_banner(cyan=CYAN, bold=BOLD, reset=RESET, green=GREEN)


def ask_choice(
    prompt: str,
    options: dict[str, tuple[str, str]],
    default_key: str,
    *,
    default_badge: str | None = None,
) -> str:
    """Kullanıcıya seçenekler sunar ve güvenli bir şekilde girdiyi alır."""
    return launcher_ui.ask_choice(
        prompt,
        options,
        default_key,
        default_badge=default_badge,
        input_fn=input,
        yellow=YELLOW,
        bold=BOLD,
        reset=RESET,
        cyan=CYAN,
        green=GREEN,
        magenta=MAGENTA,
    )


def ask_text(prompt: str, default: str = "", *, default_badge: str | None = None) -> str:
    """Kullanıcıdan metin girdisi alır."""
    return launcher_ui.ask_text(
        prompt,
        default,
        default_badge=default_badge,
        input_fn=input,
        yellow=YELLOW,
        bold=BOLD,
        reset=RESET,
        cyan=CYAN,
        green=GREEN,
    )


def confirm(prompt: str, default_yes: bool = True) -> bool:
    """Kullanıcıdan Evet/Hayır onayı alır."""
    return launcher_ui.confirm(
        prompt,
        default_yes,
        input_fn=input,
        yellow=YELLOW,
        bold=BOLD,
        reset=RESET,
        cyan=CYAN,
    )


def validate_runtime_dependencies(mode: str) -> tuple[bool, str | None]:
    """Seçilen alt süreç için kritik runtime bağımlılıklarını doğrular."""
    if CONFIG_IMPORT_OK:
        return True, None

    target_script = "web_server.py" if mode == "web" else "cli.py"
    return (
        False,
        f"config.py yüklenemediği için {target_script} güvenli şekilde başlatılamıyor. "
        "Launcher varsayılanlarla açıldı ancak child process fail-fast olarak durduruldu.",
    )


def _project_base_dir() -> Path:
    """Launcher dosyalarını repo kökünde tutmak için güvenli base dizini döndürür."""
    raw_base_dir = getattr(cfg, "BASE_DIR", Path(__file__).resolve().parent)
    try:
        return Path(raw_base_dir).expanduser().resolve()
    except TypeError:
        return Path(__file__).resolve().parent


def _launcher_session_path(base_dir: Path | None = None) -> Path:
    """Son sihirbaz seçimlerinin yazıldığı git-ignored cache dosyasını döndürür."""
    return (base_dir or _project_base_dir()) / LAUNCHER_SESSION_FILENAME


def _development_env_path(base_dir: Path | None = None) -> Path:
    """Yerel geliştirme dotenv dosyasının beklenen konumunu döndürür."""
    return (base_dir or _project_base_dir()) / ".env.development"


def _normalize_launch_selection(selection: dict[str, object]) -> dict[str, Any]:
    """Cache/varsayılan kaynaklı launcher seçimlerini güvenli değerlere normalize eder."""
    return launcher_selection.normalize_launch_selection(selection, cfg=cfg)


def _default_launch_selection() -> dict[str, Any]:
    """--skip-wizard için config/default değerlerinden çalıştırılabilir seçim üretir."""
    return launcher_selection.default_launch_selection(cfg=cfg)


def _launcher_session_lock(
    session_path: Path, *, exclusive: bool
) -> contextlib.AbstractContextManager[None]:
    """Lock launcher session cache access across concurrent terminal processes."""
    return launcher_session.session_lock(session_path, exclusive=exclusive)


def _save_launcher_session(selection: dict[str, object], path: Path | None = None) -> Path:
    """Sihirbaz seçimlerini atomik şekilde .sidar_session.json cache'ine yazar."""
    return launcher_session.save_session(
        selection,
        path or _launcher_session_path(),
        normalize=_normalize_launch_selection,
        version=LAUNCHER_SESSION_VERSION,
    )


def _load_launcher_session(path: Path | None = None) -> dict[str, Any] | None:
    """Son sihirbaz seçimlerini cache'den güvenli şekilde okur."""
    return launcher_session.load_session(
        path or _launcher_session_path(),
        normalize=_normalize_launch_selection,
        version=LAUNCHER_SESSION_VERSION,
        logger_obj=logger,
    )


def _reload_config_environment(*, profile: str | None, reason: str) -> bool:
    """Reload config dotenv chain in the launcher process after external env edits."""
    if config_module is None:
        return False

    reload_environment = getattr(config_module, "reload_environment", None)
    if not callable(reload_environment):
        logger.warning("config.reload_environment bulunamadı; %s sonrası reload atlandı.", reason)
        return False

    global cfg
    try:
        reloaded_cfg = reload_environment(profile=profile)
    except (ConfigReloadError, RuntimeError, ValueError, OSError, TypeError) as exc:
        error = ConfigReloadError(f"{reason} sonrası environment reload başarısız")
        logger.warning("%s: %s", error, exc)
        print(f"{YELLOW}⚠ Environment reload başarısız: {exc}{RESET}")
        return False

    if reloaded_cfg is not None:
        cfg = reloaded_cfg
    effective_profile = profile or os.getenv("SIDAR_ENV", "").strip().lower() or "varsayılan"
    print(f"{GREEN}✅ Environment yeniden yüklendi: SIDAR_ENV={effective_profile}{RESET}")
    return True


def _reload_environment_after_bootstrap(profile: str = "development") -> bool:
    """Reload config dotenv chain after bootstrap creates a profile env file."""
    return _reload_config_environment(profile=profile, reason="Bootstrap")


_parse_doctor_env_source_file = launcher_env_reload.parse_env_source_file


_reload_doctor_env_source_definitions = launcher_env_reload.reload_env_source_definitions


_DATABASE_AUTO_FIX_ENV_KEYS = launcher_env_reload.DATABASE_AUTO_FIX_ENV_KEYS


def _reload_database_env_from_loaded_dotenv_chain() -> bool:
    """Force Doctor auto-fixed database keys from loaded dotenv files into this process."""
    return launcher_env_reload.reload_database_env_from_dotenv_chain(
        config_module, logger_obj=logger
    )


def _reload_environment_after_auto_fix(
    details: dict[str, Any] | None = None, *, check_name: str | None = None
) -> bool:
    """Reload only required env slices in this process after a Doctor auto-fix subprocess."""
    profile = os.getenv("SIDAR_ENV", "").strip().lower() or None
    if profile is None and _development_env_path().exists():
        profile = "development"
    requires_full_reload = check_name in {
        "database_env",
        "database_connectivity",
        "rag_readiness",
        "rag_index_ready",
        "graphrag_entity_memory_ready",
    }
    config_reloaded = False
    if requires_full_reload:
        config_reloaded = _reload_config_environment(profile=profile, reason="Doctor auto-fix")
    database_env_reloaded = False
    if not config_reloaded:
        database_env_reloaded = _reload_database_env_from_loaded_dotenv_chain()
    source_reloaded = _reload_doctor_env_source_definitions(details)
    if source_reloaded or database_env_reloaded:
        print(f"{GREEN}✅ Doctor env kaynakları yeniden uygulandı.{RESET}")
    return config_reloaded or database_env_reloaded or source_reloaded


def _maybe_bootstrap_development_env() -> bool:
    """Eksik .env.development için ön kontroller sırasında opsiyonel bootstrap önerir."""
    env_path = _development_env_path()
    if env_path.exists() or not sys.stdin.isatty():
        return False

    print(
        f"{YELLOW}⚠ .env.development bulunamadı. Yerel profil sihirbazdan önce "
        f"oluşturulabilir.{RESET}"
    )
    if not confirm(
        "Şimdi uv run python -m scripts.bootstrap_env --profile development çalıştırılsın mı?",
        True,
    ):
        return False

    cmd = ["uv", "run", "python", "-m", "scripts.bootstrap_env", "--profile", "development"]
    try:
        completed = run_trusted_command(
            cmd, check=False, cwd=_project_base_dir(), env=_launcher_child_env()
        )
    except OSError as exc:
        logger.warning("Development dotenv bootstrap başlatılamadı: %s", exc)
        print(f"{RED}⛔ Bootstrap komutu başlatılamadı: {exc}{RESET}")
        return False

    if completed.returncode != 0:
        print(f"{YELLOW}⚠ Bootstrap komutu {completed.returncode} koduyla tamamlandı.{RESET}")
        return False

    _reload_environment_after_bootstrap("development")
    print(f"{GREEN}✅ .env.development bootstrap tamamlandı.{RESET}")
    return True


def _apply_cli_overrides(selection: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """--skip-wizard akışında config/default seçime açık CLI override'larını uygular."""
    return launcher_selection.apply_cli_overrides(selection, args, cfg=cfg)


def _execute_launch_selection(
    selection: dict[str, Any], *, capture_output: bool = False, child_log_path: str | None = None
) -> int:
    """Normalize edilmiş seçimden komut oluşturup çalıştırır."""
    cmd = build_command(
        selection["mode"],
        selection["provider"],
        selection["level"],
        selection["log"],
        selection["extra_args"],
    )
    return execute_command(cmd, capture_output=capture_output, child_log_path=child_log_path)


def _safe_choice(value: object, default: str, allowed: set[str]) -> str:
    """Config/env kökenli seçimleri normalize eder; geçersizde default döner."""
    return launcher_selection.safe_choice(value, default, allowed)


def _safe_text(value: object, default: str) -> str:
    """Config/env kökenli metinleri normalize eder; boş/geçersizde default döner."""
    return launcher_selection.safe_text(value, default)


def _safe_port(value: object, default: str = "7860") -> str:
    """Config/env kökenli port değerlerini güvenli biçimde doğrular."""
    return launcher_selection.safe_port(value, default)


def _safe_host(value: object, default: str = "127.0.0.1") -> str:
    """Config/env kökenli host değerlerini `ipaddress` tabanlı doğrulayıcıdan geçirir.

    Geçersiz veya üretim profilinde reddedilen değerlerde güvenli yerel
    fallback (`127.0.0.1`) döner; böylece `# nosec B104` ile bypass yapmak
    yerine politika tek bir noktada uygulanır.
    """
    return launcher_selection.safe_host(value, default)


def _doctor_status_icon(status: str) -> str:
    return launcher_doctor.doctor_status_icon(status)


def _print_doctor_check_summary(check: Any) -> None:
    launcher_doctor.print_doctor_check_summary(check)


def _doctor_auto_fix_commands(details: dict[str, Any]) -> list[str]:
    """Return ordered Doctor auto-fix commands from legacy or multi-step metadata."""
    return launcher_doctor.doctor_auto_fix_commands(details)


def _doctor_auto_fix_fallback_commands(details: dict[str, Any]) -> list[str]:
    """Return fallback Doctor commands when primary auto-fix fails."""
    return launcher_doctor.doctor_auto_fix_fallback_commands(details)


def _select_doctor_auto_fix_commands(check_name: str, commands: list[str]) -> list[str]:
    """Interactive selector for checks that publish multiple auto-fix alternatives."""
    return launcher_doctor.select_doctor_auto_fix_commands(check_name, commands)


def _launcher_auto_fix_command(cmd: list[str]) -> list[str]:
    """Normalize Doctor auto-fix command tokens without altering caller intent."""
    return launcher_doctor.launcher_auto_fix_command(cmd)


def _run_doctor_auto_fix_command(auto_fix: str) -> bool:
    """Run one validated Doctor auto-fix command without invoking a shell."""
    return launcher_doctor.run_doctor_auto_fix_command(
        auto_fix,
        cwd=_project_base_dir(),
        env=_launcher_child_env(),
        format_cmd=_format_cmd,
        logger_obj=logger,
    )


def _run_doctor_auto_fix(
    check: Any, check_func: Any | None = None, *, apply_all_mode: bool = False
) -> bool:
    """Run Doctor auto-fix command(s), optionally revalidating after each successful step."""
    global _LAST_DOCTOR_AUTO_FIX_REVALIDATION
    _LAST_DOCTOR_AUTO_FIX_REVALIDATION = None
    return launcher_doctor.run_doctor_auto_fix(
        check,
        check_func,
        apply_all_mode=apply_all_mode,
        confirm=confirm,
        run_command=_run_doctor_auto_fix_command,
        revalidate=_revalidate_doctor_check_after_auto_fix,
        max_retries=MAX_AUTOFIX_RETRIES,
        stdin_isatty=sys.stdin.isatty,
    )


def _invoke_doctor_auto_fix(check: Any, check_func: Any, apply_all_mode: bool) -> bool:
    """Call _run_doctor_auto_fix with backward-compatible signature fallback."""
    try:
        return bool(_run_doctor_auto_fix(check, check_func, apply_all_mode=apply_all_mode))
    except TypeError:
        return bool(_run_doctor_auto_fix(check, check_func))


def _doctor_auto_fix_lost_env_keys(
    source_details: dict[str, Any] | None, updated_check: Any
) -> list[str]:
    """Return env keys that were set before auto-fix but missing after re-validation."""
    return launcher_doctor.doctor_auto_fix_lost_env_keys(source_details, updated_check)


def _revalidate_doctor_check_after_auto_fix(
    check_name_or_func: Any,
    check_func_or_details: Any | None = None,
    source_details: dict[str, Any] | None = None,
) -> Any | None:
    """Run a Doctor check once after a successful auto-fix and print the result."""
    global _LAST_DOCTOR_AUTO_FIX_REVALIDATION
    _LAST_DOCTOR_AUTO_FIX_REVALIDATION = launcher_doctor.revalidate_doctor_check_after_auto_fix(
        check_name_or_func,
        check_func_or_details,
        source_details,
        reload_environment=_reload_environment_after_auto_fix,
        handled_exceptions=(
            DoctorCheckError,
            RuntimeError,
            ValueError,
            OSError,
            TypeError,
            AttributeError,
        ),
        logger_obj=logger,
    )
    return _LAST_DOCTOR_AUTO_FIX_REVALIDATION


def _clear_doctor_auto_fix_revalidation_cache() -> None:
    """Reset the latest Doctor auto-fix revalidation result before a new check."""
    global _LAST_DOCTOR_AUTO_FIX_REVALIDATION
    _LAST_DOCTOR_AUTO_FIX_REVALIDATION = None


def _doctor_final_check_after_auto_fix(initial_check: Any, auto_fix_applied: bool) -> Any:
    """Return the cached post-auto-fix Doctor result without revalidating twice."""
    if auto_fix_applied and _LAST_DOCTOR_AUTO_FIX_REVALIDATION is not None:
        return _LAST_DOCTOR_AUTO_FIX_REVALIDATION
    return initial_check


def _run_launcher_doctor_preflight(*, doctor_apply_all_yes: bool = False) -> None:
    from core.doctor.launcher_preflight import (
        LauncherDoctorPreflightHooks,
        LauncherDoctorPreflightStyle,
        run_launcher_doctor_preflight,
    )

    global _DOCTOR_APPLY_ALL_APPROVED
    _DOCTOR_APPLY_ALL_APPROVED = None if not doctor_apply_all_yes else True

    def _confirm_apply_all(prompt: str, default: bool) -> bool:
        approved = confirm(prompt, default)
        global _DOCTOR_APPLY_ALL_APPROVED
        _DOCTOR_APPLY_ALL_APPROVED = approved
        return approved

    run_launcher_doctor_preflight(
        doctor_apply_all_yes=doctor_apply_all_yes,
        hooks=LauncherDoctorPreflightHooks(
            confirm=_confirm_apply_all,
            print_check_summary=_print_doctor_check_summary,
            doctor_auto_fix_commands=_doctor_auto_fix_commands,
            invoke_auto_fix=_invoke_doctor_auto_fix,
            clear_revalidation_cache=_clear_doctor_auto_fix_revalidation_cache,
            final_check_after_auto_fix=_doctor_final_check_after_auto_fix,
        ),
        style=LauncherDoctorPreflightStyle(cyan=CYAN, yellow=YELLOW, reset=RESET),
        max_autofix_retries=MAX_AUTOFIX_RETRIES,
        handled_exceptions=(
            DoctorCheckError,
            RuntimeError,
            ValueError,
            OSError,
            TypeError,
            AttributeError,
        ),
    )


def _run_provider_preflight(provider: str) -> None:
    """Sağlayıcı ön kontrollerini geriye dönük uyumlu imzayla çalıştırır."""
    try:
        preflight(provider, doctor_apply_all_yes=_LAUNCHER_DOCTOR_AUTO_FIX_YES)
    except TypeError:
        preflight(provider)


def preflight(provider: str, *, doctor_apply_all_yes: bool = False) -> None:
    """Sistem gereksinimlerini ve API erişimlerini kontrol eder."""
    print(f"\n{CYAN}🔎 Ön kontroller yapılıyor...{RESET}")
    _maybe_bootstrap_development_env()

    env_path = Path(getattr(cfg, "BASE_DIR", BASE_DIR)) / ".env"
    if env_path.exists():
        print(f"{GREEN}✅ .env dosyası bulundu.{RESET}")
    else:
        message = ".env bulunamadı, sistem ortam değişkenleri kullanılacak."
        logger.warning(message)
        print(f"{YELLOW}⚠ {message}{RESET}")

    database_url = str(getattr(cfg, "DATABASE_URL", "") or "").strip()
    if not database_url:
        logger.warning("DATABASE_URL tanımlı değil; varsayılan SQLite fallback kullanılacak.")
    elif "://" not in database_url:
        logger.warning("DATABASE_URL beklenen şema biçiminde değil: %s", database_url)

    try:
        _run_launcher_doctor_preflight(doctor_apply_all_yes=doctor_apply_all_yes)
    except TypeError:
        _run_launcher_doctor_preflight()

    launcher_preflight.warn_missing_provider_api_key(provider, cfg, logger_obj=logger)

    if provider == "ollama":
        launcher_preflight.check_ollama_reachability(cfg, logger_obj=logger)


def build_command(
    mode: str, provider: str, level: str, log: str, extra_args: dict[str, str]
) -> list[str]:
    """Seçimlere göre çalıştırılacak terminal komutunu inşa eder."""
    return launcher_process.build_command(mode, provider, level, log, extra_args)


def _launcher_child_env() -> dict[str, str]:
    return launcher_process.launcher_child_env()


def _format_cmd(cmd: list[str]) -> str:
    return launcher_process.format_cmd(cmd)


def _stream_pipe(
    pipe: Any, target: Any, prefix: str = "", color: str = "", mirror: bool = True
) -> None:
    """Backward-compatible helper to stream lines from a pipe."""
    launcher_process.stream_pipe(pipe, target, prefix, color, mirror)


def _run_with_streaming(cmd: list[str], child_log_path: str | None) -> int:
    """Child process çıktısını canlı ve sıralı biçimde (stdout+stderr) loglar.

    ``base_dir``/``cwd`` are resolved from this module's current ``cfg``/
    ``__file__`` at call time and threaded through explicitly, so
    monkeypatching ``main.cfg`` (as the test suite does) is observed exactly
    as it was before this logic moved to launcher/process.py.
    """
    return launcher_process.run_with_streaming(
        cmd,
        child_log_path,
        base_dir=getattr(cfg, "BASE_DIR", "."),
        cwd=os.path.dirname(__file__) or ".",
    )


def run_wizard() -> int:
    """Etkileşimli menüyü çalıştırır."""
    print_banner()
    last_selection = _load_launcher_session()
    has_last = last_selection is not None
    default_badge = "Son seçim" if has_last else "Varsayılan"

    defaults = launcher_wizard.wizard_default_keys(last_selection, cfg=cfg)
    mode = ask_choice(
        "1. Hangi arayüzle başlatmak istiyorsunuz?",
        dict(launcher_wizard.MODE_OPTIONS),
        defaults["mode"],
        default_badge=default_badge,
    )
    print("-" * 50)

    provider = ask_choice(
        "2. Hangi AI Sağlayıcısı kullanılsın?",
        dict(launcher_wizard.PROVIDER_OPTIONS),
        defaults["provider"],
        default_badge=default_badge,
    )
    print("-" * 50)

    level = ask_choice(
        "3. Güvenlik/Yetki seviyesi ne olsun?",
        dict(launcher_wizard.LEVEL_OPTIONS),
        defaults["level"],
        default_badge=default_badge,
    )
    print("-" * 50)

    log_level = ask_choice(
        "4. Log seviyesini seçin:",
        dict(launcher_wizard.LOG_OPTIONS),
        defaults["log"],
        default_badge=default_badge,
    )

    extra_args = {}
    args = launcher_wizard.last_extra_args(last_selection)
    if provider == "ollama" and mode == "cli":
        extra_args["model"] = ask_text(
            "\nKullanılacak Ollama modeli",
            _safe_text(
                args.get("model", getattr(cfg, "CODING_MODEL", "qwen2.5-coder:7b")),
                "qwen2.5-coder:7b",
            ),
            default_badge=default_badge if has_last else None,
        )
    elif mode == "web":
        extra_args["host"] = ask_text(
            "\nWeb Sunucu Host IP'si",
            _safe_host(args.get("host", getattr(cfg, "WEB_HOST", "127.0.0.1")), "127.0.0.1"),
            default_badge=default_badge if has_last else None,
        )
        extra_args["port"] = ask_text(
            "Web Sunucu Portu",
            _safe_port(args.get("port", getattr(cfg, "WEB_PORT", 7860)), "7860"),
            default_badge=default_badge if has_last else None,
        )

    selection = _normalize_launch_selection(
        {
            "mode": mode,
            "provider": provider,
            "level": level,
            "log": log_level,
            "extra_args": extra_args,
        }
    )
    _save_launcher_session(selection)

    _run_provider_preflight(provider)

    runtime_ok, runtime_error = validate_runtime_dependencies(mode)
    if not runtime_ok:
        print(f"{RED}⛔ {runtime_error}{RESET}")
        return 2

    cmd = build_command(
        selection["mode"],
        selection["provider"],
        selection["level"],
        selection["log"],
        selection["extra_args"],
    )

    print(f"\n{CYAN}🚀 Başlatılacak komut:{RESET}")
    print(f"   {GREEN}{_format_cmd(cmd)}{RESET}")

    return execute_command(cmd)


def execute_command(
    cmd: list[str], capture_output: bool = False, child_log_path: str | None = None
) -> int:
    """Oluşturulan komutu alt işlem olarak çalıştırır ve gerekirse çıktıyı yakalar."""
    try:
        print(f"\n{GREEN}{BOLD}Sidar Başlatılıyor...{RESET}\n")

        if capture_output or child_log_path:
            return_code = _run_with_streaming(cmd, child_log_path)
            if return_code != 0:
                print(f"\n{RED}Program hata ile sonlandı (Çıkış Kodu: {return_code}){RESET}")
            return return_code

        run_trusted_command(
            cmd, check=True, cwd=os.path.dirname(__file__) or ".", env=_launcher_child_env()
        )
        return 0
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Başlatıcıdan çıkıldı (Kullanıcı müdahalesi).{RESET}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n{RED}Program hata ile sonlandı (Çıkış Kodu: {e.returncode}){RESET}")
        return e.returncode
    except (LauncherError, RuntimeError, OSError, ValueError) as e:
        print(f"\n{RED}Beklenmeyen bir hata oluştu: {e}{RESET}")
        return 1


def main() -> None:
    if hasattr(cfg, "init_telemetry"):
        cfg.init_telemetry(service_name="sidar-launcher")

    parser = launcher_cli_args.build_arg_parser(session_filename=LAUNCHER_SESSION_FILENAME)
    args = parser.parse_args()
    global _LAUNCHER_DOCTOR_AUTO_FIX_YES
    _LAUNCHER_DOCTOR_AUTO_FIX_YES = bool(args.yes)

    use_last_env = launcher_cli_args.use_last_from_env()
    use_last = bool(args.last or args.use_last or use_last_env)
    launch_modes = [bool(args.quick), bool(args.skip_wizard), bool(use_last)]
    if sum(launch_modes) > 1:
        parser.error("--quick, --skip-wizard ve --last/--use-last aynı anda kullanılamaz")

    if hasattr(cfg, "validate_critical_settings") and not cfg.validate_critical_settings():
        print(f"{RED}❌ Kritik yapılandırma doğrulaması başarısız. Çıkılıyor.{RESET}")
        sys.exit(2)

    launcher_cli_args.validate_port_argument(parser, args.port)

    if use_last:
        selection = _load_launcher_session()
        if selection is None:
            print(
                f"{RED}❌ Son sihirbaz oturumu bulunamadı veya okunamadı: "
                f"{_launcher_session_path()}{RESET}"
            )
            sys.exit(2)
        runtime_ok, runtime_error = validate_runtime_dependencies(selection["mode"])
        if not runtime_ok:
            print(f"{RED}⛔ {runtime_error}{RESET}")
            sys.exit(2)
        sys.exit(
            _execute_launch_selection(
                selection, capture_output=args.capture_output, child_log_path=args.child_log
            )
        )

    if args.skip_wizard:
        selection = _apply_cli_overrides(_default_launch_selection(), args)
        runtime_ok, runtime_error = validate_runtime_dependencies(selection["mode"])
        if not runtime_ok:
            print(f"{RED}⛔ {runtime_error}{RESET}")
            sys.exit(2)
        sys.exit(
            _execute_launch_selection(
                selection, capture_output=args.capture_output, child_log_path=args.child_log
            )
        )

    # Eğer --quick argümanı verilmediyse etkileşimli sihirbazı çalıştır
    if not args.quick:
        sys.exit(run_wizard())

    # --quick argümanı verildiyse varsayılanları veya cli argümanlarını kullan
    provider = args.provider or _safe_choice(
        getattr(cfg, "AI_PROVIDER", "ollama"),
        "ollama",
        {"ollama", "gemini", "openai", "anthropic"},
    )
    level = args.level or _safe_choice(
        getattr(cfg, "ACCESS_LEVEL", "full"),
        "full",
        {"restricted", "sandbox", "full"},
    )

    extra_args = {
        "model": args.model
        or _safe_text(getattr(cfg, "CODING_MODEL", "qwen2.5-coder:7b"), "qwen2.5-coder:7b"),
        "host": args.host or _safe_host(getattr(cfg, "WEB_HOST", "127.0.0.1"), "127.0.0.1"),
        "port": args.port or _safe_port(getattr(cfg, "WEB_PORT", 7860), "7860"),
    }

    runtime_ok, runtime_error = validate_runtime_dependencies(args.quick)
    if not runtime_ok:
        print(f"{RED}⛔ {runtime_error}{RESET}")
        sys.exit(2)

    _run_provider_preflight(provider)
    cmd = build_command(args.quick, provider, level, args.log.lower(), extra_args)
    sys.exit(
        execute_command(cmd, capture_output=args.capture_output, child_log_path=args.child_log)
    )


if __name__ == "__main__":
    main()
