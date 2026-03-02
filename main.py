"""
Sidar Project - Giriş Noktası
Yazılım Mühendisi AI Asistanı — CLI Arayüzü

Kullanım:
    python main.py                  # interaktif mod
    python main.py --status         # sistem durumunu göster
    python main.py -c "komut"       # tek komut çalıştır
    python main.py --level full     # erişim seviyesini geçici olarak ayarla
"""

import argparse
import asyncio
import logging
import os
import sys

# Proje kökünü sys.path'e ekle
sys.path.insert(0, os.path.dirname(__file__))

from config import Config
from agent.sidar_agent import SidarAgent


# ─────────────────────────────────────────────
#  LOGLAMA
# ─────────────────────────────────────────────

def _setup_logging(level: str) -> None:
    """
    config.py zaten logging.basicConfig'i RotatingFileHandler ile kurmuştur.
    Burada yalnızca CLI --log argümanına göre kök logger seviyesini güncelliyoruz.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.getLogger().setLevel(log_level)


# ─────────────────────────────────────────────
#  BANNER  (sürüm çalışma anında okunur)
# ─────────────────────────────────────────────

def _make_banner(version: str) -> str:
    """Sürüm numarasını dinamik olarak içeren ASCII banner'ı oluşturur."""
    ver_field = f"v{version}"
    # Sabit genişlik: 7 karakter; sağa boşluk ekle
    ver_padded = ver_field.ljust(7)
    return (
        "\n"
        " ╔══════════════════════════════════════════════╗\n"
        " ║  ███████╗██╗██████╗  █████╗ ██████╗          ║\n"
        " ║  ██╔════╝██║██╔══██╗██╔══██╗██╔══██╗         ║\n"
        " ║  ███████╗██║██║  ██║███████║██████╔╝         ║\n"
        " ║  ╚════██║██║██║  ██║██╔══██║██╔══██╗         ║\n"
        " ║  ███████║██║██████╔╝██║  ██║██║  ██║         ║\n"
        " ║  ╚══════╝╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝         ║\n"
        f" ║  Yazılım Mimarı & Baş Mühendis AI  {ver_padded}║\n"
        " ╚══════════════════════════════════════════════╝\n"
    )


HELP_TEXT = """
Komutlar:
  .status     — Sistem durumunu göster
  .clear      — Konuşma belleğini temizle
  .audit      — Proje denetimini çalıştır
  .health     — Sistem sağlık raporu
  .gpu        — GPU belleğini optimize et
  .github     — GitHub bağlantı durumu
  .level      — Mevcut erişim seviyesini göster
  .web        — Web arama durumu
  .docs       — Belge deposunu listele
  .help       — Bu yardım mesajını göster
  .exit / .q  — Çıkış

Doğrudan Komutlar (serbest metin):
  web'de ara: <sorgu>              → DuckDuckGo web araması
  pypi: <paket>                    → PyPI paket bilgisi
  npm: <paket>                     → npm paket bilgisi
  github releases: <owner/repo>    → GitHub release listesi
  docs ara: <sorgu>                → Belge deposunda ara
  belge ekle <url>                 → URL'den belge ekle
  stackoverflow: <sorgu>           → Stack Overflow araması
"""


# ─────────────────────────────────────────────
#  İNTERAKTİF DÖNGÜ
# ─────────────────────────────────────────────

