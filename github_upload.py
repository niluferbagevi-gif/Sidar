"""
Sidar  github_upload.py - Otomatik GitHub Yükleme Aracı
Sürüm: 2.1
Açıklama: Mevcut projeyi kolayca GitHub'a yedekler/yükler.
Dış dalları çekme ve hatalı işlemleri Geri Alma (Rollback) özelliklerini içerir.
Kullanım:
  python github_upload.py                 -> Normal yükleme
  python github_upload.py <branch_adi>    -> Dış dalı çekip birleştirme
  python github_upload.py -<sayi>         -> Son <sayi> işlemi geri alma (Örn: -3)
"""

import os
import re
import subprocess
import sys
from datetime import datetime
from typing import Sequence

from config import Config

cfg = Config()

# ASLA YÜKLENMEMESİ GEREKENLER (kritik güvenlik katmanı)
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
def run_command(args: Sequence[str], show_output: bool = True) -> tuple[bool, str]:
    """Komutu shell=False ile güvenli şekilde çalıştırır."""
    try:
        result = subprocess.run(
            args,
            shell=False,
            check=True,
            capture_output=True,
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
            print(f"{Colors.WARNING}Git ciktisi: {err_msg}{Colors.ENDC}")
        return False, err_msg


def _is_valid_repo_url(url: str) -> bool:
    """Temel GitHub repo URL doğrulaması."""
    if not url:
        return False
    normalized = url.strip()
    return normalized.startswith("https://github.com/") or normalized.startswith("git@github.com:")


def _normalize_path(path: str) -> str:
    """Yol formatını güvenlik kontrolleri için normalize eder."""
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    elif normalized.startswith("/"):
        normalized = normalized[1:]
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    normalized = normalized.lstrip("/")
    return normalized


def resolve_github_token() -> str:
    """
    GITHUB_TOKEN değerini farklı kaynaklardan güvenli biçimde çözer.

    Not:
    - Bazı ortamlarda `GITHUB_TOKEN` değişkeni process içinde boş string olarak
      tanımlı olabilir ve bu durum `.env` içindeki gerçek değeri gölgeleyebilir.
    - Bu nedenle alternatif anahtar adlarını da (GH_TOKEN/GITHUB_PAT) deneriz.
    """
    candidates = [
        getattr(cfg, "GITHUB_TOKEN", ""),
        os.getenv("GITHUB_TOKEN", ""),
        os.getenv("GH_TOKEN", ""),
        os.getenv("GITHUB_PAT", ""),
    ]

    for value in candidates:
        token = str(value or "").strip().strip('"').strip("'")
        if token:
            return token
    return ""


def is_forbidden_path(path: str) -> bool:
    """Hard blacklist: .gitignore'dan bağımsız kesin engel."""
    normalized = _normalize_path(path)

    # .env.example dosyasının güvenlik filtresine takılmasını önleyen istisna
    if os.path.basename(normalized) == ".env.example":
        return False

    return any(
        normalized == forbidden.rstrip("/") or normalized.startswith(forbidden)
        for forbidden in FORBIDDEN_PATHS
    )


def get_file_content(path: str) -> str | None:
    """UTF-8 güvenli okuma; binary/hatalı dosyaları atlar."""
    if is_forbidden_path(path):
        return None

    try:
        with open(path, encoding="utf-8") as file:
            return file.read()
    except (UnicodeDecodeError, OSError):
        return None


def get_deleted_files() -> list[str]:
    """Sistemden silinmiş ama Git'in geçmişte takip ettiği dosyaları bulur."""
    success, output = run_command(["git", "ls-files", "-d"], show_output=False)
    if not success or not output:
        return []

    return [line.strip() for line in output.splitlines() if line.strip()]


def collect_safe_files(deleted_files_list: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Yalnızca güvenli dosyaları stage listesine alır."""
    if deleted_files_list is None:
        deleted_files_list = []

    success, output = run_command(
        ["git", "ls-files", "-co", "--exclude-standard"], show_output=False
    )
    if not success:
        return [], []

    safe_files = []
    blocked_files = []

    TEXT_EXTENSIONS = {
        ".py",
        ".md",
        ".txt",
        ".json",
        ".yml",
        ".yaml",
        ".html",
        ".css",
        ".js",
        ".sh",
        ".csv",
        ".example",
    }

    for line in output.splitlines():
        file_path = line.strip()
        if not file_path:
            continue
        if os.path.isdir(file_path):
            continue
        if file_path in deleted_files_list:
            continue

        if is_forbidden_path(file_path):
            blocked_files.append(file_path)
            continue

        _, ext = os.path.splitext(file_path)
        if ext.lower() in TEXT_EXTENSIONS:
            if get_file_content(file_path) is None:
                blocked_files.append(file_path)
                continue

        safe_files.append(file_path)

    return safe_files, blocked_files


def stage_files(file_paths: list[str]) -> tuple[bool, str]:
    """Dosyaları git'e literal pathspec ile güvenli biçimde ekler."""
    if not file_paths:
        return True, ""

    literal_paths = [f":(literal){path}" for path in file_paths]
    return run_command(["git", "add", "--"] + literal_paths, show_output=False)


# ═══════════════════════════════════════════════════════════════
# ANA PROGRAM
# ═══════════════════════════════════════════════════════════════
def main() -> None:
    target_branch = None
    rollback_steps = 0

    # Argüman kontrolü: Dal adı mı yoksa -X (Geri alma) komutu mu?
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        # Eğer argüman -1, -5, -10 vb. formattaysa
        if re.match(r"^-\d+$", arg):
            rollback_steps = int(arg[1:])
            if rollback_steps < 1 or rollback_steps > 10:
                print(
                    f"{Colors.FAIL}❌ Hata: Sadece 1 ile 10 işlem arasına kadar geri alabilirsiniz (Örn: -3).{Colors.ENDC}"
                )
                sys.exit(1)
        else:
            target_branch = arg

    print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}")
    print(
        f"{Colors.BOLD} 🐙 Sidar - GitHub Otomatik Yükleme & Yedekleme Aracı (v2.1) {Colors.ENDC}"
    )
    print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}\n")

    github_token = resolve_github_token()
    if not github_token:
        print(
            f"{Colors.FAIL}GITHUB_TOKEN bulunamadı. "
            f"Lütfen .env içinde GITHUB_TOKEN (veya GH_TOKEN/GITHUB_PAT) tanımlayın.{Colors.ENDC}"
        )
        sys.exit(1)

    success, _ = run_command(["git", "--version"], show_output=False)
    if not success:
        print(
            f"{Colors.FAIL}Sistemde Git kurulu değil. Lütfen terminalden 'sudo apt install git' yazarak kurun.{Colors.ENDC}"
        )
        sys.exit(1)

    _, name_out = run_command(["git", "config", "user.name"], show_output=False)
    if not name_out:
        print(
            f"{Colors.WARNING}⚠️ Git kimliğiniz tanımlanmamış. Lütfen GitHub bilgilerinizi girin:{Colors.ENDC}"
        )
        git_name = input("Adınız / GitHub Kullanıcı Adınız: ").strip()
        git_email = input("GitHub E-Posta Adresiniz: ").strip()
        run_command(["git", "config", "--global", "user.name", git_name], show_output=False)
        run_command(["git", "config", "--global", "user.email", git_email], show_output=False)
        print(f"{Colors.OKGREEN}✅ Git kimliğiniz başarıyla kaydedildi.{Colors.ENDC}\n")

    if not os.path.exists(".git"):
        print(f"{Colors.WARNING}Bu klasör henüz bir Git deposu değil. Başlatılıyor...{Colors.ENDC}")
        run_command(["git", "init"], show_output=False)
        run_command(["git", "branch", "-M", "main"], show_output=False)
        print(f"{Colors.OKGREEN}✅ Git deposu oluşturuldu.{Colors.ENDC}")

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

    _, branch_out = run_command(["git", "branch", "--show-current"], show_output=False)
    current_branch = branch_out.strip() if branch_out else "main"

    # Çalışma akışını her zaman main dalında sürdür.
    if current_branch != "main":
        print(f"\n{Colors.WARNING}⚠️ Şu an '{current_branch}' dalındasınız.{Colors.ENDC}")
        print(
            f"{Colors.OKBLUE}🔄 İşlemlerin 'main' dalında yapılması için geçiş hazırlanıyor...{Colors.ENDC}"
        )

        _, stash_status = run_command(["git", "status", "--porcelain"], show_output=False)
        stash_created = False
        if stash_status.strip():
            stash_success, stash_err = run_command(
                ["git", "stash", "push", "-u", "-m", "github_upload:auto-switch-to-main"],
                show_output=False,
            )
            if not stash_success:
                print(
                    f"{Colors.FAIL}❌ Değişiklikler güvenli olarak stash'e alınamadı:\n{stash_err}{Colors.ENDC}"
                )
                sys.exit(1)
            stash_created = True

        checkout_success, checkout_err = run_command(["git", "checkout", "main"], show_output=False)
        if not checkout_success:
            print(
                f"{Colors.FAIL}❌ 'main' dalına geçiş başarısız oldu:\n{checkout_err}{Colors.ENDC}"
            )
            if stash_created:
                run_command(["git", "stash", "pop"], show_output=False)
            print(
                f"{Colors.WARNING}Lütfen terminalden 'git checkout main' yazarak çakışmaları kontrol edin.{Colors.ENDC}"
            )
            sys.exit(1)

        current_branch = "main"

        if stash_created:
            pop_success, pop_err = run_command(["git", "stash", "pop"], show_output=False)
            if not pop_success:
                print(
                    f"{Colors.FAIL}❌ Stash geri yüklenirken çakışma oluştu:\n{pop_err}{Colors.ENDC}"
                )
                print(
                    f"{Colors.WARNING}Çakışmaları çözüp commit aldıktan sonra aracı tekrar çalıştırabilirsiniz.{Colors.ENDC}"
                )
                sys.exit(1)

        print(f"{Colors.OKGREEN}✅ 'main' dalına başarıyla geçildi.{Colors.ENDC}\n")

    # ═══════════════════════════════════════════════════════════════
    # GERİ ALMA (ROLLBACK) İŞLEMİ
    # ═══════════════════════════════════════════════════════════════
    if rollback_steps > 0:
        print(
            f"\n{Colors.FAIL}{Colors.BOLD}🚨 KRİTİK UYARI: GERİ ALMA İŞLEMİ BAŞLATILDI 🚨{Colors.ENDC}"
        )
        print(
            f"{Colors.WARNING}Son {rollback_steps} commit ve yerel bilgisayarınızdaki henüz kaydedilmemiş tüm değişiklikler KALICI OLARAK SİLİNECEK.{Colors.ENDC}"
        )
        print(
            f"{Colors.WARNING}Projeniz tam {rollback_steps} adım önceki haline hem yerelde hem de GitHub'da (Force Push) zorla eşitlenecek.{Colors.ENDC}"
        )

        confirm = (
            input(f"\n{Colors.OKBLUE}Bu işlemi onaylıyor musunuz? (evet / hayır): {Colors.ENDC}")
            .strip()
            .lower()
        )

        if confirm in ["e", "evet", "y", "yes"]:
            print(
                f"\n{Colors.WARNING}⏳ Proje {rollback_steps} adım geriye sarılıyor...{Colors.ENDC}"
            )

            # 1. Yerel dosyaları sert şekilde geri al
            reset_success, reset_err = run_command(
                ["git", "reset", "--hard", f"HEAD~{rollback_steps}"], show_output=False
            )
            if not reset_success:
                print(f"{Colors.FAIL}❌ Geri alma başarısız oldu:\n{reset_err}{Colors.ENDC}")
                sys.exit(1)

            # 2. GitHub'ı zorla (force) güncelle
            print(f"{Colors.WARNING}⏳ GitHub deposu zorla (force) güncelleniyor...{Colors.ENDC}")
            push_success, push_err = run_command(
                ["git", "push", "--force", "origin", current_branch], show_output=False
            )

            if push_success:
                print(f"\n{Colors.HEADER}{'='*65}{Colors.ENDC}")
                print(
                    f"{Colors.BOLD}{Colors.OKGREEN}⏪ BAŞARILI! Proje başarıyla {rollback_steps} adım önceki haline döndürüldü.{Colors.ENDC}"
                )
                print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}")
            else:
                print(
                    f"{Colors.FAIL}❌ GitHub'a zorla yazma (Force Push) başarısız oldu:\n{push_err}{Colors.ENDC}"
                )
                print(
                    f"{Colors.WARNING}Not: GitHub deponuzda 'Branch Protection' kuralları force push'u engelliyor olabilir.{Colors.ENDC}"
                )

            sys.exit(0)  # Geri alma bitti, programdan çık
        else:
            print(
                f"\n{Colors.OKGREEN}🛡️ Geri alma işlemi iptal edildi. Kodlarınız güvende.{Colors.ENDC}"
            )
            sys.exit(0)

    # ═══════════════════════════════════════════════════════════════
    # DAL ÇEKME (PULL/MERGE) İŞLEMİ
    # ═══════════════════════════════════════════════════════════════
    if target_branch:
        print(f"\n{Colors.HEADER}📥 Dış dal (branch) algılandı: '{target_branch}'{Colors.ENDC}")
        print(
            f"{Colors.OKBLUE}🔄 '{target_branch}' GitHub'dan çekilip '{current_branch}' ile birleştiriliyor...{Colors.ENDC}"
        )

        pull_cmd = [
            "git",
            "pull",
            "origin",
            target_branch,
            "--no-rebase",
            "--allow-unrelated-histories",
            "--no-edit",
        ]
        pull_success, pull_err = run_command(pull_cmd, show_output=False)

        if pull_success or "up to date" in pull_err.lower() or "merge made" in pull_err.lower():
            print(
                f"{Colors.OKGREEN}✅ '{target_branch}' dalı başarıyla çekildi ve birleştirildi.{Colors.ENDC}"
            )
        else:
            print(
                f"{Colors.FAIL}❌ Birleştirme sırasında hata veya çakışma (conflict) oluştu:\n{pull_err}{Colors.ENDC}"
            )
            print(
                f"{Colors.WARNING}Lütfen çakışan dosyaları manuel düzenleyip aracı argümansız tekrar çalıştırın.{Colors.ENDC}"
            )
            sys.exit(1)

    # ═══════════════════════════════════════════════════════════════
    # STANDART YÜKLEME İŞLEMİ
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{Colors.OKBLUE}📦 Yerel dosyalar taranıyor ve paketleniyor...{Colors.ENDC}")
    run_command(["git", "reset"], show_output=False)

    # 1. Silinmiş dosyaları kontrol et ve onaya sun
    deleted_files = get_deleted_files()
    if deleted_files:
        print(
            f"\n{Colors.WARNING}🗑️ Aşağıdaki dosyaların yerel sistemden silindiği tespit edildi:{Colors.ENDC}"
        )
        for deleted_file in deleted_files:
            print(f"  - {deleted_file}")

        confirm_del = (
            input(
                f"{Colors.OKBLUE}Bu dosyaları kalıcı olarak silip GitHub'dan da kaldırmak istiyor musunuz? "
                f"(evet / hayır): {Colors.ENDC}"
            )
            .strip()
            .lower()
        )
        if confirm_del in ["e", "evet", "y", "yes"]:
            run_command(["git", "rm", "--ignore-unmatch"] + deleted_files, show_output=False)
            print(
                f"{Colors.OKGREEN}✅ Silinen dosyalar onaylandı ve Git'e bildirildi.{Colors.ENDC}"
            )
        else:
            print(
                f"{Colors.WARNING}⚠️ Silme işlemi onaylanmadı. "
                f"Bu dosyaların silinme işlemi GitHub'a gönderilmeyecek.{Colors.ENDC}"
            )

    # 2. Değiştirilmiş/Yeni dosyaları topla (silinen dosyaları atlayarak)
    safe_files, blocked_files = collect_safe_files(deleted_files_list=deleted_files)

    if safe_files:
        add_success, add_err = stage_files(safe_files)
        if not add_success:
            print(f"{Colors.FAIL}❌ Dosyalar eklenirken hata oluştu: {add_err}{Colors.ENDC}")
            sys.exit(1)

    if blocked_files:
        print(f"{Colors.WARNING}⛔ Güvenlik/kararlılık nedeniyle atlanan dosyalar:{Colors.ENDC}")
        for blocked in blocked_files:
            print(f"  - {blocked}")

    _, staged_status = run_command(["git", "diff", "--cached", "--name-status"], show_output=False)

    if staged_status.strip():
        version_str = getattr(cfg, "VERSION", "2.1")
        default_msg = (
            f"🚀 Sidar {version_str} - Otomatik Dağıtım "
            f"({datetime.now().strftime('%Y-%m-%d %H:%M')})"
        )
        if target_branch:
            default_msg += f" (Merged branch: {target_branch})"

        print(f"\n{Colors.WARNING}Değişiklikleri kaydetmek için bir not yazın.{Colors.ENDC}")
        commit_msg = input(
            f"{Colors.OKBLUE}Commit mesajı (Boş bırakırsanız otomatik tarih atılır): {Colors.ENDC}"
        ).strip()

        if not commit_msg:
            commit_msg = default_msg

        print(f"\n{Colors.OKBLUE}💾 Değişiklikler kaydediliyor...{Colors.ENDC}")
        commit_success, commit_err = run_command(
            ["git", "commit", "-m", commit_msg], show_output=False
        )

        if not commit_success:
            print(f"{Colors.FAIL}❌ Dosyalar kaydedilirken hata oluştu: {commit_err}{Colors.ENDC}")
            sys.exit(1)
    else:
        _, status = run_command(["git", "status", "--porcelain"], show_output=False)
        if status.strip():
            print(
                f"{Colors.WARNING}ℹ️ Commit'e uygun bir dosya bulunamadı "
                f"(atlanan/boş klasör veya desteklenmeyen girdiler olabilir).{Colors.ENDC}"
            )
        _, unpushed = run_command(
            ["git", "log", f"origin/{current_branch}..HEAD"], show_output=False
        )
        if not unpushed:
            print(
                f"{Colors.WARNING}🤷 Yüklenecek yeni bir değişiklik bulunamadı. Projeniz zaten güncel!{Colors.ENDC}"
            )
            sys.exit(0)
        else:
            print(
                f"\n{Colors.OKBLUE}💾 Yerel dosya değişikliği yok ancak yüklenmeyi bekleyen commit'ler (Birleştirme logları) bulundu.{Colors.ENDC}"
            )

    print(
        f"\n{Colors.HEADER}🚀 GitHub'a yükleniyor (Hedef: {current_branch}). Lütfen bekleyin...{Colors.ENDC}"
    )

    push_success, err_msg = run_command(
        ["git", "push", "-u", "origin", current_branch], show_output=False
    )

    if push_success:
        print(f"\n{Colors.HEADER}{'='*65}{Colors.ENDC}")
        print(
            f"{Colors.BOLD}{Colors.OKGREEN}🎉 TEBRİKLER! Proje başarıyla GitHub'a yüklendi!{Colors.ENDC}"
        )
        print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}")
    elif "rejected" in err_msg or "fetch first" in err_msg or "non-fast-forward" in err_msg:
        print(f"{Colors.WARNING}⚠️ GitHub'da bilgisayarınızda olmayan dosyalar var.{Colors.ENDC}")
        confirm = (
            input(
                f"{Colors.OKBLUE}Uzak sunucu ile otomatik birleştirme yapılsın mı? (y/n): {Colors.ENDC}"
            )
            .strip()
            .lower()
        )

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
                print(
                    f"{Colors.OKGREEN}✅ Senkronizasyon başarılı. Yeniden yükleniyor...{Colors.ENDC}"
                )

                retry_success, retry_err = run_command(
                    ["git", "push", "-u", "origin", current_branch], show_output=False
                )

                if retry_success:
                    print(f"\n{Colors.HEADER}{'='*65}{Colors.ENDC}")
                    print(
                        f"{Colors.BOLD}{Colors.OKGREEN}🎉 TEBRİKLER! Çakışma otomatik çözüldü ve proje başarıyla GitHub'a yüklendi!{Colors.ENDC}"
                    )
                    print(f"{Colors.HEADER}{'='*65}{Colors.ENDC}")
                else:
                    if "rule violations" in retry_err:
                        print(
                            f"\n{Colors.FAIL}❌ GitHub Güvenlik Duvarı (Push Protection) Devreye Girdi!{Colors.ENDC}"
                        )
                    else:
                        print(
                            f"{Colors.FAIL}❌ Yeniden yükleme başarısız oldu:\n{retry_err}{Colors.ENDC}"
                        )
            else:
                print(
                    f"{Colors.FAIL}❌ Birleştirme sırasında hata oluştu. Lütfen komutu terminale manuel yazıp hatayı okuyun:{Colors.ENDC}"
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
        print(
            f"{Colors.FAIL}❌ Yükleme sırasında bilinmeyen bir hata oluştu:\n{err_msg}{Colors.ENDC}"
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.FAIL}Islem kullanici tarafindan iptal edildi.{Colors.ENDC}")
        sys.exit(0)
