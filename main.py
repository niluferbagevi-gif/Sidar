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
import logging
import os
import shlex
import subprocess
import sys
import threading
from pathlib import Path

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
    WEB_HOST = "0.0.0.0"
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

try:
    from config import Config

    cfg = Config()
    if hasattr(cfg, "initialize_directories"):
        cfg.initialize_directories()
except (ImportError, AttributeError):
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


def preflight(provider: str) -> None:
    """Sistem gereksinimlerini ve API erişimlerini kontrol eder."""
    print(f"\n{CYAN}🔎 Ön kontroller yapılıyor...{RESET}")


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


def _format_cmd(cmd: list[str]) -> str:
    """Komutu terminalde güvenli/görsel şekilde yazdırmak için quote eder."""
    return " ".join(shlex.quote(part) for part in cmd)


def _stream_pipe(pipe, file_obj, prefix: str, color: str, mirror: bool) -> None:
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
    process = subprocess.Popen(
        cmd,
        cwd=os.path.dirname(__file__) or ".",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None
    assert process.stderr is not None

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
            _safe_text(getattr(cfg, "WEB_HOST", "0.0.0.0"), "0.0.0.0"),
        )
        extra_args["port"] = ask_text(
            "Web Sunucu Portu",
            _safe_port(getattr(cfg, "WEB_PORT", 7860), "7860"),
        )

    preflight(provider)

    runtime_ok, runtime_error = validate_runtime_dependencies(mode)
    if not runtime_ok:
        print(f"{RED}⛔ {runtime_error}{RESET}")
        return 2

    cmd = build_command(mode, provider, level, log_level, extra_args)

    print(f"\n{CYAN}🚀 Başlatılacak komut:{RESET}")
    print(f"   {GREEN}{_format_cmd(cmd)}{RESET}")

    if not confirm("Sidar'ı başlatmak istiyor musunuz?", True):
        print(f"{YELLOW}İşlem kullanıcı tarafından iptal edildi.{RESET}")
        return 0

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

        subprocess.run(cmd, check=True, cwd=os.path.dirname(__file__) or ".")
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
        "host": args.host or _safe_text(getattr(cfg, "WEB_HOST", "0.0.0.0"), "0.0.0.0"),
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
