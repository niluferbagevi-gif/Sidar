import hashlib
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

pytestmark = pytest.mark.installer_smoke


_SENSITIVE_ENV_KEYS = {
    "SIDAR_KEYS_FILE",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "LITELLM_API_KEY",
    "GITHUB_TOKEN",
    "SLACK_TOKEN",
    "SLACK_APP_LEVEL_TOKEN",
    "JIRA_TOKEN",
}


def _installer_test_env(tmp_path: Path | None = None) -> dict[str, str]:
    """Return a minimal, secret-scrubbed environment for installer subprocesses."""
    allowed = {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TERM",
        "USER",
        "LOGNAME",
        "SHELL",
        "WSL_DISTRO_NAME",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    for key in _SENSITIVE_ENV_KEYS:
        env.pop(key, None)

    env.update(
        {
            "SIDAR_ENV": "test",
            "SIDAR_KEYS_FILE": "",
            "SIDAR_TEST_LOAD_REAL_KEYS": "0",
            "SIDAR_INSTALL_TEST_MODE": "1",
        }
    )
    if tmp_path is not None:
        env["TMPDIR"] = str(tmp_path)

    return env


def test_installer_test_env_scrubs_sensitive_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in _SENSITIVE_ENV_KEYS:
        monkeypatch.setenv(key, f"secret-{key.lower()}")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))

    env = _installer_test_env(tmp_path)

    assert env["SIDAR_ENV"] == "test"
    assert env["SIDAR_KEYS_FILE"] == ""
    assert env["SIDAR_TEST_LOAD_REAL_KEYS"] == "0"
    assert env["SIDAR_INSTALL_TEST_MODE"] == "1"
    assert env["TMPDIR"] == str(tmp_path)
    assert all(env.get(key, "") == "" for key in _SENSITIVE_ENV_KEYS)


def _sha256_for_test(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _extract_bash_function(script_text: str, function_name: str) -> str:
    start_marker = f"{function_name}() {{"
    marker_start = script_text.index(start_marker)
    start = script_text.rfind("\n", 0, marker_start) + 1
    lines = script_text[start:].splitlines()
    collected: list[str] = []
    first_line = lines[0]
    close_line = f"{first_line[: len(first_line) - len(first_line.lstrip())]}}}"
    for line in lines:
        collected.append(line.rstrip())
        if line == close_line:
            break
    return "\n".join(collected) + "\n"


def _normalize_bash_function(function_text: str) -> str:
    return "\n".join(line.lstrip() for line in function_text.splitlines()) + "\n"


def test_dark_mode_assets_exist(tmp_path: Path) -> None:
    repo_root = Path(os.getcwd())
    source_dark_css = repo_root / "assets" / "dark_mode.css"
    assert source_dark_css.exists()

    script_dir = tmp_path / "sidar"
    (script_dir / "assets").mkdir(parents=True)
    (script_dir / "assets" / "dark_mode.css").write_text(
        source_dark_css.read_text(encoding="utf-8"), encoding="utf-8"
    )
    html_report = script_dir / "htmlcov" / "index.html"
    html_report.parent.mkdir(parents=True)
    html_report.write_text(
        '<html><body class="light-mode"><a href="/light-mode/help">light-mode text</a></body></html>',
        encoding="utf-8",
    )

    repo_phase_script = textwrap.dedent(
        """
        set -euo pipefail
        source scripts/install_modules/phases/02_repo.sh

        warn(){ :; }
        ok(){ :; }

        export SCRIPT_DIR="$1"
        sidar_phase_apply_coverage_dark_mode_assets
        """
    )

    subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", repo_phase_script, "sidar-smoke", str(script_dir)],
        cwd=repo_root,
        env=_installer_test_env(tmp_path),
        check=True,
    )

    coverage_css = script_dir / "htmlcov" / "assets" / "dark_mode.css"
    artifact_coverage_css = script_dir / "artifacts" / "htmlcov" / "assets" / "dark_mode.css"
    assert coverage_css.exists()
    assert artifact_coverage_css.exists()
    assert "background-color" in coverage_css.read_text(encoding="utf-8")
    html = html_report.read_text(encoding="utf-8")
    assert 'class="dark-mode"' in html
    assert '/light-mode/help' in html
    assert '>light-mode text<' in html


def test_python_version() -> None:
    assert sys.version_info >= (3, 11)


def test_installer_hash_guard_inline_fallback_matches_module() -> None:
    """Raw installer fallback hash guard must stay in sync with the module copy."""
    repo_root = Path(os.getcwd())
    installer = (repo_root / "install_sidar.sh").read_text(encoding="utf-8")
    module = (
        repo_root / "scripts" / "install_modules" / "utils" / "installer_hash_guard.sh"
    ).read_text(encoding="utf-8")

    for function_name in (
        "check_installer_hash",
        "verify_reexec_installer_or_fail",
        "sidar_resolve_resume_installer_path",
        "sidar_verify_resume_installer_or_fail",
        "verify_home_reexec_candidate_if_present",
    ):
        module_function = _normalize_bash_function(_extract_bash_function(module, function_name))
        installer_function = _normalize_bash_function(
            _extract_bash_function(installer, function_name)
        )
        assert installer_function == module_function


def test_repo_sync_uses_configured_branch_for_update_and_recovery() -> None:
    phase = Path("scripts/install_modules/phases/02_repo.sh").read_text(encoding="utf-8")

    assert 'local repo_branch="${REPO_BRANCH:-main}"' in phase
    assert 'git clone "$REPO_URL" --depth=1 --branch "$repo_branch" "$TARGET_DIR"' in phase
    assert 'git fetch origin "$repo_branch"' in phase
    assert 'git rebase "origin/${repo_branch}"' in phase
    assert 'git pull --rebase origin main' not in phase
    assert 'git fetch origin main' not in phase
    assert 'git reset --hard origin/main' not in phase


def test_auto_heal_resume_uses_repo_installer_after_bootstrap_cleanup(tmp_path: Path) -> None:
    home_dir = tmp_path / "home"
    repo_dir = tmp_path / "Sidar"
    marker = tmp_path / "resume-marker.txt"
    home_dir.mkdir()
    repo_dir.mkdir()

    temporary_installer = home_dir / "install_sidar.sh"
    temporary_installer.write_text("#!/usr/bin/env bash\nexit 77\n", encoding="utf-8")
    temporary_installer.chmod(0o755)

    repo_installer = repo_dir / "install_sidar.sh"
    repo_installer.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            printf '%s|%s|%s\n' "$0" "${{SIDAR_INSTALL_RESUME_FROM_PHASE:-}}" "${{SIDAR_INSTALL_REMEDIATION_ATTEMPT:-}}" > {shlex.quote(str(marker))}
            """
        ),
        encoding="utf-8",
    )
    repo_installer.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            textwrap.dedent(
                """
                set -euo pipefail
                info() { printf 'INFO:%s\n' "$*"; }
                ok() { printf 'OK:%s\n' "$*"; }
                warn() { printf 'WARN:%s\n' "$*"; }
                fail() { printf 'FAIL:%s\n' "$*" >&2; exit 1; }
                compute_sha256() { sha256sum "$1" | awk '{print $1}'; }

                source scripts/install_modules/utils/installer_hash_guard.sh
                source scripts/install_modules/phases/11_post_install.sh
                source scripts/install_modules/utils/install_remediation.sh

                export TARGET_DIR="$1"
                export SCRIPT_DIR="$1"
                export ORIGINAL_SCRIPT_PATH="$2"
                export ORIGINAL_SCRIPT_DIR="$(dirname "$2")"
                SIDAR_INSTALL_ORIGINAL_ARGS=()

                cleanup_bootstrap_script_copy
                [[ ! -e "$2" ]]
                [[ "$ORIGINAL_SCRIPT_PATH" == "$1/install_sidar.sh" ]]
                [[ "$ORIGINAL_SCRIPT_DIR" == "$1" ]]

                sidar_resume_after_remediation 06_services 2
                """
            ),
            "sidar-resume-smoke",
            str(repo_dir),
            str(temporary_installer),
        ],
        cwd=Path(os.getcwd()),
        env=_installer_test_env(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert marker.read_text(encoding="utf-8") == f"{repo_installer}|06_services|2\n"
    assert "Geçici kurulum betiği kaldırıldı" in result.stdout
    assert "Resume kaynağı repo installer'ına geçirildi" in result.stdout


def test_runtime_database_url_source_labels_survive_successful_resolution(tmp_path: Path) -> None:
    script = textwrap.dedent(
        """
        set -euo pipefail
        source scripts/install_modules/utils/env_utils.sh
        source scripts/install_modules/utils/database_url.sh

        SCRIPT_DIR="$1"
        unset DATABASE_URL DOTENV_FILE RUNTIME_DATABASE_URL RUNTIME_DATABASE_URL_SOURCE

        export DATABASE_URL="postgresql+asyncpg://sidar:proc@localhost:5432/sidar"
        resolve_runtime_database_url >/dev/null
        printf 'process=%s\n' "$RUNTIME_DATABASE_URL_SOURCE"

        unset DATABASE_URL RUNTIME_DATABASE_URL RUNTIME_DATABASE_URL_SOURCE
        cat > "$SCRIPT_DIR/.env" <<'EOF'
