"""Contract tests for marketplace plugin manifests."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from plugins.manifest import (
    EXTERNAL_SERVICE_PLUGIN_IDS,
    PLUGIN_MANIFESTS,
    PluginManifest,
    get_plugin_manifest,
)

VALID_SIDE_EFFECT_LEVELS = {
    "none",
    "local_read",
    "local_write",
    "external_read",
    "external_write",
}

EXPECTED_PLUGIN_MODULES = {
    "aws_management_agent": "AWSManagementAgent",
    "crypto_price_agent": "CryptoPriceAgent",
    "slack_notification_agent": "SlackNotificationAgent",
    "upload_agent": "UploadAgent",
}


def test_every_plugin_manifest_declares_required_metadata() -> None:
    """Every plugin exposes capability, side-effect, auth, dry-run, and fixture metadata."""

    assert set(PLUGIN_MANIFESTS) == {
        "aws_management",
        "crypto_price",
        "slack_notifications",
        "upload",
    }
    for plugin_id, manifest in PLUGIN_MANIFESTS.items():
        assert isinstance(manifest, PluginManifest)
        assert manifest.plugin_id == plugin_id
        assert manifest.role_name
        assert manifest.module.startswith("plugins.")
        assert manifest.class_name.endswith("Agent")
        assert manifest.capabilities
        assert all(
            capability.strip() == capability and capability for capability in manifest.capabilities
        )
        assert manifest.side_effect_level in VALID_SIDE_EFFECT_LEVELS
        assert isinstance(manifest.requires_auth, bool)
        assert isinstance(manifest.supports_dry_run, bool)
        assert manifest.test_fixture.startswith("tests/unit/plugins/test_")
        assert Path(manifest.test_fixture).is_file()


def test_plugin_manifests_match_importable_role_classes() -> None:
    """Manifest module/class entries stay aligned with concrete plugin classes."""

    for manifest in PLUGIN_MANIFESTS.values():
        module = importlib.import_module(manifest.module)
        plugin_class = getattr(module, manifest.class_name)
        assert isinstance(plugin_class, type)
        assert getattr(plugin_class, "ROLE_NAME", manifest.role_name) == manifest.role_name


def test_get_plugin_manifest_returns_metadata_and_raises_for_unknown_id() -> None:
    """Public manifest lookup returns registered plugins and preserves dict-style errors."""

    assert get_plugin_manifest("upload").plugin_id == "upload"
    with pytest.raises(KeyError):
        get_plugin_manifest("yok_boyle_plugin")


def test_all_plugin_agent_modules_are_listed_in_manifest() -> None:
    """New plugin agent modules must add a manifest entry before landing."""

    manifest_modules = {
        manifest.module.rsplit(".", 1)[-1]: manifest.class_name
        for manifest in PLUGIN_MANIFESTS.values()
    }
    assert manifest_modules == EXPECTED_PLUGIN_MODULES


def test_external_service_plugins_require_mocked_contract_tests() -> None:
    """AWS/Slack/crypto plugins must never depend on real service calls in unit tests."""

    assert EXTERNAL_SERVICE_PLUGIN_IDS == {"aws_management", "crypto_price", "slack_notifications"}
    for plugin_id in EXTERNAL_SERVICE_PLUGIN_IDS:
        manifest = PLUGIN_MANIFESTS[plugin_id]
        assert manifest.external_services
        assert manifest.requires_mocked_contract_tests is True
        assert manifest.test_fixture.endswith("_agent.py")
        fixture_text = Path(manifest.test_fixture).read_text(encoding="utf-8")
        assert "monkeypatch" in fixture_text or "respx" in fixture_text


def test_auth_and_secret_contracts_match_side_effect_risk() -> None:
    """Side-effectful plugins document whether credentials are needed."""

    for manifest in PLUGIN_MANIFESTS.values():
        if manifest.requires_auth:
            assert manifest.secret_names
        else:
            assert manifest.secret_names == ()
        if manifest.side_effect_level == "external_write":
            assert manifest.requires_auth is True
            assert manifest.supports_dry_run is False
