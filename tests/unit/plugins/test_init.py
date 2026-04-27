"""plugins paketi için temel import ve sınıf erişim testleri."""

import sys
import types


def _stub_base_agent() -> None:
    """Test ortamında ağır bağımlılıkları atlamak için BaseAgent stub'ı kurar."""
    if "agent.base_agent" not in sys.modules:
        fake_mod = types.ModuleType("agent.base_agent")

        class BaseAgent:  # pragma: no cover
            pass

        fake_mod.BaseAgent = BaseAgent
        sys.modules["agent.base_agent"] = fake_mod


_stub_base_agent()


def test_plugins_package_importable():
    """plugins paketi sorunsuz import edilebilmelidir."""
    import plugins  # noqa: F401 - sadece import testi

    assert plugins is not None


def test_upload_agent_class_importable():
    """UploadAgent sınıfı plugins.upload_agent'tan import edilebilmelidir."""
    from plugins.upload_agent import UploadAgent

    assert isinstance(UploadAgent, type)


def test_crypto_price_agent_class_importable():
    """CryptoPriceAgent sınıfı plugins.crypto_price_agent'tan import edilebilmelidir."""
    from plugins.crypto_price_agent import CryptoPriceAgent

    assert isinstance(CryptoPriceAgent, type)


def test_slack_notification_agent_class_importable():
    """SlackNotificationAgent sınıfı plugins.slack_notification_agent'tan import edilebilmelidir."""
    from plugins.slack_notification_agent import SlackNotificationAgent

    assert isinstance(SlackNotificationAgent, type)


def test_aws_management_agent_class_importable():
    """AWSManagementAgent sınıfı plugins.aws_management_agent'tan import edilebilmelidir."""
    from plugins.aws_management_agent import AWSManagementAgent

    assert isinstance(AWSManagementAgent, type)
