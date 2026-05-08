from __future__ import annotations

import json

from scripts import offline_bundle
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
