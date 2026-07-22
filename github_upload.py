"""Sidar github_upload.py - Otomatik GitHub Yükleme Aracı.

Sürüm: Sidar ürün sürümüyle senkronize edilir.
Açıklama: Mevcut projeyi kolayca GitHub'a yedekler/yükler.
Dış dalları çekme ve hatalı işlemleri Geri Alma (Rollback) özelliklerini içerir.
Kullanım:
  python github_upload.py                 -> Normal yükleme
  python github_upload.py <branch_adi>    -> Dış dalı çekip birleştirme
  python github_upload.py -<sayi>         -> Son <sayi> işlemi geri alma (Örn: -3)
"""

import os
import re
import subprocess  # nosec B404
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from config import Config
from managers.code.git_validation import is_valid_git_ref_name
from sidar_version import PRODUCT_VERSION

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

# Test ve kalite kapısı çıktıları kaynak kod değildir; .gitignore drift veya
# otomatik stage akışındaki geniş .json izinleri nedeniyle repoya girmemelidir.
SUBPROCESS_ENV_VALUE_MAX_BYTES = 32 * 1024

GENERATED_ARTIFACT_PATHS = {
    "coverage.json",
    "coverage.xml",
    "coverage-final.json",
    "htmlcov/",
    "artifacts/",
    "web_ui_react/coverage/",
    "web_ui_react/playwright-report/",
    "web_ui_react/test-results/",
}


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
def _build_subprocess_env() -> dict[str, str]:
    """Return a bounded environment so large loaded secrets do not break execve.

    Config loading can materialize very large keys into ``os.environ``. Linux passes
    environment values through the same execve argument block as argv, so a single
    oversized secret can make even ``git --version`` fail with E2BIG. Git commands
    used here only need normal process context (PATH/HOME/etc.), not large API keys.
    """
    bounded_env: dict[str, str] = {}
    for key, value in os.environ.items():
        text_value = str(value)
        if len(key.encode()) + len(text_value.encode()) > SUBPROCESS_ENV_VALUE_MAX_BYTES:
            continue
        bounded_env[key] = text_value
    return bounded_env


