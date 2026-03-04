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
import os
import shlex
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Dict, Tuple

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
    WEB_HOST = "127.0.0.1"
    WEB_PORT = 8000
    CODING_MODEL = "llama3"
    GEMINI_API_KEY = ""
    OLLAMA_URL = "http://localhost:11434"
    BASE_DIR = "."

try:
    from config import Config
    cfg = Config()
except ImportError:
    print(f"{YELLOW}⚠ config.py bulunamadı, varsayılan ayarlar kullanılıyor.{RESET}")
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


def ask_choice(prompt: str, options: Dict[str, Tuple[str, str]], default_key: str) -> str:
    """Kullanıcıya seçenekler sunar ve güvenli bir şekilde girdiyi alır."""
    print(f"{YELLOW}{BOLD}{prompt}{RESET}")
    
    for key, (desc, value) in options.items():
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


def preflight(provider: str) -> None:
    """Sistem gereksinimlerini ve API erişimlerini kontrol eder."""
    print(f"\n{CYAN}🔎 Ön kontroller yapılıyor...{RESET}")

    if sys.version_info < (3, 10):
        print(f"{YELLOW}⚠ Python 3.10+ önerilir. (Mevcut: {sys.version.split()[0]}){RESET}")

    env_path = Path(cfg.BASE_DIR) / ".env"
    if env_path.exists():
        print(f"{GREEN}✅ .env dosyası bulundu.{RESET}")
    else:
        print(f"{YELLOW}⚠ .env bulunamadı, sistem ortam değişkenleri kullanılacak.{RESET}")

    if provider == "gemini" and not getattr(cfg, "GEMINI_API_KEY", None):
        print(f"{RED}⚠ Uyarı: GEMINI_API_KEY boş görünüyor. API çağrıları başarısız olabilir.{RESET}")

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
                print(f"{YELLOW}⚠ Ollama yanıt kodu: {code}{RESET}")
        except ImportError:
            print(f"{YELLOW}⚠ 'httpx' kütüphanesi kurulu değil, Ollama ağ kontrolü atlandı.{RESET}")
        except Exception:
            print(f"{RED}⚠ Ollama erişimi doğrulanamadı. Servisin (Ollama) çalıştığından emin olun.{RESET}")


def build_command(mode: str, provider: str, level: str, log: str, extra_args: Dict[str, str]) -> List[str]:
    """Seçimlere göre çalıştırılacak terminal komutunu inşa eder."""
    target_script = "web_server.py" if mode == "web" else "cli.py"
    cmd = [sys.executable, target_script, "--provider", provider, "--level", level, "--log", log]
    
    if mode == "cli" and provider == "ollama" and extra_args.get("model"):
        cmd.extend(["--model", extra_args["model"]])
    elif mode == "web":
        cmd.extend(["--host", extra_args.get("host", "127.0.0.1"), "--port", extra_args.get("port", "8000")])
        
    return cmd


def _format_cmd(cmd: List[str]) -> str:
    """Komutu terminalde güvenli/görsel şekilde yazdırmak için quote eder."""
    return " ".join(shlex.quote(part) for part in cmd)


def _stream_pipe(pipe, collector: List[str], prefix: str, color: str, mirror: bool) -> None:
    """Child process pipe akışını satır satır okuyup toplayan yardımcı thread."""
    for line in iter(pipe.readline, ""):
        collector.append(line)
        if mirror:
            print(f"{color}{prefix}{RESET} {line}", end="")
    pipe.close()


