"""Git working-tree operations used by the upload flow (branches, merges, staging).

Extracted from ``github_upload.py``; collaborators are injected by its wrappers.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from datetime import datetime

from uploader.console import Colors


def create_upload_branch(*, run_command: Callable[..., tuple[bool, str]]) -> str:
    """Create the timestamped branch used by the default PR-first upload flow."""
    branch = f"sidar/upload-{datetime.now():%Y%m%d-%H%M%S}"
    success, error = run_command(["git", "switch", "-c", branch], show_output=False)
    if not success:
        raise RuntimeError(error or "Upload dalı oluşturulamadı.")
    return branch


def get_unmerged_files(*, run_command: Callable[..., tuple[bool, str]]) -> list[str]:
    """Çözülmemiş Git merge çakışması bulunan dosyaları döndürür."""
    success, output = run_command(
        ["git", "diff", "--name-only", "--diff-filter=U"], show_output=False
    )
    if not success or not output:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def switch_back_to_original_branch(
    original_branch: str, *, run_command: Callable[..., tuple[bool, str]]
) -> None:
    """Commit/push'a ulaşmayan erken çıkışlarda kullanıcıyı başladığı dala geri döndürür.

    ``main()`` işleyişini her zaman 'main' üzerinde sürdürmek için otomatik olarak
    'main'e (gerekirse stash ile) geçer. Bu geçişten sonra henüz hiçbir commit/push
    gerçekleşmeden bir hata ("çakışmış dosya", kalite kapısı hatası, upload dalı
    oluşturulamadı vb.) ya da "yüklenecek değişiklik yok" durumuyla çıkılırsa,
    kullanıcı fark etmeden 'main'den türetilmiş bir dalda bırakılmamalıdır.

    Commit SONRASI başarısız olan kalite kapıları için bu fonksiyon KASITLI
    OLARAK çağrılmaz — bkz. ``describe_post_commit_gate_failure``: orada
    kullanıcının çalışması (upload dalı + commit) bilerek korunur ve elle geri
    dönüş talimatı verilir.
    """
    if not original_branch or original_branch == "main":
        return

    _, active_branch = run_command(["git", "branch", "--show-current"], show_output=False)
    active_branch = active_branch.strip()
    if not active_branch or active_branch == original_branch:
        return

    checkout_success, checkout_err = run_command(
        ["git", "checkout", original_branch], show_output=False
    )
    if checkout_success:
        print(f"{Colors.OKBLUE}ℹ️ '{original_branch}' dalına geri dönüldü.{Colors.ENDC}")
    else:
        print(
            f"{Colors.WARNING}⚠️ '{original_branch}' dalına otomatik geri dönülemedi:\n"
            f"{checkout_err}\nManuel olarak 'git checkout {original_branch}' "
            f"çalıştırabilirsiniz.{Colors.ENDC}"
        )


def assert_no_unmerged_files(
    original_branch: str | None = None,
    *,
    get_unmerged_files: Callable[..., list[str]],
    switch_back_to_original_branch: Callable[..., None],
) -> None:
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
    if original_branch:
        switch_back_to_original_branch(original_branch)
    sys.exit(1)


def print_unmerged_files(
    prefix: str = "Çakışan dosyalar", *, get_unmerged_files: Callable[..., list[str]]
) -> None:
    """Kullanıcıya açması gereken unmerged dosyaları okunur biçimde listeler."""
    unmerged_files = get_unmerged_files()
    if not unmerged_files:
        return
    print(f"{Colors.WARNING}{prefix}:{Colors.ENDC}")
    for file_path in unmerged_files:
        print(f"  - {file_path}")


def abort_in_progress_merge(*, run_command: Callable[..., tuple[bool, str]]) -> None:
    """Başarısız pull/merge sonrası çalışma ağacını temiz state'e döndürmeye çalışır."""
    merge_active, _ = run_command(
        ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], show_output=False
    )
    if not merge_active:
        return
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


def create_rollback_backup_tag(*, run_command: Callable[..., tuple[bool, str]]) -> str:
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


def report_ours_strategy_changes(*, run_command: Callable[..., tuple[bool, str]]) -> None:
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


def get_deleted_files(*, run_command: Callable[..., tuple[bool, str]]) -> list[str]:
    """Sistemden silinmiş ama Git'in geçmişte takip ettiği dosyaları bulur."""
    success, output = run_command(["git", "ls-files", "-d"], show_output=False)
    if not success or not output:
        return []

    return [line.strip() for line in output.splitlines() if line.strip()]


def get_commit_count(*, run_command: Callable[..., tuple[bool, str]]) -> int:
    """Aktif dalda rollback için kullanılabilir commit sayısını güvenli biçimde döndürür."""
    success, output = run_command(["git", "rev-list", "--count", "HEAD"], show_output=False)
    if not success or not output:
        return 0

    try:
        return int(output.strip())
    except ValueError:
        return 0


def stage_files(
    file_paths: list[str],
    *,
    get_unmerged_files: Callable[..., list[str]],
    run_command: Callable[..., tuple[bool, str]],
) -> tuple[bool, str]:
    """Dosyaları git'e literal pathspec ile güvenli biçimde ekler."""
    if not file_paths:
        return True, ""

    unmerged_files = get_unmerged_files()
    if unmerged_files:
        return False, "Çözülmemiş çakışmalar var: " + ", ".join(unmerged_files)

    literal_paths = [f":(literal){path}" for path in file_paths]
    return run_command(["git", "add", "--"] + literal_paths, show_output=False)


def stage_deleted_files(
    file_paths: list[str], *, run_command: Callable[..., tuple[bool, str]]
) -> tuple[bool, str]:
    """Silinen dosyaları option injection ve pathspec globbing olmadan stage eder."""
    if not file_paths:
        return True, ""
    literal_paths = [f":(literal){path}" for path in file_paths]
    return run_command(
        ["git", "rm", "--ignore-unmatch", "--"] + literal_paths,
        show_output=False,
    )


def record_upload_source_head(*, run_command: Callable[..., tuple[bool, str]]) -> tuple[bool, str]:
    """Resolve the immutable source revision used by upload evidence and logs."""
    success, output = run_command(["git", "rev-parse", "HEAD"], show_output=False)
    revision = output.strip()
    if not success:
        return False, output
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", revision):
        return False, f"git rev-parse HEAD geçersiz revision döndürdü: {revision or '<boş>'}"
    return True, revision.lower()
