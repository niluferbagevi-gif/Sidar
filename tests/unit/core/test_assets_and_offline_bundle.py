from __future__ import annotations

import filecmp
import json

import pytest

from scripts import offline_bundle
from scripts.sync_packaged_deployment_assets import SYNC_TARGETS
from sidar_assets.paths import (
    alembic_ini_path,
    asset_path,
    helm_chart_path,
    migrations_path,
    web_dist_path,
)


def test_asset_paths_resolve_packaged_readiness_assets() -> None:
    assert web_dist_path().joinpath("index.html").is_file()
    assert helm_chart_path().joinpath("Chart.yaml").is_file()
    assert migrations_path().joinpath("env.py").is_file()
    assert alembic_ini_path().name == "alembic.ini"
    assert asset_path("migrations", require_exists=True).is_dir()


@pytest.mark.parametrize("source, packaged", SYNC_TARGETS, ids=["helm/sidar", "docker_setup"])
def test_packaged_deployment_assets_match_source_tree(source, packaged) -> None:
    """Keep sidar_assets/{helm/sidar,docker_setup} byte-for-byte aligned with their source.

    ``sidar_assets/paths.py`` prefers the packaged copy over the repository layout for
    wheel/container installs, so any drift here ships silently broken deployment assets
    to those installs (e.g. an AI worker command that references a file which does not
    exist). Regenerate the packaged copy instead of hand-editing it.
    """
    source_manifest = sorted(
        path.relative_to(source) for path in source.rglob("*") if path.is_file()
    )
    packaged_manifest = sorted(
        path.relative_to(packaged) for path in packaged.rglob("*") if path.is_file()
    )

    assert packaged_manifest == source_manifest, (
        f"sidar_assets copy of {source.name} has a different file list than the source "
        "tree. Run `uv run python scripts/sync_packaged_deployment_assets.py`."
    )

    mismatched_files = [
        relative_path.as_posix()
        for relative_path in source_manifest
        if not filecmp.cmp(source / relative_path, packaged / relative_path, shallow=False)
    ]
    assert not mismatched_files, (
        f"sidar_assets copy of {source.name} must be generated from its source tree. Run "
        "`uv run python scripts/sync_packaged_deployment_assets.py`; mismatches: "
        f"{mismatched_files}"
    )


def test_offline_bundle_manifest_create_and_verify(tmp_path) -> None:
    wheel_dir = tmp_path / "wheels"
    npm_dir = tmp_path / "npm" / "cache"
    wheel_dir.mkdir(parents=True)
    npm_dir.mkdir(parents=True)
    (wheel_dir / "sidar-0.0.0-py3-none-any.whl").write_bytes(b"fake-wheel")
    (npm_dir / "cache.tgz").write_bytes(b"fake-npm-cache")

    manifest = offline_bundle.build_manifest(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert offline_bundle.verify_manifest(tmp_path) == []

    (wheel_dir / "sidar-0.0.0-py3-none-any.whl").write_bytes(b"tampered")
    errors = offline_bundle.verify_manifest(tmp_path)
    assert errors and "sha256 mismatch" in errors[0]


def test_offline_bundle_main_create_and_verify_success(tmp_path, capsys) -> None:
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    (wheel_dir / "sidar-0.0.0-py3-none-any.whl").write_bytes(b"fake-wheel")

    assert offline_bundle.main(["create", str(tmp_path)]) == 0
    create_output = capsys.readouterr().out
    assert "wrote" in create_output
    assert "1 files" in create_output

    assert offline_bundle.main(["verify", str(tmp_path)]) == 0
    verify_output = capsys.readouterr().out
    assert "offline manifest verified" in verify_output


def test_offline_bundle_main_create_reports_io_failures(monkeypatch, tmp_path, capsys) -> None:
    def fail_build_manifest(root):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(offline_bundle, "build_manifest", fail_build_manifest)

    assert offline_bundle.main(["create", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "offline manifest creation failed" in output
    assert "No space left on device" in output


def test_offline_bundle_verify_manifest_reports_manifest_read_io_error(
    monkeypatch, tmp_path
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"files": []}', encoding="utf-8")
    original_read_text = offline_bundle.Path.read_text

    def fail_read_text(path, *args, **kwargs):
        if path == manifest_path:
            raise OSError(5, "Input/output error")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(offline_bundle.Path, "read_text", fail_read_text)

    errors = offline_bundle.verify_manifest(tmp_path)

    assert len(errors) == 1
    assert "could not read manifest" in errors[0]
    assert "Input/output error" in errors[0]


def test_offline_bundle_verify_manifest_reports_artifact_read_io_error(
    monkeypatch, tmp_path
) -> None:
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    wheel_path = wheel_dir / "sidar-0.0.0-py3-none-any.whl"
    wheel_path.write_bytes(b"fake-wheel")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": "wheels/sidar-0.0.0-py3-none-any.whl",
                        "sha256": "a" * 64,
                        "bytes": 10,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fail_sha256(path):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(offline_bundle, "sha256_file", fail_sha256)

    errors = offline_bundle.verify_manifest(tmp_path)

    assert len(errors) == 1
    assert "could not read file wheels/sidar-0.0.0-py3-none-any.whl" in errors[0]
    assert "Input/output error" in errors[0]


def test_offline_bundle_main_verify_prints_fail_closed_errors(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setattr(
        offline_bundle,
        "verify_manifest",
        lambda root: ["missing file: wheels/sidar.whl", "invalid sha256 for uv/install.sh: ''"],
    )

    assert offline_bundle.main(["verify", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "offline manifest verification failed" in output
    assert "- missing file: wheels/sidar.whl" in output
    assert "- invalid sha256 for uv/install.sh: ''" in output


def test_offline_bundle_verify_manifest_reports_malformed_entries(tmp_path) -> None:
    assert offline_bundle.verify_manifest(tmp_path) == [
        f"missing manifest: {tmp_path / 'manifest.json'}"
    ]

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("not json", encoding="utf-8")
    assert "invalid manifest JSON" in offline_bundle.verify_manifest(tmp_path)[0]

    manifest_path.write_text(json.dumps({"files": "not-a-list"}), encoding="utf-8")
    assert offline_bundle.verify_manifest(tmp_path) == ["manifest.files must be a list"]

    manifest_path.write_text(
        json.dumps(
            {
                "files": [
                    "not-an-object",
                    {"path": "../escape.whl", "sha256": "a" * 64},
                    {"path": "wheels/pkg.whl", "sha256": "short"},
                    {"path": "wheels/missing.whl", "sha256": "b" * 64},
                ]
            }
        ),
        encoding="utf-8",
    )

    errors = offline_bundle.verify_manifest(tmp_path)

    assert "manifest entry must be an object" in errors
    assert "unsafe path in manifest: '../escape.whl'" in errors
    assert "invalid sha256 for wheels/pkg.whl: 'short'" in errors
    assert "missing file: wheels/missing.whl" in errors


def test_offline_bundle_main_create_reports_manifest_write_io_failures(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setattr(
        offline_bundle, "build_manifest", lambda root: {"schema_version": 1, "files": []}
    )

    def fail_write_text(path, *args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(offline_bundle.Path, "write_text", fail_write_text)

    assert offline_bundle.main(["create", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "offline manifest creation failed" in output
    assert "could not write manifest" in output
    assert "No space left on device" in output
