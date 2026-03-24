"""
Sidar  github_upload.py - Otomatik GitHub Yükleme Aracı
Sürüm: 1.9
Açıklama: Mevcut projeyi kolayca GitHub'a yedekler/yükler.
Kimlik, çakışma ve otomatik birleştirme (Auto-Merge) kontrolleri içerir.
"""
import os
import subprocess
import sys
from fnmatch import fnmatch
from datetime import datetime
from typing import List, Sequence, Tuple

from config import Config


cfg = Config()

# ASLA YÜKLENMEMESİ GEREKENLER (kritik güvenlik katmanı)
FORBIDDEN_PATHS = [
    ".env",
    ".env.*",
    "sessions/",
    "secrets/",
    "credentials/",
    "chroma_db/",
    "__pycache__/",
    ".git/",
    "logs/",
    "data/",
    "temp/",
    "tmp/",
    "models/",
]


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
def run_command(args: Sequence[str], show_output: bool = True) -> Tuple[bool, str]:
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
    except FileNotFoundError:
        err_msg = f"Komut bulunamadı: {args[0] if args else 'bilinmiyor'}"
        if show_output:
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
    for forbidden in FORBIDDEN_PATHS:
        rule = _normalize_path(forbidden)

        if any(ch in rule for ch in "*?[]"):
            if fnmatch(normalized, rule):
                return True
            continue

        if forbidden.endswith("/"):
            dir_rule = rule.rstrip("/")
            if normalized == dir_rule or normalized.startswith(f"{dir_rule}/"):
                return True
            continue

        if normalized == rule:
            return True

    return False


