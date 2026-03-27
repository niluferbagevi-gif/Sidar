"""
Sidar github_upload.py - Otomatik GitHub Yukleme Araci
Surum: 2.2
Aciklama: Mevcut projeyi guvenli sekilde GitHub'a yedekler/yukler.
Kimlik, cakisma, silme senkronizasyonu ve otomatik birlestirme kontrolleri icerir.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
import time
from datetime import datetime

from config import Config

cfg = Config()

# ASLA YUKLENMEMESI GEREKENLER (kritik guvenlik katmani)
# Not: .gitignore'dan bagimsiz hard-blacklist.
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

_PUSH_MAX_RETRIES: int = 4
_PUSH_BACKOFF_BASE: int = 2
DEFAULT_TARGET_BRANCH = "main"


class Colors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"


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
        output = result.stdout.strip()
        if show_output and output:
            print(output)
        return True, output
    except subprocess.CalledProcessError as exc:
        err_msg = (exc.stderr or "").strip()
        out_msg = (exc.stdout or "").strip()
        if out_msg:
            err_msg = f"{err_msg}\n{out_msg}".strip()
        if show_output and err_msg:
            print(f"{Colors.WARNING}Git ciktisi: {err_msg}{Colors.ENDC}")
        return False, err_msg


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _is_valid_repo_url(url: str) -> bool:
    normalized = (url or "").strip()
    return normalized.startswith("https://github.com/") or normalized.startswith("git@github.com:")


def _is_valid_branch_name(branch: str) -> bool:
    """Git'e uygun bir branch adi olup olmadigini kontrol eder."""
    if not branch or any(ch.isspace() for ch in branch):
        return False
    ok, _ = run_command(["git", "check-ref-format", "--branch", branch], show_output=False)
    return ok


def is_forbidden_path(path: str) -> bool:
    normalized = _normalize_path(path)
    basename = os.path.basename(normalized)

    for forbidden in FORBIDDEN_PATHS:
        block = _normalize_path(forbidden)

        if block.endswith("/"):
            if normalized == block.rstrip("/") or normalized.startswith(block):
                return True
            continue

        if any(ch in block for ch in "*?[]"):
            if fnmatch.fnmatch(normalized, block) or fnmatch.fnmatch(basename, block):
                return True
            continue

        if normalized == block:
            return True

    return False


def is_file_safe_to_upload(path: str) -> tuple[bool, str]:
    if not os.path.isabs(path) and is_forbidden_path(path):
        return False, "yasakli dizin/dosya"

    if os.path.islink(path):
        return False, "symlink engellendi"

    try:
        file_size_mb = os.path.getsize(path) / (1024 * 1024)
    except OSError:
        return False, "dosya boyutu okunamadi"

    if file_size_mb > 95.0:
        return False, f"dosya cok buyuk ({file_size_mb:.1f} MB)"

    return True, ""


def collect_safe_files() -> tuple[list[str], list[str]]:
    success, output = run_command(["git", "ls-files", "-co", "--exclude-standard"], show_output=False)
    if not success:
        return [], []

    safe_files: list[str] = []
    blocked_files: list[str] = []

    for line in output.splitlines():
        file_path = line.strip()
        if not file_path or os.path.isdir(file_path):
            continue

        safe_to_upload, reason = is_file_safe_to_upload(file_path)
        if safe_to_upload:
            safe_files.append(file_path)
        else:
            blocked_files.append(f"{file_path} ({reason})")

    return safe_files, blocked_files


def collect_deleted_files() -> list[str]:
    success, output = run_command(["git", "ls-files", "-d"], show_output=False)
    if not success:
        return []

    deleted: list[str] = []
    for line in output.splitlines():
        file_path = line.strip()
        if file_path and not is_forbidden_path(file_path):
            deleted.append(file_path)
    return deleted


def _is_rebase_in_progress() -> bool:
    git_dir = ".git"
    return os.path.exists(os.path.join(git_dir, "rebase-merge")) or os.path.exists(
        os.path.join(git_dir, "rebase-apply")
    )


