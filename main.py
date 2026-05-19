"""
Sidar Project - Ultimate Launcher
=================================
Görsel olarak zenginleştirilmiş etkileşimli menüler ile
argparse tabanlı, ön kontrollü (preflight) akıllı başlatıcı.
Kullanım: python main.py
Hızlı Kullanım: python main.py --quick web --provider ollama --level full
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
import subprocess  # nosec B404
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

LAUNCHER_SESSION_FILENAME = ".sidar_session.json"
LAUNCHER_SESSION_VERSION = 1


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

try:
    import config as config_module

    Config = config_module.Config
    cfg: Any = Config()
    if hasattr(cfg, "initialize_directories"):
        cfg.initialize_directories()
except (ImportError, AttributeError):
    config_module = None
    CONFIG_IMPORT_OK = False
    print(f"{YELLOW}⚠ config.py bulunamadı veya geçersiz, varsayılan ayarlar kullanılıyor.{RESET}")
    cfg = DummyConfig()


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


def ask_choice(prompt: str, options: dict[str, tuple[str, str]], default_key: str) -> str:
    """Kullanıcıya seçenekler sunar ve güvenli bir şekilde girdiyi alır."""
    print(f"{YELLOW}{BOLD}{prompt}{RESET}")

    for key, (desc, _value) in options.items():
        is_default = f" {GREEN}(Varsayılan){RESET}" if key == default_key else ""
        print(f"  {CYAN}[{key}]{RESET} {desc}{is_default}")

    while True:
        choice = input(f"\n{BOLD}Seçiminiz [{'/'.join(options.keys())}]: {RESET}").strip()

        if not choice:
            return options[default_key][1]

        if choice in options:
            return options[choice][1]

        print(f"{MAGENTA}Geçersiz seçim. Lütfen tekrar deneyin.{RESET}")


def ask_text(prompt: str, default: str = "") -> str:
    """Kullanıcıdan metin girdisi alır."""
    suffix = f" {CYAN}[{default}]{RESET}" if default else ""
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
    mode = _safe_choice(selection.get("mode"), "web", {"web", "cli"})
    provider = _safe_choice(
        selection.get("provider"),
        _safe_choice(
            getattr(cfg, "AI_PROVIDER", "ollama"),
            "ollama",
            {"ollama", "gemini", "openai", "anthropic"},
        ),
        {"ollama", "gemini", "openai", "anthropic"},
    )
    level = _safe_choice(
        selection.get("level"),
        _safe_choice(
            getattr(cfg, "ACCESS_LEVEL", "full"), "full", {"restricted", "sandbox", "full"}
        ),
        {"restricted", "sandbox", "full"},
    )
    log_level = _safe_choice(selection.get("log"), "info", {"info", "debug", "warning", "error"})

    raw_extra_args = selection.get("extra_args")
    extra_args = raw_extra_args if isinstance(raw_extra_args, dict) else {}
    normalized_extra_args = {
        "model": _safe_text(
            extra_args.get("model"),
            _safe_text(getattr(cfg, "CODING_MODEL", "qwen2.5-coder:7b"), "qwen2.5-coder:7b"),
        ),
        "host": _safe_host(extra_args.get("host", getattr(cfg, "WEB_HOST", "127.0.0.1"))),
        "port": _safe_port(extra_args.get("port", getattr(cfg, "WEB_PORT", 7860)), "7860"),
    }
    return {
        "mode": mode,
        "provider": provider,
        "level": level,
        "log": log_level,
        "extra_args": normalized_extra_args,
    }


def _default_launch_selection() -> dict[str, Any]:
    """--skip-wizard için config/default değerlerinden çalıştırılabilir seçim üretir."""
    return _normalize_launch_selection(
        {
            "mode": "web",
            "provider": getattr(cfg, "AI_PROVIDER", "ollama"),
            "level": getattr(cfg, "ACCESS_LEVEL", "full"),
            "log": "info",
            "extra_args": {
                "model": getattr(cfg, "CODING_MODEL", "qwen2.5-coder:7b"),
                "host": getattr(cfg, "WEB_HOST", "127.0.0.1"),
                "port": getattr(cfg, "WEB_PORT", 7860),
            },
        }
    )


def _save_launcher_session(selection: dict[str, object], path: Path | None = None) -> Path:
    """Sihirbaz seçimlerini atomik şekilde .sidar_session.json cache'ine yazar."""
    session_path = path or _launcher_session_path()
    payload = {
        "version": LAUNCHER_SESSION_VERSION,
        "selection": _normalize_launch_selection(selection),
    }
    session_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = session_path.with_suffix(session_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(session_path)
    return session_path


def _load_launcher_session(path: Path | None = None) -> dict[str, Any] | None:
    """Son sihirbaz seçimlerini cache'den güvenli şekilde okur."""
    session_path = path or _launcher_session_path()
    try:
        payload = json.loads(session_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
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
    except Exception as exc:
        logger.warning("%s sonrası environment reload başarısız: %s", reason, exc)
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
    except Exception as exc:
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


def _reload_environment_after_auto_fix(details: dict[str, Any] | None = None) -> bool:
    """Reload dotenv values in this process after a Doctor auto-fix subprocess."""
    profile = os.getenv("SIDAR_ENV", "").strip().lower() or None
    if profile is None and _development_env_path().exists():
        profile = "development"
    config_reloaded = _reload_config_environment(profile=profile, reason="Doctor auto-fix")
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
        f"{YELLOW}⚠ .env.development bulunamadı. Yerel profil sihirbazdan önce oluşturulabilir.{RESET}"
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
    merged = dict(selection)
    extra_args = dict(selection.get("extra_args", {}))
    if args.provider:
        merged["provider"] = args.provider
    if args.level:
        merged["level"] = args.level
    if args.log:
        merged["log"] = str(args.log).lower()
    if args.model:
        extra_args["model"] = args.model
    if args.host:
        extra_args["host"] = args.host
    if args.port:
        extra_args["port"] = args.port
    merged["extra_args"] = extra_args
    return _normalize_launch_selection(merged)


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
    if not isinstance(value, str):
        return default

    normalized = value.strip().lower()
    if not normalized or normalized not in allowed:
        return default
    return normalized


def _safe_text(value: object, default: str) -> str:
    """Config/env kökenli metinleri normalize eder; boş/geçersizde default döner."""
    if value is None:
        return default

    normalized = str(value).strip()
    return normalized or default


def _safe_port(value: object, default: str = "7860") -> str:
    """Config/env kökenli port değerlerini güvenli biçimde doğrular."""
    normalized = _safe_text(value, default)
    try:
        port = int(normalized)
    except (TypeError, ValueError):
        return default
    return str(port) if 1 <= port <= 65535 else default


def _safe_host(value: object, default: str = "127.0.0.1") -> str:
    """Config/env kökenli host değerlerini `ipaddress` tabanlı doğrulayıcıdan geçirir.

    Geçersiz veya üretim profilinde reddedilen değerlerde güvenli yerel
    fallback (`127.0.0.1`) döner; böylece `# nosec B104` ile bypass yapmak
    yerine politika tek bir noktada uygulanır.
    """
    from core.utils.network_validation import validate_bind_host

    candidate = _safe_text(value, default)
    try:
        return validate_bind_host(candidate)
    except ValueError:
        try:
            return validate_bind_host(default)
        except ValueError:
            return "127.0.0.1"


def _doctor_status_icon(status: str) -> str:
    return {"pass": "✅", "warn": "⚠", "fail": "❌"}.get(status, "ℹ️")  # nosec B105


def _print_doctor_check_summary(check: Any) -> None:
    status = str(getattr(check, "status", "warn") or "warn")
    name = str(getattr(check, "name", "doctor") or "doctor")
    message = str(getattr(check, "message", "") or "")
    details = getattr(check, "details", {}) or {}
    color = GREEN if status == "pass" else (RED if status == "fail" else YELLOW)
    print(f"{color}{_doctor_status_icon(status)} Doctor/{name}: {message}{RESET}")

    hints = details.get("root_cause_hints") if isinstance(details, dict) else None
    if isinstance(hints, list) and status in {"warn", "fail"}:
        for hint in hints[:3]:
            print(f"{YELLOW}   • Olası neden: {hint}{RESET}")

    steps = details.get("remediation_steps") if isinstance(details, dict) else None
    if isinstance(steps, list) and status in {"warn", "fail"}:
        for step in steps[:2]:
            print(f"{YELLOW}   • Çözüm: {step}{RESET}")

    commands = details.get("recommended_commands") if isinstance(details, dict) else None
    if isinstance(commands, list) and status in {"warn", "fail"}:
        for command in commands[:3]:
            print(f"{CYAN}   • Komut: {command}{RESET}")


def _doctor_auto_fix_commands(details: dict[str, Any]) -> list[str]:
    """Return ordered Doctor auto-fix commands from legacy or multi-step metadata."""
    steps = details.get("auto_fix_steps")
    if isinstance(steps, list) and status in {"warn", "fail"}:
        commands = [step.strip() for step in steps if isinstance(step, str) and step.strip()]
        if commands:
            return commands

    auto_fix = details.get("auto_fix")
    if isinstance(auto_fix, list):
        return [step.strip() for step in auto_fix if isinstance(step, str) and step.strip()]
    if isinstance(auto_fix, str) and auto_fix.strip():
        return [auto_fix.strip()]
    return []


def _launcher_auto_fix_command(cmd: list[str]) -> list[str]:
    """Adjust known verbose Doctor auto-fix commands for interactive launcher UX."""
    if "--summary-only" in cmd or "--quiet" in cmd:
        return cmd
    for index in range(len(cmd) - 2):
        if cmd[index : index + 3] == ["python", "-m", "scripts.seed_rag"]:
            return [*cmd, "--summary-only"]
    return cmd


def _run_doctor_auto_fix_command(auto_fix: str) -> bool:
    """Run one Doctor auto-fix command without invoking a shell."""
    cmd = shlex.split(auto_fix)
    if not cmd:
        return False
    cmd = _launcher_auto_fix_command(cmd)

    print(f"{CYAN}   • Auto-fix çalışıyor: {_format_cmd(cmd)}{RESET}")
    try:
        completed = subprocess.run(  # nosec B603  # Doctor auto_fix komutu list olarak çalıştırılır, shell kullanılmaz.
            cmd, check=False, cwd=_project_base_dir(), env=_launcher_child_env()
        )
    except OSError as exc:
        logger.warning("Doctor auto_fix başlatılamadı: %s", exc)
        print(f"{RED}   • Auto-fix başlatılamadı: {exc}{RESET}")
        return False
    returncode = int(completed.returncode)

    if returncode == 0:
        print(f"{GREEN}   • Auto-fix tamamlandı.{RESET}")
        return True

    print(f"{YELLOW}   • Auto-fix {returncode} koduyla tamamlandı.{RESET}")
    return False


def _run_doctor_auto_fix(check: Any, check_func: Any | None = None) -> bool:
    """Run Doctor auto-fix command(s), optionally revalidating after each successful step."""
    global _LAST_DOCTOR_AUTO_FIX_REVALIDATION
    _LAST_DOCTOR_AUTO_FIX_REVALIDATION = None
    details = getattr(check, "details", {}) or {}
    status = str(getattr(check, "status", "warn") or "warn")
    if status not in {"warn", "fail"} or not isinstance(details, dict):
        return False

    auto_fix_commands = _doctor_auto_fix_commands(details)
    if not auto_fix_commands or not sys.stdin.isatty():
        return False

    prompt_suffix = "adımları" if len(auto_fix_commands) > 1 else "komutu"
    if not confirm(
        f"Doctor/{getattr(check, 'name', 'doctor')} için önerilen auto-fix {prompt_suffix} şimdi çalıştırılsın mı?",
        False,
    ):
        return False

    ran_any = False
    for auto_fix in auto_fix_commands:
        if not _run_doctor_auto_fix_command(auto_fix):
            return ran_any
        ran_any = True
        if check_func is None:
            continue

        updated_check = _revalidate_doctor_check_after_auto_fix(check_func, details)
        updated_status = str(getattr(updated_check, "status", "warn") or "warn")
        if updated_status == "pass":
            return True

    return ran_any


def _doctor_auto_fix_lost_env_keys(
    source_details: dict[str, Any] | None, updated_check: Any
) -> list[str]:
    """Return env keys that were set before auto-fix but missing after re-validation."""
    if not isinstance(source_details, dict):
        return []
    updated_details = getattr(updated_check, "details", {}) or {}
    if not isinstance(updated_details, dict):
        return []

    set_flags = {
        "database_url_set": "DATABASE_URL",
        "container_database_url_set": "SIDAR_CONTAINER_DATABASE_URL",
        "postgres_user_set": "POSTGRES_USER",
        "postgres_password_set": "POSTGRES_PASSWORD",
        "postgres_db_set": "POSTGRES_DB",
    }
    lost_keys: list[str] = []
    for detail_key, env_key in set_flags.items():
        if source_details.get(detail_key) is True and updated_details.get(detail_key) is False:
            lost_keys.append(env_key)
    return lost_keys


def _revalidate_doctor_check_after_auto_fix(
    check_func: Any, source_details: dict[str, Any] | None = None
) -> Any | None:
    """Run a Doctor check once after a successful auto-fix and print the result."""
    global _LAST_DOCTOR_AUTO_FIX_REVALIDATION
    _reload_environment_after_auto_fix(source_details)
    try:
        updated_check = check_func()
    except Exception as exc:  # pragma: no cover - defensive launcher path
        logger.warning("Doctor auto-fix sonrası doğrulama çalıştırılamadı: %s", exc)
        print(f"{YELLOW}   • Auto-fix sonrası doğrulama çalıştırılamadı: {exc}{RESET}")
        _LAST_DOCTOR_AUTO_FIX_REVALIDATION = None
        return None

    _LAST_DOCTOR_AUTO_FIX_REVALIDATION = updated_check
    print(f"{CYAN}   • Auto-fix sonrası yeniden doğrulama:{RESET}")
    _print_doctor_check_summary(updated_check)
    updated_status = str(getattr(updated_check, "status", "warn") or "warn")
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


def _run_launcher_doctor_preflight() -> None:
    try:
        from core.doctor import (
            check_database_connectivity,
            check_database_env,
            check_gpu_memory_config,
            check_rag_readiness,
        )
    except Exception as exc:  # pragma: no cover - defensive launcher path
        logger.debug("Doctor ön kontrol modülü yüklenemedi: %s", exc)
        return

    print(f"\n{CYAN}🩺 Doctor kısa kontrolleri...{RESET}")
    skip_database_dependents = False
    skip_summary_printed = False
    doctor_checks = (
        ("database_env", check_database_env),
        ("database_connectivity", check_database_connectivity),
        ("rag_readiness", check_rag_readiness),
        ("gpu_memory_config", check_gpu_memory_config),
    )
    for check_name, check_func in doctor_checks:
        if skip_database_dependents and check_name in {"database_connectivity", "rag_readiness"}:
            if not skip_summary_printed:
                print(
                    f"{YELLOW}   • Doctor/database_env hâlâ fail; "
                    "database_connectivity ve rag_readiness kontrolleri atlandı. "
                    f"Önce yukarıdaki database_env düzeltmesini tamamlayın.{RESET}"
                )
                skip_summary_printed = True
            continue

        try:
            check = check_func()
            _print_doctor_check_summary(check)
            _run_doctor_auto_fix(check, check_func)
            if check_name == "database_env":
                final_check = _LAST_DOCTOR_AUTO_FIX_REVALIDATION or check
                final_status = str(getattr(final_check, "status", "warn") or "warn")
                skip_database_dependents = final_status == "fail"
        except Exception as exc:  # pragma: no cover - defensive launcher path
            logger.warning("Doctor ön kontrolü çalıştırılamadı: %s", exc)
            print(f"{YELLOW}⚠ Doctor ön kontrolü çalıştırılamadı: {exc}{RESET}")


def preflight(provider: str) -> None:
    """Sistem gereksinimlerini ve API erişimlerini kontrol eder."""
    print(f"\n{CYAN}🔎 Ön kontroller yapılıyor...{RESET}")
    _maybe_bootstrap_development_env()

    env_path = Path(cfg.BASE_DIR) / ".env"
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
        except Exception as exc:
            logger.warning("Ollama erişimi doğrulanamadı: %s", exc)
            print(
                f"{RED}⚠ Ollama erişimi doğrulanamadı. Servisin (Ollama) çalıştığından emin olun.{RESET}"
            )


def build_command(
    mode: str, provider: str, level: str, log: str, extra_args: dict[str, str]
) -> list[str]:
    """Seçimlere göre çalıştırılacak terminal komutunu inşa eder."""
    valid_modes = {"web", "cli"}
    valid_providers = {"ollama", "gemini", "openai", "anthropic"}
    valid_levels = {"restricted", "sandbox", "full"}
    valid_logs = {"info", "debug", "warning", "error"}

    if mode not in valid_modes:
        raise ValueError(f"Geçersiz mode: {mode}")
    if provider not in valid_providers:
        raise ValueError(f"Geçersiz provider: {provider}")
    if level not in valid_levels:
        raise ValueError(f"Geçersiz level: {level}")
    if log not in valid_logs:
        raise ValueError(f"Geçersiz log seviyesi: {log}")

    target_script = "web_server.py" if mode == "web" else "cli.py"
    cmd = [sys.executable, target_script, "--provider", provider, "--level", level, "--log", log]

    if mode == "cli" and provider == "ollama" and extra_args.get("model"):
        cmd.extend(["--model", extra_args["model"]])
    elif mode == "web":
        cmd.extend(
            [
                "--host",
                extra_args.get("host", "127.0.0.1"),
                "--port",
                extra_args.get("port", "8000"),
            ]
        )

    return cmd


def _launcher_child_env() -> dict[str, str]:
    """Environment for child processes launched by main.py without duplicate config banners."""
    child_env = os.environ.copy()
    child_env["SIDAR_CONFIG_QUIET"] = "true"
    child_env["SIDAR_LAUNCHED_BY_MAIN"] = "true"
    return child_env


def _format_cmd(cmd: list[str]) -> str:
    """Komutu terminalde güvenli/görsel şekilde yazdırmak için quote eder."""
    return " ".join(shlex.quote(part) for part in cmd)


def _stream_pipe(
    pipe: TextIO, file_obj: TextIO | None, prefix: str, color: str, mirror: bool
) -> None:
    """Child process pipe akışını satır satır okuyup belleği şişirmeden dosyaya yazar."""
    for line in iter(pipe.readline, ""):
        if file_obj:
            file_obj.write(f"[{prefix.strip('[]')}] {line}")
            file_obj.flush()
        if mirror:
            print(f"{color}{prefix}{RESET} {line}", end="")
    pipe.close()


def _run_with_streaming(cmd: list[str], child_log_path: str | None) -> int:
    """Child process çıktısını canlı izleyerek (stdout/stderr) bellek dostu şekilde loglar."""
    process = subprocess.Popen(  # nosec B603  # komut listesi launcher tarafından güvenli şekilde üretilir.
        cmd,
        cwd=os.path.dirname(__file__) or ".",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=_launcher_child_env(),
    )

    if process.stdout is None or process.stderr is None:
        raise RuntimeError("Child process stdout/stderr pipe oluşturulamadı.")

    f = None
    log_path = None
    if child_log_path:
        candidate = Path(child_log_path)
        base_dir = Path(getattr(cfg, "BASE_DIR", ".")).resolve()
        log_path = candidate if candidate.is_absolute() else (base_dir / candidate)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        f = open(log_path, "w", encoding="utf-8")
        f.write(f"$ {_format_cmd(cmd)}\n\n")
        f.flush()

    t_out = threading.Thread(
        target=_stream_pipe,
        args=(process.stdout, f, "[stdout]", CYAN, True),
        daemon=True,
    )
    t_err = threading.Thread(
        target=_stream_pipe,
        args=(process.stderr, f, "[stderr]", YELLOW, True),
        daemon=True,
    )
    t_out.start()
    t_err.start()

    return_code = 1
    try:
        return_code = process.wait()
    finally:
        poll = getattr(process, "poll", None)
        terminate = getattr(process, "terminate", None)
        kill = getattr(process, "kill", None)
        still_running = (callable(poll) and poll() is None) or (poll is None)
        if still_running and callable(terminate):
            terminate()
            try:
                process.wait(timeout=3)
            except Exception:
                if callable(kill):  # pragma: no cover
                    kill()  # pragma: no cover
        t_out.join()
        t_err.join()

        if f:
            f.write(f"\n[exit_code]\n{return_code}\n")
            f.close()
            print(f"{GREEN}📝 Child process çıktısı kaydedildi: {log_path}{RESET}")

    return return_code


def run_wizard() -> int:
    """Etkileşimli menüyü çalıştırır."""
    print_banner()

    mode_options = {
        "1": ("Web Arayüzü Sunucusu (FastAPI + UI)", "web"),
        "2": ("CLI Terminal Arayüzü", "cli"),
    }
    mode = ask_choice("1. Hangi arayüzle başlatmak istiyorsunuz?", mode_options, "1")
    print("-" * 50)

    default_provider_map = {"ollama": "1", "gemini": "2", "openai": "3", "anthropic": "4"}
    default_provider_value = _safe_choice(
        getattr(cfg, "AI_PROVIDER", "ollama"),
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
        "2. Hangi AI Sağlayıcısı kullanılsın?", provider_options, default_provider
    )
    print("-" * 50)

    default_level_val = _safe_choice(
        getattr(cfg, "ACCESS_LEVEL", "full"),
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
    level = ask_choice("3. Güvenlik/Yetki seviyesi ne olsun?", level_options, default_level)
    print("-" * 50)

    log_options = {
        "1": ("INFO (Standart)", "info"),
        "2": ("DEBUG (Detaylı Geliştirici Logları)", "debug"),
        "3": ("WARNING (Sadece Uyarılar ve Hatalar)", "warning"),
    }
    log_level = ask_choice("4. Log seviyesini seçin:", log_options, "1")

    extra_args = {}
    if provider == "ollama" and mode == "cli":
        extra_args["model"] = ask_text(
            "\nKullanılacak Ollama modeli",
            _safe_text(getattr(cfg, "CODING_MODEL", "qwen2.5-coder:7b"), "qwen2.5-coder:7b"),
        )
    elif mode == "web":
        extra_args["host"] = ask_text(
            "\nWeb Sunucu Host IP'si",
            _safe_host(getattr(cfg, "WEB_HOST", "127.0.0.1"), "127.0.0.1"),
        )
        extra_args["port"] = ask_text(
            "Web Sunucu Portu",
            _safe_port(getattr(cfg, "WEB_PORT", 7860), "7860"),
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

    preflight(provider)

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
    except Exception as e:
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
    args = parser.parse_args()

    launch_modes = [bool(args.quick), bool(args.skip_wizard), bool(args.last)]
    if sum(launch_modes) > 1:
        parser.error("--quick, --skip-wizard ve --last aynı anda kullanılamaz")

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

    if args.last:
        selection = _load_launcher_session()
        if selection is None:
            print(
                f"{RED}❌ Son sihirbaz oturumu bulunamadı veya okunamadı: {_launcher_session_path()}{RESET}"
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

    cmd = build_command(args.quick, provider, level, args.log.lower(), extra_args)
    sys.exit(
        execute_command(cmd, capture_output=args.capture_output, child_log_path=args.child_log)
    )


if __name__ == "__main__":
    main()