def _run_with_streaming(cmd: List[str], child_log_path: str | None) -> int:
    """Child process çıktısını canlı izleyerek (stdout/stderr) isteğe bağlı log dosyasına yazar."""
    process = subprocess.Popen(
        cmd,
        cwd=os.path.dirname(__file__) or ".",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stdout_lines: List[str] = []
    stderr_lines: List[str] = []

    assert process.stdout is not None
    assert process.stderr is not None

    t_out = threading.Thread(
        target=_stream_pipe,
        args=(process.stdout, stdout_lines, "[Child stdout]", CYAN, True),
        daemon=True,
    )
    t_err = threading.Thread(
        target=_stream_pipe,
        args=(process.stderr, stderr_lines, "[Child stderr]", YELLOW, True),
        daemon=True,
    )
    t_out.start()
    t_err.start()

    return_code = process.wait()
    t_out.join()
    t_err.join()

    if child_log_path:
        log_path = Path(child_log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"$ {_format_cmd(cmd)}\n\n"
            f"[stdout]\n{''.join(stdout_lines)}\n"
            f"[stderr]\n{''.join(stderr_lines)}\n"
            f"[exit_code]\n{return_code}\n",
            encoding="utf-8",
        )
        print(f"{GREEN}📝 Child process çıktısı kaydedildi: {log_path}{RESET}")

    return return_code


def run_wizard() -> int:
    """Etkileşimli menüyü çalıştırır."""
    print_banner()

    mode_options = {
        "1": ("Web Arayüzü Sunucusu (FastAPI + UI)", "web"),
        "2": ("CLI Terminal Arayüzü", "cli")
    }
    mode = ask_choice("1. Hangi arayüzle başlatmak istiyorsunuz?", mode_options, "1")
    print("-" * 50)

    default_provider = "1" if getattr(cfg, "AI_PROVIDER", "ollama").lower() == "ollama" else "2"
    provider_options = {
        "1": ("Ollama (Yerel LLM)", "ollama"),
        "2": ("Gemini (Bulut LLM)", "gemini")
    }
    provider = ask_choice("2. Hangi AI Sağlayıcısı kullanılsın?", provider_options, default_provider)
    print("-" * 50)

    default_level_val = getattr(cfg, "ACCESS_LEVEL", "full").lower()
    default_level = "1" if default_level_val == "full" else "2" if default_level_val == "sandbox" else "3"
    level_options = {
        "1": ("Full (Sınırsız Sistem Erişimi)", "full"),
        "2": ("Sandbox (Docker İzolasyonlu Sınırlandırılmış Erişim)", "sandbox"),
        "3": ("Restricted (Sadece Okuma ve Sohbet)", "restricted")
    }
    level = ask_choice("3. Güvenlik/Yetki seviyesi ne olsun?", level_options, default_level)
    print("-" * 50)

    log_options = {
        "1": ("INFO (Standart)", "INFO"),
        "2": ("DEBUG (Detaylı Geliştirici Logları)", "DEBUG"),
        "3": ("WARNING (Sadece Uyarılar ve Hatalar)", "WARNING")
    }
    log_level = ask_choice("4. Log seviyesini seçin:", log_options, "1")

    extra_args = {}
    if provider == "ollama" and mode == "cli":
        extra_args["model"] = ask_text("\nKullanılacak Ollama modeli", getattr(cfg, "CODING_MODEL", "llama3"))
    elif mode == "web":
        extra_args["host"] = ask_text("\nWeb Sunucu Host IP'si", getattr(cfg, "WEB_HOST", "127.0.0.1"))
        extra_args["port"] = ask_text("Web Sunucu Portu", str(getattr(cfg, "WEB_PORT", 8000)))

    preflight(provider)

    cmd = build_command(mode, provider, level, log_level, extra_args)

    print(f"\n{CYAN}🚀 Başlatılacak komut:{RESET}")
    print(f"   {GREEN}{_format_cmd(cmd)}{RESET}")

    if not confirm("Sidar'ı başlatmak istiyor musunuz?", True):
        print(f"{YELLOW}İşlem kullanıcı tarafından iptal edildi.{RESET}")
        return 0

    return execute_command(cmd)


def execute_command(cmd: List[str], capture_output: bool = False, child_log_path: str | None = None) -> int:
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
    parser = argparse.ArgumentParser(description="Sidar Akıllı Başlatıcı")
    parser.add_argument("--quick", choices=["cli", "web"], help="Sihirbazı atla ve belirtilen modda hızlı başlat")
    parser.add_argument("--provider", choices=["ollama", "gemini"], help="Hızlı başlat için AI sağlayıcı")
    parser.add_argument("--level", choices=["restricted", "sandbox", "full"], help="Hızlı başlat için erişim seviyesi")
    parser.add_argument("--model", help="Hızlı CLI başlat için Ollama modeli")
    parser.add_argument("--host", help="Hızlı web başlat için host adresi")
    parser.add_argument("--port", help="Hızlı web başlat için port numarası")
    parser.add_argument("--log", default="INFO", help="Log seviyesi (INFO, DEBUG, WARNING)")
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

    # Eğer --quick argümanı verilmediyse etkileşimli sihirbazı çalıştır
    if not args.quick:
        sys.exit(run_wizard())

    # --quick argümanı verildiyse varsayılanları veya cli argümanlarını kullan
    provider = args.provider or getattr(cfg, "AI_PROVIDER", "ollama").lower()
    level = args.level or getattr(cfg, "ACCESS_LEVEL", "full").lower()
    
    extra_args = {
        "model": args.model or getattr(cfg, "CODING_MODEL", "llama3"),
        "host": args.host or getattr(cfg, "WEB_HOST", "127.0.0.1"),
        "port": args.port or str(getattr(cfg, "WEB_PORT", 8000))
    }

    cmd = build_command(args.quick, provider, level, args.log, extra_args)
    sys.exit(execute_command(cmd, capture_output=args.capture_output, child_log_path=args.child_log))


if __name__ == "__main__":
    main()