def run_command(
    args: Sequence[str],
    show_output: bool = True,
    extra_env: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Komutu shell=False ile güvenli ve sınırlı environment ile çalıştırır."""
    try:
        env = _build_subprocess_env()
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(  # nosec B603  # args listesi sistem içi oluşturulur, shell kullanılmaz.
            args,
            shell=False,
            check=True,
            capture_output=True,
            text=True,
            env=env,
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
    except OSError as e:
        err_msg = str(e)
        if show_output and err_msg:
            print(f"{Colors.WARNING}Komut baslatilamadi: {err_msg}{Colors.ENDC}")
        return False, err_msg


def reexec_after_external_branch_merge() -> None:
    """Reload uploader code after a branch merge updates this running script.

    Python keeps the pre-merge module in memory. Re-exec without the already-merged
    branch argument so newly merged pin-repair and quality-gate logic is used
    immediately and the external branch is not pulled a second time.
    """
    if os.environ.get("SIDAR_GITHUB_UPLOAD_REEXEC_AFTER_MERGE") == "1":
        return
    script = Path(__file__).resolve()
    env = _build_subprocess_env()
    env["SIDAR_GITHUB_UPLOAD_REEXEC_AFTER_MERGE"] = "1"
    os.execve(sys.executable, [sys.executable, str(script)], env)  # nosec B606  # sabit argümanlar, shell yok; B603 ile aynı güvenli desen.


def _is_valid_repo_url(url: str) -> bool:
    """GitHub origin URL'ini temel enjeksiyon ve yazım hatalarına karşı doğrular."""
    normalized = str(url or "").strip()
    if not normalized or any(char.isspace() for char in normalized):
        return False

    https_pattern = r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?/?$"
    ssh_pattern = r"^git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$"
    return bool(re.fullmatch(https_pattern, normalized) or re.fullmatch(ssh_pattern, normalized))


def _is_valid_branch_name(branch_name: str) -> bool:
    """Git branch adını komut argümanı olarak güvenli ve geçerli olacak şekilde denetler.

    Backwards-compatible facade for managers.code.git_validation.is_valid_git_ref_name,
    the single source of truth shared with web/routes/project_ops.py.
    """
    return is_valid_git_ref_name(branch_name)


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
    """GITHUB_TOKEN değerini farklı kaynaklardan güvenli biçimde çözer.

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


def resolve_upload_version() -> str:
    """Commit mesajı ve başlık için merkezi Sidar sürümünü çöz."""
    configured_version = str(getattr(cfg, "VERSION", "") or "").strip()
    return configured_version or PRODUCT_VERSION


def is_forbidden_path(path: str) -> bool:
    """Hard blacklist: .gitignore'dan bağımsız kesin engel."""
    normalized = _normalize_path(path)

    # .env*.example dosyalarının güvenlik filtresine takılmasını önleyen istisna
    # Örn: .env.example, .env.test.example, .env.prod.example
    base_name = os.path.basename(normalized)
    if base_name.startswith(".env") and base_name.endswith(".example"):
        return False

    blocked_paths = [*FORBIDDEN_PATHS, *GENERATED_ARTIFACT_PATHS]
    return any(
        normalized == forbidden.rstrip("/") or normalized.startswith(forbidden)
        for forbidden in blocked_paths
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


CONFLICT_MARKER_RE = re.compile(r"^<{7}(?:\s|$)|^={7}$|^>{7}(?:\s|$)", re.MULTILINE)


def get_unmerged_files() -> list[str]:
    """Çözülmemiş Git merge çakışması bulunan dosyaları döndürür."""
    success, output = run_command(
        ["git", "diff", "--name-only", "--diff-filter=U"], show_output=False
    )
    if not success or not output:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def assert_no_unmerged_files() -> None:
    """Unmerged dosya varsa commit/push akışını fail-closed durdurur."""
    unmerged_files = get_unmerged_files()
    if not unmerged_files:
        return

    conflict_message = "❌ Çözülmemiş Git çakışmaları var; commit/push durduruldu:"
    print(f"{Colors.FAIL}{conflict_message}{Colors.ENDC}")
    for file_path in unmerged_files:
        print(f"  - {file_path}")
    print(
        f"{Colors.WARNING}Çakışmaları çözüp `git add` ile işaretledikten sonra "
        f"aracı tekrar çalıştırın.{Colors.ENDC}"
    )
    sys.exit(1)


def print_unmerged_files(prefix: str = "Çakışan dosyalar") -> None:
    """Kullanıcıya açması gereken unmerged dosyaları okunur biçimde listeler."""
    unmerged_files = get_unmerged_files()
    if not unmerged_files:
        return
    print(f"{Colors.WARNING}{prefix}:{Colors.ENDC}")
    for file_path in unmerged_files:
        print(f"  - {file_path}")


def abort_in_progress_merge() -> None:
    """Başarısız pull/merge sonrası çalışma ağacını temiz state'e döndürmeye çalışır."""
    abort_success, abort_err = run_command(["git", "merge", "--abort"], show_output=False)
    if abort_success:
        print(
            f"{Colors.OKGREEN}✅ Başarısız merge otomatik olarak geri alındı; "
            f"çalışma ağacı temizlendi.{Colors.ENDC}"
        )
    elif abort_err:
        print(
            f"{Colors.WARNING}⚠️ Otomatik `git merge --abort` başarısız oldu; "
            f"manuel kontrol gerekebilir:\n{abort_err}{Colors.ENDC}"
        )


def has_conflict_markers(path: str) -> bool:
    """Metin dosyasında kalmış klasik merge conflict marker satırlarını tespit eder."""
    content = get_file_content(path)
    return bool(content and CONFLICT_MARKER_RE.search(content))


def create_rollback_backup_tag() -> str:
    """Force-push rollback öncesi mevcut HEAD için kurtarma etiketi oluşturur."""
    tag_name = f"backup/pre-rollback-{datetime.now():%Y%m%d%H%M%S}"
    tag_success, tag_err = run_command(["git", "tag", tag_name], show_output=False)
    if tag_success:
        tag_message = f"🛟 Rollback öncesi yedek tag oluşturuldu: {tag_name}"
        print(f"{Colors.OKGREEN}{tag_message}{Colors.ENDC}")
    else:
        print(
            f"{Colors.WARNING}⚠️ Rollback yedek tag'i oluşturulamadı; "
            "işlem güvenlik için durduruldu:\n"
            f"{tag_err}{Colors.ENDC}"
        )
        sys.exit(1)
    return tag_name


def report_ours_strategy_changes() -> None:
    """`-X ours` merge sonrasında değişen dosyaları görünür hale getirir."""
    _, changed = run_command(
        ["git", "diff", "--name-only", "ORIG_HEAD..HEAD"],
        show_output=False,
    )
    changed_files = [line.strip() for line in changed.splitlines() if line.strip()]
    if not changed_files:
        return
    print(
        f"{Colors.WARNING}⚠️ `-X ours` stratejisi sonrası değişen/yerel "
        f"sürümün korunduğu dosyalar:{Colors.ENDC}"
    )
    for file_path in changed_files:
        print(f"  - {file_path}")


def get_deleted_files() -> list[str]:
    """Sistemden silinmiş ama Git'in geçmişte takip ettiği dosyaları bulur."""
    success, output = run_command(["git", "ls-files", "-d"], show_output=False)
    if not success or not output:
        return []

    return [line.strip() for line in output.splitlines() if line.strip()]


def get_commit_count() -> int:
    """Aktif dalda rollback için kullanılabilir commit sayısını güvenli biçimde döndürür."""
    success, output = run_command(["git", "rev-list", "--count", "HEAD"], show_output=False)
    if not success or not output:
        return 0

    try:
        return int(output.strip())
    except ValueError:
        return 0


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
            if has_conflict_markers(file_path):
                blocked_files.append(file_path)
                continue

        safe_files.append(file_path)

    return safe_files, blocked_files


def stage_files(file_paths: list[str]) -> tuple[bool, str]:
    """Dosyaları git'e literal pathspec ile güvenli biçimde ekler."""
    if not file_paths:
        return True, ""

    unmerged_files = get_unmerged_files()
    if unmerged_files:
        return False, "Çözülmemiş çakışmalar var: " + ", ".join(unmerged_files)

    literal_paths = [f":(literal){path}" for path in file_paths]
    return run_command(["git", "add", "--"] + literal_paths, show_output=False)


def sync_install_manifests_before_commit() -> tuple[bool, str]:
    """Commit öncesi install manifestlerini tazeler ve drift düzeltmelerini stage eder."""
    sync_steps = [
        ["bash", "scripts/sync_install_module_hashes.sh"],
        ["bash", "scripts/sync_install_manifest.sh"],
        ["git", "add", "install_sidar.sh", ".sidar_manifest.txt"],
    ]

    for cmd in sync_steps:
        success, output = run_command(cmd, show_output=False)
        if not success:
            return False, output

    return True, ""


def stamp_install_manifest_pin_after_commit() -> tuple[bool, str]:
    """Az önce oluşturulan commit'i install_sidar.sh'ın embedded modül pinine damgalar.

    Pin, commit oluşturulmadan ÖNCE damgalanırsa HEAD hâlâ PARENT commit'i işaret
    eder; scripts/install_modules/* bu commit'te değiştiyse pin, gömülü modül
    hash'leriyle asla eşleşmeyen bir commit'e sabitlenmiş olur ve raw tek dosya
    kurulumu kırılır (bkz. docs/CI_REQUIRED_CHECKS.md "Installer manifest and
    smoke gate"). Bu yüzden damgalama burada, commit gerçekten oluşturulduktan
    SONRA çalışır. Pin, kendi içinde bulunduğu commit'e değil (bu, commit
    hash'i kendi içeriğine bağlı olduğu için imkânsızdır), bu commit'i takip
    eden ayrı ve küçük bir fixup commit'ine yazılır.
    """
    head_success, head_out = run_command(["git", "rev-parse", "HEAD"], show_output=False)
    if not head_success:
        return False, head_out
    commit = head_out.strip()

    stamp_success, stamp_err = run_command(
        [
            "uv",
            "run",
            "python",
            "scripts/tools/update_install_module_hash_manifest.py",
            "--target",
            "install_sidar.sh",
            "--stamp-commit",
            commit,
        ],
        show_output=False,
    )
    if not stamp_success:
        return False, stamp_err

    diff_success, diff_out = run_command(
        ["git", "diff", "--name-only", "--", "install_sidar.sh"], show_output=False
    )
    if not diff_success:
        return False, diff_out
    if not diff_out.strip():
        return True, ""

    add_success, add_err = stage_files(["install_sidar.sh"])
    if not add_success:
        return False, add_err

    commit_success, commit_err = run_command(
        ["git", "commit", "-m", f"Pin install_sidar.sh embedded module commit to {commit}"],
        show_output=False,
    )
    if not commit_success:
        return False, commit_err

    return True, ""


def ensure_full_git_history_for_manifest_checks() -> tuple[bool, str]:
    """--check-pin doğrulamasının shallow clone'larda yanlış pozitif vermesini önler.

    ``update_install_module_hash_manifest.py``'nin ``--check``/``--check-pin``
    adımları, ``SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT`` pinini ``git show
    <pin>:<path>`` ile doğrular. Yerel klon shallow ise (ör. sınırlı derinlikte
    bir clone) pinlenen commit hiç yerel object database'de bulunmayabilir;
    bu durumda her dosya için "yok" (okunamadı) sonucu döner ve gerçek bir
    drift olmamasına rağmen 36 modülün tamamı hatalı biçimde drift olarak
    raporlanır. CI bunu ``fetch-depth: 0`` ile önlüyor (bkz. ci.yml); burada da
    aynı garantiyi shallow ise ``git fetch --unshallow`` ile sağlıyoruz.
    """
    shallow_success, shallow_out = run_command(
        ["git", "rev-parse", "--is-shallow-repository"], show_output=False
    )
    if not shallow_success:
        return False, shallow_out
    if shallow_out.strip() != "true":
        return True, ""

    return run_command(["git", "fetch", "--unshallow", "origin"], show_output=False)


def run_pre_push_quality_gate() -> tuple[bool, str]:
    """Push öncesi unit/static/installer kapılarını fail-closed çalıştırır.

    github_upload.py, PR/branch-protection akışını atlayıp doğrudan main'e push
    eder; bu yüzden CI'daki PR-only zorunlu "Installer manifest and smoke gate"
    hiçbir zaman devreye girmez. Buradaki adımlar unit testleri ve o job'ın
    (installer-smoke, .github/workflows/ci.yml) pin-drift'i yakalayan
    kısımlarını kapsar; böylece direkt push öncesinde kod/test sözleşmesi veya
    installer drift hataları yerelde yakalanır.
    """
    history_success, history_err = ensure_full_git_history_for_manifest_checks()
    if not history_success:
        return False, f"git fetch --unshallow origin\n{history_err}".strip()

    quality_steps: list[tuple[list[str], dict[str, str] | None]] = [
        (["uv", "run", "ruff", "format", "--check", "."], None),
        (["uv", "run", "ruff", "check", "."], None),
        (["uv", "run", "pytest", "tests/unit", "-q", "--no-cov", "-x"], None),
        (["make", "installer-shellcheck"], None),
        (["sha256sum", "-c", ".sidar_manifest.txt"], None),
        (["uv", "run", "python", "scripts/tools/update_core_install_manifest.py", "--check"], None),
        (
            [
                "uv",
                "run",
                "python",
                "scripts/tools/update_install_module_hash_manifest.py",
                "--target",
                "install_sidar.sh",
                "--check",
            ],
            None,
        ),
        (
            [
                "uv",
                "run",
                "python",
                "scripts/tools/update_install_module_hash_manifest.py",
                "--target",
                "install_sidar.sh",
                "--check-pin",
            ],
            None,
        ),
        (["bash", "-n", "install_sidar.sh"], None),
        (
            ["bash", "install_sidar.sh"],
            {"SIDAR_INSTALL_TEST_MODE": "1", "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY": "1"},
        ),
        (
            [
                "uv",
                "run",
                "pytest",
                "-q",
                "--no-cov",
                "tests/smoke/test_install_verification.py"
                "::test_install_sidar_embedded_manifests_in_sync",
            ],
            None,
        ),
    ]

    for cmd, extra_env in quality_steps:
        success, output = run_command(cmd, show_output=False, extra_env=extra_env)
        if not success:
            failure = f"{' '.join(cmd)}\n{output}".strip()
            if cmd == ["uv", "run", "ruff", "format", "--check", "."]:
                failure += "\n\nDüzeltmek için: uv run ruff format ."
            return False, failure

    return True, ""


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
                    f"{Colors.FAIL}❌ Hata: Sadece 1 ile 10 işlem arasına kadar geri alabilirsiniz "
                    f"(Örn: -3).{Colors.ENDC}"
                )
                sys.exit(1)
        else:
            if not _is_valid_branch_name(arg):
                print(
                    f"{Colors.FAIL}❌ Hata: Geçersiz dal adı. "
                    "Dal adı boşluk, kontrol karakteri veya Git ref için riskli semboller içeremez."
                    f"{Colors.ENDC}"
                )
                sys.exit(1)
            target_branch = arg

    print(f"{Colors.HEADER}{'=' * 65}{Colors.ENDC}")
    upload_version = resolve_upload_version()
    print(
        f"{Colors.BOLD} 🐙 Sidar - GitHub Otomatik Yükleme & Yedekleme Aracı "
        f"(Sidar v{upload_version}) {Colors.ENDC}"
    )
    print(f"{Colors.HEADER}{'=' * 65}{Colors.ENDC}\n")

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
            f"{Colors.FAIL}Sistemde Git kurulu değil. Lütfen terminalden 'sudo apt install git' "
            f"yazarak kurun.{Colors.ENDC}"
        )
        sys.exit(1)

    _, name_out = run_command(["git", "config", "user.name"], show_output=False)
    if not name_out:
        print(
            f"{Colors.WARNING}⚠️ Git kimliğiniz tanımlanmamış. Lütfen GitHub bilgilerinizi "
            f"girin:{Colors.ENDC}"
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

    assert_no_unmerged_files()

    # Çalışma akışını her zaman main dalında sürdür.
    if current_branch != "main":
        print(f"\n{Colors.WARNING}⚠️ Şu an '{current_branch}' dalındasınız.{Colors.ENDC}")
        print(
            f"{Colors.OKBLUE}🔄 İşlemlerin 'main' dalında yapılması için geçiş "
            f"hazırlanıyor...{Colors.ENDC}"
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
                    f"{Colors.FAIL}❌ Değişiklikler güvenli olarak stash'e "
                    f"alınamadı:\n{stash_err}{Colors.ENDC}"
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
                f"{Colors.WARNING}Lütfen terminalden 'git checkout main' yazarak çakışmaları "
                f"kontrol edin.{Colors.ENDC}"
            )
            sys.exit(1)

        current_branch = "main"

        if stash_created:
            pop_success, pop_err = run_command(["git", "stash", "pop"], show_output=False)
            if not pop_success:
                print(
                    f"{Colors.FAIL}❌ Stash geri yüklenirken çakışma "
                    f"oluştu:\n{pop_err}{Colors.ENDC}"
                )
                print(
                    f"{Colors.WARNING}Çakışmaları çözüp commit aldıktan sonra aracı tekrar "
                    f"çalıştırabilirsiniz.{Colors.ENDC}"
                )
                sys.exit(1)

        print(f"{Colors.OKGREEN}✅ 'main' dalına başarıyla geçildi.{Colors.ENDC}\n")

    # ═══════════════════════════════════════════════════════════════
    # GERİ ALMA (ROLLBACK) İŞLEMİ
    # ═══════════════════════════════════════════════════════════════
    if rollback_steps > 0:
        print(
            f"\n{Colors.FAIL}{Colors.BOLD}🚨 KRİTİK UYARI: GERİ ALMA İŞLEMİ BAŞLATILDI "
            f"🚨{Colors.ENDC}"
        )
        print(
            f"{Colors.WARNING}Son {rollback_steps} commit ve yerel bilgisayarınızdaki henüz "
            f"kaydedilmemiş tüm değişiklikler KALICI OLARAK SİLİNECEK.{Colors.ENDC}"
        )
        print(
            f"{Colors.WARNING}Projeniz tam {rollback_steps} adım önceki haline hem yerelde hem de "
            f"GitHub'da (Force Push) zorla eşitlenecek.{Colors.ENDC}"
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

            # 1. Yerel commit geçmişini kullanıcının istediği kadar adım geri sar.
            # ORIG_HEAD merge/pull geçmişine bağlı olarak beklenmedik referansa işaret edebilir;
            # kullanıcı -N verdiğinde en anlaşılır ve deterministik hedef HEAD~N'dir.
            print(f"{Colors.OKBLUE}📍 Mevcut dal: {current_branch}{Colors.ENDC}")

            available_commits = get_commit_count()
            if available_commits <= rollback_steps:
                print(
                    f"{Colors.FAIL}❌ Geri alma başarısız: Bu dalda yalnızca {available_commits} "
                    f"commit var, "
                    f"{rollback_steps} adım geriye gidilemez.{Colors.ENDC}"
                )
                sys.exit(1)

            create_rollback_backup_tag()

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
                print(f"\n{Colors.HEADER}{'=' * 65}{Colors.ENDC}")
                print(
                    f"{Colors.BOLD}{Colors.OKGREEN}⏪ BAŞARILI! Proje başarıyla {rollback_steps} "
                    f"adım önceki haline döndürüldü.{Colors.ENDC}"
                )
                print(f"{Colors.HEADER}{'=' * 65}{Colors.ENDC}")
            else:
                print(
                    f"{Colors.FAIL}❌ GitHub'a zorla yazma (Force Push) başarısız "
                    f"oldu:\n{push_err}{Colors.ENDC}"
                )
                print(
                    f"{Colors.WARNING}Not: GitHub deponuzda 'Branch Protection' kuralları force "
                    f"push'u engelliyor olabilir.{Colors.ENDC}"
                )

            sys.exit(0 if push_success else 1)  # Geri alma bitti, başarı durumuna göre çık
        else:
            print(
                f"\n{Colors.OKGREEN}🛡️ Geri alma işlemi iptal edildi. Kodlarınız "
                f"güvende.{Colors.ENDC}"
            )
            sys.exit(0)

    # ═══════════════════════════════════════════════════════════════
    # DAL ÇEKME (PULL/MERGE) İŞLEMİ
    # ═══════════════════════════════════════════════════════════════
    if target_branch:
        print(f"\n{Colors.HEADER}📥 Dış dal (branch) algılandı: '{target_branch}'{Colors.ENDC}")
        print(
            f"{Colors.OKBLUE}🔄 '{target_branch}' GitHub'dan çekilip "
            f"'{current_branch}' ile birleştiriliyor...{Colors.ENDC}"
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
                f"{Colors.OKGREEN}✅ '{target_branch}' dalı başarıyla çekildi ve "
                f"birleştirildi.{Colors.ENDC}"
            )
            reexec_after_external_branch_merge()
        else:
            print(
                f"{Colors.FAIL}❌ Birleştirme sırasında hata veya çakışma (conflict) "
                f"oluştu:\n{pull_err}{Colors.ENDC}"
            )
            print_unmerged_files()
            abort_in_progress_merge()
            print(
                f"{Colors.WARNING}Başarısız merge geri alındı. "
                "Lütfen ilgili dalı güncelleyip/çakışmayı manuel test ederek "
                "aracı tekrar çalıştırın."
                f"{Colors.ENDC}"
            )
            sys.exit(1)

    # ═══════════════════════════════════════════════════════════════
    # STANDART YÜKLEME İŞLEMİ
    # ═══════════════════════════════════════════════════════════════
    assert_no_unmerged_files()

    print(f"\n{Colors.OKBLUE}📦 Yerel dosyalar taranıyor ve paketleniyor...{Colors.ENDC}")
    run_command(["git", "reset"], show_output=False)

    # 1. Silinmiş dosyaları kontrol et ve onaya sun
    deleted_files = get_deleted_files()
    if deleted_files:
        print(
            f"\n{Colors.WARNING}🗑️ Aşağıdaki dosyaların yerel sistemden silindiği tespit "
            f"edildi:{Colors.ENDC}"
        )
        for deleted_file in deleted_files:
            print(f"  - {deleted_file}")

        confirm_del = (
            input(
                f"{Colors.OKBLUE}Bu dosyaları kalıcı olarak silip GitHub'dan da kaldırmak istiyor "
                f"musunuz? "
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

    manifest_success, manifest_err = sync_install_manifests_before_commit()
    if not manifest_success:
        print(
            f"{Colors.FAIL}❌ Install manifestleri commit öncesi senkronize edilemedi: "
            f"{manifest_err}{Colors.ENDC}"
        )
        sys.exit(1)

    _, staged_status = run_command(["git", "diff", "--cached", "--name-status"], show_output=False)

    if staged_status.strip():
        default_msg = (
            f"🚀 Sidar {upload_version} - Otomatik Dağıtım "
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

        pin_success, pin_err = stamp_install_manifest_pin_after_commit()
        if not pin_success:
            print(
                f"{Colors.FAIL}❌ Install manifest pini commit sonrası damgalanamadı: "
                f"{pin_err}{Colors.ENDC}"
            )
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
                f"{Colors.WARNING}🤷 Yüklenecek yeni bir değişiklik bulunamadı. Projeniz zaten "
                f"güncel!{Colors.ENDC}"
            )
            sys.exit(0)
        else:
            print(
                f"\n{Colors.OKBLUE}💾 Yerel dosya değişikliği yok ancak yüklenmeyi bekleyen "
                f"commit'ler (Birleştirme logları) bulundu.{Colors.ENDC}"
            )

    # Dış branch merge'i veya yalnız unpushed commit bulunan akışta yeni bir
    # çalışma ağacı değişikliği olmayabilir. Bu durumda da pin eski/orphan bir
    # commit'i gösterebilir; kalite kapısından önce mevcut, erişilebilir HEAD'e
    # damgala ve gerekiyorsa ayrı fixup commit'i oluştur.
    pin_success, pin_err = stamp_install_manifest_pin_after_commit()
    if not pin_success:
        print(
            f"{Colors.FAIL}❌ Install manifest pini push öncesi onarılamadı: {pin_err}{Colors.ENDC}"
        )
        sys.exit(1)

    gate_success, gate_err = run_pre_push_quality_gate()
    if not gate_success:
        print(
            f"{Colors.FAIL}❌ Push öncesi kalite kapısı başarısız oldu; GitHub'a yükleme "
            f"durduruldu:\n"
            f"{gate_err}{Colors.ENDC}"
        )
        sys.exit(1)

    print(
        f"\n{Colors.HEADER}🚀 GitHub'a yükleniyor (Hedef: {current_branch}). Lütfen "
        f"bekleyin...{Colors.ENDC}"
    )

    push_success, err_msg = run_command(
        ["git", "push", "-u", "origin", current_branch], show_output=False
    )

    if push_success:
        print(f"\n{Colors.HEADER}{'=' * 65}{Colors.ENDC}")
        print(
            f"{Colors.BOLD}{Colors.OKGREEN}🎉 TEBRİKLER! Proje başarıyla GitHub'a "
            f"yüklendi!{Colors.ENDC}"
        )
        print(f"{Colors.HEADER}{'=' * 65}{Colors.ENDC}")
    elif "rejected" in err_msg or "fetch first" in err_msg or "non-fast-forward" in err_msg:
        print(f"{Colors.WARNING}⚠️ GitHub'da bilgisayarınızda olmayan dosyalar var.{Colors.ENDC}")
        confirm = (
            input(
                f"{Colors.OKBLUE}Uzak sunucu ile otomatik birleştirme yapılsın mı? (y/n): "
                f"{Colors.ENDC}"
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
                report_ours_strategy_changes()
                assert_no_unmerged_files()
                print(
                    f"{Colors.OKGREEN}✅ Senkronizasyon başarılı. Yeniden "
                    f"yükleniyor...{Colors.ENDC}"
                )

                pin_success, pin_err = stamp_install_manifest_pin_after_commit()
                if not pin_success:
                    print(
                        f"{Colors.FAIL}❌ Install manifest pini birleştirme sonrası "
                        f"damgalanamadı: {pin_err}{Colors.ENDC}"
                    )
                    sys.exit(1)

                gate_success, gate_err = run_pre_push_quality_gate()
                if not gate_success:
                    print(
                        f"{Colors.FAIL}❌ Push retry öncesi kalite kapısı başarısız oldu; "
                        f"GitHub'a yükleme durduruldu:\n{gate_err}{Colors.ENDC}"
                    )
                    sys.exit(1)

                retry_success, retry_err = run_command(
                    ["git", "push", "-u", "origin", current_branch], show_output=False
                )

                if retry_success:
                    print(f"\n{Colors.HEADER}{'=' * 65}{Colors.ENDC}")
                    print(
                        f"{Colors.BOLD}{Colors.OKGREEN}🎉 TEBRİKLER! Çakışma otomatik çözüldü ve "
                        f"proje başarıyla GitHub'a yüklendi!{Colors.ENDC}"
                    )
                    print(f"{Colors.HEADER}{'=' * 65}{Colors.ENDC}")
                else:
                    if "rule violations" in retry_err:
                        print(
                            f"\n{Colors.FAIL}❌ GitHub Güvenlik Duvarı (Push Protection) Devreye "
                            f"Girdi!{Colors.ENDC}"
                        )
                    else:
                        print(
                            f"{Colors.FAIL}❌ Yeniden yükleme başarısız "
                            f"oldu:\n{retry_err}{Colors.ENDC}"
                        )
            else:
                print(
                    f"{Colors.FAIL}❌ Birleştirme sırasında hata oluştu. Lütfen komutu terminale "
                    f"manuel yazıp hatayı okuyun:{Colors.ENDC}"
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
