"""
Sidar Project - CLI Arayüzü
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

Dosyanın içeriği orijinal `main.py` dosyasından taşınmıştır. CLI giriş
noktasının tüm yetenekleri aynı şekilde çalışmaya devam eder.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# Proje kökünü sys.path'e ekle
sys.path.insert(0, os.path.dirname(__file__))

from agent.sidar_agent import SidarAgent
from config import Config
from core.ci_remediation import build_ci_remediation_payload

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
    print(
        f"  Web Arama       : {'Aktif' if agent.web.is_available() else 'duckduckgo-search kurulu değil'}"
    )
    print(f"  Paket Bilgi     : {agent.pkg.status()}")
    print(f"  Belge Deposu    : {agent.docs.status()}")
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
    asyncio.run(_interactive_loop_async(agent))


async def _ensure_cli_memory_user(agent: SidarAgent) -> None:
    """CLI oturumları için varsayılan bir kullanıcı bağlamı hazırlar."""
    user = await agent.memory.db.ensure_user("cli")
    await agent.memory.set_active_user(user.id, user.username)


def _extract_python_targets_from_log(log_text: str) -> list[str]:
    """mypy çıktısından aday python dosya yollarını çıkarır."""
    targets: list[str] = []
    seen: set[str] = set()
    for line in str(log_text or "").splitlines():
        candidate = line.split(":", 1)[0].strip()
        if not candidate or not candidate.endswith(".py"):
            continue
        path = Path(candidate)
        if not path.exists() or not path.is_file():
            continue
        normalized = path.as_posix()
        if normalized in seen:
            continue
        seen.add(normalized)
        targets.append(normalized)
    return targets[:20]


async def _run_heal_mode(
    agent: SidarAgent,
    *,
    log_path: str,
    output_path: str,
) -> int:
    """Log girdisinden self-heal remediation döngüsünü çalıştırır."""
    log_file = Path(log_path)
    if not log_file.exists():
        print(f"Sidar > ✗ Heal log dosyası bulunamadı: {log_file}")
        return 1

    log_text = log_file.read_text(encoding="utf-8", errors="replace").strip()
    if not log_text:
        print(f"Sidar > ✗ Heal log dosyası boş: {log_file}")
        return 1

    await agent.initialize()
    await _ensure_cli_memory_user(agent)
    if not bool(getattr(agent.cfg, "ENABLE_AUTONOMOUS_SELF_HEAL", False)):
        agent.cfg.ENABLE_AUTONOMOUS_SELF_HEAL = True

    suspected_targets = _extract_python_targets_from_log(log_text)
    diagnosis = "\n".join(log_text.splitlines()[:20]).strip()
    ci_context = {
        "ci_failure": True,
        "pipeline_failed": True,
        "workflow_name": "local_mypy_gate",
        "failure_summary": "mypy static analysis failure",
        "log_excerpt": log_text[:4000],
        "logs": log_text[:4000],
        "suspected_targets": suspected_targets,
        "branch": os.getenv("GIT_BRANCH", "local"),
        "base_branch": os.getenv("GIT_BASE_BRANCH", "main"),
        "run_id": f"local-heal-{int(time.time())}",
    }
    remediation = build_ci_remediation_payload(ci_context, diagnosis)
    await agent._attempt_autonomous_self_heal(
        ci_context=ci_context,
        diagnosis=diagnosis,
        remediation=remediation,
    )

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(remediation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    execution = dict(remediation.get("self_heal_execution") or {})
    status = str(execution.get("status") or "unknown").strip().lower()
    operations = list((remediation.get("self_heal_plan") or {}).get("operations") or [])
    print(
        "Sidar > Heal sonucu:"
        f" status={status}, hedef_dosya={len(suspected_targets)}, patch_op={len(operations)}"
    )
    print(f"Sidar > Heal raporu: {output_file}")
    return 0 if status == "applied" else 1


# ─────────────────────────────────────────────
#  GİRİŞ NOKTASI
# ─────────────────────────────────────────────


def main() -> None:
    cfg_defaults = Config()

    parser = argparse.ArgumentParser(
        description="Sidar — Yazılım Mühendisi AI Asistanı (CLI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-c", "--command", help="Tek komut çalıştır ve çık")
    parser.add_argument(
        "--heal",
        metavar="LOG_PATH",
        help="mypy/CI hata logundan otonom self-heal döngüsünü tetikle",
    )
    parser.add_argument(
        "--heal-output",
        default="artifacts/remediation/heal_result.json",
        help="Heal çıktısının JSON olarak yazılacağı dosya",
    )
    parser.add_argument("--status", action="store_true", help="Sistem durumunu göster ve çık")
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
    args = parser.parse_args()

    _setup_logging(args.log)

    # Config nesnesini oluştur; CLI flag'leri instance attribute olarak
    # doğrudan override et. os.environ üzerinden override ÇALIŞMAZ çünkü
    # Config sınıf attribute'ları module import anında bir kez değerlendirilir.
    cfg = Config()
    cfg.initialize_directories()
    if not cfg.validate_critical_settings():
        raise SystemExit("❌ Kritik yapılandırma doğrulaması başarısız. Çıkılıyor.")
    if args.level:
        cfg.ACCESS_LEVEL = args.level
    if args.provider:
        cfg.AI_PROVIDER = args.provider
    if args.model:
        cfg.CODING_MODEL = args.model
    if args.command:
        cfg.CLI_FAST_MODE = True
    if args.heal:
        cfg.CLI_FAST_MODE = True

    agent = SidarAgent(cfg)

    if args.heal:
        code = asyncio.run(_run_heal_mode(agent, log_path=args.heal, output_path=args.heal_output))
        raise SystemExit(code)

    if args.status:
        asyncio.run(agent.initialize())
        print(agent.status())
        return

    if args.command:
        # Komut modunda init + kullanıcı bağlamı + yanıt zincirini
        # tek timeout penceresinde çalıştır.
        async def _run_command_with_setup() -> None:
            await agent.initialize()
            await _ensure_cli_memory_user(agent)
            print("Sidar > ", end="", flush=True)
            async for chunk in agent.respond(args.command):
                print(chunk, end="", flush=True)
            print()

        command_timeout = max(5, int(getattr(cfg, "CLI_COMMAND_TIMEOUT", 25) or 25))
        try:
            asyncio.run(asyncio.wait_for(_run_command_with_setup(), timeout=command_timeout))
        except TimeoutError:
            print(f"\nSidar > ⚠ Komut zaman aşımına uğradı ({command_timeout}s).")
        return

    asyncio.run(agent.initialize())
    asyncio.run(_ensure_cli_memory_user(agent))
    interactive_loop(agent)


if __name__ == "__main__":
    main()
