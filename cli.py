"""Sidar Project - CLI Arayüzü.

==================================

Bu modül, proje için terminal tabanlı etkileşimli arayüzün giriş noktasıdır.
Önceden `main.py` olarak adlandırılıyordu. İsim değişikliği yapılarak
`cli.py` olarak taşınmıştır. Dosyanın geri kalanı, önceki sürümdeki
komut satırı argüman işleme, yapılandırma override etme ve `SidarAgent`
oluşturma mantığını korur.

Kullanım:

    python cli.py                  # interaktif mod
    python cli.py --status         # sistem durumunu göster
    python cli.py -c "komut"       # tek komut çalıştır
    python cli.py --level full     # erişim seviyesini geçici olarak ayarla
    python cli.py doctor           # artifacts/install/doctor.json sağlık raporu üret

Dosyanın içeriği orijinal `main.py` dosyasından taşınmıştır. CLI giriş
noktasının tüm yetenekleri aynı şekilde çalışmaya devam eder.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Proje kökünü sys.path'e ekle
sys.path.insert(0, os.path.dirname(__file__))

from agent.sidar_agent import SidarAgent
from config import Config

# ─────────────────────────────────────────────
#  LOGLAMA
# ─────────────────────────────────────────────


def _setup_logging(level: str) -> None:
    """config.py zaten logging.basicConfig'i RotatingFileHandler ile kurmuştur.

    Burada yalnızca CLI --log argümanına göre kök logger seviyesini güncelliyoruz.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.getLogger().setLevel(log_level)


# ─────────────────────────────────────────────
#  BANNER  (sürüm çalışma anında okunur)
# ─────────────────────────────────────────────


def _make_banner(version: str) -> str:
    """Sürüm numarasını çerçeve içine, gerekirse kırparak basan ASCII banner'ı oluşturur."""
    ver_field = f"v{version}" if version else "v?"
    # İç alan: " ║  " (4) + 44 karakter + "║" (1) = 49 toplam
    # "Yazılım Mimarı & Baş Mühendis AI " = 33 karakter → kalan 11 karakter versiyon için
    _VER_AREA = 11
    _PREFIX = "Yazılım Mimarı & Baş Mühendis AI "  # 33 karakter
    if len(ver_field) <= _VER_AREA:
        ver_str = ver_field.ljust(_VER_AREA)
    else:
        ver_str = ver_field[: _VER_AREA - 1] + "…"
    subtitle_line = f" ║  {_PREFIX}{ver_str}║"
    lines = [
        "",
        " ╔══════════════════════════════════════════════╗",
        " ║  ███████╗██╗██████╗  █████╗ ██████╗          ║",
        " ║  ██╔════╝██║██╔══██╗██╔══██╗██╔══██╗         ║",
        " ║  ███████╗██║██║  ██║███████║██████╔╝         ║",
        " ║  ╚════██║██║██║  ██║██╔══██║██╔══██╗         ║",
        " ║  ███████║██║██████╔╝██║  ██║██║  ██║         ║",
        " ║  ╚══════╝╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝         ║",
        subtitle_line,
        " ╚══════════════════════════════════════════════╝",
    ]
    return "\n".join(lines) + "\n"


