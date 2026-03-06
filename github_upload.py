"""
Sidar github_upload.py - Otomatik GitHub Yükleme Aracı
Sürüm: 2.7.0
Açıklama: Mevcut projeyi güvenli şekilde GitHub'a yedekler/yükler.
Kimlik, çakışma, hassas dosya engelleme ve UTF-8 dosya güvenliği kontrolleri içerir.
"""

import os
import subprocess
import sys
from datetime import datetime

from config import Config


cfg = Config()
GITHUB_TOKEN = cfg.GITHUB_TOKEN

# Script seviyesinde sert engelleme: Bu yollar asla stage edilmez.
FORBIDDEN_PATHS = [
    ".env",
    "sessions/",
    "chroma_db/",
    "__pycache__/",
    ".git/",
    "logs/",
    "models/",
]


# ═══════════════════════════════════════════════════════════════
# RENK KODLARI
# ═══════════════════════════════════════════════════════════════
class Colors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"


# ═══════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════
def run_command(args, show_output=True):
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
    except subprocess.CalledProcessError as error:
        err_msg = error.stderr.strip()
        if error.stdout and error.stdout.strip():
            err_msg += "\n" + error.stdout.strip()

        if show_output and err_msg:
            print(f"{Colors.WARNING}Git çıktısı: {err_msg}{Colors.ENDC}")
        return False, err_msg


def _is_valid_repo_url(url: str) -> bool:
    """Temel GitHub repo URL doğrulaması."""
    if not url:
        return False
    normalized = url.strip()
    return normalized.startswith("https://github.com/") or normalized.startswith("git@github.com:")


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def is_forbidden_path(path: str) -> bool:
    """Hard blacklist kontrolü."""
    normalized = _normalize_path(path)

    for forbidden in FORBIDDEN_PATHS:
        marker = _normalize_path(forbidden)
        marker = marker.rstrip("/")

        if normalized == marker:
            return True
        if normalized.startswith(f"{marker}/"):
            return True
        if marker and marker in normalized and marker in ("__pycache__",):
            return True

    return False


