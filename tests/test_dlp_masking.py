"""
Tests for core/dlp.py — DLP & PII maskeleme modülü.
"""
import pytest
import core.dlp as dlp_mod
from core.dlp import DLPEngine, mask_pii, mask_messages, _is_valid_tckn


# ─── TCKN doğrulama ──────────────────────────────────────────────────────────

class TestTCKNValidation:
    def test_valid_tckn(self):
        # Geçerli TCKN örnekleri (test verileri; gerçek kişilerle ilişkili değil)
        assert _is_valid_tckn("10000000146") is True

    def test_invalid_tckn_starts_with_zero(self):
        assert _is_valid_tckn("01234567890") is False

    def test_invalid_tckn_wrong_length(self):
        assert _is_valid_tckn("1234567") is False

    def test_invalid_tckn_bad_checksum(self):
        assert _is_valid_tckn("12345678900") is False

    def test_invalid_tckn_fails_last_digit_checksum_guard(self):
        assert _is_valid_tckn("10000000147") is False


# ─── DLPEngine: temel maskeleme ──────────────────────────────────────────────

class TestDLPEngineMasking:
    def setup_method(self):
        self.engine = DLPEngine(replacement="[X]")

    def test_bearer_token_masked(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def"
        masked, dets = self.engine.mask(text)
        assert "eyJhbGci" not in masked
        assert "[X]" in masked
        assert any(d.pattern_name == "jwt" or d.pattern_name == "bearer_token" for d in dets)

    def test_sk_key_masked(self):
        text = "API key: sk-abcdefghijklmnopqrstuvwxyz1234"
        masked, dets = self.engine.mask(text)
        assert "sk-abcdef" not in masked
        assert any(d.pattern_name == "sk_key" for d in dets)

    def test_github_token_masked(self):
        token = "ghp_" + "A" * 36
        masked, dets = self.engine.mask(f"token: {token}")
        assert token not in masked
        assert any(d.pattern_name == "github_token" for d in dets)

    def test_email_masked(self):
        text = "İletişim: user@example.com adresine yazın"
        masked, dets = self.engine.mask(text)
        assert "user@example.com" not in masked
        assert any(d.pattern_name == "email" for d in dets)

    def test_password_kv_masked(self):
        text = "Bağlantı: password=SuperSecret123"
        masked, dets = self.engine.mask(text)
        assert "SuperSecret123" not in masked
        assert any(d.pattern_name == "password" for d in dets)

    def test_kv_secret_masked(self):
        text = "api_key=abcdef1234567890xyz"
        masked, dets = self.engine.mask(text)
        assert "abcdef1234567890xyz" not in masked
        assert any(d.pattern_name == "kv_secret" for d in dets)

    def test_jwt_masked(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        masked, dets = self.engine.mask(f"Token: {jwt}")
        assert jwt not in masked
        assert any(d.pattern_name == "jwt" for d in dets)

    def test_aws_key_masked(self):
        text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        masked, dets = self.engine.mask(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in masked
        assert any(d.pattern_name == "aws_access_key" for d in dets)

    def test_empty_text_unchanged(self):
        masked, dets = self.engine.mask("")
        assert masked == ""
        assert dets == []

    def test_clean_text_unchanged(self):
        text = "Bu metin tamamen temizdir ve maskelenmemelidir."
        masked, dets = self.engine.mask(text)
        assert masked == text
        assert dets == []


    def test_log_detections_emits_warning_when_masking_occurs(self, monkeypatch):
        engine = DLPEngine(replacement="[X]", log_detections=True)
        warnings = []
        monkeypatch.setattr(dlp_mod.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))

        masked, dets = engine.mask("İletişim: user@example.com")

        assert masked != "İletişim: user@example.com"
        assert any(d.pattern_name == "email" for d in dets)
        assert warnings and "hassas veri tespit edildi" in warnings[0]


# ─── mask_messages ───────────────────────────────────────────────────────────

class TestMaskMessages:
    def test_single_message_with_secret(self):
        messages = [
            {"role": "user", "content": "api_key=mysecretkey12345678"}
        ]
        result = mask_messages(messages)
        assert result[0]["content"] != messages[0]["content"]
        assert "mysecretkey12345678" not in result[0]["content"]

    def test_system_message_preserved_when_clean(self):
        messages = [
            {"role": "system", "content": "Sen yardımcı bir asistansın."},
            {"role": "user", "content": "Merhaba"},
        ]
        result = mask_messages(messages)
        assert result[0]["content"] == "Sen yardımcı bir asistansın."
        assert result[1]["content"] == "Merhaba"

    def test_message_without_content_key(self):
        messages = [{"role": "assistant"}]
        result = mask_messages(messages)
        assert result == messages

    def test_multiple_secrets_in_one_message(self):
        messages = [
            {"role": "user", "content": "key: sk-abcdefghijklmnop123456789 ve email: x@y.com"}
        ]
        result = mask_messages(messages)
        assert "sk-abcdef" not in result[0]["content"]
        assert "x@y.com" not in result[0]["content"]


    def test_non_string_content_is_left_untouched(self):
        messages = [{"role": "user", "content": ["api_key=secret"]}]
        result = mask_messages(messages)
        assert result == messages


# ─── Disabled engine ─────────────────────────────────────────────────────────

class TestDisabledEngine:
    def test_disabled_engine_passes_through(self):
        engine = DLPEngine(
            mask_bearer=False, mask_sk_keys=False, mask_github_tokens=False,
            mask_aws_keys=False, mask_kv_secrets=False, mask_passwords=False,
            mask_tckn=False, mask_email=False, mask_credit_cards=False,
            mask_jwt=False, mask_long_hex=False,
        )
        text = "password=secret123 email=a@b.com sk-testkey12345678901"
        masked, dets = engine.mask(text)
        assert masked == text
        assert dets == []


# ─── mask_pii kolaylık fonksiyonu ─────────────────────────────────────────────

def test_mask_pii_convenience():
    # sk- prefix + 20+ chars required by regex
    result = mask_pii("Kullanıcı: admin@corp.com, token: sk-abcdefghijklmnopqrst12345")
    assert "admin@corp.com" not in result
    assert "sk-abcdefghijklmnopqrst12345" not in result

def test_build_engine_from_env_returns_passive_engine_when_disabled(monkeypatch):
    monkeypatch.setenv("DLP_ENABLED", "false")

    engine = dlp_mod._build_engine_from_env()
    masked, dets = engine.mask("email=user@example.com password=secret123")

    assert masked == "email=user@example.com password=secret123"
    assert dets == []
    assert engine.mask_email is False
    assert engine.mask_passwords is False
