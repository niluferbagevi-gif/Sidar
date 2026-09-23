"""Installer manifest sync and pin stamping around the upload commit.

Extracted from ``github_upload.py``; collaborators are injected by its wrappers.
"""

from __future__ import annotations

from collections.abc import Callable


def sync_install_manifests_before_commit(
    *, run_command: Callable[..., tuple[bool, str]]
) -> tuple[bool, str]:
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


def stamp_install_manifest_pin_after_commit(
    *, run_command: Callable[..., tuple[bool, str]], stage_files: Callable[..., tuple[bool, str]]
) -> tuple[bool, str]:
    """Az önce oluşturulan commit'i install_sidar.sh'ın embedded modül pinine damgalar.

    Pin, commit oluşturulmadan ÖNCE damgalanırsa HEAD hâlâ PARENT commit'i işaret
    eder; scripts/install_modules/* bu commit'te değiştiyse pin, gömülü modül
    hash'leriyle asla eşleşmeyen bir commit'e sabitlenmiş olur ve raw tek dosya
    kurulumu kırılır (bkz. docs/CI_REQUIRED_CHECKS.md "Installer manifest and
    smoke gate"). Bu yüzden damgalama burada, commit gerçekten oluşturulduktan
    SONRA çalışır. Pin, kendi içinde bulunduğu commit'e değil (bu, commit
    hash'i kendi içeriğine bağlı olduğu için imkânsızdır), bu commit'i takip
    eden ayrı ve küçük bir fixup commit'ine yazılır.

    Damganın yazdığı SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT satırı 40 karakter
    hex bir commit SHA'sı olduğu için detect-secrets bunu "Hex High Entropy
    String" olarak işaretler; .secrets.baseline bu satırın hash'ini sabitler ve
    pin her değiştiğinde baseline bayatlar (bkz. commit 5ccfe56 — o zaman
    baseline elle tazelendi). Bu, tek seferlik değil, pin her damgalandığında
    tekrar eden bir durum olduğundan burada da otomatik tazeleniyor: dosyayı
    detect-secrets ile yeniden tarayıp baseline'ı güncelliyoruz ve değiştiyse
    aynı fixup commit'ine dahil ediyoruz — aksi halde pre-commit hook'u bu
    fixup commit'ini her seferinde reddeder.
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

    rescan_success, rescan_err = run_command(
        [
            "uv",
            "run",
            "detect-secrets",
            "scan",
            "--baseline",
            ".secrets.baseline",
            "install_sidar.sh",
        ],
        show_output=False,
    )
    if not rescan_success:
        return False, rescan_err

    fixup_paths = ["install_sidar.sh"]
    baseline_diff_success, baseline_diff_out = run_command(
        ["git", "diff", "--name-only", "--", ".secrets.baseline"], show_output=False
    )
    if not baseline_diff_success:
        return False, baseline_diff_out
    if baseline_diff_out.strip():
        fixup_paths.append(".secrets.baseline")

    add_success, add_err = stage_files(fixup_paths)
    if not add_success:
        return False, add_err

    commit_success, commit_err = run_command(
        ["git", "commit", "-m", f"Pin install_sidar.sh embedded module commit to {commit}"],
        show_output=False,
    )
    if not commit_success:
        return False, commit_err

    return True, ""


def ensure_full_git_history_for_manifest_checks(
    *, run_command: Callable[..., tuple[bool, str]]
) -> tuple[bool, str]:
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
