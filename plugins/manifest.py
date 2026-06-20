"""Plugin metadata contracts for Sidar marketplace plugins.

The manifest is intentionally read-only: runtime plugin loading can use it for
inspection, while tests and CI can assert that every plugin declares its side
-effects, authentication needs, dry-run support, and mock-based contract fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SideEffectLevel = Literal["none", "local_read", "local_write", "external_read", "external_write"]


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """Static contract metadata for a hot-loadable plugin."""

    plugin_id: str
    role_name: str
    module: str
    class_name: str
    capabilities: tuple[str, ...]
    side_effect_level: SideEffectLevel
    requires_auth: bool
    secret_names: tuple[str, ...]
    supports_dry_run: bool
    test_fixture: str
    external_services: tuple[str, ...] = ()
    requires_mocked_contract_tests: bool = False


PLUGIN_MANIFESTS: dict[str, PluginManifest] = {
    "aws_management": PluginManifest(
        plugin_id="aws_management",
        role_name="aws_management",
        module="plugins.aws_management_agent",
        class_name="AWSManagementAgent",
        capabilities=("aws_management", "cloud_ops", "inventory_read"),
        side_effect_level="external_read",
        requires_auth=True,
        secret_names=("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE"),
        supports_dry_run=False,
        test_fixture="tests/unit/plugins/test_aws_management_agent.py",
        external_services=("aws",),
        requires_mocked_contract_tests=True,
    ),
    "crypto_price": PluginManifest(
        plugin_id="crypto_price",
        role_name="crypto_price",
        module="plugins.crypto_price_agent",
        class_name="CryptoPriceAgent",
        capabilities=("crypto_price", "market_data", "price_lookup"),
        side_effect_level="external_read",
        requires_auth=False,
        secret_names=(),
        supports_dry_run=False,
        test_fixture="tests/unit/plugins/test_crypto_price_agent.py",
        external_services=("coingecko",),
        requires_mocked_contract_tests=True,
    ),
    "slack_notifications": PluginManifest(
        plugin_id="slack_notifications",
        role_name="slack_notifications",
        module="plugins.slack_notification_agent",
        class_name="SlackNotificationAgent",
        capabilities=("slack_notification", "team_notifications", "webhook_post"),
        side_effect_level="external_write",
        requires_auth=True,
        secret_names=("SLACK_WEBHOOK_URL", "SLACK_TOKEN"),
        supports_dry_run=False,
        test_fixture="tests/unit/plugins/test_slack_notification_agent.py",
        external_services=("slack",),
        requires_mocked_contract_tests=True,
    ),
    "upload": PluginManifest(
        plugin_id="upload",
        role_name="upload",
        module="plugins.upload_agent",
        class_name="UploadAgent",
        capabilities=("plugin_upload", "echo_task"),
        side_effect_level="none",
        requires_auth=False,
        secret_names=(),
        supports_dry_run=True,
        test_fixture="tests/unit/plugins/test_upload_agent.py",
    ),
}


EXTERNAL_SERVICE_PLUGIN_IDS = frozenset(
    plugin_id
    for plugin_id, manifest in PLUGIN_MANIFESTS.items()
    if manifest.external_services or manifest.side_effect_level.startswith("external_")
)


def get_plugin_manifest(plugin_id: str) -> PluginManifest:
    """Return manifest metadata for a plugin id."""

    return PLUGIN_MANIFESTS[plugin_id]
