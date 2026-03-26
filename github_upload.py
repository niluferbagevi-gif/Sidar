"""
Sidar  github_upload.py - Otomatik GitHub Yukleme Araci
Surum: 2.1
Aciklama: Mevcut projeyi kolayca GitHub'a yedekler/yukler.
Kimlik, cakisma, silme senkronizasyonu ve otomatik birlestirme (Auto-Merge) kontrolleri icerir.
"""
import os
import fnmatch
import subprocess
import sys
import time
from datetime import datetime

from config import Config


cfg = Config()

# ASLA YUKLENMEMESI GEREKENLER (kritik guvenlik katmani)
# Not: .gitignore'dan bagimsiz hard-blacklist; collect_safe_files() icinde
# git add -u KULLANILMAZ - bu liste tracked dosya sizintisina karsi da korur.
FORBIDDEN_PATHS: list[str] = [
    ".env",
    ".env.*",
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
    "media_cache/",
    "downloads/",
    "web_ui_react/test-results/",
    "web_ui_react/playwright-report/",
    ".cursor/",
    ".idea/",
    "htmlcov/",
    ".coverage",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
]

# Push yeniden deneme ayarlari (CLAUDE.md: exponential backoff)
_PUSH_MAX_RETRIES: int = 4
_PUSH_BACKOFF_BASE: int = 2  # saniye


# ================================================================
# RENK KODLARI
# ================================================================
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


# ================================================================
# YARDIMCI FONKSIYONLAR
# ================================================================
def run_command(args: list[str], show_output: bool = True) -> tuple[bool, str]:
    """Komutu shell=False ile guvenli sekilde calistirir."""
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
    """Temel GitHub repo URL dogrulamasi."""
    if not url:
        return False
    normalized = url.strip()
    return (
        normalized.startswith("https://github.com/")
        or normalized.startswith("git@github.com:")
    )


def _normalize_path(path: str) -> str:
    """Yol formatini guvenlik kontrolleri icin normalize eder."""
    return path.replace("\\", "/").lstrip("./")


def is_forbidden_path(path: str) -> bool:
    """Hard blacklist: .gitignore'dan bagimsiz kesin engel."""
    normalized = _normalize_path(path)
    basename = os.path.basename(normalized)

    for forbidden in FORBIDDEN_PATHS:
        normalized_forbidden = _normalize_path(forbidden)

        # Klasor tabanli engelleme
        if normalized_forbidden.endswith("/"):
            if normalized == normalized_forbidden.rstrip("/") or normalized.startswith(normalized_forbidden):
                return True
            continue

        # Glob tabanli engelleme (*.db, .env.* vb.)
        if any(ch in normalized_forbidden for ch in "*?[]"):
            if fnmatch.fnmatch(normalized, normalized_forbidden) or fnmatch.fnmatch(basename, normalized_forbidden):
                return True
            continue

        # Dosya tam eslesmesi
        if normalized == normalized_forbidden:
            return True

    return False


def is_file_safe_to_upload(path: str) -> tuple[bool, str]:
    """Dosyanin yasakli yolda olup olmadigini ve boyutunu kontrol eder."""
    if not os.path.isabs(path) and is_forbidden_path(path):
        return False, "yasakli dizin/dosya"

    if os.path.islink(path):
        return False, "sembolik baglar (symlink) guvenlik geregi engellendi"

    try:
        file_size_mb = os.path.getsize(path) / (1024 * 1024)
    except OSError:
        return False, "dosya boyutu okunamadi"

    if file_size_mb > 95.0:
        return False, f"dosya cok buyuk ({file_size_mb:.1f} MB)"

    return True, ""