DATABASE_URL=postgresql+asyncpg://sidar:env@localhost:5432/sidar
EOF
        resolve_runtime_database_url >/dev/null
        printf 'env_database=%s\n' "$RUNTIME_DATABASE_URL_SOURCE"

        unset RUNTIME_DATABASE_URL RUNTIME_DATABASE_URL_SOURCE
        cat > "$SCRIPT_DIR/.env" <<'EOF'
SIDAR_ENV=development
EOF
        cat > "$SCRIPT_DIR/.env.development" <<'EOF'
DATABASE_URL=postgresql+asyncpg://sidar:dev@localhost:5432/sidar
EOF
        resolve_runtime_database_url >/dev/null
        printf 'development_database=%s\n' "$RUNTIME_DATABASE_URL_SOURCE"

        unset RUNTIME_DATABASE_URL RUNTIME_DATABASE_URL_SOURCE
        cat > "$SCRIPT_DIR/.env" <<'EOF'
POSTGRES_USER=sidar
POSTGRES_PASSWORD=parts
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=sidar
EOF
        rm -f "$SCRIPT_DIR/.env.development"
        resolve_runtime_database_url >/dev/null
        printf 'env_postgres=%s\n' "$RUNTIME_DATABASE_URL_SOURCE"
        """
    )

    result = subprocess.run(
        ["bash", "-c", script, "sidar-db-url-source", str(tmp_path)],
        cwd=Path(os.getcwd()),
        env=_installer_test_env(tmp_path),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "process=process:DATABASE_URL" in result.stdout
    assert "env_database=.env:DATABASE_URL" in result.stdout
    assert "development_database=.env.development:DATABASE_URL" in result.stdout
    assert "env_postgres=.env:POSTGRES_*" in result.stdout
    assert "bilinmiyor" not in result.stdout


def test_run_migrations_logs_resolved_database_url_source_not_unknown(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python_stub = fake_bin / "python3"
    python_stub.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "${1:-}" == "-m" && "${2:-}" == "alembic" ]]; then
              case "${3:-}" in
                upgrade) echo "upgrade ok"; exit 0 ;;
                current) echo "  0001_initial (head)"; exit 0 ;;
                heads) echo "  0001_initial (head)"; exit 0 ;;
              esac
            fi
            exit 1
            """
        ),
        encoding="utf-8",
    )
    python_stub.chmod(0o755)
    (tmp_path / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")

    script = textwrap.dedent(
        """
        set -euo pipefail
        source scripts/install_modules/utils/env_utils.sh
        source scripts/install_modules/utils/database_url.sh
        source scripts/install_modules/phases/12_alembic.sh

        step() { :; }
        info() { printf 'INFO:%s\n' "$*"; }
        ok() { printf 'OK:%s\n' "$*"; }
        warn() { printf 'WARN:%s\n' "$*"; }
        fail() { printf 'FAIL:%s\n' "$*" >&2; exit 1; }
        debug() { :; }

        export SCRIPT_DIR="$1"
        export PATH="$2:$PATH"
        export DATABASE_URL="sqlite:///$1/alembic-smoke.db"
        export DOCKER_ONLY=false
        export MIGRATION_DOCKER_POLICY=disabled

        run_migrations
        """
    )

    result = subprocess.run(
        ["bash", "-c", script, "sidar-alembic-source", str(tmp_path), str(fake_bin)],
        cwd=Path(os.getcwd()),
        env=_installer_test_env(tmp_path),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "Alembic DB URL kaynağı: process:DATABASE_URL" in result.stdout
    assert "Alembic DB URL kaynağı: bilinmiyor" not in result.stdout


def test_install_sidar_embedded_manifests_in_sync() -> None:
    repo_root = Path(os.getcwd())
    for tool, extra in (
        ("update_core_install_manifest.py", []),
        ("update_install_module_hash_manifest.py", ["--target", "install_sidar.sh"]),
    ):
        result = subprocess.run(
            [sys.executable, f"scripts/tools/{tool}", *extra, "--check"],
            cwd=repo_root,
            env=_installer_test_env(),
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
    assert start is not None and end is not None, (
        f"{install_sidar_path} içinde EMBEDDED_MODULE_HASHES_MANIFEST heredoc bloğu bulunamadı."
    )
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
    subprocess.run([*git, "init", "-q", "-b", "main"], env=_installer_test_env(origin), check=True)
    subprocess.run([*git, "config", "user.email", "smoke@example.com"], env=_installer_test_env(origin), check=True)
    subprocess.run([*git, "config", "user.name", "smoke"], env=_installer_test_env(origin), check=True)
    subprocess.run([*git, "config", "commit.gpgsign", "false"], env=_installer_test_env(origin), check=True)
    subprocess.run([*git, "add", "-A"], env=_installer_test_env(origin), check=True, capture_output=True)
    subprocess.run([*git, "commit", "-q", "-m", "synthetic bootstrap origin"], env=_installer_test_env(origin), check=True)
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
            env=_installer_test_env(),
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.1)
    raise AssertionError(f"Yerel raw installer HTTP sunucusu hazır olmadı: {url}")


def test_install_sidar_direct_module_download_smoke(tmp_path: Path) -> None:
    """Simulate the fresh-user scenario: no local repo, only a raw install_sidar.sh.

    The installer should detect the missing local scripts/install_modules tree,
    download the pinned module set directly, then continue through bootstrap
    synchronization before an abort-after-hash smoke exit if core files were
    unavailable to the standalone raw script.
    """
    repo_root = Path(os.getcwd())
    origin = tmp_path / "origin"
    branch = _build_synthetic_bootstrap_origin(repo_root, origin)

    host = tmp_path / "host"
    host.mkdir()
    standalone = host / "install_sidar.sh"
    shutil.copy2(repo_root / "install_sidar.sh", standalone)
    standalone.chmod(0o755)

    env = _installer_test_env(tmp_path) | {
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
        "SIDAR_INSTALL_MODULE_BASE_URL": (origin / "scripts/install_modules").as_uri(),
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
    assert "Git clone/re-exec öncesi fallback modüller doğrudan indirilecek" in combined
    assert "Fallback modül indirildi: install_helpers.sh ->" in combined
    assert "çekirdek manifest doğrulaması repo senkronizasyonu sonrasına ertelendi" in combined
    assert "Bootstrap clone tamamlandı" in combined
    assert "Test modu file:// fallback modül doğrulaması atlandı" in combined, (
        "file:// test fixture için fallback modül indirme doğrulaması görülemedi.\n"
        f"--- combined ---\n{combined}"
    )
    assert "ALLOW_UNVERIFIED_REMOTE_SCRIPTS" not in combined, (
        "ALLOW_UNVERIFIED_REMOTE_SCRIPTS bypass mesajı görüldü; manifest "
        "uyumsuzluğu olduğu halde testten kaçınılmış olabilir.\n"
        f"--- combined ---\n{combined}"
    )


def test_install_sidar_wget_raw_direct_module_download_smoke(tmp_path: Path) -> None:
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
        env=_installer_test_env(tmp_path),
    )
    try:
        _wait_for_http_server(raw_url)

        host = tmp_path / "host"
        host.mkdir()
        subprocess.run(["wget", "-q", raw_url], cwd=host, env=_installer_test_env(tmp_path), check=True)
        standalone = host / "install_sidar.sh"
        standalone.chmod(0o755)

        env = _installer_test_env(tmp_path) | {
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
            "SIDAR_INSTALL_MODULE_BASE_URL": (origin / "scripts/install_modules").as_uri(),
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
        "Git clone/re-exec öncesi fallback modüller doğrudan indirilecek",
        "Fallback modül indirildi: install_helpers.sh ->",
        "Test modu file:// fallback modül doğrulaması atlandı",
        "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY=1",
        "çekirdek manifest doğrulaması repo senkronizasyonu sonrasına ertelendi",
        "Bootstrap clone tamamlandı",
    ):
        assert required_marker in combined, (
            f"wget raw installer smoke çıktısında beklenen marker yok: {required_marker!r}.\n"
            f"--- combined ---\n{combined}"
        )
    assert "ALLOW_UNVERIFIED_REMOTE_SCRIPTS" not in combined


def test_install_sidar_direct_module_hash_drift_blocks_install(tmp_path: Path) -> None:
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
    subprocess.run([*git, "add", "-A"], env=_installer_test_env(tmp_path), check=True, capture_output=True)
    subprocess.run([*git, "commit", "-q", "-m", "tamper drift"], env=_installer_test_env(tmp_path), check=True)

    host = tmp_path / "host"
    host.mkdir()
    standalone = host / "install_sidar.sh"
    shutil.copy2(repo_root / "install_sidar.sh", standalone)
    standalone.chmod(0o755)

    env = _installer_test_env(tmp_path) | {
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
        "SIDAR_INSTALL_MODULE_BASE_URL": (origin / "scripts/install_modules").as_uri(),
        "SIDAR_INSTALL_ENFORCE_FILE_MODULE_HASHES": "1",
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
    assert "Fallback modül hash doğrulaması başarısız: utils/ollama_models.sh" in combined, (
        "Direct module fallback hash gate'in drift'i hata mesajıyla raporlaması bekleniyordu.\n"
        f"--- combined ---\n{combined}"
    )
    for required_marker in (
        "Git clone/re-exec öncesi fallback modüller doğrudan indirilecek",
        "beklenen=",
        "mevcut=",
        "utils/ollama_models.sh",
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


def test_install_sidar_home_reexec_hash_drift_blocks_stale_installer(tmp_path: Path) -> None:
    """A stale $HOME/Sidar installer must not be re-execed silently."""
    repo_root = Path(os.getcwd())
    host = tmp_path / "home"
    run_dir = tmp_path / "run"
    stale_repo = host / "Sidar"
    host.mkdir()
    run_dir.mkdir()
    (stale_repo / ".git").mkdir(parents=True)
    stale_installer = stale_repo / "install_sidar.sh"
    stale_installer.write_text(
        "#!/usr/bin/env bash\necho stale-installer-ran >&2\nexit 42\n",
        encoding="utf-8",
    )
    stale_installer.chmod(0o755)

    standalone = run_dir / "install_sidar.sh"
    shutil.copy2(repo_root / "install_sidar.sh", standalone)
    standalone.chmod(0o755)

    env = _installer_test_env(tmp_path) | {
        "HOME": str(host),
        "PWD": str(run_dir),
        "TMPDIR": str(tmp_path),
        "SIDAR_INSTALL_TEST_MODE": "1",
        "SIDAR_INSTALL_ALLOW_HOME_REEXEC_IN_TEST_MODE": "1",
        "SIDAR_INSTALL_ALLOW_STALE_REEXEC": "0",
    }

    result = subprocess.run(
        ["bash", str(standalone)],
        cwd=run_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    combined = result.stdout + result.stderr
    debug_context = textwrap.dedent(
        f"""
        --- install_sidar home re-exec hash drift debug ---
        cwd: {run_dir}
        HOME: {env["HOME"]}
        PWD: {env["PWD"]}
        TMPDIR: {env["TMPDIR"]}
        SIDAR_INSTALL_TEST_MODE: {env["SIDAR_INSTALL_TEST_MODE"]}
        SIDAR_INSTALL_ALLOW_HOME_REEXEC_IN_TEST_MODE: {env["SIDAR_INSTALL_ALLOW_HOME_REEXEC_IN_TEST_MODE"]}
        standalone: {standalone}
        standalone_sha256: {_sha256_for_test(standalone)}
        stale_installer: {stale_installer}
        stale_installer_sha256: {_sha256_for_test(stale_installer)}
        returncode: {result.returncode}
        --- stdout ---
        {result.stdout}
        --- stderr ---
        {result.stderr}
        --- combined ---
        {combined}
        """
    ).strip()

    assert result.returncode != 42, (
        "Stale $HOME/Sidar/install_sidar.sh çalıştırılmamalıydı; returncode=42 "
        "stale betiğin gerçekten exec edildiğini gösterir.\n"
        f"{debug_context}"
    )
    assert result.returncode != 0, (
        "Hash drift guard stale re-exec yolunu durdurmalıydı; returncode=0 fallback veya normal "
        "kurulum akışının drift'i maskelendiğini gösterir.\n"
        f"{debug_context}"
    )
    assert "Mevcut" in combined and "re-exec install_sidar.sh SHA256 farklı" in combined, (
        f"Installer hash drift hatası kullanıcıya açık şekilde raporlanmalıydı.\n{debug_context}"
    )
    assert "NEXT STEP → hash drift kaynağını temizleyin" in combined
    assert 'rm -f "$HOME/Sidar/install_sidar.sh"' in combined
    assert "stale-installer-ran" not in combined, (
        "Stale installer çıktısı görülmemeliydi; bu, korumanın eski betiği çalıştırmadan önce "
        "fail-closed olmadığını gösterir.\n"
        f"{debug_context}"
    )


def test_install_sidar_bootstrap_reexec_hash_drift_blocks_stale_installer(tmp_path: Path) -> None:
    """Bootstrap clone must fail closed when the cloned installer differs from the raw installer."""
    repo_root = Path(os.getcwd())
    origin = tmp_path / "origin"
    branch = _build_synthetic_bootstrap_origin(repo_root, origin)

    tampered = origin / "install_sidar.sh"
    tampered.write_text(
        tampered.read_text(encoding="utf-8") + "\n# smoke-test installer drift\n",
        encoding="utf-8",
    )
    git = ["git", "-C", str(origin)]
    subprocess.run([*git, "add", "-A"], env=_installer_test_env(tmp_path), check=True, capture_output=True)
    subprocess.run([*git, "commit", "-q", "-m", "tamper installer drift"], env=_installer_test_env(tmp_path), check=True)

    host = tmp_path / "host"
    host.mkdir()
    standalone = host / "install_sidar.sh"
    shutil.copy2(repo_root / "install_sidar.sh", standalone)
    standalone.chmod(0o755)

    env = _installer_test_env(tmp_path) | {
        "HOME": str(host),
        "PWD": str(host),
        "TMPDIR": str(tmp_path),
        "SIDAR_INSTALL_TEST_MODE": "1",
        "SIDAR_INSTALL_ALLOW_BOOTSTRAP_IN_TEST_MODE": "1",
        "SIDAR_INSTALL_ALLOW_STALE_REEXEC": "0",
        "SIDAR_INSTALL_SKIP_DIRECT_MODULE_DOWNLOAD": "1",
        "SIDAR_BOOTSTRAP_CLONE_URL": f"file://{origin}",
        "SIDAR_BOOTSTRAP_CLONE_PARENT_DIR": str(host),
        "SIDAR_BOOTSTRAP_CLONE_DIRNAME": "Sidar",
        "SIDAR_BOOTSTRAP_CLONE_REF": branch,
        "SIDAR_REPO_BRANCH": branch,
    }

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
        "Installer drift bulunan bootstrap re-exec fail-closed olmalıydı."
    )
    assert "Bootstrap clone re-exec install_sidar.sh SHA256 farklı" in combined
    assert "NEXT STEP → hash drift kaynağını temizleyin" in combined
    assert "SIDAR_INSTALL_ALLOW_STALE_REEXEC=1" in combined


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
    subprocess.run([*git, "add", "-A"], env=_installer_test_env(tmp_path), check=True, capture_output=True)
    subprocess.run([*git, "commit", "-q", "-m", "tamper core drift"], env=_installer_test_env(tmp_path), check=True)

    host = tmp_path / "host"
    host.mkdir()
    standalone = host / "install_sidar.sh"
    shutil.copy2(repo_root / "install_sidar.sh", standalone)
    standalone.chmod(0o755)

    env = _installer_test_env(tmp_path) | {
        "HOME": str(host),
        "PWD": str(host),
        "SIDAR_INSTALL_TEST_MODE": "1",
        "SIDAR_INSTALL_ALLOW_BOOTSTRAP_IN_TEST_MODE": "1",
        "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY": "1",
        "SIDAR_INSTALL_SKIP_DIRECT_MODULE_DOWNLOAD": "1",
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
        "SIDAR_INSTALL_SKIP_DIRECT_MODULE_DOWNLOAD=1; fallback modül indirme atlandı",
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
        f"Çekirdek drift, modül manifest hatası gibi raporlanmamalı.\n--- combined ---\n{combined}"
    )


def _decode_timeout_stream(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _run_bash_smoke(
    script: str, tmp_path: Path, timeout_seconds: int | None = None
) -> subprocess.CompletedProcess[str]:
    smoke_env = _installer_test_env(tmp_path)
    smoke_env.pop("INSTALL_SIDAR_VERSION", None)
    guarded_script = f"""
    unset INSTALL_SIDAR_VERSION
    export SIDAR_INSTALL_TEST_MODE=1
    export TMPDIR={shlex.quote(str(tmp_path))}
    {script}
    """
    if timeout_seconds is None:
        timeout_seconds = int(os.environ.get("SIDAR_INSTALL_SMOKE_BASH_TIMEOUT", "30"))
    try:
        result = subprocess.run(
            ["bash", "-c", guarded_script],
            cwd=Path(os.getcwd()),
            env=smoke_env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0 and not result.stdout and not result.stderr:
            diagnostic = _diagnose_silent_bash_smoke_failure(guarded_script, tmp_path)
            return subprocess.CompletedProcess(
                args=result.args,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=diagnostic,
            )
        return result
    except subprocess.TimeoutExpired as exc:
        out = _decode_timeout_stream(exc.stdout)
        err = _decode_timeout_stream(exc.stderr)
        try:
            diag = subprocess.run(
                ["bash", "-c", "echo BASH_OK=$$; type python3 || true; command -v sed"],
                env=_installer_test_env(tmp_path),
                capture_output=True,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
            )
            diag_text = (
                f"--- timeout diagnostic returncode ---\n{diag.returncode}\n"
                f"--- timeout diagnostic stdout ---\n{diag.stdout[-4000:]}\n"
                f"--- timeout diagnostic stderr ---\n{diag.stderr[-4000:]}\n"
            )
        except subprocess.TimeoutExpired as diag_exc:
            diag_text = f"--- timeout diagnostic ---\nbash/python/sed diagnostic timed out after {diag_exc.timeout}s\n"
        raise AssertionError(
            f"_run_bash_smoke {timeout_seconds}s içinde tamamlanamadı.\n"
            f"--- guarded_script ---\n{guarded_script}\n"
            f"--- partial stdout ---\n{out[-4000:]}\n"
            f"--- partial stderr ---\n{err[-4000:]}\n"
            f"{diag_text}"
        ) from exc


def _diagnose_silent_bash_smoke_failure(guarded_script: str, tmp_path: Path) -> str:
    return (
        "--- silent _run_bash_smoke failure diagnostic ---\n"
        "The bash smoke subprocess exited non-zero with empty stdout/stderr.\n"
        f"--- guarded_script ---\n{guarded_script}\n"
        f"--- sourced install/version diagnostics ---\n{_diagnose_sourced_install_version(tmp_path)}"
    )


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
    diagnose_timeout = int(os.environ.get("SIDAR_INSTALL_SMOKE_BASH_TIMEOUT", "60"))
    diagnosis_env = _installer_test_env(tmp_path)
    diagnosis_env.pop("INSTALL_SIDAR_VERSION", None)
    diagnostic_script = f"""
    unset INSTALL_SIDAR_VERSION
    export SIDAR_INSTALL_TEST_MODE=1
    export TMPDIR={shlex.quote(str(tmp_path))}
    set +e
    echo '--- command diagnostics ---'
    printf 'which python3: '; which python3 2>&1 || true
    printf 'command -v python3: '; command -v python3 2>&1 || true
    printf 'type -a python3:\n'; type -a python3 2>&1 || true
    printf 'command -v install_sidar.sh: '; command -v install_sidar.sh 2>&1 || true
    printf 'repo ./install_sidar.sh: '; readlink -f ./install_sidar.sh 2>&1 || true
    printf 'command -v sha256sum: '; command -v sha256sum 2>&1 || true
    printf 'command -v readlink: '; command -v readlink 2>&1 || true
    printf 'command -v sed: '; command -v sed 2>&1 || true
    echo '--- timed probe ---'
    {_fake_python3_fails_snippet()}
    TIMEFORMAT='probe real=%3R user=%3U sys=%3S'
    time bash -c 'set -euo pipefail; export SIDAR_INSTALL_TEST_MODE=1 SIDAR_INSTALL_VERSION_PROBE_ONLY=1; source ./install_sidar.sh >/dev/null; printf "INSTALL_SIDAR_VERSION=%s\\n" "${{INSTALL_SIDAR_VERSION:-EMPTY}}"'
    printf 'timed_probe_status=%s\n' "$?"
    echo '--- xtrace probe ---'
    trace_file="$TMPDIR/install-sidar-source-xtrace.log"
    PS4='+${{BASH_SOURCE}}:${{LINENO}}:${{FUNCNAME[0]:-main}}: '
    BASH_XTRACEFD=2 bash -x -c 'set -euo pipefail; export SIDAR_INSTALL_TEST_MODE=1 SIDAR_INSTALL_VERSION_PROBE_ONLY=1; source ./install_sidar.sh >/dev/null; printf "INSTALL_SIDAR_VERSION=%s\\n" "${{INSTALL_SIDAR_VERSION:-EMPTY}}"' 2>"$trace_file"
    printf 'xtrace_probe_status=%s\n' "$?"
    tail -n 80 "$trace_file" 2>/dev/null || true
    """
    try:
        diagnosis = subprocess.run(
            ["bash", "-c", diagnostic_script],
            cwd=Path(os.getcwd()),
            env=diagnosis_env,
            capture_output=True,
            text=True,
            timeout=diagnose_timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        return (
            f"--- diagnosis timeout ---\n{diagnose_timeout}s\n"
            f"--- diagnosis partial stdout ---\n{_decode_timeout_stream(exc.stdout)[-4000:]}\n"
            f"--- diagnosis partial stderr ---\n{_decode_timeout_stream(exc.stderr)[-4000:]}\n"
        )
    return (
        f"--- diagnosis args ---\n{diagnosis.args}\n"
        f"--- diagnosis returncode ---\n{diagnosis.returncode}\n"
        f"--- diagnosis stdout ---\n{diagnosis.stdout!r}\n"
        f"--- diagnosis stderr ---\n{diagnosis.stderr!r}\n"
    )


def test_run_bash_smoke_silent_failure_includes_diagnostics(tmp_path: Path) -> None:
    result = _run_bash_smoke("set -euo pipefail\nfalse", tmp_path)

    assert result.returncode == 1
    assert "silent _run_bash_smoke failure diagnostic" in result.stderr
    assert "--- guarded_script ---" in result.stderr
    assert "--- sourced install/version diagnostics ---" in result.stderr
    assert "which python3:" in result.stderr
    assert "--- timed probe ---" in result.stderr


def test_install_sidar_probe_failure_diagnosis_includes_command_context(tmp_path: Path) -> None:
    diagnosis = _diagnose_sourced_install_version(tmp_path)

    assert "which python3:" in diagnosis
    assert "command -v install_sidar.sh:" in diagnosis
    assert "repo ./install_sidar.sh:" in diagnosis
    assert "command -v sha256sum:" in diagnosis
    assert "--- timed probe ---" in diagnosis
    assert "--- xtrace probe ---" in diagnosis
    assert "probe real=" in diagnosis or "--- diagnosis timeout ---" in diagnosis, diagnosis
    assert "timed_probe_status=" in diagnosis or "--- diagnosis timeout ---" in diagnosis, diagnosis
    assert "xtrace_probe_status=" in diagnosis or "--- diagnosis timeout ---" in diagnosis, (
        diagnosis
    )


def test_install_sidar_smoke_source_uses_repo_relative_installer_when_path_is_shadowed(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    shadow_installer = fake_bin / "install_sidar.sh"
    shadow_installer.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'PATH shadow install_sidar.sh should not be sourced' >&2\n"
        "exit 99\n",
        encoding="utf-8",
    )
    shadow_installer.chmod(0o755)

    result = _run_bash_smoke(
        f"""
        set -euo pipefail
        export PATH={shlex.quote(str(fake_bin))}:$PATH
        source ./install_sidar.sh >/dev/null
        test -n "${{INSTALL_SIDAR_VERSION:-}}"
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PATH shadow install_sidar.sh should not be sourced" not in (
        result.stdout + result.stderr
    )


def test_install_sidar_probe_only_source_does_not_leave_error_trap_installed(
    tmp_path: Path,
) -> None:
    result = _run_bash_smoke(
        """
        set +e
        export SIDAR_INSTALL_VERSION_PROBE_ONLY=1
        source ./install_sidar.sh >/dev/null
        unset SIDAR_INSTALL_VERSION_PROBE_ONLY
        set +e
        false
        status=$?
        test "$status" -eq 1
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "install_sidar.sh: satır=" not in result.stderr


def test_install_sidar_test_mode_and_uv_only_contract() -> None:
    repo_root = Path(os.getcwd())
    installer = repo_root / "install_sidar.sh"
    installer_text = installer.read_text(encoding="utf-8")
    alembic_phase = repo_root / "scripts" / "install_modules" / "phases" / "12_alembic.sh"
    alembic_prelude = alembic_phase.read_text(encoding="utf-8").split(
        "resolve_alembic_python", maxsplit=1
    )[0]
    with (repo_root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject_version = tomllib.load(pyproject_file)["project"]["version"]

    assert 'if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]]; then' in installer_text
    assert 'main "$@"' in installer_text
    strict_mode_idx = installer_text.index("set -Eeuo pipefail")
    pretrap_func_idx = installer_text.index("on_install_error()")
    pretrap_idx = installer_text.index('trap \'on_install_error "$LINENO" "$BASH_COMMAND"\' ERR')
    blank_idx = installer_text.index("is_blank()")
    resolve_idx = installer_text.index("resolve_install_sidar_version()")
    validate_idx = installer_text.index("validate_install_utility_modules()")
    validate_call_idx = installer_text.index(
        "validate_install_utility_modules\nsidar_source_install_utils"
    )
    export_idx = installer_text.index("export INSTALL_SIDAR_VERSION")
    load_phase_idx = installer_text.index("load_install_phase_modules\n# END_BUNDLE_MODULES")
    assert blank_idx < resolve_idx
    early_probe_idx = installer_text.index(
        'if [[ "${SIDAR_INSTALL_VERSION_PROBE_ONLY:-0}" == "1" ]]; then'
    )
    probe_idx = installer_text.index(
        'if [[ "${SIDAR_INSTALL_VERSION_PROBE_ONLY:-0}" == "1" ]]; then',
        resolve_idx,
    )
    assert early_probe_idx < blank_idx
    assert strict_mode_idx < pretrap_func_idx < pretrap_idx < early_probe_idx
    assert (
        "Ultra fast-path: smoke/version probe akışı"
        in installer_text[early_probe_idx - 500 : early_probe_idx]
    )
    assert resolve_idx < validate_idx < probe_idx < validate_call_idx
    probe_only_guard = 'if [[ "${SIDAR_INSTALL_VERSION_PROBE_ONLY:-0}" != "1" ]]; then'
    original_path_idx = installer_text.index(
        'ORIGINAL_SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"'
    )
    original_dir_idx = installer_text.index('ORIGINAL_SCRIPT_DIR="$SCRIPT_DIR"')
    populate_call_idx = installer_text.index(
        "populate_remote_module_hashes_from_embedded_manifest\nfi"
    )
    helper_source_idx = installer_text.index('source "$INSTALL_HELPERS_MODULE"')
    core_source_guard_idx = installer_text.index(
        "SIDAR_INSTALL_TEST_MODE=1 source akışı: çekirdek manifest doğrulaması atlandı."
    )
    manifest_verify_idx = installer_text.index(
        "verify_core_install_manifest || core_manifest_status=$?"
    )
    assert core_source_guard_idx < manifest_verify_idx
    assert installer_text.rfind(probe_only_guard, 0, original_path_idx) != -1
    assert original_path_idx < original_dir_idx
    assert installer_text.rfind(probe_only_guard, 0, populate_call_idx) != -1
    assert installer_text.rfind(probe_only_guard, 0, helper_source_idx) != -1
    assert installer_text.rfind(probe_only_guard, 0, manifest_verify_idx) != -1
    assert export_idx < load_phase_idx
    bash_resolve_idx = installer_text.index("Always try the Bash-only pyproject parser")
    python_probe_idx = installer_text.index("scripts/version_probe.py", resolve_idx)
    assert resolve_idx < bash_resolve_idx < python_probe_idx
    assert "return 0" in installer_text[bash_resolve_idx:python_probe_idx]
    assert "sed -nE" not in installer_text[resolve_idx:python_probe_idx]
    assert installer_text.count('if is_blank "$INSTALL_SIDAR_VERSION"; then') == 3
    assert "trap - ERR\n    return 0 2>/dev/null || exit 0" in installer_text
    assert "return 0 2>/dev/null || exit 0" in installer_text
    assert "INSTALL_SIDAR_VERSION//[[:space:]]" not in installer_text
    assert "load_install_phase_modules\n# END_BUNDLE_MODULES" in installer_text
    assert (
        "modül hash doğrulaması atlandı; fonksiyon modülleri yüklenmeye devam edecek"
        in installer_text
    )
    assert "mask_install_log_stream | tee" in installer_text
    assert "export INSTALL_SIDAR_VERSION" in installer_text
    assert "uv venv" in installer_text
    assert (
        'sidar_run_install_phase "02_repo" sidar_phase_bootstrap_repo_system\n'
        "    cleanup_bootstrap_script_copy\n"
        '    sidar_run_install_phase "03_runtime" sidar_phase_runtime_prerequisites'
    ) in installer_text
    assert "Accepted values:" in installer_text
    assert "  Commands: doctor | prepare-system" in installer_text
    assert "Kabul edilen değerler:" in installer_text
    assert "  Komutlar: doctor | prepare-system" in installer_text
    assert "Tests/automation:" in installer_text
    assert "Test/otomasyon:" in installer_text
    assert "processors=__SIDAR_WSL_PROCESSORS__" in installer_text
    assert "kernelCommandLine=__SIDAR_WSL_KERNEL_COMMAND_LINE__" in installer_text
    assert "[experimental]" in installer_text
    assert "sparseVhd=__SIDAR_WSL_SPARSE_VHD__" in installer_text
    assert "_detect_host_processors" in installer_text
    assert "kernelCommandLine=${target_kernel_command_line}" in installer_text
    assert "sparseVhd=${target_sparse_vhd}" in installer_text
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


def test_install_sidar_test_mode_source_resolves_pyproject_version_without_python(
    tmp_path: Path,
) -> None:
    repo_root = Path(os.getcwd())
    with (repo_root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject_version = tomllib.load(pyproject_file)["project"]["version"]

    result = _run_bash_smoke(
        f"""
        set -euo pipefail
        export SIDAR_INSTALL_TEST_MODE=1
        unset SIDAR_INSTALL_VERSION
        {_fake_python3_fails_snippet()}
        source ./install_sidar.sh >/dev/null
        if [[ "${{INSTALL_SIDAR_VERSION:-}}" != {shlex.quote(pyproject_version)} ]]; then
          echo "INSTALL_SIDAR_VERSION=${{INSTALL_SIDAR_VERSION:-<boş>}}; expected={pyproject_version}" >&2
          exit 1
        fi
        """,
        tmp_path,
        timeout_seconds=int(os.environ.get("SIDAR_INSTALL_SMOKE_BASH_TIMEOUT", "60")),
    )
    assert result.returncode == 0, (
        "SIDAR_INSTALL_TEST_MODE source akışı python3 olmadan pyproject sürümünü çözmeli.\n"
        f"--- stdout ---\n{result.stdout!r}\n"
        f"--- stderr ---\n{result.stderr!r}"
    )


def test_install_sidar_source_exports_pyproject_version_without_python(tmp_path: Path) -> None:
    repo_root = Path(os.getcwd())
    with (repo_root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject_version = tomllib.load(pyproject_file)["project"]["version"]

    probe_timeout_seconds = int(os.environ.get("SIDAR_INSTALL_SMOKE_BASH_TIMEOUT", "60"))
    version_result = _run_bash_smoke(
        f"""
        set -euo pipefail
        export SIDAR_INSTALL_VERSION_PROBE_ONLY=1
        {_fake_python3_fails_snippet()}
        source ./install_sidar.sh >/dev/null
        if [[ "${{INSTALL_SIDAR_VERSION:-}}" != {shlex.quote(pyproject_version)} ]]; then
          echo "INSTALL_SIDAR_VERSION=${{INSTALL_SIDAR_VERSION:-<boş>}}; expected={pyproject_version}" >&2
          exit 1
        fi
        """,
        tmp_path,
        timeout_seconds=probe_timeout_seconds,
    )
    assert version_result.returncode == 0, (
        "INSTALL_SIDAR_VERSION sourced akışta beklenen değere set olmadı.\n"
        f"--- args ---\n{version_result.args}\n"
        f"--- stdout ---\n{version_result.stdout!r}\n"
        f"--- stderr ---\n{version_result.stderr!r}\n"
        f"--- INSTALL_SIDAR_VERSION (post-run) ---\n{_diagnose_sourced_install_version(tmp_path)}"
    )


def test_install_sidar_version_probe_fails_on_env_pyproject_mismatch(tmp_path: Path) -> None:
    repo_root = Path(os.getcwd())
    with (repo_root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject_version = tomllib.load(pyproject_file)["project"]["version"]

    mismatch_result = _run_bash_smoke(
        """
        set -euo pipefail
        export SIDAR_INSTALL_VERSION_PROBE_ONLY=1
        export INSTALL_SIDAR_VERSION=0.0.0-test-mismatch
        source ./install_sidar.sh >/dev/null
        """,
        tmp_path,
        timeout_seconds=int(os.environ.get("SIDAR_INSTALL_SMOKE_BASH_TIMEOUT", "60")),
    )
    assert mismatch_result.returncode != 0, (
        "Version probe INSTALL_SIDAR_VERSION/pyproject.toml uyumsuzluğunu fail-closed "
        "yakalamalıydı.\n"
        f"expected_pyproject_version={pyproject_version}\n"
        f"--- stdout ---\n{mismatch_result.stdout!r}\n"
        f"--- stderr ---\n{mismatch_result.stderr!r}"
    )
    assert "INSTALL_SIDAR_VERSION uyumsuz" in mismatch_result.stderr
    assert f"pyproject.toml={pyproject_version}" in mismatch_result.stderr


def test_install_sidar_is_blank_helper_handles_whitespace(tmp_path: Path) -> None:
    result = _run_bash_smoke(
        """
        set -euo pipefail
        source ./install_sidar.sh >/dev/null
        is_blank ""
        is_blank "   "
        is_blank $'\\t\\n'
        ! is_blank "5.2.0"
        """,
        tmp_path,
    )
    assert result.returncode == 0, (
        "is_blank helper boş/whitespace sürüm kontrollerini beklenen şekilde ele almadı.\n"
        f"--- args ---\n{result.args}\n"
        f"--- stdout ---\n{result.stdout!r}\n"
        f"--- stderr ---\n{result.stderr!r}"
    )


def test_install_sidar_fail_reports_clean_auto_heal_command(tmp_path: Path) -> None:
    result = _run_bash_smoke(
        """
        set -euo pipefail
        source ./install_sidar.sh >/dev/null
        sidar_handle_install_failure() {
          printf 'handler_cmd=%s\\n' "$3"
          printf 'handler_reason=%s\\n' "$4"
          return 1
        }
        fail "servis smoke failed"
        """,
        tmp_path,
    )
    assert result.returncode == 1
    assert "handler_cmd=fail" in result.stdout
    assert "handler_reason=servis smoke failed" in result.stdout
    assert "sidar_handle_install_failure 1" not in result.stdout
    assert "sidar_handle_install_failure 1" not in result.stderr


def test_install_remediation_explains_legacy_conda_non_retryable_signature() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source scripts/install_modules/utils/install_remediation.sh
            warn() { printf 'WARN:%s\\n' "$*"; }
            sidar_write_remediation_report() { printf 'REPORT:%s|%s|%s\\n' "$1" "$2" "$3"; }
            export SIDAR_CURRENT_INSTALL_PHASE=06_services
            sidar_handle_install_failure 1 42 'conda env create' 'EnvironmentFileNotFound: environment.yml'
            """,
        ],
        cwd=Path(os.getcwd()),
        env=_installer_test_env(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "öğrenilmiş kalıcı hata imzası" in result.stdout
    assert "eski conda tabanlı kurulumdan kalma olabilir" in result.stdout
    assert "~/Sidar veya PATH üzerinde stale install_sidar.sh" in result.stdout
    assert "repo kökündeki ./install_sidar.sh" in result.stdout
    assert "REPORT:06_services|learned-non-retryable-failure|" in result.stdout


def test_install_remediation_fail_fast_for_test_gate_failures() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source scripts/install_modules/utils/install_remediation.sh
            warn() { printf 'WARN:%s\n' "$*"; }
            sidar_write_remediation_report() { printf 'REPORT:%s|%s|%s\n' "$1" "$2" "$3"; }
            sidar_resume_after_remediation() { printf 'UNEXPECTED_RESUME\n'; exit 99; }
            export SIDAR_CURRENT_INSTALL_PHASE=06_services
            export SCRIPT_DIR=/repo/Sidar
            sidar_handle_install_failure \
              1 \
              42 \
              fail \
              'Smoke testlerde hata var. FAILED tests/smoke/test_install_python_env_lock.py::test_profile_matrix - AssertionError' || true
            """,
        ],
        cwd=Path(os.getcwd()),
        env=_installer_test_env(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "UNEXPECTED_RESUME" not in result.stdout
    assert "deterministik test gate hatası" in result.stdout
    assert (
        "Başarısız test: tests/smoke/test_install_python_env_lock.py::test_profile_matrix"
        in result.stdout
    )
    assert (
        "Tekrar komutu: uv run pytest tests/smoke/test_install_python_env_lock.py::test_profile_matrix -v --no-cov"
        in result.stdout
    )
    assert "REPORT:06_services|test-gate-failure|fail-fast;no-retry;no-resume;" in result.stdout


def test_install_sidar_fail_records_last_fail_message_for_err_trap() -> None:
    installer = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert 'SIDAR_LAST_FAIL_MESSAGE="$fail_reason"' in installer
    assert 'local remediation_reason="${SIDAR_LAST_FAIL_MESSAGE:-ERR trap}"' in installer
    assert (
        'sidar_handle_install_failure "$exit_code" "$failed_line" "$failed_cmd" "$remediation_reason"'
        in installer
    )


def test_install_remediation_explains_installer_hash_drift_next_step() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source scripts/install_modules/utils/install_remediation.sh
            warn() { printf 'WARN:%s\\n' "$*"; }
            sidar_write_remediation_report() { printf 'REPORT:%s|%s|%s\\n' "$1" "$2" "$3"; }
            sidar_phase_remediation_strategy 02_repo fail 'Mevcut /home/user/Sidar re-exec install_sidar.sh SHA256 farklı' || true
            sidar_emit_remediation_guidance 02_repo fail 'Mevcut /home/user/Sidar re-exec install_sidar.sh SHA256 farklı'
            """,
        ],
        cwd=Path(os.getcwd()),
        env=_installer_test_env(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert (
        "REPORT:02_repo|installer-hash-drift|no-retry;remove-stale-home-installer-or-refresh-clone"
        in result.stdout
    )
    assert "installer hash drift hatası" in result.stdout
    assert 'rm -f "$HOME/Sidar/install_sidar.sh"' in result.stdout
    assert "git pull --ff-only" in result.stdout


def test_pre_service_smoke_gate_uses_pyproject_version_without_source_preflight() -> None:
    phase = Path("scripts/install_modules/phases/06_services.sh").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    install_options = Path("docs/install-script-options.md").read_text(encoding="utf-8")
    troubleshooting = Path("docs/INSTALL_SMOKE_GATE_TROUBLESHOOTING.md").read_text(encoding="utf-8")
    installer = Path("install_sidar.sh").read_text(encoding="utf-8")
    version_contract_block = phase[
        phase.index("local expected_installer_version=") : phase.index("local smoke_log")
    ]

    assert "--skip-smoke-test/RUN_SMOKE_TESTS_MODE=never" in phase
    assert "RUN_SMOKE_TESTS_MODE=never" in readme
    assert "docs/install-script-options.md" in readme
    assert "SIDAR_INSTALL_SMOKE_BASH_TIMEOUT=240 ./install_sidar.sh" in readme
    assert "`--skip-smoke-test` son çare" in readme
    assert "RUN_SMOKE_TESTS_MODE=never" in install_options
    assert "SIDAR_INSTALL_SMOKE_BASH_TIMEOUT=<saniye>" in install_options
    assert "Smoke gate'i kapatmadan önce tercih edilen ilk tanılama adımıdır" in install_options
    assert "Bu seçenek son çaredir" in install_options
    assert "SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=0" in install_options
    assert "SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=0 ./install_sidar.sh" in troubleshooting
    assert "timeout artırma ve drift" in troubleshooting
    assert "telafi doğrulaması yapılmalıdır" in troubleshooting
    assert 'Add-MpPreference -ExclusionProcess "wsl.exe"' in troubleshooting
    assert "Add-MpPreference -ExclusionPath" in troubleshooting
    assert "pyproject.toml" in version_contract_block
    assert 'SIDAR_INSTALL_SMOKE_BASH_TIMEOUT="${SIDAR_INSTALL_SMOKE_BASH_TIMEOUT:-180}"' in phase
    assert "SIDAR_ENV=test" in phase
    assert 'SIDAR_KEYS_FILE=""' in phase
    assert "SIDAR_TEST_LOAD_REAL_KEYS=0" in phase
    assert '--confcutdir="$SCRIPT_DIR/tests/smoke"' in phase
    assert "SIDAR_INSTALL_SMOKE_BASH_TIMEOUT=240" in phase
    assert "WSL2 ortamında smoke bash helper timeout değeri 180 saniyeye yükseltildi" in installer
    assert "export SIDAR_INSTALL_SMOKE_BASH_TIMEOUT=180" in installer
    assert "final `tests/smoke` çalıştırması WSL2 algılandığında" in troubleshooting
    assert "Ubuntu 26.04/resolute" in troubleshooting
    assert "Windows Defender real-time scanning" in troubleshooting
    assert "güncel akış Conda değil `uv` kullanır" in troubleshooting
    assert "60 saniyelik varsayılan timeout" in troubleshooting
    assert "--skip-smoke-test veya RUN_SMOKE_TESTS_MODE=never" in phase
    assert "SIDAR_LAST_FAILED_TEST" in phase
    assert "Smoke subprocess environment boyutu işletim sistemi sınırını aştı." in phase
    assert "SIDAR_KEYS_FILE ve dotenv zincirindeki büyük değerleri kontrol edin." in phase
    assert "Argument list too long" in troubleshooting
    assert "TOTAL_ENV_BYTES" in troubleshooting
    assert "--confcutdir=tests/smoke" in troubleshooting
    assert "Smoke gate probe timeout belirtisi" in phase
    assert "test_install_sidar_bootstrap_core_hash_drift_reports_core_layer" in phase
    assert "core_manifest_status=2 durumunu maskelemediğini kontrol edin" in phase
    assert "sidar_phase06_cleanup_pre_service_smoke_log" in phase
    assert "SIDAR_PHASE06_PRE_SERVICE_SMOKE_LOG" in phase
    assert "sidar_phase06_fail_with_smoke_cleanup" in phase
    assert "sidar_phase06_cleanup_pre_service_smoke_log || true" in installer
    assert "Installer sürüm sözleşmesi pyproject.toml üzerinden okunuyor" in version_contract_block
    assert "Source/export doğrulaması CI smoke testi kapsamındadır" in version_contract_block
    assert "source ./install_sidar.sh" not in version_contract_block
    assert "sidar_smoke_version" not in version_contract_block
    assert "bash --norc --noprofile -c" not in version_contract_block
    assert "env -i" not in version_contract_block

    remediation_utils = Path("scripts/install_modules/utils/install_remediation.sh").read_text(
        encoding="utf-8"
    )
    assert "SIDAR_INSTALL_SUPPRESS_AUTO_HEAL" in remediation_utils
    assert "sidar_install_auto_heal_enabled || return 1" in remediation_utils


def test_ci_verifies_installer_smoke_isolation_from_user_secrets() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Verify installer smoke isolation from user secrets" in ci
    assert "OPENAI_API_KEY=%0200000d" in ci
    assert "SIDAR_TEST_LOAD_REAL_KEYS=0" in ci
    assert "--confcutdir=tests/smoke" in ci
    assert "tests/smoke/test_install_verification.py" in ci


def test_install_remediation_prefers_last_failed_test_from_smoke_log() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source scripts/install_modules/utils/install_remediation.sh
            export SIDAR_LAST_FAILED_TEST=tests/smoke/test_install_verification.py::test_dark_mode_assets_exist
            sidar_test_gate_failure_guidance fail 'Servis öncesi installer smoke gate başarısız'
            """,
        ],
        cwd=Path(os.getcwd()),
        env=_installer_test_env(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Başarısız test: tests/smoke/test_install_verification.py::test_dark_mode_assets_exist" in result.stdout
    assert "bilinmiyor" not in result.stdout


def test_docker_compose_start_checks_daemon_access_before_up() -> None:
    phase = Path("scripts/install_modules/phases/06_services.sh").read_text(encoding="utf-8")
    start_idx = phase.index("start_docker_services_or_fail()")
    start_body = phase[start_idx : phase.index("wait_for_compose_services_health()", start_idx)]

    assert "ensure_docker_compose_access_or_fail()" in phase
    assert "docker info" in phase
    assert "sudo -n docker info" in phase
    assert 'ensure_docker_compose_access_or_fail "${compose_cmd[@]}"' in start_body
    assert "permission denied" in phase
    assert "docker grubuna ekleyin" in phase
    assert start_body.index("ensure_docker_compose_access_or_fail") < start_body.index(
        "maybe_reset_postgres_volume_after_password_hardening"
    )
    assert start_body.index("ensure_docker_compose_access_or_fail") < start_body.index(" up -d ")


def test_pre_service_smoke_gate_does_not_source_installer_before_pytest(tmp_path: Path) -> None:
    script_dir = tmp_path / "sidar"
    (script_dir / "tests" / "smoke").mkdir(parents=True)
    (script_dir / "tests" / "smoke" / "test_install_verification.py").write_text(
        "# smoke placeholder\n",
        encoding="utf-8",
    )
    (script_dir / "scripts").mkdir()
    (script_dir / "scripts" / "sync_database_passwords.py").write_text(
        "# sync placeholder\n",
        encoding="utf-8",
    )
    (script_dir / "pyproject.toml").write_text(
        '[project]\nversion = "5.2.0"\n',
        encoding="utf-8",
    )
    (script_dir / "install_sidar.sh").write_text(
        "echo 'install_sidar.sh should not be sourced by preflight' >&2\nexit 43\n",
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_uv.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            textwrap.dedent(
                """
                set -euo pipefail
                source scripts/install_modules/phases/06_services.sh
                info(){ printf 'INFO:%s\n' "$*" >&2; }
                warn(){ printf 'WARN:%s\n' "$*" >&2; }
                ok(){ printf 'OK:%s\n' "$*" >&2; }
                fail(){ printf 'FAIL:%s\n' "$*" >&2; return 99; }
                normalize_bool(){ [[ "$1" == "1" ]] && printf true || printf '%s' "$1"; }
                export SCRIPT_DIR="$1"
                export APP_RUNTIME_MODE_SELECTED=local
                export SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=1
                run_pre_service_installer_smoke_gate
                """
            ),
            "preflight-no-source-regression",
            str(script_dir),
        ],
        cwd=Path(os.getcwd()),
        env=_installer_test_env(tmp_path) | {"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )

    combined_output = result.stdout + result.stderr
    assert result.returncode == 0, combined_output
    assert "install_sidar.sh should not be sourced by preflight" not in combined_output
    assert "Installer sürüm sözleşmesi pyproject.toml üzerinden okunuyor" in combined_output
    assert "Servis öncesi installer smoke gate başarılı" in combined_output


def test_pre_service_smoke_gate_ignores_silent_installer_source_abort(tmp_path: Path) -> None:
    script_dir = tmp_path / "sidar"
    (script_dir / "tests" / "smoke").mkdir(parents=True)
    (script_dir / "tests" / "smoke" / "test_install_verification.py").write_text(
        "# smoke placeholder\n",
        encoding="utf-8",
    )
    (script_dir / "scripts").mkdir()
    (script_dir / "scripts" / "sync_database_passwords.py").write_text(
        "# sync placeholder\n",
        encoding="utf-8",
    )
    (script_dir / "pyproject.toml").write_text(
        '[project]\nversion = "5.2.0"\n',
        encoding="utf-8",
    )
    (script_dir / "install_sidar.sh").write_text("exit 1\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_uv.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            textwrap.dedent(
                """
                set -euo pipefail
                source scripts/install_modules/phases/06_services.sh
                info(){ printf 'INFO:%s\n' "$*" >&2; }
                warn(){ printf 'WARN:%s\n' "$*" >&2; }
                ok(){ printf 'OK:%s\n' "$*" >&2; }
                fail(){ printf 'FAIL:%s\n' "$*" >&2; return 99; }
                normalize_bool(){ [[ "$1" == "1" ]] && printf true || printf '%s' "$1"; }
                export SCRIPT_DIR="$1"
                export APP_RUNTIME_MODE_SELECTED=local
                export SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=1
                run_pre_service_installer_smoke_gate
                """
            ),
            "preflight-silent-source-abort-regression",
            str(script_dir),
        ],
        cwd=Path(os.getcwd()),
        env=_installer_test_env(tmp_path) | {"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )

    combined_output = result.stdout + result.stderr
    assert result.returncode == 0, combined_output
    assert "Smoke gate version preflight stderr" not in combined_output
    assert "Tanılayıcı bash -x re-run" not in combined_output
    assert "source ./install_sidar.sh" not in combined_output
    assert "Servis öncesi installer smoke gate başarılı" in combined_output


def test_install_alembic_head_check_after_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script_dir = tmp_path / "sidar"
    venv_bin = script_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://ambient-user:ambient-pass@ambient-host:5432/ambient-db",
    )
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
        source ./install_sidar.sh > "$TMPDIR/source-install.out" 2>&1
        if grep -Eq "Ön Koşullar Kontrol Ediliyor|Kurulum yöneticisi|Sidar AI.*Kurulum" "$TMPDIR/source-install.out"; then
          echo "install_sidar.sh source işlemi main() kurulum akışını tetikledi" >&2
          cat "$TMPDIR/source-install.out" >&2
          exit 1
        fi
        test "${{LOG_FILE:-}}" = ""
        SCRIPT_DIR={shlex.quote(str(script_dir))}
        export SCRIPT_DIR
        unset DATABASE_URL
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
        'printf \'%s\\n\' "$*" >> "$SCRIPT_DIR/unexpected-alembic-call.log"\n'
        "exit 2\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    result = _run_bash_smoke(
        f"""
        set -euo pipefail
        source ./install_sidar.sh
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


def test_install_alembic_head_check_derives_url_from_postgres_parts(tmp_path: Path) -> None:
    script_dir = tmp_path / "sidar"
    venv_bin = script_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (script_dir / ".env").write_text(
        "\n".join(
            [
                "POSTGRES_USER=sidar",
                "POSTGRES_PASSWORD=secret",
                "POSTGRES_HOST=localhost",
                "POSTGRES_PORT=5432",
                "POSTGRES_DB=sidar",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (script_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    fake_python = venv_bin / "python"
    fake_python.write_text(
        textwrap.dedent(
            """
            #!/usr/bin/env bash
            set -euo pipefail
            printf '%s|%s\n' "${DATABASE_URL:-}" "$*" >> "$SCRIPT_DIR/dburl.log"
            case "$*" in
              "-m alembic current --check-heads") exit 2 ;;
              "-m alembic current") printf '%s\n' "  0006_access_control_schema (head)" ;;
              "-m alembic heads") printf '%s\n' "  0006_access_control_schema (head)" ;;
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
        source ./install_sidar.sh
        SCRIPT_DIR={shlex.quote(str(script_dir))}
        export SCRIPT_DIR
        unset DATABASE_URL
        is_alembic_at_head
        grep -q '^postgresql+asyncpg://sidar:secret@localhost:5432/sidar|-m alembic current$' "$SCRIPT_DIR/dburl.log"
        """,
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_env_keys_synced_to_runtime_profiles_but_not_test_by_default(tmp_path: Path) -> None:
    script_dir = tmp_path / "sidar"
    script_dir.mkdir()
    source_check = _run_bash_smoke(
        "set -euo pipefail; source ./install_sidar.sh; type sidar_user_api_key_names >/dev/null",
        tmp_path,
    )
    if source_check.returncode != 0:
        pytest.skip(
            "install_sidar.sh source edilemedi; API key senkronizasyon adımı anlamlı şekilde çalıştırılamaz.\n"
            f"{source_check.stdout}{source_check.stderr}"
        )

    key_script = "source ./install_sidar.sh; sidar_user_api_key_names"
    keys_result = _run_bash_smoke(key_script, tmp_path)
    assert keys_result.returncode == 0, keys_result.stdout + keys_result.stderr
    keys = [line.strip() for line in keys_result.stdout.splitlines() if line.strip()]
    assert len(keys) == 18

    env_lines = [f"{key}=value_{idx}" for idx, key in enumerate(keys, start=1)]
    (script_dir / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    for name in (".env.advanced", ".env.development", ".env.test"):
        (script_dir / name).write_text(
            "\n".join(f"{key}=" for key in keys) + "\n", encoding="utf-8"
        )

    result = _run_bash_smoke(
        f"""
        set -euo pipefail
        source ./install_sidar.sh
        SCRIPT_DIR={shlex.quote(str(script_dir))}
        ENV_FILE="$SCRIPT_DIR/.env"
        NO_INTERACTION=true
        unset SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV
        SIDAR_KEYS_FILE="$SCRIPT_DIR/.sidar_keys.env"
        export SCRIPT_DIR ENV_FILE NO_INTERACTION SIDAR_KEYS_FILE
        collect_api_keys_interactive "$ENV_FILE"
        for key in $(sidar_user_api_key_names); do
          expected=$(read_env_value_from_file "$key" "$ENV_FILE")
          actual_secret=$(read_env_value_from_file "$key" "$SIDAR_KEYS_FILE")
          if [[ "$actual_secret" != "$expected" ]]; then
            echo "SIDAR_KEYS_FILE:$key expected=$expected actual=$actual_secret" >&2
            exit 1
          fi
          for profile in .env.advanced .env.development .env.test; do
            actual=$(read_env_value_from_file "$key" "$SCRIPT_DIR/$profile")
            if [[ -n "$actual" && "$actual" == "$expected" ]]; then
              echo "$profile:$key unexpectedly received real key value: $actual" >&2
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
    combined_output = result.stdout + result.stderr
    assert "18 API anahtarı SIDAR_KEYS_FILE" in combined_output
    assert "içinde doğrulandı/güncellendi" in combined_output
    assert "üzerinden .env dosyasına aktarıldı" not in combined_output


def test_env_keys_synced_to_test_profile_with_explicit_opt_in(tmp_path: Path) -> None:
    script_dir = tmp_path / "sidar"
    script_dir.mkdir()
    source_check = _run_bash_smoke(
        "set -euo pipefail; source ./install_sidar.sh; type sidar_user_api_key_names >/dev/null",
        tmp_path,
    )
    if source_check.returncode != 0:
        pytest.skip(
            "install_sidar.sh source edilemedi; API key senkronizasyon adımı anlamlı şekilde çalıştırılamaz.\n"
            f"{source_check.stdout}{source_check.stderr}"
        )

    key_script = "source ./install_sidar.sh; sidar_user_api_key_names"
    keys_result = _run_bash_smoke(key_script, tmp_path)
    assert keys_result.returncode == 0, keys_result.stdout + keys_result.stderr
    keys = [line.strip() for line in keys_result.stdout.splitlines() if line.strip()]
    assert len(keys) == 18

    env_lines = [f"{key}=value_{idx}" for idx, key in enumerate(keys, start=1)]
    (script_dir / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    for name in (".env.advanced", ".env.development", ".env.test"):
        (script_dir / name).write_text(
            "\n".join(f"{key}=" for key in keys) + "\n", encoding="utf-8"
        )

    result = _run_bash_smoke(
        f"""
        set -euo pipefail
        source ./install_sidar.sh
        SCRIPT_DIR={shlex.quote(str(script_dir))}
        ENV_FILE="$SCRIPT_DIR/.env"
        NO_INTERACTION=true
        SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV=1
        SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV=1
        SIDAR_KEYS_FILE="$SCRIPT_DIR/.sidar_keys.env"
        export SCRIPT_DIR ENV_FILE NO_INTERACTION SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV SIDAR_KEYS_FILE
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
        """,
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    combined_output = result.stdout + result.stderr
    assert "18 API anahtarı" in combined_output
    assert "materialization açık" in combined_output
    assert ".env: 18 API anahtarı güncellendi." in combined_output
    assert ".env.advanced: 18 API anahtarı güncellendi." in combined_output
    assert ".env.development: 18 API anahtarı güncellendi." in combined_output
    assert ".env.test: 18 API anahtarı güncellendi." in combined_output


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
        source ./install_sidar.sh
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
    subprocess.run(
        ["bash", str(bundle_script)], cwd=repo_root, env=_installer_test_env(), check=True
    )

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