def get_file_content(path: str):
    """UTF-8 metin dosyası içeriğini döner; binary/okuma hatasında None döner."""
    if is_forbidden_path(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read()
    except (UnicodeDecodeError, OSError):
        return None


def sanitize_staging_area():
    """Stage edilen dosyalarda hassas yol ve binary/UTF-8 kontrolü yapar."""
    success, staged_output = run_command(["git", "diff", "--cached", "--name-only"], show_output=False)
    if not success:
        return

    skipped = []
    for raw_path in staged_output.splitlines():
        path = raw_path.strip()
        if not path:
            continue

        if is_forbidden_path(path):
            run_command(["git", "restore", "--staged", "--", path], show_output=False)
            skipped.append((path, "forbidden"))
            continue

        # Silinmiş dosyalarda içerik okunamaz; sadece mevcut dosyayı kontrol ederiz.
        if os.path.isfile(path):
            content = get_file_content(path)
            if content is None:
                run_command(["git", "restore", "--staged", "--", path], show_output=False)
                skipped.append((path, "binary_or_encoding"))

    if skipped:
        print(f"{Colors.WARNING}⚠️ Güvenlik nedeniyle stage dışı bırakılan dosyalar:{Colors.ENDC}")
        for path, reason in skipped:
            print(f"  - {path} ({reason})")


def build_push_target(current_branch: str) -> str:
    """HTTPS origin varsa token ile anlık push URL'i üretir."""
    success, remote_url = run_command(["git", "remote", "get-url", "origin"], show_output=False)
    if not success or not remote_url:
        return "origin"

    remote_url = remote_url.strip()
    if remote_url.startswith("https://github.com/"):
        if not GITHUB_TOKEN:
            print(f"{Colors.FAIL}❌ config.py/.env üzerinden GITHUB_TOKEN bulunamadı. Push işlemi durduruldu.{Colors.ENDC}")
            sys.exit(1)
        repo_path = remote_url.replace("https://github.com/", "", 1)
        return f"https://{GITHUB_TOKEN}@github.com/{repo_path}"

    return "origin"


# ═══════════════════════════════════════════════════════════════
# ANA PROGRAM
# ═══════════════════════════════════════════════════════════════
def main():
    print(f"{Colors.HEADER}{'=' * 65}{Colors.ENDC}")
    print(
        f"{Colors.BOLD} 🐙 Sidar - GitHub Otomatik Yükleme & Yedekleme Aracı "
        f"(v{cfg.VERSION}) {Colors.ENDC}"
    )
    print(f"{Colors.HEADER}{'=' * 65}{Colors.ENDC}\n")

    if not GITHUB_TOKEN:
        print(f"{Colors.FAIL}❌ GITHUB_TOKEN boş. Lütfen .env dosyanızı güncelleyin.{Colors.ENDC}")
        sys.exit(1)

    # 1. Git kurulu mu?
    success, _ = run_command(["git", "--version"], show_output=False)
    if not success:
        print(
            f"{Colors.FAIL}Sistemde Git kurulu değil. "
            "Lütfen terminalden 'sudo apt install git' yazarak kurun."
            f"{Colors.ENDC}"
        )
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
            f"(Örn: https://github.com/niluferbagevi-gif/sidar_project): {Colors.ENDC}"
        ).strip()

        if not _is_valid_repo_url(repo_url):
            print(f"{Colors.FAIL}Geçersiz veya boş URL. İşlem iptal edildi.{Colors.ENDC}")
            sys.exit(1)

        run_command(["git", "remote", "add", "origin", repo_url], show_output=False)
        print(f"{Colors.OKGREEN}✅ GitHub deposu sisteme bağlandı.{Colors.ENDC}")
    else:
        print(f"{Colors.OKGREEN}✅ Mevcut GitHub bağlantısı algılandı.{Colors.ENDC}")

    # 4. Değişiklikleri ekle + sert güvenlik filtreleri uygula
    print(f"\n{Colors.OKBLUE}📦 Dosyalar taranıyor ve güvenli şekilde paketleniyor...{Colors.ENDC}")
    run_command(["git", "add", "-A"], show_output=False)
    sanitize_staging_area()

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
        f"{Colors.OKBLUE}Commit mesajı (Boş bırakırsanız sürüm-tarih mesajı atanır): {Colors.ENDC}"
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
    push_target = build_push_target(current_branch)
    print(f"\n{Colors.HEADER}🚀 GitHub'a yükleniyor (Hedef: {current_branch}). Lütfen bekleyin...{Colors.ENDC}")

    push_success, err_msg = run_command(["git", "push", "-u", push_target, current_branch], show_output=False)

    if push_success:
        print(f"\n{Colors.HEADER}{'=' * 65}{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.OKGREEN}🎉 TEBRİKLER! Proje başarıyla GitHub'a yüklendi!{Colors.ENDC}")
        print(f"{Colors.HEADER}{'=' * 65}{Colors.ENDC}")
    else:
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
                    "git",
                    "pull",
                    "origin",
                    current_branch,
                    "--rebase=false",
                    "--allow-unrelated-histories",
                    "--no-edit",
                    "-X",
                    "ours",
                ]
                pull_success, pull_err = run_command(pull_cmd, show_output=False)

                if pull_success or "up to date" in pull_err.lower() or "merge made" in pull_err.lower():
                    print(f"{Colors.OKGREEN}✅ Senkronizasyon başarılı. Yeniden yükleniyor...{Colors.ENDC}")

                    retry_success, retry_err = run_command(
                        ["git", "push", "-u", push_target, current_branch],
                        show_output=False,
                    )

                    if retry_success:
                        print(f"\n{Colors.HEADER}{'=' * 65}{Colors.ENDC}")
                        print(
                            f"{Colors.BOLD}{Colors.OKGREEN}🎉 TEBRİKLER! "
                            "Çakışma otomatik çözüldü ve proje başarıyla GitHub'a yüklendi!"
                            f"{Colors.ENDC}"
                        )
                        print(f"{Colors.HEADER}{'=' * 65}{Colors.ENDC}")
                    else:
                        if "rule violations" in retry_err:
                            print(
                                f"\n{Colors.FAIL}❌ GitHub Güvenlik Duvarı "
                                "(Push Protection) Devreye Girdi!"
                                f"{Colors.ENDC}"
                            )
                            print(
                                f"{Colors.WARNING}İçinde şifre barındıran bir dosya yüklemeye çalışıyorsunuz. "
                                "Lütfen yukarıdaki hata logunu okuyup şifreli dosyayı gizleyin (.gitignore) "
                                "veya linke tıklayıp izin verin."
                                f"{Colors.ENDC}"
                            )
                        else:
                            print(f"{Colors.FAIL}❌ Yeniden yükleme başarısız oldu:\n{retry_err}{Colors.ENDC}")
                else:
                    print(
                        f"{Colors.FAIL}❌ Birleştirme sırasında hata oluştu. "
                        "Lütfen komutu terminale manuel yazıp hatayı okuyun:"
                        f"{Colors.ENDC}"
                    )
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


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.FAIL}İşlem kullanıcı tarafından iptal edildi.{Colors.ENDC}")
        sys.exit(0)