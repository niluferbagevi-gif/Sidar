import os
import shlex
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import tomllib
from pathlib import Path

import pytest


def test_dark_mode_assets_exist(tmp_path: Path) -> None:
    repo_root = Path(os.getcwd())
    source_dark_css = repo_root / "assets" / "dark_mode.css"
    assert source_dark_css.exists()

    script_dir = tmp_path / "sidar"
    (script_dir / "assets").mkdir(parents=True)
    (script_dir / "assets" / "dark_mode.css").write_text(
        source_dark_css.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (script_dir / "web_ui").mkdir(parents=True)
    (script_dir / "web_ui" / "style.css").write_text("/* light-mode */\n", encoding="utf-8")

    repo_phase_script = textwrap.dedent(
        """
        set -euo pipefail
        source scripts/install_modules/phases/02_repo.sh

        step(){ :; }
        info(){ :; }
        warn(){ :; }
        ok(){ :; }
        install_system_dependencies(){ :; }
        sync_repo(){ :; }

        export SCRIPT_DIR="$1"
        sidar_phase_bootstrap_repo_system
        """
    )

    subprocess.run(
        ["bash", "-lc", repo_phase_script, "sidar-smoke", str(script_dir)],
        cwd=repo_root,
        check=True,
    )

    style_css = script_dir / "web_ui" / "style.css"
    assert style_css.exists()
    assert "background-color" in style_css.read_text(encoding="utf-8")


def test_python_version() -> None:
    assert sys.version_info >= (3, 11)


def test_install_sidar_embedded_manifests_in_sync() -> None:
    repo_root = Path(os.getcwd())
    for tool, extra in (
        ("update_core_install_manifest.py", []),
        ("update_install_module_hash_manifest.py", ["--target", "install_sidar.sh"]),
    ):
        result = subprocess.run(
            [sys.executable, f"scripts/tools/{tool}", *extra, "--check"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"{tool} drift tespit etti. install_sidar.sh içindeki gömülü manifest, "
            "scripts/install_modules veya core/* gerçek dosyalarıyla uyumsuz. "
            "Düzeltmek için scripts/sync_install_module_hashes.sh veya "
            "scripts/sync_install_manifest.sh çalıştırın.\n"
            f"stderr: {result.stderr}"
        )


def _extract_embedded_module_hashes(install_sidar_path: Path) -> str:
    lines = install_sidar_path.read_text(encoding="utf-8").splitlines()
    start: int | None = None
    end: int | None = None
    for idx, line in enumerate(lines):
        if start is None and "<<'SIDAR_MODULE_HASHES_EOF'" in line:
            start = idx + 1
            continue
        if start is not None and line.strip() == "SIDAR_MODULE_HASHES_EOF":
            end = idx
            break
    assert (
        start is not None and end is not None
    ), f"{install_sidar_path} içinde EMBEDDED_MODULE_HASHES_MANIFEST heredoc bloğu bulunamadı."
    return "\n".join(lines[start:end])


def _build_synthetic_bootstrap_origin(repo_root: Path, origin: Path) -> str:
    """Construct a minimal git origin from the live working tree.

    Reflects whatever install_sidar.sh and scripts/install_modules currently
    look like (including uncommitted changes) so the smoke test always exercises
    the on-disk state rather than the last committed snapshot.
    """
    origin.mkdir(parents=True, exist_ok=True)
    required = [
        Path("install_sidar.sh"),
        Path(".sidar_manifest.txt"),
        Path("core/memory.py"),
        Path("core/multimodal.py"),
    ]
    for module in (repo_root / "scripts/install_modules").rglob("*"):
        if module.is_file():
            required.append(module.relative_to(repo_root))

    for rel in required:
        src = repo_root / rel
        dst = origin / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    git = ["git", "-C", str(origin)]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    subprocess.run([*git, "config", "user.email", "smoke@example.com"], check=True)
    subprocess.run([*git, "config", "user.name", "smoke"], check=True)
    subprocess.run([*git, "config", "commit.gpgsign", "false"], check=True)
    subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*git, "commit", "-q", "-m", "synthetic bootstrap origin"], check=True)
    return "main"


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_http_server(url: str, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["wget", "-q", "--spider", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.1)
    raise AssertionError(f"Yerel raw installer HTTP sunucusu hazır olmadı: {url}")


def test_install_sidar_bootstrap_clone_smoke(tmp_path: Path) -> None:
    """Simulate the fresh-user scenario: no local repo, only a raw install_sidar.sh.

    Reproduces the original bug report flow:
      1. User has no repository checked out anywhere.
      2. raw install_sidar.sh is downloaded and executed.
      3. install_sidar.sh detects missing modules and bootstrap-clones the repo.
      4. After clone, verify_install_module_hashes_if_present() runs.
      5. With no ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1, the hash gate must pass and
         the installer must reach the post-verification abort hook cleanly.
    """
    repo_root = Path(os.getcwd())
    origin = tmp_path / "origin"
    branch = _build_synthetic_bootstrap_origin(repo_root, origin)

    host = tmp_path / "host"
    host.mkdir()
    standalone = host / "install_sidar.sh"
    shutil.copy2(repo_root / "install_sidar.sh", standalone)
    standalone.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(host),
        "PWD": str(host),
        "TMPDIR": str(tmp_path),
        "SIDAR_INSTALL_TEST_MODE": "1",
        "SIDAR_INSTALL_ALLOW_BOOTSTRAP_IN_TEST_MODE": "1",
        "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY": "1",
        "SIDAR_BOOTSTRAP_CLONE_URL": f"file://{origin}",
        "SIDAR_BOOTSTRAP_CLONE_PARENT_DIR": str(host),
        "SIDAR_BOOTSTRAP_CLONE_DIRNAME": "Sidar",
        "SIDAR_BOOTSTRAP_CLONE_REF": branch,
        "SIDAR_REPO_BRANCH": branch,
    }
    env.pop("ALLOW_UNVERIFIED_REMOTE_SCRIPTS", None)

    result = subprocess.run(
        ["bash", str(standalone)],
        cwd=host,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        "Bootstrap clone smoke beklenmedik şekilde başarısız oldu (exit="
        f"{result.returncode}).\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "bootstrap clone" in combined.lower(), (
        "Bootstrap clone yolunun çalıştığı doğrulanamadı; install_sidar.sh "
        "muhtemelen mevcut $HOME/Sidar üzerinden re-exec etti."
    )
    assert "Kurulum modül hash doğrulaması başarılı" in combined, (
        "verify_install_module_hashes_if_present başarılı mesajı görülemedi.\n"
        f"--- combined ---\n{combined}"
    )
    assert "ALLOW_UNVERIFIED_REMOTE_SCRIPTS" not in combined, (
        "ALLOW_UNVERIFIED_REMOTE_SCRIPTS bypass mesajı görüldü; manifest "
        "uyumsuzluğu olduğu halde testten kaçınılmış olabilir.\n"
        f"--- combined ---\n{combined}"
    )


