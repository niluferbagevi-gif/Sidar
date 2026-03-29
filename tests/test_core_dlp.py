"""
core/dlp.py için birim testleri.
DLPEngine, _is_valid_tckn, mask_pii, mask_messages ve
get_dlp_engine singleton davranışını kapsar.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest


# ──────────────────────────────────────────────────────────────
# Yardımcı: modülü temiz yükle
# ──────────────────────────────────────────────────────────────

def _get_dlp():
    if "core.dlp" in sys.modules:
        del sys.modules["core.dlp"]
    import core.dlp as dlp
    # Singleton'ı her test için sıfırla
    dlp._ENGINE = None
    return dlp


# ══════════════════════════════════════════════════════════════
# _is_valid_tckn
# ══════════════════════════════════════════════════════════════

class TestIsValidTckn:
    def setup_method(self):
        self.fn = _get_dlp()._is_valid_tckn

    def test_valid_tckn(self):
        # Gerçek algoritmayla doğrulanmış TCKN
        assert self.fn("10000000146") is True

    def test_starts_with_zero_is_invalid(self):
        assert self.fn("01234567890") is False

    def test_wrong_length_short(self):
        assert self.fn("1234567890") is False

    def test_wrong_length_long(self):
        assert self.fn("123456789012") is False

    def test_non_digits_invalid(self):
        assert self.fn("1234567890a") is False

    def test_all_zeros_invalid(self):
        assert self.fn("00000000000") is False

    def test_random_11_digits_likely_invalid(self):
        # Tamamen rastgele → büyük ihtimalle geçersiz
        assert self.fn("12345678901") is False

    def test_invalid_when_11th_digit_checksum_mismatch(self):
        # 10000000146 geçerli; son haneyi bozunca 11. hane doğrulaması patlar.
        assert self.fn("10000000147") is False


# ══════════════════════════════════════════════════════════════
# DLPEngine.mask — Bearer token
# ══════════════════════════════════════════════════════════════

class TestDLPEngineBearer:
    def setup_method(self):
        dlp = _get_dlp()
        self.engine = dlp.DLPEngine()
        self.mask = dlp._DEFAULT_MASK

    def test_bearer_token_masked(self):
        text = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz12345"
        result, dets = self.engine.mask(text)
        assert self.mask in result
        assert len(dets) >= 1
        assert dets[0].pattern_name == "bearer_token"

    def test_bearer_disabled_keeps_token(self):
        dlp = _get_dlp()
        engine = dlp.DLPEngine(mask_bearer=False)
        text = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz12345"
        result, dets = engine.mask(text)
        assert "abcdefghijklmnopqrstuvwxyz12345" in result
        assert not any(d.pattern_name == "bearer_token" for d in dets)


# ══════════════════════════════════════════════════════════════
# DLPEngine.mask — SK key
# ══════════════════════════════════════════════════════════════

class TestDLPEngineSKKey:
    def setup_method(self):
        dlp = _get_dlp()
        self.engine = dlp.DLPEngine()
        self.mask = dlp._DEFAULT_MASK

    def test_sk_key_masked(self):
        text = "API anahtarı: sk-abcdefghijklmnopqrstuvwxyz1234"
        result, dets = self.engine.mask(text)
        assert self.mask in result

    def test_sk_live_key_masked(self):
        text = "key=sk-live-abcdefghijklmnopqrstuv1234"
        result, dets = self.engine.mask(text)
        assert self.mask in result


# ══════════════════════════════════════════════════════════════
# DLPEngine.mask — GitHub token
# ══════════════════════════════════════════════════════════════

class TestDLPEngineGitHubToken:
    def setup_method(self):
        dlp = _get_dlp()
        self.engine = dlp.DLPEngine()
        self.mask = dlp._DEFAULT_MASK

    def test_github_pat_masked(self):
        # ghp_ + 36 alfanümerik karakter
        token = "ghp_" + "A" * 36
        result, dets = self.engine.mask(f"token: {token}")
        assert self.mask in result

    def test_github_token_disabled_keeps_token(self):
        dlp = _get_dlp()
        engine = dlp.DLPEngine(mask_github_tokens=False)
        token = "ghp_" + "A" * 36
        result, _ = engine.mask(f"token: {token}")
        assert token in result


# ══════════════════════════════════════════════════════════════
# DLPEngine.mask — AWS key
# ══════════════════════════════════════════════════════════════

class TestDLPEngineAWSKey:
    def setup_method(self):
        dlp = _get_dlp()
        self.engine = dlp.DLPEngine()
        self.mask = dlp._DEFAULT_MASK

    def test_aws_key_masked(self):
        text = "aws_access_key_id=AKIAIOSFODNN7EXAMPLE"
        result, dets = self.engine.mask(text)
        assert self.mask in result

    def test_non_akia_not_masked(self):
        text = "some key: BKIAIOSFODNN7EXAMPLE"
        result, _ = self.engine.mask(text)
        assert "BKIAIOSFODNN7EXAMPLE" in result


# ══════════════════════════════════════════════════════════════
# DLPEngine.mask — E-posta
# ══════════════════════════════════════════════════════════════

class TestDLPEngineEmail:
    def setup_method(self):
        dlp = _get_dlp()
        self.engine = dlp.DLPEngine()
        self.mask = dlp._DEFAULT_MASK

    def test_email_masked(self):
        result, dets = self.engine.mask("iletişim: test@example.com adresine yazın")
        assert self.mask in result
        assert any(d.pattern_name == "email" for d in dets)

    def test_multiple_emails_masked(self):
        result, dets = self.engine.mask("a@a.com ve b@b.org")
        assert result.count(self.mask) >= 2

    def test_email_disabled_keeps_address(self):
        dlp = _get_dlp()
        engine = dlp.DLPEngine(mask_email=False)
        result, _ = engine.mask("test@example.com")
        assert "test@example.com" in result


# ══════════════════════════════════════════════════════════════
# DLPEngine.mask — Şifre KV
# ══════════════════════════════════════════════════════════════

class TestDLPEnginePassword:
    def setup_method(self):
        dlp = _get_dlp()
        self.engine = dlp.DLPEngine()
        self.mask = dlp._DEFAULT_MASK

    def test_password_kv_masked(self):
        result, dets = self.engine.mask("password=supersecret123")
        assert self.mask in result
        assert any(d.pattern_name == "password" for d in dets)

    def test_parola_turkish_masked(self):
        result, _ = self.engine.mask("parola=gizli1234")
        assert self.mask in result

    def test_password_disabled_not_masked(self):
        dlp = _get_dlp()
        engine = dlp.DLPEngine(mask_passwords=False)
        result, _ = engine.mask("password=supersecret123")
        assert "supersecret123" in result


# ══════════════════════════════════════════════════════════════
# DLPEngine.mask — TCKN
# ══════════════════════════════════════════════════════════════

class TestDLPEngineTCKN:
    def setup_method(self):
        dlp = _get_dlp()
        self.engine = dlp.DLPEngine()
        self.mask = dlp._DEFAULT_MASK

    def test_valid_tckn_masked(self):
        # 10000000146 algoritmaya göre geçerli
        result, dets = self.engine.mask("TC: 10000000146")
        assert self.mask in result
        assert any(d.pattern_name == "tckn" for d in dets)

    def test_invalid_tckn_not_masked(self):
        # 12345678901 geçersiz algoritma
        result, _ = self.engine.mask("sayı: 12345678901")
        assert "12345678901" in result

    def test_tckn_disabled_keeps_number(self):
        dlp = _get_dlp()
        engine = dlp.DLPEngine(mask_tckn=False)
        result, _ = engine.mask("TC: 10000000146")
        assert "10000000146" in result


# ══════════════════════════════════════════════════════════════
# DLPEngine.mask — JWT
# ══════════════════════════════════════════════════════════════

class TestDLPEngineJWT:
    def setup_method(self):
        dlp = _get_dlp()
        self.engine = dlp.DLPEngine()
        self.mask = dlp._DEFAULT_MASK

    def test_jwt_token_masked(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMSJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        result, dets = self.engine.mask(f"token: {jwt}")
        assert self.mask in result

    def test_jwt_disabled_keeps_token(self):
        dlp = _get_dlp()
        engine = dlp.DLPEngine(mask_jwt=False)
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMSJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        result, _ = engine.mask(f"token: {jwt}")
        assert jwt in result


# ══════════════════════════════════════════════════════════════
# DLPEngine.mask — Genel edge case'ler
# ══════════════════════════════════════════════════════════════

class TestDLPEngineEdgeCases:
    def setup_method(self):
        dlp = _get_dlp()
        self.engine = dlp.DLPEngine()

    def test_empty_string_returns_empty(self):
        result, dets = self.engine.mask("")
        assert result == ""
        assert dets == []

    def test_none_falsy_string_returns_as_is(self):
        result, dets = self.engine.mask("")
        assert dets == []

    def test_clean_text_no_detections(self):
        result, dets = self.engine.mask("Merhaba dünya! Bugün hava güzel.")
        assert dets == []
        assert result == "Merhaba dünya! Bugün hava güzel."

    def test_custom_replacement(self):
        dlp = _get_dlp()
        engine = dlp.DLPEngine(replacement="***")
        result, _ = engine.mask("test@example.com")
        assert "***" in result

    def test_long_hex_disabled_by_default(self):
        dlp = _get_dlp()
        engine = dlp.DLPEngine()
        # 32 hex karakter — varsayılan kapalı
        result, dets = engine.mask("hash: " + "a" * 32)
        assert not any(d.pattern_name == "long_hex" for d in dets)

    def test_long_hex_enabled(self):
        dlp = _get_dlp()
        engine = dlp.DLPEngine(mask_long_hex=True)
        result, dets = engine.mask("hash: " + "a" * 32)
        assert any(d.pattern_name == "long_hex" for d in dets)

    def test_log_detections_emits_warning(self):
        dlp = _get_dlp()
        engine = dlp.DLPEngine(log_detections=True)
        with patch.object(dlp.logger, "warning") as warning_mock:
            _, dets = engine.mask("mail: ali@example.com")
        assert dets
        warning_mock.assert_called_once()


# ══════════════════════════════════════════════════════════════
# DLPEngine.mask_messages
# ══════════════════════════════════════════════════════════════

class TestDLPEngineMaskMessages:
    def setup_method(self):
        dlp = _get_dlp()
        self.engine = dlp.DLPEngine()
        self.mask = dlp._DEFAULT_MASK

    def test_message_with_email_masked(self):
        messages = [
            {"role": "user", "content": "e-posta: user@example.com"},
        ]
        result, dets = self.engine.mask_messages(messages)
        assert self.mask in result[0]["content"]
        assert len(dets) >= 1

    def test_clean_message_unchanged(self):
        messages = [{"role": "user", "content": "Merhaba!"}]
        result, dets = self.engine.mask_messages(messages)
        assert result[0] is messages[0]  # aynı obje döner
        assert dets == []

    def test_non_string_content_passed_through(self):
        messages = [{"role": "user", "content": None}]
        result, _ = self.engine.mask_messages(messages)
        assert result[0] is messages[0]

    def test_original_list_not_modified(self):
        messages = [{"role": "user", "content": "test@example.com"}]
        original_content = messages[0]["content"]
        self.engine.mask_messages(messages)
        assert messages[0]["content"] == original_content

    def test_multiple_messages_all_masked(self):
        messages = [
            {"role": "user", "content": "a@a.com"},
            {"role": "assistant", "content": "tamam"},
            {"role": "user", "content": "b@b.com"},
        ]
        result, dets = self.engine.mask_messages(messages)
        assert self.mask in result[0]["content"]
        assert result[1]["content"] == "tamam"
        assert self.mask in result[2]["content"]


# ══════════════════════════════════════════════════════════════
# mask_pii convenience wrapper
# ══════════════════════════════════════════════════════════════

class TestMaskPii:
    def test_returns_masked_string(self):
        dlp = _get_dlp()
        result = dlp.mask_pii("email: ali@example.com")
        assert isinstance(result, str)
        assert "@" not in result or dlp._DEFAULT_MASK in result

    def test_clean_text_returned_as_is(self):
        dlp = _get_dlp()
        result = dlp.mask_pii("temiz metin")
        assert result == "temiz metin"


# ══════════════════════════════════════════════════════════════
# mask_messages convenience wrapper
# ══════════════════════════════════════════════════════════════

class TestMaskMessagesWrapper:
    def test_returns_list(self):
        dlp = _get_dlp()
        result = dlp.mask_messages([{"role": "user", "content": "merhaba"}])
        assert isinstance(result, list)


# ══════════════════════════════════════════════════════════════
# get_dlp_engine singleton
# ══════════════════════════════════════════════════════════════

class TestGetDlpEngine:
    def test_returns_dlp_engine_instance(self):
        dlp = _get_dlp()
        engine = dlp.get_dlp_engine()
        assert isinstance(engine, dlp.DLPEngine)

    def test_same_instance_on_repeated_calls(self):
        dlp = _get_dlp()
        e1 = dlp.get_dlp_engine()
        e2 = dlp.get_dlp_engine()
        assert e1 is e2

    def test_dlp_disabled_via_env(self):
        dlp = _get_dlp()
        with patch.dict(os.environ, {"DLP_ENABLED": "false"}):
            dlp._ENGINE = None
            engine = dlp.get_dlp_engine()
        # Tüm maskeler kapalı
        assert engine.mask_email is False
        assert engine.mask_bearer is False
        dlp._ENGINE = None  # sonraki testler için sıfırla


# ══════════════════════════════════════════════════════════════
# DLPDetection dataclass
# ══════════════════════════════════════════════════════════════

class TestDLPDetection:
    def test_fields_set_correctly(self):
        dlp = _get_dlp()
        det = dlp.DLPDetection(
            pattern_name="email",
            start=5,
            end=20,
            original_value="ali@ex…",
        )
        assert det.pattern_name == "email"
        assert det.start == 5
        assert det.end == 20
        assert "ali" in det.original_value
