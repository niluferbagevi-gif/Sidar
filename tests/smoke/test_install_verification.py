import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


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