def _summarize_staged_areas() -> str:
    success, output = run_command(["git", "diff", "--cached", "--name-only"], show_output=False)
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
    return " ".join(f"{area}/" for area in areas[:4]) if areas else "workspace"


def setup_git_identity() -> None:
    _, name_out = run_command(["git", "config", "user.name"], show_output=False)
    if name_out:
        return

    print(f"{Colors.WARNING}Git kimliginiz tanimli degil. Lutfen bilgileri girin:{Colors.ENDC}")
    git_name = input("Adiniz / GitHub Kullanici Adiniz: ").strip()
    git_email = input("GitHub E-Posta Adresiniz: ").strip()
    run_command(["git", "config", "--global", "user.name", git_name], show_output=False)
    run_command(["git", "config", "--global", "user.email", git_email], show_output=False)
    print(f"{Colors.OKGREEN}Git kimligi kaydedildi.{Colors.ENDC}\n")


def ensure_git_repo() -> None:
    if not os.path.exists(".git"):
        print(f"{Colors.WARNING}Bu klasor Git reposu degil, olusturuluyor...{Colors.ENDC}")
        run_command(["git", "init"], show_output=False)
        run_command(["git", "branch", "-M", DEFAULT_TARGET_BRANCH], show_output=False)


def ensure_remote() -> None:
    _, remotes = run_command(["git", "remote", "-v"], show_output=False)
    if "origin" in remotes:
        print(f"{Colors.OKGREEN}Origin remote algilandi.{Colors.ENDC}")
        return

    print(f"{Colors.WARNING}Origin remote bulunamadi.{Colors.ENDC}")
    repo_url = input(
        f"{Colors.OKBLUE}GitHub Depo URL'si (orn: https://github.com/niluferbagevi-gif/Sidar): {Colors.ENDC}"
    ).strip()
    if not _is_valid_repo_url(repo_url):
        print(f"{Colors.FAIL}Gecersiz URL, islem sonlandirildi.{Colors.ENDC}")
        sys.exit(1)

    run_command(["git", "remote", "add", "origin", repo_url], show_output=False)
    print(f"{Colors.OKGREEN}Origin remote eklendi.{Colors.ENDC}")


def _local_branch_exists(branch: str) -> bool:
    ok, _ = run_command(["git", "show-ref", "--verify", f"refs/heads/{branch}"], show_output=False)
    return ok


def _remote_branch_exists(branch: str) -> bool:
    ok, output = run_command(["git", "ls-remote", "--heads", "origin", branch], show_output=False)
    return ok and bool(output.strip())


def checkout_target_branch(branch: str) -> None:
    """
    Hedef branch'i localde hazirlar:
    - localde varsa ona gecer
    - yoksa remote'da varsa track ederek olusturur
    - hic yoksa yeni local branch olusturur
    """
    run_command(["git", "fetch", "origin"], show_output=False)

    if _local_branch_exists(branch):
        ok, err = run_command(["git", "checkout", branch], show_output=False)
        if not ok:
            print(f"{Colors.FAIL}Branch degistirme basarisiz: {err}{Colors.ENDC}")
            sys.exit(1)
        return

    if _remote_branch_exists(branch):
        ok, err = run_command(["git", "checkout", "-b", branch, "--track", f"origin/{branch}"], show_output=False)
        if not ok:
            print(f"{Colors.FAIL}Remote branch track edilirken hata: {err}{Colors.ENDC}")
            sys.exit(1)
        return

    ok, err = run_command(["git", "checkout", "-b", branch], show_output=False)
    if not ok:
        print(f"{Colors.FAIL}Yeni branch olusturulamadi: {err}{Colors.ENDC}")
        sys.exit(1)