def test_install_sidar_wget_raw_bootstrap_clone_smoke(tmp_path: Path) -> None:
    """Exercise the documented wget/chmod flow against a branch-local raw URL."""
    if shutil.which("wget") is None:
        raise AssertionError("wget bu smoke test için gereklidir.")

    repo_root = Path(os.getcwd())
    origin = tmp_path / "origin"
    branch = _build_synthetic_bootstrap_origin(repo_root, origin)

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    shutil.copy2(repo_root / "install_sidar.sh", raw_dir / "install_sidar.sh")

    port = _free_local_port()
    raw_url = f"http://127.0.0.1:{port}/install_sidar.sh"
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=raw_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        _wait_for_http_server(raw_url)

        host = tmp_path / "host"
        host.mkdir()
        subprocess.run(["wget", "-q", raw_url], cwd=host, check=True)
        standalone = host / "install_sidar.sh"
        standalone.chmod(0o755)

        env = {
            **os.environ,
            "HOME": str(host),
            "PWD": str(host),
            "SIDAR_INSTALL_TEST_MODE": "1",
            "SIDAR_INSTALL_ALLOW_BOOTSTRAP_IN_TEST_MODE": "1",
            "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY": "1",
            "SIDAR_BOOTSTRAP_CLONE_URL": f"file://{origin}",
            "SIDAR_BOOTSTRAP_CLONE_PARENT_DIR": str(host),
            "SIDAR_BOOTSTRAP_CLONE_DIRNAME": "Sidar",
            "SIDAR_BOOTSTRAP_CLONE_REF": branch,
            "SIDAR_REPO_BRANCH": branch,
        }
        env.pop("ALLOW_UNVERIFIED_REMOTE_SCRIPTS", None)

        result = subprocess.run(
            ["./install_sidar.sh"],
            cwd=host,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)

    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        "wget raw installer smoke beklenmedik şekilde başarısız oldu (exit="
        f"{result.returncode}).\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    for required_marker in (
        "bootstrap clone",
        "Bootstrap clone tamamlandı",
        "Çekirdek kurulum manifest hash doğrulaması başarılı",
        "Kurulum modül hash doğrulaması başarılı",
        "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY=1",
    ):
        assert required_marker in combined, (
            f"wget raw installer smoke çıktısında beklenen marker yok: {required_marker!r}.\n"
            f"--- combined ---\n{combined}"
        )
    assert "ALLOW_UNVERIFIED_REMOTE_SCRIPTS" not in combined