HELP_TEXT = """
Komutlar:
  .status     — Sistem durumunu göster
  .clear      — Konuşma belleğini temizle
  /clear      — Konuşma belleğini temizle (alias)
  /reset      — Konuşma belleğini temizle (alias)
  .audit      — Proje denetimini çalıştır
  .health     — Sistem sağlık raporu
  .gpu        — GPU belleğini optimize et
  .github     — GitHub bağlantı durumu
  .level      — Mevcut erişim seviyesini göster
  .level <seviye> — Erişim seviyesini değiştir (restricted/sandbox/full)
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
    """Tek asyncio.run() çağrısıyla yönetilen interaktif döngü.

    Sorun (eski kod): while döngüsü içinde her mesajda asyncio.run() çağrılıyordu.
    Her çağrı yeni bir Event Loop açıp kapattığından, ikinci mesajda
    agent._lock eski (kapalı) loop'a bağlı kalıyordu → RuntimeError riski.

    Çözüm: Tüm döngü tek bir async fonksiyon içine alındı.
    asyncio.Lock() tüm oturum boyunca aynı loop'ta yaşar.
    """
    banner_already_shown = os.getenv("SIDAR_BANNER_SHOWN", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if not banner_already_shown:
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
        gpu_info = str(getattr(agent.cfg, "GPU_INFO", "") or "").strip()
        use_gpu_env = os.getenv("USE_GPU", "").strip().lower()
        if use_gpu_env in {"0", "false", "no", "off"}:
            if gpu_info:
                print(f"  GPU             : ✗ {gpu_info} (CPU modu, USE_GPU=false)")
            else:
                print("  GPU             : ℹ CPU modu (USE_GPU=false)")
        elif gpu_info.lower() == "cuda bulunamadı":
            print("  GPU             : ✗ GPU bulunamadı (CPU modunda çalışıyor)")
        elif gpu_info:
            print(f"  GPU             : ✗ {gpu_info}")
        else:
            print(f"  GPU             : ℹ CPU modu ({gpu_info or 'GPU devre dışı'})")
    print(f"  GitHub          : {'Hazır' if agent.github.is_available() else 'Hazır değil'}")
    print(
        f"  Web Arama       : "
        f"{'Aktif' if agent.web.is_available() else 'duckduckgo-search kurulu değil'}"
    )
    print(f"  Paket Bilgi     : {agent.pkg.status()}")
    docs_status = agent.docs.status()
    print(f"  Belge Deposu    : {docs_status}")
    if "pgvector (pasif)" in docs_status:
        print(
            "  RAG Uyarısı     : pgvector pasif; `uv run python -m core.doctor "
            "artifacts/install/doctor.json` ile DB/pgvector teşhislerini çalıştırın."
        )
    if "RAG: 0 belge" in docs_status:
        print("  RAG İpucu       : indeks boş; `belge ekle <url>` komutuyla belge ekleyin.")
    print("\n  '.help' yazarak komut listesini görebilirsiniz.\n")

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
        elif user_input.lower() in (".clear", "/clear", "/reset"):
            print(await agent.clear_memory())
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
        elif user_input.lower().startswith(".level"):
            parts = user_input.strip().split(maxsplit=1)
            if len(parts) > 1:
                print(f"\nSidar > {await agent.set_access_level(parts[1])}\n")
            else:
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
        except asyncio.CancelledError:
            print("\nSidar > İşlem iptal edildi. Kapatılıyor. ✓")
            break
        except Exception as exc:
            print(f"\nSidar > ✗ Hata: {exc}\n")
            logging.exception("Ajan yanıt hatası")


def interactive_loop(agent: SidarAgent) -> None:
    """Geri uyumluluk için ince sarmalayıcı.

    Yeni ana akış (``main()``) artık tek bir ``asyncio.run()`` çağrısı
    içinden ``_run_interactive_session`` kullanır; bu sarmalayıcı sadece
    eski testler/çağırıcılar bozulmasın diye burada tutuluyor.
    """
    asyncio.run(_interactive_loop_async(agent))


async def _ensure_cli_memory_user(agent: SidarAgent) -> None:
    """CLI oturumları için varsayılan bir kullanıcı bağlamı hazırlar."""
    user = await agent.memory.db.ensure_user("cli")
    await agent.memory.set_active_user(user.id, user.username)


async def _shutdown_agent(agent: SidarAgent) -> None:
    """Asyncpg pool ve SQLite bağlantılarını mevcut event loop'ta kapatır.

    asyncpg bağlantıları oluşturuldukları event loop'a kilitlidir — havuzu
    yaratıldığı loop dışında kapatmaya çalışmak `InterfaceError` üretir.
    Bu yardımcı, kapanışın her zaman doğru loop içinden çağrılmasını sağlar.
    """
    try:
        db = getattr(getattr(agent, "memory", None), "db", None)
        if db is not None and callable(getattr(db, "close", None)):
            await db.close()
    except Exception:  # pragma: no cover - shutdown best-effort
        logging.exception("Veritabanı kapatılırken hata")


async def _run_interactive_session(agent: SidarAgent) -> None:
    """Tüm CLI yaşam döngüsünü tek event loop içinde yürütür.

    Önceki sürümde `asyncio.run()` üç ayrı çağrı ile kullanılıyordu
    (initialize, ensure_user, interactive_loop). Her çağrı yeni bir
    event loop oluşturduğundan, asyncpg connection pool ilk loop'a
    bağlı kalıyor; ikinci loop'tan kullanıldığında
    `Task got Future attached to a different loop` ve ardından
    `InterfaceError: another operation is in progress` hataları
    yükseliyordu. Tek bir loop kullanarak bu kök nedeni gideriyoruz.
    """
    try:
        await agent.initialize()
        await _ensure_cli_memory_user(agent)
        await _interactive_loop_async(agent)
    finally:
        await _shutdown_agent(agent)


# ─────────────────────────────────────────────
#  DOCTOR KOMUTU
# ─────────────────────────────────────────────


def _run_doctor_command(
    output_path: str = "artifacts/install/doctor.json", *, fix: bool = False
) -> int:
    """Run the install/readiness doctor and persist its JSON report."""
    from core.doctor import _apply_database_env_fix, run_doctor_report
    from core.doctor.reporting import write_doctor_report

    repair = _apply_database_env_fix() if fix else None
    report = run_doctor_report(output_path=Path(output_path))
    if repair is not None:
        report["repairs"] = [repair]
        write_doctor_report(report, Path(output_path))
    print(f"Sidar Doctor overall_status={report['overall_status']}")
    print(f"Rapor: {output_path}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    repair_failed = repair is not None and repair.get("attempted") and not repair.get("success")
    return 0 if report["overall_status"] in {"pass", "warn"} and not repair_failed else 1


# ─────────────────────────────────────────────
#  GİRİŞ NOKTASI
# ─────────────────────────────────────────────


def main_cli(argv: list[str] | None = None) -> int:
    use_process_argv = argv is None
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) > 0 and argv[0] == "doctor":
        doctor_parser = argparse.ArgumentParser(description="Sidar Doctor sağlık raporu üret")
        doctor_parser.add_argument("doctor", nargs="?")
        doctor_parser.add_argument(
            "--output",
            default="artifacts/install/doctor.json",
            help="Doctor JSON rapor yolu",
        )
        doctor_parser.add_argument(
            "--fix",
            action="store_true",
            help="Düzenlenebilir veritabanı ortam sapmasını güvenli biçimde onar",
        )
        doctor_args = doctor_parser.parse_args(argv)
        if doctor_args.fix:
            return _run_doctor_command(doctor_args.output, fix=True)
        return _run_doctor_command(doctor_args.output)

    cfg_defaults = Config()

    parser = argparse.ArgumentParser(
        description="Sidar — Yazılım Mühendisi AI Asistanı (CLI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-c", "--command", help="Tek komut çalıştır ve çık")
    parser.add_argument("--status", action="store_true", help="Sistem durumunu göster ve çık")
    parser.add_argument("--doctor", action="store_true", help="Doctor sağlık raporu üret ve çık")
    parser.add_argument(
        "--level",
        choices=["restricted", "sandbox", "full"],
        default=getattr(cfg_defaults, "ACCESS_LEVEL", "full"),
        help="Erişim seviyesini geçici olarak ayarla",
    )
    parser.add_argument(
        "--provider",
        choices=["ollama", "gemini", "openai", "anthropic"],
        default=getattr(cfg_defaults, "AI_PROVIDER", "ollama"),
        help="AI sağlayıcısı",
    )
    parser.add_argument(
        "--model",
        default=getattr(cfg_defaults, "CODING_MODEL", "qwen2.5-coder:7b"),
        help="Ollama model adı",
    )
    parser.add_argument(
        "--log",
        default=getattr(cfg_defaults, "LOG_LEVEL", "INFO"),
        help="Log seviyesi (DEBUG/INFO/WARNING)",
    )
    if use_process_argv:
        args = parser.parse_args()
    else:
        args = parser.parse_args(argv)

    _setup_logging(args.log)

    if getattr(args, "doctor", False):
        return _run_doctor_command()

    # Config nesnesini oluştur; CLI flag'leri instance attribute olarak
    # doğrudan override et. os.environ üzerinden override ÇALIŞMAZ çünkü
    # Config sınıf attribute'ları module import anında bir kez değerlendirilir.
    cfg = Config()
    cfg.initialize_directories()
    if args.level:
        cfg.ACCESS_LEVEL = args.level
    if args.provider:
        cfg.AI_PROVIDER = args.provider
    if args.model:
        cfg.CODING_MODEL = args.model
    if args.command:
        cfg.CLI_FAST_MODE = True
    skip_boot_checks = os.getenv("SIDAR_SKIP_BOOT_CHECKS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if not skip_boot_checks and not cfg.validate_critical_settings():
        print("❌ Kritik yapılandırma doğrulaması başarısız. Çıkılıyor.")
        raise SystemExit("Kritik yapılandırma doğrulaması başarısız")

    agent = SidarAgent(cfg)

    if args.status:

        async def _status_flow() -> None:
            try:
                await agent.initialize()
                print(agent.status())
            finally:
                await _shutdown_agent(agent)

        asyncio.run(_status_flow())
        return 0

    if args.command:
        # Komut modunda init + kullanıcı bağlamı + yanıt zincirini
        # tek timeout penceresinde, tek event loop içinde çalıştır.
        async def _run_command_with_setup() -> None:
            try:
                await agent.initialize()
                await _ensure_cli_memory_user(agent)
                print("Sidar > ", end="", flush=True)
                async for chunk in agent.respond(args.command):
                    print(chunk, end="", flush=True)
                print()
            finally:
                await _shutdown_agent(agent)

        command_timeout = max(5, int(getattr(cfg, "CLI_COMMAND_TIMEOUT", 25) or 25))
        try:
            asyncio.run(asyncio.wait_for(_run_command_with_setup(), timeout=command_timeout))
        except TimeoutError:
            print(f"\nSidar > ⚠ Komut zaman aşımına uğradı ({command_timeout}s).")
        return 0

    # İnteraktif mod: initialize + ensure_user + REPL hepsi aynı event loop'ta.
    try:
        asyncio.run(_run_interactive_session(agent))
    except KeyboardInterrupt:
        print("\nSidar > Görüşürüz. ✓")
    return 0


def main() -> int:
    argv = list(sys.argv[1:])
    if (len(argv) > 0 and argv[0] == "doctor") or "--doctor" in argv:
        raise SystemExit(main_cli(argv))
    return main_cli()


if __name__ == "__main__":
    raise SystemExit(main())