def collect_safe_files() -> tuple[list[str], list[str]]:
    """Yalnizca guvenli ve boyutu uygun dosyalari stage listesine alir.

    Yalnizca mevcut (untracked + tracked) dosyalari kapsar.
    Silinen dosyalar icin collect_deleted_files() kullanilir.
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

        safe_to_upload, reason = is_file_safe_to_upload(file_path)
        if not safe_to_upload:
            blocked_files.append(f"{file_path} ({reason})")
            continue

        safe_files.append(file_path)

    return safe_files, blocked_files


def collect_deleted_files() -> list[str]:
    """Local'de silinmis ama Git'te hala tracked olan dosyalari bulur.

    Bu dosyalar GitHub'a push edildiginde uzak repoda da silinir;
    boylece local <-> GitHub senkronizasyonu saglanir.

    Returns:
        to_delete -- GitHub'dan da silinecek dosyalar
    """
    success, output = run_command(["git", "ls-files", "-d"], show_output=False)
    if not success:
        return []

    to_delete: list[str] = []

    for line in output.splitlines():
        file_path = line.strip()
        if not file_path:
            continue

        # Forbidden path'ler silme islemine de dahil edilmez;
        # bu dosyalar zaten GitHub'da olmak zorunda degildi.
        if is_forbidden_path(file_path):
            continue

        to_delete.append(file_path)

    return to_delete


def collect_tracked_ignored_files() -> list[str]:
    """Git tarafindan tracked ama .gitignore'da olan dosyalari listeler."""
    success, output = run_command(
        ["git", "ls-files", "-ci", "--exclude-standard"], show_output=False
    )
    if not success:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def _summarize_staged_areas() -> str:
    """Stage'deki degisikliklerden klasor/alan ozeti uretir."""
    success, output = run_command(
        ["git", "diff", "--cached", "--name-only"], show_output=False
    )
    if not success or not output.strip():
        return "workspace"

    areas: list[str] = []
    for raw in output.splitlines():
        path = _normalize_path(raw.strip())
        if not path:
            continue
        area = path.split("/", 1)[0]
        if area not in areas:
            areas.append(area)

    if not areas:
        return "workspace"

    return " ".join(f"{area}/" for area in areas[:4])


# ================================================================
# KURULUM ADIMLARI
# ================================================================
def setup_git_identity() -> None:
    """Eksikse Git kullanici kimligini interaktif olarak ayarlar."""
    _, name_out = run_command(["git", "config", "user.name"], show_output=False)
    if not name_out:
        print(f"{Colors.WARNING}Git kimliginiz tanimlanmamis. Lutfen GitHub bilgilerinizi girin:{Colors.ENDC}")
        git_name = input("Adiniz / GitHub Kullanici Adiniz: ").strip()
        git_email = input("GitHub E-Posta Adresiniz: ").strip()
        run_command(["git", "config", "--global", "user.name", git_name], show_output=False)
        run_command(["git", "config", "--global", "user.email", git_email], show_output=False)
        print(f"{Colors.OKGREEN}Git kimliginiz basariyla kaydedildi.{Colors.ENDC}\n")


def ensure_git_repo() -> None:
    """Klasoru gerekirse Git deposuna donusturur."""
    if not os.path.exists(".git"):
        print(f"{Colors.WARNING}Bu klasor henuz bir Git deposu degil. Baslatiliyor...{Colors.ENDC}")
        run_command(["git", "init"], show_output=False)
        run_command(["git", "branch", "-M", "main"], show_output=False)
        print(f"{Colors.OKGREEN}Git deposu olusturuldu.{Colors.ENDC}")


def ensure_remote() -> None:
    """Origin remote yoksa kullanicidan URL alarak ekler."""
    _, remotes = run_command(["git", "remote", "-v"], show_output=False)
    if "origin" not in remotes:
        print(f"{Colors.WARNING}GitHub depo (repository) baglantisi bulunamadi.{Colors.ENDC}")
        repo_url = input(
            f"{Colors.OKBLUE}Lutfen GitHub Depo URL'sini girin\n"
            f"(Orn: https://github.com/niluferbagevi-gif/Sidar): {Colors.ENDC}"
        ).strip()

        if not _is_valid_repo_url(repo_url):
            print(f"{Colors.FAIL}Gecersiz veya bos URL. Islem iptal edildi.{Colors.ENDC}")
            sys.exit(1)

        run_command(["git", "remote", "add", "origin", repo_url], show_output=False)
        print(f"{Colors.OKGREEN}GitHub deposu sisteme baglandi.{Colors.ENDC}")
    else:
        print(f"{Colors.OKGREEN}Mevcut GitHub baglantisi algilandi.{Colors.ENDC}")