def build_commit() -> None:
    print(f"\n{Colors.OKBLUE}Dosyalar taraniyor ve stage'e aliniyor...{Colors.ENDC}")
    run_command(["git", "reset"], show_output=False)

    safe_files, blocked_files = collect_safe_files()
    if safe_files:
        run_command(["git", "add", "--"] + safe_files, show_output=False)

    deleted_files = collect_deleted_files()
    for path in deleted_files:
        run_command(["git", "add", "-u", "--", path], show_output=False)

    if deleted_files:
        print(f"{Colors.OKGREEN}{len(deleted_files)} silinmis dosya senkronizasyona eklendi.{Colors.ENDC}")

    if blocked_files:
        print(f"{Colors.WARNING}Atlanan dosyalar:{Colors.ENDC}")
        for blocked in blocked_files:
            print(f"  - {blocked}")

    rebase_in_progress = _is_rebase_in_progress()
    _, staged_status = run_command(["git", "diff", "--cached", "--name-only"], show_output=False)
    has_staged_changes = bool(staged_status.strip())

    if not has_staged_changes and not rebase_in_progress:
        print(f"{Colors.WARNING}Yeni degisiklik yok, proje guncel.{Colors.ENDC}")
        sys.exit(0)

    version = getattr(cfg, "VERSION", "?")
    staged_area_summary = _summarize_staged_areas()
    default_msg = (
        f"Sidar {version} - Otomatik Dagitim: {staged_area_summary} "
        f"({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    )

    print(f"\n{Colors.WARNING}Commit mesaji (bos birakirsan otomatik):{Colors.ENDC}")
    commit_msg = input(f"{Colors.OKBLUE}> {Colors.ENDC}").strip() or default_msg

    commit_cmd = ["git", "commit", "-m", commit_msg]
    if rebase_in_progress:
        if has_staged_changes:
            commit_cmd = ["git", "commit", "--amend", "-m", commit_msg]
        else:
            print(f"{Colors.WARNING}Rebase acik; degisiklik yok, mevcut commit no-edit amend edilecek.{Colors.ENDC}")
            commit_cmd = ["git", "commit", "--amend", "--no-edit"]

    ok, err = run_command(commit_cmd, show_output=False)
    if not ok:
        print(f"{Colors.FAIL}Commit olusturulamadi: {err}{Colors.ENDC}")
        sys.exit(1)


def _try_push(remote_branch: str) -> tuple[bool, str]:
    # Her kosulda mevcut HEAD'i origin/<remote_branch> dalina gonderir.
    return run_command(["git", "push", "-u", "origin", f"HEAD:{remote_branch}"], show_output=False)


def push_with_retry(remote_branch: str) -> tuple[bool, str]:
    err_msg = ""
    for attempt in range(_PUSH_MAX_RETRIES + 1):
        success, err_msg = _try_push(remote_branch)
        if success:
            return True, ""

        if any(kw in err_msg for kw in ("rejected", "fetch first", "non-fast-forward", "rule violations")):
            return False, err_msg

        if attempt < _PUSH_MAX_RETRIES:
            wait = _PUSH_BACKOFF_BASE ** (attempt + 1)
            print(
                f"{Colors.WARNING}Push basarisiz (deneme {attempt + 1}/{_PUSH_MAX_RETRIES}), "
                f"{wait}s sonra tekrar denenecek...{Colors.ENDC}"
            )
            time.sleep(wait)

    return False, err_msg


def _handle_conflict(remote_branch: str) -> None:
    print(f"{Colors.WARNING}Uzak depoda fark var (non-fast-forward).{Colors.ENDC}")
    confirm = input(
        f"{Colors.OKBLUE}origin/{remote_branch} ile rebase yapilip tekrar push denensin mi? (y/n): {Colors.ENDC}"
    ).strip().lower()

    if confirm != "y":
        print(f"{Colors.WARNING}Islem guvenlik icin durduruldu.{Colors.ENDC}")
        return

    pull_cmd = ["git", "pull", "--rebase", "origin", remote_branch]
    print(f"{Colors.OKBLUE}Rebase ile senkronizasyon yapiliyor...{Colors.ENDC}")
    pull_success, pull_err = run_command(pull_cmd, show_output=False)
    if not pull_success:
        print(f"{Colors.FAIL}Rebase basarisiz: {pull_err}{Colors.ENDC}")
        print(f"{Colors.WARNING}Manuel kontrol: {' '.join(pull_cmd)}{Colors.ENDC}")
        return

    retry_success, retry_err = push_with_retry(remote_branch)
    if retry_success:
        print(f"{Colors.OKGREEN}Senkronizasyon ve push tamamlandi.{Colors.ENDC}")
    else:
        _print_push_error(retry_err)


def _print_push_error(err_msg: str) -> None:
    if "rule violations" in err_msg:
        print(f"{Colors.FAIL}GitHub Push Protection devreye girdi (secret tespiti).{Colors.ENDC}")
    else:
        print(f"{Colors.FAIL}Push hatasi: {err_msg}{Colors.ENDC}")


def finalize_rebase_if_needed() -> None:
    """Rebase aciksa devam ettirir; tamamlanmadan push'a gecmez."""
    if not _is_rebase_in_progress():
        return

    ok, err = run_command(["git", "rebase", "--continue"], show_output=False)
    if not ok:
        print(f"{Colors.FAIL}Rebase --continue basarisiz: {err}{Colors.ENDC}")
        print(f"{Colors.WARNING}Lutfen rebase'i manuel tamamlayip tekrar deneyin.{Colors.ENDC}")
        sys.exit(1)

    if _is_rebase_in_progress():
        print(f"{Colors.WARNING}Rebase halen acik. Tum adimlari manuel tamamlayin ve scripti tekrar calistirin.{Colors.ENDC}")
        sys.exit(1)


def main() -> None:
    version = getattr(cfg, "VERSION", "2.2")
    target_branch = sys.argv[1].strip() if len(sys.argv) > 1 else DEFAULT_TARGET_BRANCH
    if not _is_valid_branch_name(target_branch):
        print(f"{Colors.FAIL}Gecersiz branch adi: '{target_branch}'{Colors.ENDC}")
        print(f"{Colors.WARNING}Ornek kullanim: python github_upload.py main{Colors.ENDC}")
        sys.exit(1)

    print(f"{Colors.HEADER}{'=' * 68}{Colors.ENDC}")
    print(f"{Colors.BOLD} Sidar - GitHub Otomatik Yukleme Araci (v{version}) {Colors.ENDC}")
    print(f"{Colors.HEADER}{'=' * 68}{Colors.ENDC}")
    print(f"{Colors.OKBLUE}Hedef branch: origin/{target_branch}{Colors.ENDC}\n")

    success, _ = run_command(["git", "--version"], show_output=False)
    if not success:
        print(f"{Colors.FAIL}Git kurulu degil. 'sudo apt install git' ile kurabilirsiniz.{Colors.ENDC}")
        sys.exit(1)

    # Token yoksa da SSH / credential helper ile push calisabilir.
    if not getattr(cfg, "GITHUB_TOKEN", None):
        print(f"{Colors.WARNING}GITHUB_TOKEN bulunamadi; mevcut Git kimlik bilgileriyle devam ediliyor.{Colors.ENDC}")

    setup_git_identity()
    ensure_git_repo()
    ensure_remote()
    checkout_target_branch(target_branch)
    build_commit()
    finalize_rebase_if_needed()

    print(f"\n{Colors.HEADER}GitHub'a yukleniyor: origin/{target_branch}{Colors.ENDC}")
    push_success, err_msg = push_with_retry(target_branch)

    if push_success:
        print(f"\n{Colors.OKGREEN}{Colors.BOLD}Basarili: local degisiklikler origin/{target_branch} dalina push edildi.{Colors.ENDC}")
        return

    if any(kw in err_msg for kw in ("rejected", "fetch first", "non-fast-forward")):
        _handle_conflict(target_branch)
    else:
        _print_push_error(err_msg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.FAIL}Islem kullanici tarafindan iptal edildi.{Colors.ENDC}")
        sys.exit(0)
