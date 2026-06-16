import os
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
    assert start is not None and end is not None, (
        f"{install_sidar_path} içinde EMBEDDED_MODULE_HASHES_MANIFEST heredoc bloğu bulunamadı."
    )
    return "\n".join(lines[start:end])


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