def get_file_content(path: str) -> str | None:
    """UTF-8 güvenli okuma; binary/hatalı dosyaları atlar."""
    if is_forbidden_path(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read()
    except (UnicodeDecodeError, OSError):
        return None


def collect_safe_files() -> Tuple[List[str], List[str]]:
    """Yalnızca güvenli ve UTF-8 okunabilir dosyaları stage listesine alır."""
    success, output = run_command(["git", "ls-files", "-co", "--exclude-standard"], show_output=False)
    if not success:
        return [], []

    safe_files = []
    blocked_files = []

    for line in output.splitlines():
        file_path = line.strip()
        if not file_path:
            continue
        if os.path.isdir(file_path):
            continue

        if is_forbidden_path(file_path):
            blocked_files.append(file_path)
            continue

        if get_file_content(file_path) is None:
            blocked_files.append(file_path)
            continue

        safe_files.append(file_path)

    return safe_files, blocked_files


# ═══════════════════════════════════════════════════════════════
# ANA PROGRAM
# ═══════════════════════════════════════════════════════════════
def main() -> None:
    print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}")
    print(f"{Colors.BOLD} 🐙 Sidar - GitHub Otomatik Yükleme & Yedekleme Aracı (v{cfg.VERSION}) {Colors.ENDC}")
    print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}\n")

    # 0. Merkezi yapılandırmadan token kontrolü
    if not cfg.GITHUB_TOKEN:
        print(f"{Colors.FAIL}GITHUB_TOKEN config.py/.env üzerinden bulunamadı. İşlem güvenlik nedeniyle durduruldu.{Colors.ENDC}")
        sys.exit(1)

    # 1. Git kurulu mu?
    success, _ = run_command(["git", "--version"], show_output=False)
    if not success:
        print(f"{Colors.FAIL}Sistemde Git kurulu değil. Lütfen terminalden 'sudo apt install git' yazarak kurun.{Colors.ENDC}")
        sys.exit(1)

    # 1.5 Git Kimlik (Identity) Kontrolü
    _, name_out = run_command(["git", "config", "user.name"], show_output=False)
    if not name_out:
        print(f"{Colors.WARNING}⚠️ Git kimliğiniz tanımlanmamış. Lütfen GitHub bilgilerinizi girin:{Colors.ENDC}")
        git_name = input("Adınız / GitHub Kullanıcı Adınız: ").strip()
        git_email = input("GitHub E-Posta Adresiniz: ").strip()
        run_command(["git", "config", "--global", "user.name", git_name], show_output=False)
        run_command(["git", "config", "--global", "user.email", git_email], show_output=False)
        print(f"{Colors.OKGREEN}✅ Git kimliğiniz başarıyla kaydedildi.{Colors.ENDC}\n")

    # 2. Git reposu mu?
    if not os.path.exists(".git"):
        print(f"{Colors.WARNING}Bu klasör henüz bir Git deposu değil. Başlatılıyor...{Colors.ENDC}")
        run_command(["git", "init"], show_output=False)
        run_command(["git", "branch", "-M", "main"], show_output=False)
        print(f"{Colors.OKGREEN}✅ Git deposu oluşturuldu.{Colors.ENDC}")

    # 3. Remote (Uzak Sunucu) kontrolü
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

    # 4. Değişiklikleri güvenli şekilde ekle (hard blacklist + UTF-8 kontrol)
    print(f"\n{Colors.OKBLUE}📦 Dosyalar taranıyor ve paketleniyor...{Colors.ENDC}")
    run_command(["git", "reset"], show_output=False)
    safe_files, blocked_files = collect_safe_files()

    if safe_files:
        run_command(["git", "add", "--"] + safe_files, show_output=False)

    if blocked_files:
        print(f"{Colors.WARNING}⛔ Güvenlik/kararlılık nedeniyle atlanan dosyalar:{Colors.ENDC}")
        for blocked in blocked_files:
            print(f"  - {blocked}")

    # 5. Durum Kontrolü (Değişen dosya var mı?)
    _, status = run_command(["git", "status", "--porcelain"], show_output=False)
    if not status:
        print(f"{Colors.WARNING}🤷 Yüklenecek yeni bir değişiklik bulunamadı. Projeniz zaten güncel!{Colors.ENDC}")
        sys.exit(0)

    # 6. Commit (Kaydetme) Mesajı
    default_msg = (
        f"🚀 Sidar {cfg.VERSION} - Otomatik Dağıtım "
        f"({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    )
    print(f"\n{Colors.WARNING}Değişiklikleri kaydetmek için bir not yazın.{Colors.ENDC}")
    commit_msg = input(
        f"{Colors.OKBLUE}Commit mesajı (Boş bırakırsanız otomatik tarih atılır): {Colors.ENDC}"
    ).strip()

    if not commit_msg:
        commit_msg = default_msg

    print(f"\n{Colors.OKBLUE}💾 Değişiklikler kaydediliyor...{Colors.ENDC}")
    commit_success, commit_err = run_command(["git", "commit", "-m", commit_msg], show_output=False)

    if not commit_success:
        print(f"{Colors.FAIL}❌ Dosyalar kaydedilirken hata oluştu: {commit_err}{Colors.ENDC}")
        sys.exit(1)

    # 7. Branch (Dal) belirle
    _, branch = run_command(["git", "branch", "--show-current"], show_output=False)
    current_branch = branch if branch else "main"

    # 8. GitHub'a Gönder (Push)
    print(f"\n{Colors.HEADER}🚀 GitHub'a yükleniyor (Hedef: {current_branch}). Lütfen bekleyin...{Colors.ENDC}")

    # Push işlemini dene
    push_success, err_msg = run_command(["git", "push", "-u", "origin", current_branch], show_output=False)

    if push_success:
        print(f"\n{Colors.HEADER}{'='*65}{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.OKGREEN}🎉 TEBRİKLER! Proje başarıyla GitHub'a yüklendi!{Colors.ENDC}")
        print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}")
    else:
        # Çakışma varsa (fetch first / rejected)
        if "rejected" in err_msg or "fetch first" in err_msg or "non-fast-forward" in err_msg:
            print(f"{Colors.WARNING}⚠️ GitHub'da bilgisayarınızda olmayan dosyalar var.{Colors.ENDC}")
            confirm = input(
                f"{Colors.OKBLUE}Uzak sunucu ile otomatik birleştirme yapılsın mı? (y/n): {Colors.ENDC}"
            ).strip().lower()

            if confirm == "y":
                print(
                    f"{Colors.OKBLUE}🔄 Uzak sunucu ile dosyalar birleştiriliyor "
                    f"(Çakışmalarda yerel dosyalar korunacak)...{Colors.ENDC}"
                )
                pull_cmd = [
                    "git", "pull", "origin", current_branch,
                    "--rebase=false", "--allow-unrelated-histories", "--no-edit", "-X", "ours",
                ]
                pull_success, pull_err = run_command(pull_cmd, show_output=False)

                if pull_success or "up to date" in pull_err.lower() or "merge made" in pull_err.lower():
                    print(f"{Colors.OKGREEN}✅ Senkronizasyon başarılı. Yeniden yükleniyor...{Colors.ENDC}")

                    retry_success, retry_err = run_command(["git", "push", "-u", "origin", current_branch], show_output=False)

                    if retry_success:
                        print(f"\n{Colors.HEADER}{'='*65}{Colors.ENDC}")
                        print(f"{Colors.BOLD}{Colors.OKGREEN}🎉 TEBRİKLER! Çakışma otomatik çözüldü ve proje başarıyla GitHub'a yüklendi!{Colors.ENDC}")
                        print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}")
                    else:
                        if "rule violations" in retry_err:
                            print(f"\n{Colors.FAIL}❌ GitHub Güvenlik Duvarı (Push Protection) Devreye Girdi!{Colors.ENDC}")
                            print(f"{Colors.WARNING}İçinde şifre barındıran bir dosya yüklemeye çalışıyorsunuz. Lütfen yukarıdaki hata logunu okuyup şifreli dosyayı gizleyin (.gitignore) veya linke tıklayıp izin verin.{Colors.ENDC}")
                        else:
                            print(f"{Colors.FAIL}❌ Yeniden yükleme başarısız oldu:\n{retry_err}{Colors.ENDC}")
                else:
                    print(f"{Colors.FAIL}❌ Birleştirme sırasında hata oluştu. Lütfen komutu terminale manuel yazıp hatayı okuyun:{Colors.ENDC}")
                    print(f"{Colors.WARNING}{' '.join(pull_cmd)}{Colors.ENDC}")
                    print(f"Hata Çıktısı:\n{pull_err}")
            else:
                print(
                    f"{Colors.WARNING}⏹️ Otomatik birleştirme iptal edildi. "
                    "Veri kaybını önlemek için push durduruldu."
                    f"{Colors.ENDC}"
                )
        else:
            print(f"{Colors.FAIL}❌ Yükleme sırasında bilinmeyen bir hata oluştu:\n{err_msg}{Colors.ENDC}")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.FAIL}İşlem kullanıcı tarafından iptal edildi.{Colors.ENDC}")
        sys.exit(0)
