"""
Sidar github_upload.py - Güvenli GitHub Senkronizasyon Aracı
Sürüm: 3.0
Açıklama:
- Yerel proje ile GitHub arasında mirror sync yapar.
- Yerelde silinen tracked dosyaları GitHub'dan da kaldırmak için commit'e delete ekler.
- Güvenlik için hard blacklist, dry-run, korumalı yol (whitelist/protect), loglama sağlar.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import Config

cfg = Config()

# ASLA YÜKLENMEMESİ GEREKENLER (hard blacklist)
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

_PUSH_MAX_RETRIES: int = 4
_PUSH_BACKOFF_BASE: int = 2  # saniye
DEFAULT_LOG_FILE = "logs/github_upload.log"


class Colors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"


@dataclass
class SyncPlan:
    add_or_update: list[str]
    delete: list[str]
    blocked: list[str]


@dataclass
class CliArgs:
    dry_run: bool
    mirror: bool
    force_delete: bool
    protect_paths: list[str]
    message: Optional[str]
    non_interactive: bool
    log_file: str
    branch: Optional[str]


def setup_logging(log_file: str) -> None:
    """Dosyaya ve konsola loglama kurar."""
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run_command(args: list[str], show_output: bool = True) -> tuple[bool, str]:
    """Komutu shell=False ile güvenli şekilde çalıştırır."""
    logging.debug("Komut çalıştırılıyor: %s", " ".join(args))
    try:
        result = subprocess.run(
            args,
            shell=False,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        out = result.stdout.strip()
        if show_output and out:
            print(out)
        return True, out
    except subprocess.CalledProcessError as e:
        err_msg = (e.stderr or "").strip()
        if e.stdout and e.stdout.strip():
            err_msg += "\n" + e.stdout.strip()
        if show_output and err_msg:
            print(f"{Colors.WARNING}Git çıktısı: {err_msg}{Colors.ENDC}")
        logging.warning("Komut başarısız: %s | %s", " ".join(args), err_msg)
        return False, err_msg


def get_file_content(path: str) -> str:
    """Test uyumluluğu için yardımcı; dosyayı UTF-8 okur."""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _is_valid_repo_url(url: str) -> bool:
    if not url:
        return False
    normalized = url.strip()
    return normalized.startswith("https://github.com/") or normalized.startswith("git@github.com:")


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _is_prefix_match(path: str, rule: str) -> bool:
    normalized_path = _normalize_path(path)
    normalized_rule = _normalize_path(rule).rstrip("/")
    return normalized_path == normalized_rule or normalized_path.startswith(f"{normalized_rule}/")


def is_forbidden_path(path: str) -> bool:
    normalized = _normalize_path(path)
    return any(
        normalized == forbidden.rstrip("/") or normalized.startswith(forbidden)
        for forbidden in FORBIDDEN_PATHS
    )


def is_protected_path(path: str, protected_rules: list[str]) -> bool:
    return any(_is_prefix_match(path, rule) for rule in protected_rules)


def _is_readable_utf8(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            fh.read(1)
        return True
    except (UnicodeDecodeError, OSError):
        return False


def _git_lines(args: list[str]) -> list[str]:
    ok, output = run_command(args, show_output=False)
    if not ok or not output:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def build_sync_plan(protected_rules: list[str], mirror: bool) -> SyncPlan:
    """Stage planı üretir: eklenecek/güncellenecek ve silinecek dosyalar."""
    all_candidates = _git_lines(["git", "ls-files", "-co", "--exclude-standard"])
    add_or_update: list[str] = []
    blocked: list[str] = []

    for file_path in all_candidates:
        if os.path.isdir(file_path):
            continue
        if is_forbidden_path(file_path):
            blocked.append(file_path)
            continue
        if not _is_readable_utf8(file_path):
            blocked.append(file_path)
            continue
        add_or_update.append(file_path)

    delete: list[str] = []
    if mirror:
        deleted_candidates = _git_lines(["git", "ls-files", "--deleted"])
        for file_path in deleted_candidates:
            if is_forbidden_path(file_path):
                blocked.append(file_path)
                continue
            if is_protected_path(file_path, protected_rules):
                logging.info("Korumalı yol silinmeyecek: %s", file_path)
                continue
            delete.append(file_path)

    return SyncPlan(add_or_update=sorted(add_or_update), delete=sorted(delete), blocked=sorted(set(blocked)))


def collect_safe_files() -> tuple[list[str], list[str]]:
    """Geriye dönük uyumluluk: güvenli dosyaları döndürür."""
    plan = build_sync_plan(protected_rules=[], mirror=False)
    return plan.add_or_update, plan.blocked


def setup_git_identity(non_interactive: bool) -> None:
    _, name_out = run_command(["git", "config", "user.name"], show_output=False)
    if name_out:
        return

    if non_interactive:
        print(f"{Colors.FAIL}Git kimliği tanımlı değil ve --non-interactive aktif.{Colors.ENDC}")
        sys.exit(1)

    print(f"{Colors.WARNING}⚠️ Git kimliğiniz tanımlanmamış. Lütfen bilgilerinizi girin:{Colors.ENDC}")
    git_name = input("Adınız / GitHub Kullanıcı Adınız: ").strip()
    git_email = input("GitHub E-Posta Adresiniz: ").strip()
    run_command(["git", "config", "--global", "user.name", git_name], show_output=False)
    run_command(["git", "config", "--global", "user.email", git_email], show_output=False)
    print(f"{Colors.OKGREEN}✅ Git kimliğiniz kaydedildi.{Colors.ENDC}\n")


def ensure_git_repo() -> None:
    if not os.path.exists(".git"):
        print(f"{Colors.WARNING}Klasör Git deposu değil. Başlatılıyor...{Colors.ENDC}")
        run_command(["git", "init"], show_output=False)
        run_command(["git", "branch", "-M", "main"], show_output=False)
        print(f"{Colors.OKGREEN}✅ Git deposu oluşturuldu.{Colors.ENDC}")


def ensure_remote(non_interactive: bool) -> None:
    _, remotes = run_command(["git", "remote", "-v"], show_output=False)
    if "origin" in remotes:
        print(f"{Colors.OKGREEN}✅ Mevcut GitHub bağlantısı algılandı.{Colors.ENDC}")
        return

    if non_interactive:
        print(f"{Colors.FAIL}Origin remote yok ve --non-interactive aktif.{Colors.ENDC}")
        sys.exit(1)

    print(f"{Colors.WARNING}GitHub repo bağlantısı bulunamadı.{Colors.ENDC}")
    repo_url = input(
        f"{Colors.OKBLUE}GitHub Depo URL'sini girin (örn: https://github.com/org/repo): {Colors.ENDC}"
    ).strip()
    if not _is_valid_repo_url(repo_url):
        print(f"{Colors.FAIL}Geçersiz veya boş URL. İşlem iptal edildi.{Colors.ENDC}")
        sys.exit(1)

    run_command(["git", "remote", "add", "origin", repo_url], show_output=False)
    print(f"{Colors.OKGREEN}✅ GitHub deposu bağlandı.{Colors.ENDC}")


def _confirm_deletions(paths: list[str], force_delete: bool, non_interactive: bool) -> bool:
    if not paths:
        return True
    if force_delete:
        return True
    if non_interactive:
        logging.warning("Silme adımı --non-interactive modda ve --force-delete yok: iptal")
        return False

    print(f"{Colors.WARNING}⚠️ {len(paths)} dosya GitHub'dan da silinecek (mirror).{Colors.ENDC}")
    preview = "\n".join(f"  - {p}" for p in paths[:20])
    print(preview)
    if len(paths) > 20:
        print(f"  ... ve {len(paths) - 20} dosya daha")
    answer = input(f"{Colors.OKBLUE}Silmeleri onaylıyor musunuz? (y/n): {Colors.ENDC}").strip().lower()
    return answer == "y"


def stage_plan(plan: SyncPlan, cli: CliArgs) -> None:
    """Planı stage eder (dry-run destekli)."""
    run_command(["git", "reset"], show_output=False)

    if plan.blocked:
        print(f"{Colors.WARNING}⛔ Atlanan (forbidden/binary) yollar:{Colors.ENDC}")
        for blocked in plan.blocked:
            print(f"  - {blocked}")

    if cli.dry_run:
        print(f"{Colors.OKBLUE}[DRY-RUN] Eklenecek/Güncellenecek: {len(plan.add_or_update)} dosya{Colors.ENDC}")
        print(f"{Colors.OKBLUE}[DRY-RUN] Silinecek: {len(plan.delete)} dosya{Colors.ENDC}")
        return

    if plan.add_or_update:
        run_command(["git", "add", "--"] + plan.add_or_update, show_output=False)

    if plan.delete:
        if not _confirm_deletions(plan.delete, cli.force_delete, cli.non_interactive):
            print(f"{Colors.WARNING}Silme senkronizasyonu kullanıcı tarafından iptal edildi.{Colors.ENDC}")
        else:
            run_command(["git", "rm", "--"] + plan.delete, show_output=False)


def build_commit(cli: CliArgs) -> bool:
    print(f"\n{Colors.OKBLUE}📦 Senkronizasyon planı hazırlanıyor...{Colors.ENDC}")
    plan = build_sync_plan(cli.protect_paths, mirror=cli.mirror)
    logging.info("Plan: add/update=%s, delete=%s, blocked=%s", len(plan.add_or_update), len(plan.delete), len(plan.blocked))
    stage_plan(plan, cli)

    if cli.dry_run:
        print(f"{Colors.OKGREEN}✅ Dry-run tamamlandı. Commit/push yapılmadı.{Colors.ENDC}")
        return False

    _, status = run_command(["git", "status", "--porcelain"], show_output=False)
    if not status:
        print(f"{Colors.WARNING}🤷 Değişiklik bulunamadı. Repo zaten güncel.{Colors.ENDC}")
        return False

    version = getattr(cfg, "VERSION", "?")
    default_msg = f"Sidar {version} - Mirror sync ({datetime.now().strftime('%Y-%m-%d %H:%M')})"

    commit_msg = cli.message
    if not commit_msg and not cli.non_interactive:
        print(f"\n{Colors.WARNING}Commit notu girin (boşsa otomatik kullanılacak).{Colors.ENDC}")
        commit_msg = input(f"{Colors.OKBLUE}Commit mesajı: {Colors.ENDC}").strip() or default_msg
    if not commit_msg:
        commit_msg = default_msg

    print(f"\n{Colors.OKBLUE}💾 Commit oluşturuluyor...{Colors.ENDC}")
    commit_success, commit_err = run_command(["git", "commit", "-m", commit_msg], show_output=False)
    if not commit_success:
        print(f"{Colors.FAIL}❌ Commit hatası: {commit_err}{Colors.ENDC}")
        sys.exit(1)

    return True


def _try_push(branch: str) -> tuple[bool, str]:
    return run_command(["git", "push", "-u", "origin", branch], show_output=False)


def _print_push_error(err_msg: str) -> None:
    if "rule violations" in err_msg:
        print(f"\n{Colors.FAIL}❌ GitHub Push Protection engelledi.{Colors.ENDC}")
        print(f"{Colors.WARNING}Muhtemelen gizli bilgi içeren dosya var. Logları inceleyin.{Colors.ENDC}")
    else:
        print(f"{Colors.FAIL}❌ Push hatası:\n{err_msg}{Colors.ENDC}")


def push_with_retry(branch: str) -> tuple[bool, str]:
    for attempt in range(_PUSH_MAX_RETRIES + 1):
        success, err_msg = _try_push(branch)
        if success:
            return True, ""

        if any(kw in err_msg for kw in ("rejected", "fetch first", "non-fast-forward", "rule violations")):
            return False, err_msg

        if attempt < _PUSH_MAX_RETRIES:
            wait = _PUSH_BACKOFF_BASE ** (attempt + 1)
            print(
                f"{Colors.WARNING}⚠️ Push başarısız (deneme {attempt + 1}/{_PUSH_MAX_RETRIES}), {wait}s sonra tekrar...{Colors.ENDC}"
            )
            time.sleep(wait)

    return False, err_msg  # type: ignore[return-value]


def _handle_conflict(branch: str, non_interactive: bool) -> None:
    print(f"{Colors.WARNING}⚠️ Uzakta farklı commitler var (non-fast-forward).{Colors.ENDC}")
    if non_interactive:
        print(f"{Colors.FAIL}--non-interactive modda otomatik merge yapılmadı.{Colors.ENDC}")
        return

    confirm = input(f"{Colors.OKBLUE}Uzak ile otomatik birleştirme yapılsın mı? (y/n): {Colors.ENDC}").strip().lower()
    if confirm != "y":
        print(f"{Colors.WARNING}⏹️ Otomatik birleştirme iptal edildi.{Colors.ENDC}")
        return

    pull_cmd = [
        "git",
        "pull",
        "origin",
        branch,
        "--rebase=false",
        "--allow-unrelated-histories",
        "--no-edit",
        "-X",
        "ours",
    ]
    pull_success, pull_err = run_command(pull_cmd, show_output=False)
    if not (pull_success or "up to date" in pull_err.lower() or "merge made" in pull_err.lower()):
        print(f"{Colors.FAIL}❌ Merge hatası: {pull_err}{Colors.ENDC}")
        return

    retry_success, retry_err = push_with_retry(branch)
    if not retry_success:
        _print_push_error(retry_err)


def parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(description="Sidar GitHub mirror upload aracı")
    parser.add_argument("--dry-run", action="store_true", help="Sadece planı göster, commit/push yapma")
    parser.add_argument("--no-mirror", dest="mirror", action="store_false", help="Delete sync kapat")
    parser.add_argument("--force-delete", action="store_true", help="Silme onayını sormadan uygula")
    parser.add_argument("--protect", action="append", default=[], help="Silinmemesi gereken yol/prefix")
    parser.add_argument("--message", type=str, default=None, help="Commit mesajı")
    parser.add_argument("--non-interactive", action="store_true", help="Input istemeden çalış")
    parser.add_argument("--log-file", type=str, default=DEFAULT_LOG_FILE, help="Log dosyası yolu")
    parser.add_argument("--branch", type=str, default=None, help="Push yapılacak branch")
    parser.set_defaults(mirror=True)
    ns, _unknown = parser.parse_known_args()
    return CliArgs(
        dry_run=ns.dry_run,
        mirror=ns.mirror,
        force_delete=ns.force_delete,
        protect_paths=[_normalize_path(p) for p in ns.protect],
        message=ns.message,
        non_interactive=ns.non_interactive,
        log_file=ns.log_file,
        branch=ns.branch,
    )


def main() -> None:
    cli = parse_args()
    setup_logging(cli.log_file)

    version = getattr(cfg, "VERSION", "3.0")
    print(f"{Colors.HEADER}{'=' * 65}{Colors.ENDC}")
    print(f"{Colors.BOLD} Sidar - GitHub Mirror Upload Aracı (v{version}) {Colors.ENDC}")
    print(f"{Colors.HEADER}{'=' * 65}{Colors.ENDC}\n")

    if not cfg.GITHUB_TOKEN:
        print(f"{Colors.FAIL}GITHUB_TOKEN config.py/.env üzerinden bulunamadı.{Colors.ENDC}")
        sys.exit(1)

    success, _ = run_command(["git", "--version"], show_output=False)
    if not success:
        print(f"{Colors.FAIL}Sistemde Git kurulu değil.{Colors.ENDC}")
        sys.exit(1)

    setup_git_identity(cli.non_interactive)
    ensure_git_repo()
    ensure_remote(cli.non_interactive)
    committed = build_commit(cli)

    if not committed:
        return

    branch = cli.branch
    if not branch:
        _, branch_out = run_command(["git", "branch", "--show-current"], show_output=False)
        branch = branch_out or "main"

    print(f"\n{Colors.HEADER}🚀 GitHub'a yükleniyor (Hedef: {branch})...{Colors.ENDC}")
    push_success, err_msg = push_with_retry(branch)
    if push_success:
        print(f"{Colors.OKGREEN}✅ Push başarılı.{Colors.ENDC}")
    elif any(kw in err_msg for kw in ("rejected", "fetch first", "non-fast-forward")):
        _handle_conflict(branch, cli.non_interactive)
    else:
        _print_push_error(err_msg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.FAIL}İşlem kullanıcı tarafından iptal edildi.{Colors.ENDC}")
        sys.exit(0)