def test_install_sidar_bootstrap_hash_drift_blocks_install(tmp_path: Path) -> None:
    """Drift case: clone origin carries a tampered module but standalone
    install_sidar.sh's embedded manifest still pins the original hash. The
    installer must refuse to continue without ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1.
    """
    repo_root = Path(os.getcwd())
    origin = tmp_path / "origin"
    branch = _build_synthetic_bootstrap_origin(repo_root, origin)

    # Tamper with a module in the origin after the initial commit so the
    # cloned working tree diverges from the embedded manifest baked into the
    # standalone installer.
    tampered = origin / "scripts/install_modules/utils/ollama_models.sh"
    tampered.write_text(
        tampered.read_text(encoding="utf-8") + "# smoke-test drift\n", encoding="utf-8"
    )
    git = ["git", "-C", str(origin)]
    subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*git, "commit", "-q", "-m", "tamper drift"], check=True)

    host = tmp_path / "host"
    host.mkdir()
    standalone = host / "install_sidar.sh"
    shutil.copy2(repo_root / "install_sidar.sh", standalone)
    standalone.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(host),
        "PWD": str(host),
        "TMPDIR": str(tmp_path),
        "SIDAR_INSTALL_TEST_MODE": "1",
        "SIDAR_INSTALL_ALLOW_BOOTSTRAP_IN_TEST_MODE": "1",
        "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY": "1",
        "SIDAR_BOOTSTRAP_CLONE_URL": f"file://{origin}",
        "SIDAR_BOOTSTRAP_CLONE_PARENT_DIR": str(host),
        "SIDAR_BOOTSTRAP_CLONE_DIRNAME": "Sidar",
        "SIDAR_BOOTSTRAP_CLONE_REF": branch,
        "SIDAR_REPO_BRANCH": branch,
    }
    env.pop("ALLOW_UNVERIFIED_REMOTE_SCRIPTS", None)

    result = subprocess.run(
        ["bash", str(standalone)],
        cwd=host,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, (
        "Tampered modülle drift testi başarısız olmalıydı (exit=0); manifest "
        f"gate kullanıcıyı koruyamadı.\n--- combined ---\n{combined}"
    )
    assert "Kurulum modül hash doğrulaması başarısız" in combined, (
        "Manifest gate'in drift'i hata mesajıyla raporlaması bekleniyordu.\n"
        f"--- combined ---\n{combined}"
    )
    for required_marker in (
        "Karşılaştırma:",
        "Beklenen (raw installer):",
        "Mevcut (klonlanmış repo):",
        "Uyumsuz modüller",
        "scripts/install_modules/utils/ollama_models.sh",
        "scripts/sync_install_module_hashes.sh",
        "ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1",
    ):
        assert required_marker in combined, (
            f"Drift hata mesajında beklenen bilgi yok: {required_marker!r}.\n"
            f"--- combined ---\n{combined}"
        )
    leaked_manifests = sorted(tmp_path.glob("sidar_module_hashes.*"))
    assert leaked_manifests == [], (
        "Embedded module hash manifest geçici dosyası hata yolunda temizlenmeliydi; "
        f"kalan dosyalar: {leaked_manifests}"
    )


def test_install_sidar_embedded_manifest_temp_cleanup_trap_is_registered() -> None:
    installer = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "EMBEDDED_MODULE_HASH_MANIFEST_TEMP_FILE" in installer
    assert "cleanup_embedded_module_hash_manifest_temp_file" in installer
    assert "trap 'cleanup_embedded_module_hash_manifest_temp_file' EXIT" in installer
    assert "trap 'cleanup_embedded_module_hash_manifest_temp_file; exit 130' INT" in installer
    assert "trap 'cleanup_embedded_module_hash_manifest_temp_file; exit 143' TERM" in installer


def test_install_sidar_bootstrap_core_hash_drift_reports_core_layer(tmp_path: Path) -> None:
    """Core drift must be reported as a core manifest failure, not as module drift."""
    repo_root = Path(os.getcwd())
    origin = tmp_path / "origin"
    branch = _build_synthetic_bootstrap_origin(repo_root, origin)

    tampered = origin / "core/memory.py"
    tampered.write_text(
        tampered.read_text(encoding="utf-8") + "\n# smoke-test core drift\n",
        encoding="utf-8",
    )
    git = ["git", "-C", str(origin)]
    subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*git, "commit", "-q", "-m", "tamper core drift"], check=True)

    host = tmp_path / "host"
    host.mkdir()
    standalone = host / "install_sidar.sh"
    shutil.copy2(repo_root / "install_sidar.sh", standalone)
    standalone.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(host),
        "PWD": str(host),
        "SIDAR_INSTALL_TEST_MODE": "1",
        "SIDAR_INSTALL_ALLOW_BOOTSTRAP_IN_TEST_MODE": "1",
        "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY": "1",
        "SIDAR_BOOTSTRAP_CLONE_URL": f"file://{origin}",
        "SIDAR_BOOTSTRAP_CLONE_PARENT_DIR": str(host),
        "SIDAR_BOOTSTRAP_CLONE_DIRNAME": "Sidar",
        "SIDAR_BOOTSTRAP_CLONE_REF": branch,
        "SIDAR_REPO_BRANCH": branch,
    }
    env.pop("ALLOW_UNVERIFIED_REMOTE_SCRIPTS", None)

    result = subprocess.run(
        ["bash", str(standalone)],
        cwd=host,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, (
        "Tampered çekirdek dosya drift testi başarısız olmalıydı (exit=0); "
        f"çekirdek manifest gate kullanıcıyı koruyamadı.\n--- combined ---\n{combined}"
    )
    assert "Güvenlik ihlali: çekirdek kurulum dosyaları hash doğrulamasını geçemedi" in combined
    for required_marker in (
        "kurulum modül manifestinden (scripts/install_modules) değil",
        "kurulum manifestinden gelir",
        "core/memory.py",
        "Uyumsuz çekirdek dosyalar",
        "Uyumsuz çekirdek dosya detayları",
        "Beklenen:",
        "Mevcut:",
        "Bootstrap durumu:",
        "Clone/re-exec tamamlandı",
        "Clone HEAD:",
        "Clone remote:",
        "Raw installer metadata:",
        "Raw installer SHA256:",
        "Clone install_sidar.sh SHA256:",
        "Raw/clone installer ilişkisi:",
        "Repo durumu:",
        "HEAD:",
        "git clone veya helper modül yükleme hatası değildir",
        "hata clone sonrası çekirdek manifest karşılaştırmasında oluştu",
        "scripts/sync_install_manifest.sh",
        "SIDAR_INSTALL_MANIFEST_EOF",
        "core dosyası değiştiği halde çekirdek manifestin",
        "Kurulum güvenlik nedeniyle durduruldu",
        "çekirdek dosya manifesti için bypass uygulanmaz",
    ):
        assert required_marker in combined, (
            f"Çekirdek drift hata mesajında beklenen bilgi yok: {required_marker!r}.\n"
            f"--- combined ---\n{combined}"
        )
    assert "Kurulum modül hash doğrulaması başarısız" not in combined, (
        "Çekirdek drift, modül manifest hatası gibi raporlanmamalı.\n"
        f"--- combined ---\n{combined}"
    )


def _decode_timeout_stream(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _run_bash_smoke(script: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    smoke_env = {**os.environ, "SIDAR_INSTALL_TEST_MODE": "1", "TMPDIR": str(tmp_path)}
    smoke_env.pop("INSTALL_SIDAR_VERSION", None)
    guarded_script = f"""
    unset INSTALL_SIDAR_VERSION
    export SIDAR_INSTALL_TEST_MODE=1
    export TMPDIR={shlex.quote(str(tmp_path))}
    {script}
    """
    timeout_seconds = int(os.environ.get("SIDAR_INSTALL_SMOKE_BASH_TIMEOUT", "180"))
    try:
        return subprocess.run(
            ["bash", "-c", guarded_script],
            cwd=Path(os.getcwd()),
            env=smoke_env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        out = _decode_timeout_stream(exc.stdout)
        err = _decode_timeout_stream(exc.stderr)
        raise AssertionError(
            f"_run_bash_smoke {timeout_seconds}s içinde tamamlanamadı.\n"
            f"--- guarded_script ---\n{guarded_script}\n"
            f"--- partial stdout ---\n{out[-4000:]}\n"
            f"--- partial stderr ---\n{err[-4000:]}\n"
        ) from exc


def _fake_python3_fails_snippet() -> str:
    return """
    mkdir -p "$TMPDIR/fake-bin"
    printf '%s\n' '#!/usr/bin/env bash' \
      'echo "python3 should not be required for SIDAR_INSTALL_TEST_MODE version resolution" >&2' \
      'exit 42' > "$TMPDIR/fake-bin/python3"
    chmod +x "$TMPDIR/fake-bin/python3"
    export PATH="$TMPDIR/fake-bin:$PATH"
    """


def _diagnose_sourced_install_version(tmp_path: Path) -> str:
    diagnosis = _run_bash_smoke(
        f"""
        set -euo pipefail
        {_fake_python3_fails_snippet()}
        source install_sidar.sh >/dev/null
        printf '%s' "${{INSTALL_SIDAR_VERSION:-EMPTY}}"
        """,
        tmp_path,
    )
    return (
        f"--- diagnosis args ---\n{diagnosis.args}\n"
        f"--- diagnosis returncode ---\n{diagnosis.returncode}\n"
        f"--- diagnosis stdout ---\n{diagnosis.stdout!r}\n"
        f"--- diagnosis stderr ---\n{diagnosis.stderr!r}\n"
    )


def test_install_sidar_test_mode_and_uv_only_contract() -> None:
    repo_root = Path(os.getcwd())
    installer = repo_root / "install_sidar.sh"
    installer_text = installer.read_text(encoding="utf-8")
    alembic_phase = repo_root / "scripts" / "install_modules" / "phases" / "12_alembic.sh"
    alembic_prelude = alembic_phase.read_text(encoding="utf-8").split("resolve_alembic_python", maxsplit=1)[0]
    with (repo_root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject_version = tomllib.load(pyproject_file)["project"]["version"]

    assert 'if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]]; then' in installer_text
    assert 'main "$@"' in installer_text
    resolve_idx = installer_text.index("resolve_install_sidar_version()")
    validate_idx = installer_text.index("validate_install_utility_modules()")
    export_idx = installer_text.index("export INSTALL_SIDAR_VERSION")
    load_phase_idx = installer_text.index("load_install_phase_modules\n# END_BUNDLE_MODULES")
    assert resolve_idx < validate_idx
    assert export_idx < load_phase_idx
    assert "load_install_phase_modules\n# END_BUNDLE_MODULES" in installer_text
    assert "modül hash doğrulaması atlandı; fonksiyon modülleri yüklenmeye devam edecek" in installer_text
    assert "mask_install_log_stream | tee" in installer_text
    assert "export INSTALL_SIDAR_VERSION" in installer_text
    assert "uv venv" in installer_text
    assert "set -e" not in alembic_prelude
    assert "set -u" not in alembic_prelude
    assert f"v{pyproject_version}" not in installer_text

    legacy_install_markers = (
        "conda env create",
        "environment.yml",
        "miniconda",
    )
    lowered_installer = installer_text.lower()
    for marker in legacy_install_markers:
        assert marker not in lowered_installer, (
            f"{marker!r} aktif install_sidar.sh akışına geri dönmemeli; "
            "Conda yalnızca docs/archive altında tarihsel kayıt olarak kalabilir."
        )


def test_install_sidar_source_exports_pyproject_version_without_python(tmp_path: Path) -> None:
    repo_root = Path(os.getcwd())
    with (repo_root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject_version = tomllib.load(pyproject_file)["project"]["version"]

    version_result = _run_bash_smoke(
        f"""
        set -euo pipefail
        {_fake_python3_fails_snippet()}
        source install_sidar.sh >/dev/null
        if [[ "${{INSTALL_SIDAR_VERSION:-}}" != {shlex.quote(pyproject_version)} ]]; then
          echo "INSTALL_SIDAR_VERSION=${{INSTALL_SIDAR_VERSION:-<boş>}}; expected={pyproject_version}" >&2
          exit 1
        fi
        """,
        tmp_path,
    )
    assert version_result.returncode == 0, (
        "INSTALL_SIDAR_VERSION sourced akışta beklenen değere set olmadı.\n"
        f"--- args ---\n{version_result.args}\n"
        f"--- stdout ---\n{version_result.stdout!r}\n"
        f"--- stderr ---\n{version_result.stderr!r}\n"
        f"--- INSTALL_SIDAR_VERSION (post-run) ---\n{_diagnose_sourced_install_version(tmp_path)}"
    )


def test_pre_service_smoke_version_preflight_preserves_diagnostics() -> None:
    phase = Path("scripts/install_modules/phases/06_services.sh").read_text(encoding="utf-8")

    assert 'mktemp "${TMPDIR:-/tmp}/sidar_smoke_version.XXXXXX"' in phase
    assert 'local sourced_rc=0' in phase
    assert "</dev/null" in phase
    assert '} 2>"$smoke_preflight_log"' in phase
    assert ')" || sourced_rc=$?' in phase
    assert ')" 2>"$smoke_preflight_log" || sourced_rc=$?' not in phase
    assert 'sed -n \'1,80p\' "$smoke_preflight_log" | sed \'s/^/  | /\'' in phase
    assert "rc=${sourced_rc}" in phase
    assert 'rm -f "$smoke_preflight_log"' in phase
    assert "2>/dev/null || true" not in phase[
        phase.index("local expected_installer_version=") : phase.index("local smoke_log")
    ]


def test_install_alembic_head_check_after_migration(tmp_path: Path) -> None:
    script_dir = tmp_path / "sidar"
    venv_bin = script_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (script_dir / ".env").write_text(
        "DATABASE_URL= postgresql://sidar:sidar@localhost:5432/sidar \n",
        encoding="utf-8",
    )
    (script_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    fake_python = venv_bin / "python"
    fake_python.write_text(
        textwrap.dedent(
            """
            #!/usr/bin/env bash
            set -euo pipefail
            printf '%s\n' "$DATABASE_URL" >> "$SCRIPT_DIR/dburl.log"
            case "$*" in
              "-m alembic current")
                printf '%s\n' "INFO [alembic.runtime.migration] Context impl PostgresqlImpl."
                printf '%s\n' "  1abc23def456 (head)"
                ;;
              "-m alembic heads")
                printf '%s\n' "INFO [alembic.runtime.migration] noisy prefix"
                printf '%s\n' " 1abc23def456 (head)"
                ;;
              *) exit 2 ;;
            esac
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    result = _run_bash_smoke(
        f"""
        set -euo pipefail
        source install_sidar.sh > "$TMPDIR/source-install.out" 2>&1
        if grep -Eq "Ön Koşullar Kontrol Ediliyor|Kurulum yöneticisi|Sidar AI.*Kurulum" "$TMPDIR/source-install.out"; then
          echo "install_sidar.sh source işlemi main() kurulum akışını tetikledi" >&2
          cat "$TMPDIR/source-install.out" >&2
          exit 1
        fi
        test "${{LOG_FILE:-}}" = ""
        SCRIPT_DIR={shlex.quote(str(script_dir))}
        export SCRIPT_DIR
        if ! is_alembic_at_head; then
          echo "is_alembic_at_head failed" >&2
          exit 1
        fi
        test "$(sort -u "$SCRIPT_DIR/dburl.log")" = "postgresql://sidar:sidar@localhost:5432/sidar"
        """,
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_install_alembic_head_check_requires_database_url(tmp_path: Path) -> None:
    script_dir = tmp_path / "sidar"
    venv_bin = script_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (script_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    fake_python = venv_bin / "python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$SCRIPT_DIR/unexpected-alembic-call.log\"\n"
        "exit 2\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    result = _run_bash_smoke(
        f"""
        set -euo pipefail
        source install_sidar.sh
        SCRIPT_DIR={shlex.quote(str(script_dir))}
        export SCRIPT_DIR
        unset DATABASE_URL
        if is_alembic_at_head; then
          echo "is_alembic_at_head should fail without DATABASE_URL" >&2
          exit 1
        fi
        test ! -e "$SCRIPT_DIR/unexpected-alembic-call.log"
        """,
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_env_keys_synced_across_profiles(tmp_path: Path) -> None:
    script_dir = tmp_path / "sidar"
    script_dir.mkdir()
    source_check = _run_bash_smoke("set -euo pipefail; source install_sidar.sh; type sidar_user_api_key_names >/dev/null", tmp_path)
    if source_check.returncode != 0:
        pytest.skip(
            "install_sidar.sh source edilemedi; API key senkronizasyon adımı anlamlı şekilde çalıştırılamaz.\n"
            f"{source_check.stdout}{source_check.stderr}"
        )

    key_script = "source install_sidar.sh; sidar_user_api_key_names"
    keys_result = _run_bash_smoke(key_script, tmp_path)
    assert keys_result.returncode == 0, keys_result.stdout + keys_result.stderr
    keys = [line.strip() for line in keys_result.stdout.splitlines() if line.strip()]
    assert len(keys) == 18

    env_lines = [f"{key}=value_{idx}" for idx, key in enumerate(keys, start=1)]
    (script_dir / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    for name in (".env.advanced", ".env.development", ".env.test"):
        (script_dir / name).write_text("\n".join(f"{key}=" for key in keys) + "\n", encoding="utf-8")

    result = _run_bash_smoke(
        f"""
        set -euo pipefail
        source install_sidar.sh
        SCRIPT_DIR={shlex.quote(str(script_dir))}
        ENV_FILE="$SCRIPT_DIR/.env"
        NO_INTERACTION=true
        export SCRIPT_DIR ENV_FILE NO_INTERACTION
        collect_api_keys_interactive "$ENV_FILE"
        for profile in .env.advanced .env.development .env.test; do
          for key in $(sidar_user_api_key_names); do
            expected=$(read_env_value_from_file "$key" "$ENV_FILE")
            actual=$(read_env_value_from_file "$key" "$SCRIPT_DIR/$profile")
            if [[ "$actual" != "$expected" ]]; then
              echo "$profile:$key expected=$expected actual=$actual" >&2
              exit 1
            fi
          done
        done
        report_env_api_key_status "$ENV_FILE"
        test "$ENV_API_KEYS_TOTAL" -eq 18
        test "$ENV_API_KEYS_FILLED" -eq 18
        """,
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_playwright_ubuntu26_override_used(tmp_path: Path) -> None:
    os_release = tmp_path / "os-release"
    os_release.write_text('ID=ubuntu\nVERSION_ID="26.04"\n', encoding="utf-8")
    fake_python = tmp_path / "python"
    fake_python.write_text("#!/usr/bin/env bash\nprintf '26.04\\n'\n", encoding="utf-8")
    fake_python.chmod(0o755)
    override_file = tmp_path / "override-os-release"

    result = _run_bash_smoke(
        f"""
        set -euo pipefail
        source scripts/install_modules/utils/playwright_ubuntu_override.sh
        is_playwright_ubuntu_override_recommended {shlex.quote(str(os_release))}
        supported=$(playwright_latest_supported_ubuntu_version {shlex.quote(str(os_release))} {shlex.quote(str(fake_python))})
        test "$supported" = "26.04"
        test "$(playwright_ubuntu_override_platform "$supported")" = "ubuntu26.04-x64"
        prepare_playwright_ubuntu_override_file {shlex.quote(str(os_release))} {shlex.quote(str(override_file))} "$supported"
        grep -q 'VERSION_ID="26.04"' {shlex.quote(str(override_file))}
        """,
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_compose_health_wait_timeout_honors_env(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    compose = fake_bin / "compose"
    compose.write_text(
        "#!/usr/bin/env bash\nif [[ $1 == ps && $2 == -q ]]; then echo fake-container; exit 0; fi\nexit 2\n",
        encoding="utf-8",
    )
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\nif [[ $1 == inspect ]]; then echo starting; exit 0; fi\nexit 0\n",
        encoding="utf-8",
    )
    compose.chmod(0o755)
    docker.chmod(0o755)

    result = _run_bash_smoke(
        f"""
        set -euo pipefail
        export PATH={shlex.quote(str(fake_bin))}:$PATH
        export COMPOSE_HEALTH_WAIT_TIMEOUT_SECONDS=1
        export COMPOSE_HEALTH_WAIT_POLL_SECONDS=1
        source install_sidar.sh
        if wait_for_compose_services_health compose -- postgres; then
          echo "timeout was expected" >&2
          exit 1
        fi
        """,
        tmp_path,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "timeout=1s" in combined
    assert "Servis health timeout: postgres" in combined


def test_bundled_install_sidar_manifest_matches() -> None:
    repo_root = Path(os.getcwd())
    bundle_script = repo_root / "scripts" / "tools" / "bundle_install_sidar.sh"
    subprocess.run(["bash", str(bundle_script)], cwd=repo_root, check=True)

    bundled_installer = repo_root / "dist" / "install_sidar.sh"
    module_hashes = repo_root / "dist" / "MODULE_HASHES.txt"
    assert bundled_installer.exists(), "Bundle çıktısı dist/install_sidar.sh oluşmadı."
    assert module_hashes.exists(), "Bundle çıktısı dist/MODULE_HASHES.txt oluşmadı."

    embedded = _extract_embedded_module_hashes(repo_root / "install_sidar.sh")
    manifest_payload = "\n".join(
        line
        for line in module_hashes.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    assert embedded == manifest_payload, (
        "install_sidar.sh gömülü modül hash manifesti dist/MODULE_HASHES.txt ile "
        "uyumsuz. Bundle release'i durdurun ve scripts/sync_install_module_hashes.sh "
        "çalıştırdıktan sonra yeniden bundle alın."
    )