def build_commit() -> None:
    """Guvenli dosyalari stage'e alir, silmeleri senkronize eder ve commit olusturur."""
    print(f"\n{Colors.OKBLUE}Dosyalar taraniyor ve paketleniyor...{Colors.ENDC}")
    run_command(["git", "reset"], show_output=False)

    # 1. Guncellenmis / yeni dosyalari ekle
    safe_files, blocked_files = collect_safe_files()
    if safe_files:
        run_command(["git", "add", "--"] + safe_files, show_output=False)

    # 2. Local'de silinmis dosyalari tespit et ve GitHub'dan da kaldir
    deleted_files = collect_deleted_files()
    for f in deleted_files:
        run_command(["git", "add", "-u", "--", f], show_output=False)
    if deleted_files:
        print(
            f"{Colors.OKGREEN}{len(deleted_files)} dosya GitHub'dan kaldirilmak uzere isaretlendi.{Colors.ENDC}"
        )

    # 3. Engellenen yollari raporla
    if blocked_files:
        print(f"{Colors.WARNING}Guvenlik/kararlilik nedeniyle atlanan dosyalar:{Colors.ENDC}")
        for blocked in blocked_files:
            print(f"  - {blocked}")

    # 4. Degisiklik var mi?
    _, status = run_command(["git", "status", "--porcelain"], show_output=False)
    if not status:
        print(
            f"{Colors.WARNING}Yuklenecek yeni bir degisiklik bulunamadi. "
            f"Projeniz zaten guncel!{Colors.ENDC}"
        )
        sys.exit(0)

    # 5. Commit mesaji
    version: str = getattr(cfg, "VERSION", "?")
    staged_area_summary = _summarize_staged_areas()
    default_msg = (
        f"Sidar {version} - Otomatik Dagitim: {staged_area_summary} "
        f"({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    )
    print(f"\n{Colors.WARNING}Degisiklikleri kaydetmek icin bir not yazin.{Colors.ENDC}")
    commit_msg = input(
        f"{Colors.OKBLUE}Commit mesaji (Bos birakırsaniz otomatik tarih atilir): {Colors.ENDC}"
    ).strip() or default_msg

    print(f"\n{Colors.OKBLUE}Degisiklikler kaydediliyor...{Colors.ENDC}")
    commit_success, commit_err = run_command(
        ["git", "commit", "-m", commit_msg], show_output=False
    )
    if not commit_success:
        print(f"{Colors.FAIL}Dosyalar kaydedilirken hata olustu: {commit_err}{Colors.ENDC}")
        sys.exit(1)


# ================================================================
# PUSH ISLEMLERI
# ================================================================
def _try_push(current_branch: str) -> tuple[bool, str]:
    """Tek push denemesi; sonucu doner."""
    return run_command(["git", "push", "-u", "origin", current_branch], show_output=False)


def _handle_conflict(branch: str) -> None:
    """Cakisma durumunda kullaniciya merge secenegi sunar ve push'u yeniden dener."""
    print(f"{Colors.WARNING}GitHub'da bilgisayarinizda olmayan dosyalar var.{Colors.ENDC}")
    confirm = input(
        f"{Colors.OKBLUE}Uzak sunucu ile otomatik birlestirme yapilsin mi? (y/n): {Colors.ENDC}"
    ).strip().lower()

    if confirm != "y":
        print(
            f"{Colors.WARNING}Otomatik birlestirme iptal edildi. "
            "Veri kaybini onlemek icin push durduruldu."
            f"{Colors.ENDC}"
        )
        return

    pull_cmd = [
        "git", "pull", "origin", branch,
        "--rebase",
    ]
    print(
        f"{Colors.OKBLUE}Uzak sunucu ile dosyalar birlestiriliyor "
        f"(rebase modu; cakisma olursa islem durdurulacak)...{Colors.ENDC}"
    )
    pull_success, pull_err = run_command(pull_cmd, show_output=False)

    if not (pull_success or "up to date" in pull_err.lower() or "merge made" in pull_err.lower()):
        print(f"{Colors.FAIL}Birlestirme sirasinda hata olustu. Manuel kontrol gerekli:{Colors.ENDC}")
        print(f"{Colors.WARNING}{' '.join(pull_cmd)}{Colors.ENDC}")
        print(f"Hata Ciktisi:\n{pull_err}")
        return

    print(f"{Colors.OKGREEN}Senkronizasyon basarili. Yeniden yukleniyor...{Colors.ENDC}")
    retry_success, retry_err = push_with_retry(branch)
    if not retry_success:
        _print_push_error(retry_err)


def _print_push_error(err_msg: str) -> None:
    """Push hata mesajini siniflandirarak ekrana basar."""
    if "rule violations" in err_msg:
        print(f"\n{Colors.FAIL}GitHub Guvenlik Duvari (Push Protection) Devreye Girdi!{Colors.ENDC}")
        print(
            f"{Colors.WARNING}Icinde sifre barindiran bir dosya yuklemeye calisiyorsunuz. "
            "Lutfen yukaridaki hata logunu okuyup sifreli dosyayi gizleyin (.gitignore) "
            f"veya linke tiklayip izin verin.{Colors.ENDC}"
        )
    else:
        print(f"{Colors.FAIL}Yukleme sirasinda bilinmeyen bir hata olustu:\n{err_msg}{Colors.ENDC}")


def push_with_retry(branch: str) -> tuple[bool, str]:
    """Push islemini exponential backoff ile yeniden dener (CLAUDE.md gereksinimleri).

    Yeniden deneme araliklarI: 2s, 4s, 8s, 16s
    """
    for attempt in range(_PUSH_MAX_RETRIES + 1):
        success, err_msg = _try_push(branch)
        if success:
            return True, ""

        # Cakisma/rejected hatalar ag sorunu degil; yeniden deneme anlamsiz
        if any(kw in err_msg for kw in ("rejected", "fetch first", "non-fast-forward", "rule violations")):
            return False, err_msg

        if attempt < _PUSH_MAX_RETRIES:
            wait = _PUSH_BACKOFF_BASE ** (attempt + 1)
            print(
                f"{Colors.WARNING}Push basarisiz (deneme {attempt + 1}/{_PUSH_MAX_RETRIES}). "
                f"{wait}s sonra yeniden deneniyor...{Colors.ENDC}"
            )
            time.sleep(wait)

    return False, err_msg  # type: ignore[return-value]


# ================================================================
# ANA PROGRAM
# ================================================================
def main() -> None:
    version: str = getattr(cfg, "VERSION", "2.1")
    print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}")
    print(f"{Colors.BOLD} Sidar - GitHub Otomatik Yukleme & Yedekleme Araci (v{version}) {Colors.ENDC}")
    print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}\n")

    # 0. Token kontrolu
    if not cfg.GITHUB_TOKEN:
        print(
            f"{Colors.FAIL}GITHUB_TOKEN config.py/.env uzerinden bulunamadi. "
            f"Islem guvenlik nedeniyle durduruldu.{Colors.ENDC}"
        )
        sys.exit(1)

    # 1. Git kurulu mu?
    success, _ = run_command(["git", "--version"], show_output=False)
    if not success:
        print(
            f"{Colors.FAIL}Sistemde Git kurulu degil. "
            f"Lutfen terminalden 'sudo apt install git' yazarak kurun.{Colors.ENDC}"
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
    print(f"\n{Colors.HEADER}GitHub'a yukleniyor (Hedef: {current_branch}). Lutfen bekleyin...{Colors.ENDC}")
    push_success, err_msg = push_with_retry(current_branch)

    if push_success:
        print(f"\n{Colors.HEADER}{'='*65}{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.OKGREEN}TEBRIKLER! Proje basariyla GitHub'a yuklendi!{Colors.ENDC}")
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