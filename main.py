"""Sidar Project - Ultimate Launcher.

=================================
Görsel olarak zenginleştirilmiş etkileşimli menüler ile
argparse tabanlı, ön kontrollü (preflight) akıllı başlatıcı.
Kullanım: python main.py
Hızlı Kullanım: python main.py --quick web --provider ollama --level full
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import json
import logging
import os
import subprocess  # nosec B404
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from launcher import doctor as launcher_doctor
from launcher import process as launcher_process
from launcher import selection as launcher_selection

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
    banner = f"""{CYAN}{BOLD}
 ╔══════════════════════════════════════════════╗
 ║  ███████╗██╗██████╗  █████╗ ██████╗          ║
 ║  ██╔════╝██║██╔══██╗██╔══██╗██╔══██╗         ║
 ║  ███████╗██║██║  ██║███████║██████╔╝         ║
 ║  ╚════██║██║██║  ██║██╔══██║██╔══██╗         ║
 ║  ███████║██║██████╔╝██║  ██║██║  ██║         ║
 ║  ╚══════╝╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝         ║
 ║         SİDAR AKILLI BAŞLATICI               ║
 ╚══════════════════════════════════════════════╝{RESET}
    """
    print(banner)
    print(f"{GREEN}Hoş geldiniz! Lütfen Sidar'ı nasıl başlatmak istediğinizi seçin.{RESET}\n")


def ask_choice(
    prompt: str,
    options: dict[str, tuple[str, str]],
    default_key: str,
    *,
    default_badge: str | None = None,
) -> str:
    """Kullanıcıya seçenekler sunar ve güvenli bir şekilde girdiyi alır."""
    print(f"{YELLOW}{BOLD}{prompt}{RESET}")

    for key, (desc, _value) in options.items():
        if key == default_key:
            badge = default_badge or "Varsayılan"
            is_default = f" {GREEN}({badge}){RESET}"
        else:
            is_default = ""
        print(f"  {CYAN}[{key}]{RESET} {desc}{is_default}")

    while True:
        choice = input(f"\n{BOLD}Seçiminiz [{'/'.join(options.keys())}]: {RESET}").strip()

        if not choice:
            return options[default_key][1]

        if choice in options:
            return options[choice][1]

        print(f"{MAGENTA}Geçersiz seçim. Lütfen tekrar deneyin.{RESET}")


def ask_text(prompt: str, default: str = "", *, default_badge: str | None = None) -> str:
    """Kullanıcıdan metin girdisi alır."""
    if default:
        badge = f" {GREEN}({default_badge}){RESET}" if default_badge else ""
        suffix = f" {CYAN}[{default}]{RESET}{badge}"
    else:
        suffix = ""
    raw = input(f"{YELLOW}{BOLD}{prompt}{RESET}{suffix}: ").strip()
    return raw or default


def confirm(prompt: str, default_yes: bool = True) -> bool:
    """Kullanıcıdan Evet/Hayır onayı alır."""
    hint = "[Y/n]" if default_yes else "[y/N]"
    raw = input(f"\n{YELLOW}{BOLD}{prompt}{RESET} {CYAN}{hint}{RESET}: ").strip().lower()
    if not raw:
        return default_yes
    return raw in {"y", "yes", "e", "evet"}


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


@contextlib.contextmanager
def _launcher_session_lock(session_path: Path, *, exclusive: bool) -> Iterator[None]:
    """Lock launcher session cache access across concurrent terminal processes."""
    lock_path = session_path.with_suffix(session_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        with contextlib.suppress(OSError):
            os.chmod(lock_path, 0o600)
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(lock_file.fileno(), operation)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _save_launcher_session(selection: dict[str, object], path: Path | None = None) -> Path:
    """Sihirbaz seçimlerini atomik şekilde .sidar_session.json cache'ine yazar."""
    session_path = path or _launcher_session_path()
    payload = {
        "version": LAUNCHER_SESSION_VERSION,
        "selection": _normalize_launch_selection(selection),
    }
    session_path.parent.mkdir(parents=True, exist_ok=True)
    with _launcher_session_lock(session_path, exclusive=True):
        tmp_path = session_path.with_suffix(f"{session_path.suffix}.{os.getpid()}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # Session cache may contain provider/model choices and future auth/session metadata;
        # keep it readable only by the current user before and after the atomic replace.
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(session_path)
        os.chmod(session_path, 0o600)
    return session_path


def _load_launcher_session(path: Path | None = None) -> dict[str, Any] | None:
    """Son sihirbaz seçimlerini cache'den güvenli şekilde okur."""
    session_path = path or _launcher_session_path()
    try:
        with _launcher_session_lock(session_path, exclusive=False):
            payload = json.loads(session_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug(
            "Launcher oturum cache'i henüz yok (ilk çalıştırma olabilir): %s", session_path
        )
        return None
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Launcher oturum cache'i okunamadı (%s): %s", session_path, exc)
        return None

    if not isinstance(payload, dict) or payload.get("version") != LAUNCHER_SESSION_VERSION:
        logger.warning("Launcher oturum cache'i desteklenmeyen biçimde: %s", session_path)
        return None

    selection = payload.get("selection")
    if not isinstance(selection, dict):
        logger.warning("Launcher oturum cache'i seçim alanı içermiyor: %s", session_path)
        return None
    return _normalize_launch_selection(selection)


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


def _parse_doctor_env_source_file(path: Path) -> dict[str, str]:
    """Parse simple dotenv assignments for Doctor source reloads without logging values."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not key or any(char.isspace() for char in key):
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _reload_doctor_env_source_definitions(details: dict[str, Any] | None) -> bool:
    """Best-effort reload of Doctor-reported dotenv source files into ``os.environ``."""
    if not isinstance(details, dict):
        return False
    definitions = details.get("env_source_definitions")
    if not isinstance(definitions, dict):
        return False

    applied = False
    for key, sources in definitions.items():
        if not isinstance(key, str) or not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue
            raw_path = str(source.get("path", "") or "").strip()
            if not raw_path:
                continue
            values = _parse_doctor_env_source_file(Path(raw_path).expanduser())
            if key in values:
                os.environ[key] = values[key]
                applied = True
    return applied


_DATABASE_AUTO_FIX_ENV_KEYS = ("DATABASE_URL", "SIDAR_CONTAINER_DATABASE_URL", "POSTGRES_PASSWORD")


def _reload_database_env_from_loaded_dotenv_chain() -> bool:
    """Force Doctor auto-fixed database keys from loaded dotenv files into this process."""
    if config_module is None or not hasattr(config_module, "get_dotenv_load_report"):
        return False

    try:
        events = config_module.get_dotenv_load_report()
    except (RuntimeError, ValueError, OSError, TypeError, AttributeError) as exc:
        logger.debug("Doctor auto-fix dotenv raporu okunamadı: %s", exc)
        return False

    effective_values: dict[str, str] = {}
    applied = False
    for event in events:
        if not event.get("loaded"):
            continue
        raw_path = str(event.get("path", "") or "").strip()
        if not raw_path:
            continue
        values = _parse_doctor_env_source_file(Path(raw_path).expanduser())
        override = bool(event.get("override"))
        for key in _DATABASE_AUTO_FIX_ENV_KEYS:
            if key not in values:
                continue
            if override or key not in effective_values:
                effective_values[key] = values[key]

    for key, value in effective_values.items():
        if os.environ.get(key) != value:
            os.environ[key] = value
            applied = True

    if applied and hasattr(config_module, "Config"):
        config_cls = config_module.Config
        if hasattr(config_module, "get_database_url"):
            config_cls.DATABASE_URL = config_module.get_database_url()
        if hasattr(config_module, "get_container_database_url"):
            config_cls.CONTAINER_DATABASE_URL = config_module.get_container_database_url()
    return applied


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
        completed = subprocess.run(  # nosec B603  # sabit komut listesi, kullanıcı girdisi eklenmez.
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
    try:
        from core.doctor import validate_auto_fix_command

        cmd = validate_auto_fix_command(auto_fix)
    except ValueError as exc:
        logger.warning("Doctor auto_fix komutu reddedildi: %s", exc)
        print(f"{RED}   • Auto-fix komutu güvenlik doğrulamasından geçmedi: {exc}{RESET}")
        return False
    cmd = _launcher_auto_fix_command(cmd)
    print(f"{CYAN}   • Auto-fix çalışıyor: {_format_cmd(cmd)}{RESET}")
    try:
        completed = subprocess.run(  # nosec B603  # Doctor auto_fix komutu list olarak çalıştırılır, shell kullanılmaz.
            cmd, check=False, cwd=_project_base_dir(), env=_launcher_child_env()
        )
    except OSError as exc:
        error = DoctorCheckError("Doctor auto_fix başlatılamadı")
        logger.warning("%s: %s", error, exc)
        print(f"{RED}   • Auto-fix başlatılamadı: {exc}{RESET}")
        return False
    returncode = int(completed.returncode)

    if returncode == 0:
        print(f"{GREEN}   • Auto-fix tamamlandı.{RESET}")
        return True

    print(f"{YELLOW}   • Auto-fix {returncode} koduyla tamamlandı.{RESET}")
    return False


def _run_doctor_auto_fix(
    check: Any, check_func: Any | None = None, *, apply_all_mode: bool = False
) -> bool:
    """Run Doctor auto-fix command(s), optionally revalidating after each successful step."""
    global _LAST_DOCTOR_AUTO_FIX_REVALIDATION
    _LAST_DOCTOR_AUTO_FIX_REVALIDATION = None
    details = getattr(check, "details", {}) or {}
    check_name = str(getattr(check, "name", "doctor") or "doctor")
    status = str(getattr(check, "status", "warn") or "warn")
    if status not in {"warn", "fail"} or not isinstance(details, dict):
        return False

    auto_fix_commands = _doctor_auto_fix_commands(details)
    if not auto_fix_commands or not sys.stdin.isatty():
        return False
    if apply_all_mode:
        selected_auto_fix_commands = auto_fix_commands
    else:
        selected_auto_fix_commands = _select_doctor_auto_fix_commands(check_name, auto_fix_commands)
        prompt_suffix = "adımları" if len(selected_auto_fix_commands) > 1 else "komutu"
        if not confirm(
            f"Doctor/{getattr(check, 'name', 'doctor')} için önerilen auto-fix {prompt_suffix} şimdi çalıştırılsın mı?",
            False,
        ):
            return False

    ran_any = False
    pending_commands = list(selected_auto_fix_commands)
    fallback_commands = _doctor_auto_fix_fallback_commands(details)
    used_fallback = False
    index = 0
    attempts = 0
    while index < len(pending_commands):
        if attempts >= MAX_AUTOFIX_RETRIES:
            print(
                f"{YELLOW}   • Auto-fix tekrar limiti aşıldı "
                f"({MAX_AUTOFIX_RETRIES}); kalan komutlar atlandı.{RESET}"
            )
            return ran_any
        attempts += 1
        auto_fix = pending_commands[index]
        index += 1
        if not _run_doctor_auto_fix_command(auto_fix):
            if not used_fallback and fallback_commands:
                used_fallback = True
                pending_commands.extend(fallback_commands)
                print(f"{YELLOW}   • Auto-fix başarısız; fallback komutları denenecek.{RESET}")
                continue
            return ran_any
        ran_any = True
        if check_func is None:
            continue

        updated_check = _revalidate_doctor_check_after_auto_fix(check_name, check_func, details)
        updated_status = str(getattr(updated_check, "status", "warn") or "warn")
        if updated_status == "pass":
            return True

    return ran_any


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
    if callable(check_name_or_func):
        check_name = "database_env"
        check_func = check_name_or_func
        if isinstance(check_func_or_details, dict):
            source_details = check_func_or_details
    else:
        check_name = str(check_name_or_func or "doctor")
        check_func = check_func_or_details

    try:
        _reload_environment_after_auto_fix(source_details, check_name=check_name)
    except TypeError:
        _reload_environment_after_auto_fix(source_details)
    try:
        updated_check = check_func()
    except (
        DoctorCheckError,
        RuntimeError,
        ValueError,
        OSError,
        TypeError,
        AttributeError,
    ) as exc:  # pragma: no cover - defensive launcher path
        logger.warning("Doctor auto-fix sonrası doğrulama çalıştırılamadı: %s", exc)
        print(f"{YELLOW}   • Auto-fix sonrası doğrulama çalıştırılamadı: {exc}{RESET}")
        _LAST_DOCTOR_AUTO_FIX_REVALIDATION = None
        return None

    updated_status = str(getattr(updated_check, "status", "warn") or "warn")
    if updated_status == "fail":
        doctor_checks: dict[str, str] = {
            "database_env": "check_database_env",
            "database_connectivity": "check_database_connectivity",
            "rag_readiness": "check_rag_readiness",
            "graphrag_entity_memory_ready": "check_graphrag_entity_memory_ready",
        }
        check_attr = doctor_checks.get(check_name)
        if check_attr and check_name != "database_env":
            with contextlib.suppress(Exception):
                from core import doctor as doctor_module

                fresh_check = getattr(doctor_module, check_attr, None)
                if callable(fresh_check):
                    refreshed = fresh_check()
                    refreshed_status = str(getattr(refreshed, "status", "warn") or "warn")
                    if refreshed_status != "fail":
                        updated_check = refreshed
                        updated_status = refreshed_status

    _LAST_DOCTOR_AUTO_FIX_REVALIDATION = updated_check
    print(f"{CYAN}   • Auto-fix sonrası yeniden doğrulama:{RESET}")
    _print_doctor_check_summary(updated_check)
    updated_name = str(getattr(updated_check, "name", "doctor") or "doctor")
    lost_env_keys = _doctor_auto_fix_lost_env_keys(source_details, updated_check)
    if lost_env_keys:
        print(
            f"{RED}   • Auto-fix Doctor/{updated_name} regresyon üretti: "
            f"önceden set olan {', '.join(lost_env_keys)} yeniden doğrulamada boş görünüyor. "
            f"Bu durum düzeltilmiş kabul edilmedi; env reload zincirini manuel inceleyin.{RESET}"
        )
    elif updated_status == "fail":
        print(
            f"{RED}   • Auto-fix Doctor/{updated_name} sorununu gideremedi; "
            f"yukarıdaki önerileri manuel uygulayın.{RESET}"
        )
    elif updated_status == "pass":
        print(f"{GREEN}   • Auto-fix Doctor/{updated_name} kontrolünü düzeltti.{RESET}")
    else:
        print(
            f"{YELLOW}   • Auto-fix Doctor/{updated_name} kontrolünü yeniden çalıştırdı; "
            f"kalan uyarıları inceleyin.{RESET}"
        )
    return updated_check


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

    if provider == "gemini" and not getattr(cfg, "GEMINI_API_KEY", None):
        message = "Uyarı: GEMINI_API_KEY boş görünüyor. API çağrıları başarısız olabilir."
        logger.warning(message)
        print(f"{RED}⚠ {message}{RESET}")

    if provider == "openai" and not getattr(cfg, "OPENAI_API_KEY", None):
        message = "Uyarı: OPENAI_API_KEY boş görünüyor. API çağrıları başarısız olabilir."
        logger.warning(message)
        print(f"{RED}⚠ {message}{RESET}")

    if provider == "anthropic" and not getattr(cfg, "ANTHROPIC_API_KEY", None):
        message = "Uyarı: ANTHROPIC_API_KEY boş görünüyor. API çağrıları başarısız olabilir."
        logger.warning(message)
        print(f"{RED}⚠ {message}{RESET}")

    if provider == "ollama":
        try:
            import httpx

            httpx_http_error: type[BaseException] = getattr(httpx, "HTTPError", RuntimeError)
            base = getattr(cfg, "OLLAMA_URL", "http://localhost:11434").rstrip("/")
            tags_url = base + "/tags" if base.endswith("/api") else base + "/api/tags"
            with httpx.Client(timeout=2) as client:
                code = client.get(tags_url).status_code
            if code == 200:
                print(f"{GREEN}✅ Ollama erişimi başarılı ({base}).{RESET}")
            else:
                logger.warning("Ollama health kontrolü beklenmeyen durum kodu döndürdü: %s", code)
                print(f"{YELLOW}⚠ Ollama yanıt kodu: {code}{RESET}")
        except ImportError:
            logger.warning("'httpx' kütüphanesi kurulu değil, Ollama ağ kontrolü atlandı.")
            print(f"{YELLOW}⚠ 'httpx' kütüphanesi kurulu değil, Ollama ağ kontrolü atlandı.{RESET}")
        except (httpx_http_error, RuntimeError, OSError) as exc:
            logger.warning("Ollama erişimi doğrulanamadı: %s", exc)
            print(
                f"{RED}⚠ Ollama erişimi doğrulanamadı. Servisin (Ollama) çalıştığından emin "
                f"olun.{RESET}"
            )


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

    mode_options = {
        "1": ("Web Arayüzü Sunucusu (FastAPI + UI)", "web"),
        "2": ("CLI Terminal Arayüzü", "cli"),
    }
    mode_default = "1"
    if has_last and last_selection is not None:
        mode_default = "2" if last_selection.get("mode") == "cli" else "1"
    mode = ask_choice(
        "1. Hangi arayüzle başlatmak istiyorsunuz?",
        mode_options,
        mode_default,
        default_badge=default_badge,
    )
    print("-" * 50)

    default_provider_map = {"ollama": "1", "gemini": "2", "openai": "3", "anthropic": "4"}
    provider_default_source = (
        last_selection.get("provider")
        if has_last and last_selection is not None
        else getattr(cfg, "AI_PROVIDER", "ollama")
    )
    default_provider_value = _safe_choice(
        provider_default_source,
        "ollama",
        {"ollama", "gemini", "openai", "anthropic"},
    )
    default_provider = default_provider_map.get(default_provider_value, "1")
    provider_options = {
        "1": ("Ollama (Yerel LLM)", "ollama"),
        "2": ("Gemini (Bulut LLM)", "gemini"),
        "3": ("OpenAI (Bulut LLM)", "openai"),
        "4": ("Anthropic Claude (Bulut LLM)", "anthropic"),
    }
    provider = ask_choice(
        "2. Hangi AI Sağlayıcısı kullanılsın?",
        provider_options,
        default_provider,
        default_badge=default_badge,
    )
    print("-" * 50)

    level_default_source = (
        last_selection.get("level")
        if has_last and last_selection is not None
        else getattr(cfg, "ACCESS_LEVEL", "full")
    )
    default_level_val = _safe_choice(
        level_default_source,
        "full",
        {"restricted", "sandbox", "full"},
    )
    default_level = (
        "1" if default_level_val == "full" else "2" if default_level_val == "sandbox" else "3"
    )
    level_options = {
        "1": ("Full (Sınırsız Sistem Erişimi)", "full"),
        "2": ("Sandbox (Docker İzolasyonlu Sınırlandırılmış Erişim)", "sandbox"),
        "3": ("Restricted (Sadece Okuma ve Sohbet)", "restricted"),
    }
    level = ask_choice(
        "3. Güvenlik/Yetki seviyesi ne olsun?",
        level_options,
        default_level,
        default_badge=default_badge,
    )
    print("-" * 50)

    log_options = {
        "1": ("INFO (Standart)", "info"),
        "2": ("DEBUG (Detaylı Geliştirici Logları)", "debug"),
        "3": ("WARNING (Sadece Uyarılar ve Hatalar)", "warning"),
    }
    log_default_source = (
        last_selection.get("log") if has_last and last_selection is not None else "info"
    )
    default_log = {"info": "1", "debug": "2", "warning": "3", "error": "3"}.get(
        _safe_choice(log_default_source, "info", {"info", "debug", "warning", "error"}),
        "1",
    )
    log_level = ask_choice(
        "4. Log seviyesini seçin:", log_options, default_log, default_badge=default_badge
    )

    extra_args = {}
    last_extra_args = (
        last_selection.get("extra_args")
        if has_last
        and last_selection is not None
        and isinstance(last_selection.get("extra_args"), dict)
        else {}
    )
    args = last_extra_args or {}
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

        subprocess.run(  # nosec B603  # komut listesi launcher tarafından güvenli şekilde üretilir.
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

    parser = argparse.ArgumentParser(description="Sidar Akıllı Başlatıcı")
    parser.add_argument(
        "--quick", choices=["cli", "web"], help="Sihirbazı atla ve belirtilen modda hızlı başlat"
    )
    parser.add_argument(
        "--skip-wizard",
        action="store_true",
        help="Sihirbaz sorularını atla ve config/default seçimlerle başlat",
    )
    parser.add_argument(
        "--last",
        action="store_true",
        help=f"Son {LAUNCHER_SESSION_FILENAME} sihirbaz seçimleriyle başlat",
    )
    parser.add_argument(
        "--use-last",
        action="store_true",
        help=f"--last ile aynı: son {LAUNCHER_SESSION_FILENAME} seçimlerini kullan",
    )
    parser.add_argument(
        "--provider",
        choices=["ollama", "gemini", "openai", "anthropic"],
        help="Hızlı başlat için AI sağlayıcı",
    )
    parser.add_argument(
        "--level",
        choices=["restricted", "sandbox", "full"],
        help="Hızlı başlat için erişim seviyesi",
    )
    parser.add_argument("--model", help="Hızlı CLI başlat için Ollama modeli")
    parser.add_argument("--host", help="Hızlı web başlat için host adresi")
    parser.add_argument("--port", help="Hızlı web başlat için port numarası")
    parser.add_argument("--log", default="info", help="Log seviyesi (info, debug, warning)")
    parser.add_argument(
        "--capture-output",
        action="store_true",
        help="Alt süreç stdout/stderr çıktısını launcherdan yakala ve yazdır",
    )
    parser.add_argument(
        "--child-log",
        help="Alt süreç stdout/stderr çıktısını dosyaya kaydet (ör. logs/child.log)",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Doctor preflight için tüm auto-fix önerilerini tek onayla uygula",
    )
    args = parser.parse_args()
    global _LAUNCHER_DOCTOR_AUTO_FIX_YES
    _LAUNCHER_DOCTOR_AUTO_FIX_YES = bool(args.yes)

    use_last_env = os.getenv("SIDAR_LAUNCHER_USE_LAST", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    use_last = bool(args.last or args.use_last or use_last_env)
    launch_modes = [bool(args.quick), bool(args.skip_wizard), bool(use_last)]
    if sum(launch_modes) > 1:
        parser.error("--quick, --skip-wizard ve --last/--use-last aynı anda kullanılamaz")

    if hasattr(cfg, "validate_critical_settings") and not cfg.validate_critical_settings():
        print(f"{RED}❌ Kritik yapılandırma doğrulaması başarısız. Çıkılıyor.{RESET}")
        sys.exit(2)

    # --port değeri verilmişse 1-65535 aralığında olduğunu doğrula
    if args.port is not None:
        try:
            _port_val = int(args.port)
            if not (1 <= _port_val <= 65535):
                raise ValueError
        except ValueError:
            parser.error(
                f"--port değeri 1-65535 arasında tam sayı olmalıdır (verilen: {args.port!r})"
            )

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
