"""Local quality gates run before/after the upload commit and before push.

Extracted from ``github_upload.py``; collaborators are injected by its wrappers.
"""

from __future__ import annotations

from collections.abc import Callable


def run_quality_steps(
    quality_steps: list[tuple[list[str], dict[str, str] | None]],
    *,
    run_command: Callable[..., tuple[bool, str]],
) -> tuple[bool, str]:
    for cmd, extra_env in quality_steps:
        success, output = run_command(cmd, show_output=False, extra_env=extra_env)
        if not success:
            failure = f"{' '.join(cmd)}\n{output}".strip()
            if cmd == ["uv", "run", "ruff", "format", "--check", "."]:
                failure += "\n\nDüzeltmek için: uv run ruff format ."
            return False, failure

    return True, ""


def run_pre_commit_fast_gate(
    *, _run_quality_steps: Callable[..., tuple[bool, str]]
) -> tuple[bool, str]:
    """Kod/test sözleşmesini branch veya commit oluşturulmadan ÖNCE fail-closed çalıştırır.

    Bu kapı yalnızca çalışma ağacındaki mevcut dosyaları kontrol eder (Ruff format,
    Ruff lint, unit testleri); git durumundan bağımsızdır. Kasıtlı olarak
    ``run_post_commit_integrity_gate()``'ten ÖNCE ve upload dalı/commit
    oluşturulmadan önce çalışır: en sık görülen hata sınıfı (bozuk format, kırık
    unit test) burada yakalanınca kullanıcı hiçbir geçici upload dalında/commit'te
    kalmaz — ortada temizlenecek bir şey olmaz.
    """
    return _run_quality_steps(
        [
            (["uv", "run", "ruff", "format", "--check", "."], None),
            (["uv", "run", "ruff", "check", "."], None),
            (["uv", "run", "pytest", "tests/unit", "-q", "--no-cov", "-x"], None),
        ]
    )


def run_post_commit_integrity_gate(
    *,
    _run_quality_steps: Callable[..., tuple[bool, str]],
    ensure_full_git_history_for_manifest_checks: Callable[..., tuple[bool, str]],
) -> tuple[bool, str]:
    """Push öncesi installer/manifest bütünlük kapılarını fail-closed çalıştırır.

    Bu adımlar yalnızca commit alındıktan SONRA anlamlıdır: pin damgalama
    (``stamp_install_manifest_pin_after_commit``) HEAD'in gerçek commit'ini
    gerektirir ve sha256/manifest/installer-smoke kontrolleri de o commit'in
    içeriğini doğrular. Bu kapı, "Installer manifest and smoke gate" job'ının
    (installer-smoke, .github/workflows/ci.yml) pin-drift'i yakalayan kısımlarını
    yerelde tekrarlar; böylece direkt push öncesinde installer drift hataları
    yerelde yakalanır.

    Bu kapı başarısız olursa, o ana kadar oluşturulan upload dalı/commit
    ÖNCEDEN ``run_pre_commit_fast_gate()`` geçmiş demektir — yani kod/test
    sözleşmesi sağlamdır, sadece installer/manifest bütünlüğü eksiktir. Bu
    yüzden çağıran taraf (``main``) burada branch/commit'i sessizce atmak
    yerine kullanıcıya devam/iptal talimatı vermelidir (bkz.
    ``describe_post_commit_gate_failure``).
    """
    history_success, history_err = ensure_full_git_history_for_manifest_checks()
    if not history_success:
        return False, f"git fetch --unshallow origin\n{history_err}".strip()

    return _run_quality_steps(
        [
            (["make", "installer-shellcheck"], None),
            (["sha256sum", "-c", ".sidar_manifest.txt"], None),
            (
                ["uv", "run", "python", "scripts/tools/update_core_install_manifest.py", "--check"],
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
    )


def run_pre_push_quality_gate(
    *,
    run_post_commit_integrity_gate: Callable[..., tuple[bool, str]],
    run_pre_commit_fast_gate: Callable[..., tuple[bool, str]],
) -> tuple[bool, str]:
    """Push öncesi unit/static/installer kapılarının tamamını fail-closed çalıştırır.

    ``run_pre_commit_fast_gate()`` + ``run_post_commit_integrity_gate()``'in
    birleşimidir. Bu tamamı, commit zaten mevcutken tekrar doğrulama yapılan
    akışlarda kullanılır (ör. push reddi sonrası uzak birleştirme retry'ı);
    ilk (varsayılan) upload denemesi bunun yerine iki kapıyı ayrı ayrı,
    branch/commit oluşturulmadan önce ve sonra çağırır — bkz. ``main()``.
    """
    fast_success, fast_err = run_pre_commit_fast_gate()
    if not fast_success:
        return False, fast_err

    return run_post_commit_integrity_gate()


def describe_post_commit_gate_failure(
    current_branch: str, *, direct_main: bool, run_command: Callable[..., tuple[bool, str]]
) -> str:
    """Kalite kapısı commit sonrası başarısız olduğunda kurtarma talimatlarını üretir.

    ``run_post_commit_integrity_gate()`` başarısız olduğunda upload dalı ve
    commit BİLEREK atılmaz (kullanıcı çalışmasını kaybetmesin diye); bunun
    yerine mevcut durumu ve devam/iptal komutlarını açıkça yazdırırız.
    """
    _, head_out = run_command(["git", "rev-parse", "--short", "HEAD"], show_output=False)
    commit = head_out.strip() if head_out and head_out.strip() else "bilinmiyor"

    lines = [
        "",
        "Upload başarısız.",
        f"  Korunan branch : {current_branch}",
        f"  Korunan commit : {commit}",
        "  GitHub'a push  : yapılmadı",
        "",
    ]
    if direct_main:
        lines += [
            "SIDAR_GITHUB_UPLOAD_DIRECT_MAIN açıkken bu commit doğrudan 'main' dalına "
            "alındı; GitHub'a hiçbir şey gönderilmedi.",
            "Devam etmek: sorunu düzeltip aracı tekrar çalıştırın.",
            f"İptal etmek: git reset --hard {commit}~1  (pin damgalama ayrı bir fixup "
            "commit'i oluşturduysa ~2 gerekebilir)",
        ]
    else:
        lines += [
            "Devam etmek (zaten bu daldasınız):",
            f"  git switch {current_branch}",
            "",
            "İptal etmek:",
            "  git switch main",
            f"  git branch -D {current_branch}",
        ]
    return "\n".join(lines)


def run_direct_main_readiness_gate(
    *, run_command: Callable[..., tuple[bool, str]]
) -> tuple[bool, str]:
    """Require local static and production-readiness evidence for direct main pushes.

    PR-first uploads rely on required remote checks after the branch is pushed.
    Direct-main bypasses that review boundary, so it must first pass both the
    explicit static gate and the repository's canonical release-readiness gate.
    """
    commands = [
        ["bash", "run_tests.sh", "--stage", "static"],
        ["make", "production-readiness"],
    ]
    for command in commands:
        success, output = run_command(command, show_output=False)
        if not success:
            return False, f"{' '.join(command)}\n{output}".strip()
    return True, ""
