"""
Sidar  github_upload.py - Otomatik GitHub Yükleme Aracı
Sürüm: 2.0
Açıklama: Mevcut projeyi kolayca GitHub'a yedekler/yükler.
Kimlik, çakışma ve otomatik birleştirme (Auto-Merge) kontrolleri içerir.
"""
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional

from config import Config


cfg = Config()

# ASLA YÜKLENMEMESİ GEREKENLER (kritik güvenlik katmanı)
# Not: .gitignore'dan bağımsız hard-blacklist; collect_safe_files() içinde
# git add -u KULLANILMAZ — bu liste tracked dosya sızıntısına karşı da korur.
FORBIDDEN_PATHS: list[str] = [
    ".env",
    "sessions/",
    "chroma_db/",
    "__pycache__/",
    ".git/",
    "logs/",
    "models/",
    "secrets/",
    "credentials/",
    "data/",
    "temp/",
    "tmp/",
]

# Push yeniden deneme ayarları (CLAUDE.md: exponential backoff)
_PUSH_MAX_RETRIES: int = 4
_PUSH_BACKOFF_BASE: int = 2  # saniye


# ═══════════════════════════════════════════════════════════════
# RENK KODLARI
# ═══════════════════════════════════════════════════════════════
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


# ═══════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════
def run_command(args: list[str], show_output: bool = True) -> tuple[bool, str]:
    """Komutu shell=False ile güvenli şekilde çalıştırır."""
    try:
        result = subprocess.run(
            args,
            shell=False,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if show_output and result.stdout.strip():
            print(result.stdout.strip())
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.strip()
        if e.stdout and e.stdout.strip():
            err_msg += "\n" + e.stdout.strip()
        if show_output and err_msg:
            print(f"{Colors.WARNING}Git çıktısı: {err_msg}{Colors.ENDC}")
        return False, err_msg


def _is_valid_repo_url(url: str) -> bool:
    """Temel GitHub repo URL doğrulaması."""
    if not url:
        return False
    normalized = url.strip()
    return (
        normalized.startswith("https://github.com/")
        or normalized.startswith("git@github.com:")
    )


def _normalize_path(path: str) -> str:
    """Yol formatını güvenlik kontrolleri için normalize eder."""
    return path.replace("\\", "/").lstrip("./")


def is_forbidden_path(path: str) -> bool:
    """Hard blacklist: .gitignore'dan bağımsız kesin engel."""
    normalized = _normalize_path(path)
    return any(
        normalized == forbidden.rstrip("/") or normalized.startswith(forbidden)
        for forbidden in FORBIDDEN_PATHS
    )


def _is_readable_utf8(path: str) -> bool:
    """Dosyanın UTF-8 olarak açılabilir olup olmadığını kontrol eder (içerik yüklenmez)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            fh.read(1)
        return True
    except (UnicodeDecodeError, OSError):
        return False


def collect_safe_files() -> tuple[list[str], list[str]]:
    """Yalnızca güvenli ve UTF-8 okunabilir dosyaları stage listesine alır.

    Not: git add -u kasıtlı olarak kullanılmaz. Bu sayede daha önce
    yanlışlıkla commit edilmiş forbidden-path dosyaları push'a dahil olmaz.
    """
    success, output = run_command(
        ["git", "ls-files", "-co", "--exclude-standard"], show_output=False
    )
    if not success:
        return [], []

    safe_files: list[str] = []
    blocked_files: list[str] = []

    for line in output.splitlines():
        file_path = line.strip()
        if not file_path or os.path.isdir(file_path):
            continue

        if is_forbidden_path(file_path):
            blocked_files.append(file_path)
            continue

        if not _is_readable_utf8(file_path):
            blocked_files.append(file_path)
            continue

        safe_files.append(file_path)

    return safe_files, blocked_files


# ═══════════════════════════════════════════════════════════════
# KURULUM ADIMLARI
# ═══════════════════════════════════════════════════════════════
def setup_git_identity() -> None:
    """Eksikse Git kullanıcı kimliğini interaktif olarak ayarlar."""
    _, name_out = run_command(["git", "config", "user.name"], show_output=False)
    if not name_out:
        print(f"{Colors.WARNING}⚠️ Git kimliğiniz tanımlanmamış. Lütfen GitHub bilgilerinizi girin:{Colors.ENDC}")
        git_name = input("Adınız / GitHub Kullanıcı Adınız: ").strip()
        git_email = input("GitHub E-Posta Adresiniz: ").strip()
        run_command(["git", "config", "--global", "user.name", git_name], show_output=False)
        run_command(["git", "config", "--global", "user.email", git_email], show_output=False)
        print(f"{Colors.OKGREEN}✅ Git kimliğiniz başarıyla kaydedildi.{Colors.ENDC}\n")


def ensure_git_repo() -> None:
    """Klasörü gerekirse Git deposuna dönüştürür."""
    if not os.path.exists(".git"):
        print(f"{Colors.WARNING}Bu klasör henüz bir Git deposu değil. Başlatılıyor...{Colors.ENDC}")
        run_command(["git", "init"], show_output=False)
        run_command(["git", "branch", "-M", "main"], show_output=False)
        print(f"{Colors.OKGREEN}✅ Git deposu oluşturuldu.{Colors.ENDC}")


def ensure_remote() -> None:
    """Origin remote yoksa kullanıcıdan URL alarak ekler."""
    _, remotes = run_command(["git", "remote", "-v"], show_output=False)
    if "origin" not in remotes:
        print(f"{Colors.WARNING}GitHub depo (repository) bağlantısı bulunamadı.{Colors.ENDC}")
        repo_url = input(
            f"{Colors.OKBLUE}Lütfen GitHub Depo URL'sini girin\n"
            f"(Örn: https://github.com/niluferbagevi-gif/Sidar): {Colors.ENDC}"
        ).strip()

        if not _is_valid_repo_url(repo_url):
            print(f"{Colors.FAIL}Geçersiz veya boş URL. İşlem iptal edildi.{Colors.ENDC}")
            sys.exit(1)

        run_command(["git", "remote", "add", "origin", repo_url], show_output=False)
        print(f"{Colors.OKGREEN}✅ GitHub deposu sisteme bağlandı.{Colors.ENDC}")
    else:
        print(f"{Colors.OKGREEN}✅ Mevcut GitHub bağlantısı algılandı.{Colors.ENDC}")


def build_commit() -> None:
    """Güvenli dosyaları stage'e alır ve commit oluşturur."""
    print(f"\n{Colors.OKBLUE}📦 Dosyalar taranıyor ve paketleniyor...{Colors.ENDC}")
    run_command(["git", "reset"], show_output=False)
    safe_files, blocked_files = collect_safe_files()

    if safe_files:
        run_command(["git", "add", "--"] + safe_files, show_output=False)

    # NOT: git add -u burada kasıtlı olarak kullanılmıyor.
    # Tracked forbidden dosyaların (örn. yanlışlıkla commit edilmiş .env)
    # push'a sızmasını engellemek için silinen dosyalar manuel takip edilmez.

    if blocked_files:
        print(f"{Colors.WARNING}⛔ Güvenlik/kararlılık nedeniyle atlanan dosyalar:{Colors.ENDC}")
        for blocked in blocked_files:
            print(f"  - {blocked}")

    _, status = run_command(["git", "status", "--porcelain"], show_output=False)
    if not status:
        print(f"{Colors.WARNING}🤷 Yüklenecek yeni bir değişiklik bulunamadı. Projeniz zaten güncel!{Colors.ENDC}")
        sys.exit(0)

    version: str = getattr(cfg, "VERSION", "?")
    default_msg = (
        f"Sidar {version} - Otomatik Dagtim "
        f"({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    )
    print(f"\n{Colors.WARNING}Değişiklikleri kaydetmek için bir not yazın.{Colors.ENDC}")
    commit_msg = input(
        f"{Colors.OKBLUE}Commit mesajı (Boş bırakırsanız otomatik tarih atılır): {Colors.ENDC}"
    ).strip() or default_msg

    print(f"\n{Colors.OKBLUE}💾 Değişiklikler kaydediliyor...{Colors.ENDC}")
    commit_success, commit_err = run_command(["git", "commit", "-m", commit_msg], show_output=False)
    if not commit_success:
        print(f"{Colors.FAIL}❌ Dosyalar kaydedilirken hata oluştu: {commit_err}{Colors.ENDC}")
        sys.exit(1)


def _try_push(branch: str) -> tuple[bool, str]:
    """Tek push denemesi; sonucu döner."""
    return run_command(["git", "push", "-u", "origin", branch], show_output=False)


def _handle_conflict(branch: str) -> None:
    """Çakışma durumunda kullanıcıya merge seçeneği sunar ve push'u yeniden dener."""
    print(f"{Colors.WARNING}⚠️ GitHub'da bilgisayarınızda olmayan dosyalar var.{Colors.ENDC}")
    confirm = input(
        f"{Colors.OKBLUE}Uzak sunucu ile otomatik birleştirme yapılsın mı? (y/n): {Colors.ENDC}"
    ).strip().lower()

    if confirm != "y":
        print(
            f"{Colors.WARNING}⏹️ Otomatik birleştirme iptal edildi. "
            "Veri kaybını önlemek için push durduruldu."
            f"{Colors.ENDC}"
        )
        return

    pull_cmd = [
        "git", "pull", "origin", branch,
        "--rebase=false", "--allow-unrelated-histories", "--no-edit", "-X", "ours",
    ]
    print(
        f"{Colors.OKBLUE}🔄 Uzak sunucu ile dosyalar birleştiriliyor "
        f"(Çakışmalarda yerel dosyalar korunacak)...{Colors.ENDC}"
    )
    pull_success, pull_err = run_command(pull_cmd, show_output=False)

    if not (pull_success or "up to date" in pull_err.lower() or "merge made" in pull_err.lower()):
        print(f"{Colors.FAIL}❌ Birleştirme sırasında hata oluştu. Manuel kontrol gerekli:{Colors.ENDC}")
        print(f"{Colors.WARNING}{' '.join(pull_cmd)}{Colors.ENDC}")
        print(f"Hata Çıktısı:\n{pull_err}")
        return

    print(f"{Colors.OKGREEN}✅ Senkronizasyon başarılı. Yeniden yükleniyor...{Colors.ENDC}")
    retry_success, retry_err = push_with_retry(branch)
    if not retry_success:
        _print_push_error(retry_err)


def _print_push_error(err_msg: str) -> None:
    """Push hata mesajını sınıflandırarak ekrana basar."""
    if "rule violations" in err_msg:
        print(f"\n{Colors.FAIL}❌ GitHub Güvenlik Duvarı (Push Protection) Devreye Girdi!{Colors.ENDC}")
        print(
            f"{Colors.WARNING}İçinde şifre barındıran bir dosya yüklemeye çalışıyorsunuz. "
            "Lütfen yukarıdaki hata logunu okuyup şifreli dosyayı gizleyin (.gitignore) "
            f"veya linke tıklayıp izin verin.{Colors.ENDC}"
        )
    else:
        print(f"{Colors.FAIL}❌ Yükleme sırasında bilinmeyen bir hata oluştu:\n{err_msg}{Colors.ENDC}")


def push_with_retry(branch: str) -> tuple[bool, str]:
    """Push işlemini exponential backoff ile yeniden dener (CLAUDE.md gereksinimi).

    Yeniden deneme aralıkları: 2s, 4s, 8s, 16s
    """
    for attempt in range(_PUSH_MAX_RETRIES + 1):
        success, err_msg = _try_push(branch)
        if success:
            return True, ""

        # Çakışma/rejected hataları ağ sorunu değil; yeniden deneme anlamsız
        if any(kw in err_msg for kw in ("rejected", "fetch first", "non-fast-forward", "rule violations")):
            return False, err_msg

        if attempt < _PUSH_MAX_RETRIES:
            wait = _PUSH_BACKOFF_BASE ** (attempt + 1)
            print(
                f"{Colors.WARNING}⚠️ Push başarısız (deneme {attempt + 1}/{_PUSH_MAX_RETRIES}). "
                f"{wait}s sonra yeniden deneniyor...{Colors.ENDC}"
            )
            time.sleep(wait)

    return False, err_msg  # type: ignore[return-value]  # döngü en az 1 iterasyon yapar


# ═══════════════════════════════════════════════════════════════
# ANA PROGRAM
# ═══════════════════════════════════════════════════════════════
def main() -> None:
    version: str = getattr(cfg, "VERSION", "2.0")
    print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}")
    print(f"{Colors.BOLD} Sidar - GitHub Otomatik Yükleme & Yedekleme Aracı (v{version}) {Colors.ENDC}")
    print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}\n")

    # 0. Token kontrolü
    if not cfg.GITHUB_TOKEN:
        print(
            f"{Colors.FAIL}GITHUB_TOKEN config.py/.env üzerinden bulunamadı. "
            f"İşlem güvenlik nedeniyle durduruldu.{Colors.ENDC}"
        )
        sys.exit(1)

    # 1. Git kurulu mu?
    success, _ = run_command(["git", "--version"], show_output=False)
    if not success:
        print(
            f"{Colors.FAIL}Sistemde Git kurulu değil. "
            f"Lütfen terminalden 'sudo apt install git' yazarak kurun.{Colors.ENDC}"
        )
        sys.exit(1)

    setup_git_identity()
    ensure_git_repo()
    ensure_remote()
    build_commit()

    # Branch belirle
    _, branch = run_command(["git", "branch", "--show-current"], show_output=False)
    current_branch: str = branch if branch else "main"

    # Push
    print(f"\n{Colors.HEADER}🚀 GitHub'a yükleniyor (Hedef: {current_branch}). Lütfen bekleyin...{Colors.ENDC}")
    push_success, err_msg = push_with_retry(current_branch)

    if push_success:
        print(f"\n{Colors.HEADER}{'='*65}{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.OKGREEN}🎉 TEBRİKLER! Proje başarıyla GitHub'a yüklendi!{Colors.ENDC}")
        print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}")
    elif any(kw in err_msg for kw in ("rejected", "fetch first", "non-fast-forward")):
        _handle_conflict(current_branch)
    else:
        _print_push_error(err_msg)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.FAIL}İşlem kullanıcı tarafından iptal edildi.{Colors.ENDC}")
        sys.exit(0)