async def _interactive_loop_async(agent: SidarAgent) -> None:
    """
    Tek asyncio.run() çağrısıyla yönetilen interaktif döngü.

    Sorun (eski kod): while döngüsü içinde her mesajda asyncio.run() çağrılıyordu.
    Her çağrı yeni bir Event Loop açıp kapattığından, ikinci mesajda
    agent._lock eski (kapalı) loop'a bağlı kalıyordu → RuntimeError riski.

    Çözüm: Tüm döngü tek bir async fonksiyon içine alındı.
    asyncio.Lock() tüm oturum boyunca aynı loop'ta yaşar.
    """
    print(_make_banner(agent.VERSION))

    # Sağlayıcıya göre doğru model adını göster
    if agent.cfg.AI_PROVIDER == "gemini":
        model_display = getattr(agent.cfg, "GEMINI_MODEL", "gemini-2.0-flash")
    else:
        model_display = agent.cfg.CODING_MODEL

    print(f"  Erişim Seviyesi : {agent.cfg.ACCESS_LEVEL.upper()}")
    print(f"  AI Sağlayıcı    : {agent.cfg.AI_PROVIDER} ({model_display})")
    if agent.cfg.USE_GPU:
        gpu_line = f"✓ {agent.cfg.GPU_INFO}"
        if getattr(agent.cfg, "CUDA_VERSION", "N/A") != "N/A":
            gpu_line += f"  (CUDA {agent.cfg.CUDA_VERSION}"
            if getattr(agent.cfg, "GPU_COUNT", 1) > 1:
                gpu_line += f", {agent.cfg.GPU_COUNT} GPU"
            gpu_line += ")"
        print(f"  GPU             : {gpu_line}")
    else:
        print(f"  GPU             : ✗ CPU Modu  ({agent.cfg.GPU_INFO})")
    print(f"  GitHub          : {'Bağlı' if agent.github.is_available() else 'Bağlı değil'}")
    print(f"  Web Arama       : {'Aktif' if agent.web.is_available() else 'duckduckgo-search kurulu değil'}")
    print(f"  Paket Bilgi     : {agent.pkg.status()}")
    print(f"  Belge Deposu    : {agent.docs.status()}")
    print(f"\n  '.help' yazarak komut listesini görebilirsiniz.\n")

    while True:
        try:
            # input() senkron olduğu için event loop'u bloke etmemesi için thread'e itilir
            user_input = (await asyncio.to_thread(input, "Sen  > ")).strip()
        except (EOFError, KeyboardInterrupt, asyncio.CancelledError):
            print("\nSidar > Görüşürüz. ✓")
            break

        if not user_input:
            continue

        # Dahili komutlar
        if user_input.lower() in (".exit", ".q", "exit", "quit", "çıkış"):
            print("Sidar > Görüşürüz. ✓")
            break
        elif user_input.lower() == ".help":
            print(HELP_TEXT)
            continue
        elif user_input.lower() == ".status":
            print(agent.status())
            continue
        elif user_input.lower() == ".clear":
            print(agent.clear_memory())
            continue
        elif user_input.lower() == ".audit":
            print(agent.code.audit_project("."))
            continue
        elif user_input.lower() == ".health":
            print(agent.health.full_report())
            continue
        elif user_input.lower() == ".gpu":
            print(agent.health.optimize_gpu_memory())
            continue
        elif user_input.lower() == ".github":
            print(agent.github.status())
            continue
        elif user_input.lower() == ".level":
            print(agent.security.status_report())
            continue
        elif user_input.lower() == ".web":
            print(agent.web.status())
            continue
        elif user_input.lower() == ".docs":
            print(agent.docs.list_documents())
            continue

        # Ajan yanıtı — aynı event loop içinde doğrudan async for kullanılır
        try:
            print("Sidar > ", end="", flush=True)
            async for chunk in agent.respond(user_input):
                print(chunk, end="", flush=True)
            print("\n")
        except Exception as exc:
            print(f"\nSidar > ✗ Hata: {exc}\n")
            logging.exception("Ajan yanıt hatası")


def interactive_loop(agent: SidarAgent) -> None:
    asyncio.run(_interactive_loop_async(agent))


# ─────────────────────────────────────────────
#  GİRİŞ NOKTASI
# ─────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sidar — Yazılım Mühendisi AI Asistanı",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-c", "--command", help="Tek komut çalıştır ve çık")
    parser.add_argument("--status", action="store_true", help="Sistem durumunu göster ve çık")
    parser.add_argument(
        "--level",
        choices=["restricted", "sandbox", "full"],
        help="Erişim seviyesini geçici olarak ayarla",
    )
    parser.add_argument("--provider", choices=["ollama", "gemini"], help="AI sağlayıcısı")
    parser.add_argument("--model", help="Ollama model adı")
    parser.add_argument("--log", default="INFO", help="Log seviyesi (DEBUG/INFO/WARNING)")
    args = parser.parse_args()

    _setup_logging(args.log)

    # Config nesnesini oluştur; CLI flag'leri instance attribute olarak
    # doğrudan override et. os.environ üzerinden override ÇALIŞMAZ çünkü
    # Config sınıf attribute'ları module import anında bir kez değerlendirilir.
    cfg = Config()
    if args.level:
        cfg.ACCESS_LEVEL = args.level
    if args.provider:
        cfg.AI_PROVIDER = args.provider
    if args.model:
        cfg.CODING_MODEL = args.model

    agent = SidarAgent(cfg)

    if args.status:
        print(agent.status())
        return

    if args.command:
        # respond() async generator olduğu için asyncio.run() ile çalıştırılır
        async def _run_command() -> None:
            print("Sidar > ", end="", flush=True)
            async for chunk in agent.respond(args.command):
                print(chunk, end="", flush=True)
            print()

        asyncio.run(_run_command())
        return

    interactive_loop(agent)


if __name__ == "__main__":
    main() 