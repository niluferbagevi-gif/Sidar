"""
tests/test_core_dlp.py
======================
core/dlp.py — DLP (Data Loss Prevention) & PII maskeleme modülünün birim testleri.
"""

from __future__ import annotations

import importlib
import sys

import pytest


def _fresh():
    sys.modules.pop("core.dlp", None)
    return importlib.import_module("core.dlp")


# ─────────────────────────────────────────────────────────────────────────────
# _is_valid_tckn
# ─────────────────────────────────────────────────────────────────────────────

class TestIsValidTCKN:
    """TCKN algoritma doğrulama testleri."""

    def setup_method(self):
        self.mod = _fresh()

    def test_gecerli_tckn(self):
        # Geçerli bir TCKN (algoritma uyumlu)
        assert self.mod._is_valid_tckn("10000000146") is True

    def test_sifirla_baslayan_gecersiz(self):
        assert self.mod._is_valid_tckn("01234567890") is False

    def test_11_hane_degil(self):
        assert self.mod._is_valid_tckn("1234567890") is False    # 10 hane
        assert self.mod._is_valid_tckn("123456789012") is False  # 12 hane

    def test_rakam_olmayan(self):
        assert self.mod._is_valid_tckn("1234567890x") is False

    def test_yanlis_kontrol_hanesi(self):
        assert self.mod._is_valid_tckn("12345678901") is False


# ─────────────────────────────────────────────────────────────────────────────
# DLPDetection
# ─────────────────────────────────────────────────────────────────────────────

class TestDLPDetection:
    """DLPDetection dataclass testleri."""

    def setup_method(self):
        self.mod = _fresh()

    def test_olusturma(self):
        det = self.mod.DLPDetection("email", 0, 10, "test@ex…")
        assert det.pattern_name == "email"
        assert det.start == 0
        assert det.end == 10


# ─────────────────────────────────────────────────────────────────────────────
# DLPEngine.mask
# ─────────────────────────────────────────────────────────────────────────────

class TestDLPEngineMask:
    """DLPEngine.mask() fonksiyonunun tüm örüntüleri için testler."""

    def setup_method(self):
        self.mod = _fresh()
        self.engine = self.mod.DLPEngine()

    def test_bos_metin_degismeden_doner(self):
        result, dets = self.engine.mask("")
        assert result == ""
        assert dets == []

    def test_email_maskelenir(self):
        text = "Mail: user@example.com adresine gönder"
        result, dets = self.engine.mask(text)
        assert "user@example.com" not in result
        assert "[MASKED]" in result
        assert any(d.pattern_name == "email" for d in dets)

    def test_bearer_token_maskelenir(self):
        text = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz1234"
        result, dets = self.engine.mask(text)
        assert "abcdefghijklmnopqrstuvwxyz1234" not in result
        assert any(d.pattern_name == "bearer_token" for d in dets)

    def test_sk_key_maskelenir(self):
        text = "key = sk-abcdefghijklmnopqrst123456789"
        result, dets = self.engine.mask(text)
        assert any(d.pattern_name == "sk_key" for d in dets)

    def test_aws_access_key_maskelenir(self):
        text = "access_key = AKIAIOSFODNN7EXAMPLE"
        result, dets = self.engine.mask(text)
        assert any(d.pattern_name == "aws_access_key" for d in dets)

    def test_kv_secret_maskelenir(self):
        text = "api_key=mysupersecretvalue12345"
        result, dets = self.engine.mask(text)
        assert any(d.pattern_name == "kv_secret" for d in dets)

    def test_password_maskelenir(self):
        text = "password=gizlisifre123"
        result, dets = self.engine.mask(text)
        assert any(d.pattern_name == "password" for d in dets)

    def test_jwt_maskelenir(self):
        # Geçerli JWT formatı (3 bölüm, ey ile başlayan)
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMTIzIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        text = f"token: {jwt}"
        result, dets = self.engine.mask(text)
        assert any(d.pattern_name == "jwt" for d in dets)

    def test_kredi_karti_maskelenir(self):
        text = "Kart: 4111111111111111"
        result, dets = self.engine.mask(text)
        assert any(d.pattern_name == "credit_card" for d in dets)

    def test_uzun_hex_varsayilan_kapali(self):
        text = "hash: " + "a" * 32
        result, dets = self.engine.mask(text)
        # Varsayılan kapalı → maskelenmemeli
        assert not any(d.pattern_name == "long_hex" for d in dets)

    def test_uzun_hex_acikca_etkin(self):
        engine = self.mod.DLPEngine(mask_long_hex=True)
        text = "hash: " + "a" * 32
        result, dets = engine.mask(text)
        assert any(d.pattern_name == "long_hex" for d in dets)

    def test_kapatilan_oruntu_maskelemez(self):
        engine = self.mod.DLPEngine(mask_email=False)
        text = "Mail: user@example.com"
        result, dets = engine.mask(text)
        assert "user@example.com" in result
        assert not any(d.pattern_name == "email" for d in dets)

    def test_ozel_replacement(self):
        engine = self.mod.DLPEngine(replacement="***GIZLI***")
        text = "email: user@example.com"
        result, _ = engine.mask(text)
        assert "***GIZLI***" in result

    def test_temiz_metin_degismeden_doner(self):
        text = "Merhaba dünya, bu güvenli bir metindir."
        result, dets = self.engine.mask(text)
        assert result == text
        assert dets == []

    def test_log_detections_etkin(self, caplog):
        import logging
        engine = self.mod.DLPEngine(log_detections=True)
        with caplog.at_level(logging.WARNING):
            engine.mask("token: sk-abcdefghijklmnopqrstuvwxyz")
        # Log mesajı üretilmiş olabilir (DLP uyarısı)
        # Test sadece hata fırlatmadığını doğrular

    def test_tckn_gecerli_maskelenir(self):
        # Geçerli TCKN
        text = "TC: 10000000146"
        result, dets = self.engine.mask(text)
        assert any(d.pattern_name == "tckn" for d in dets)

    def test_tckn_gecersiz_maskelenmez(self):
        text = "sayi: 12345678901"
        result, dets = self.engine.mask(text)
        assert not any(d.pattern_name == "tckn" for d in dets)


# ─────────────────────────────────────────────────────────────────────────────
# DLPEngine.mask_messages
# ─────────────────────────────────────────────────────────────────────────────

class TestDLPEngineMaskMessages:
    """DLPEngine.mask_messages() testleri."""

    def setup_method(self):
        self.mod = _fresh()
        self.engine = self.mod.DLPEngine()

    def test_bos_liste(self):
        result, dets = self.engine.mask_messages([])
        assert result == []
        assert dets == []

    def test_temiz_mesajlar_ayni_referans(self):
        msgs = [{"role": "user", "content": "Merhaba"}]
        result, _ = self.engine.mask_messages(msgs)
        assert result[0] is msgs[0]  # Aynı nesne (değişmedi)

    def test_hassas_mesaj_maskelenir(self):
        msgs = [{"role": "user", "content": "email: test@example.com"}]
        result, dets = self.engine.mask_messages(msgs)
        assert "test@example.com" not in result[0]["content"]
        assert len(dets) > 0

    def test_bos_content(self):
        msgs = [{"role": "user", "content": ""}]
        result, dets = self.engine.mask_messages(msgs)
        assert result[0] is msgs[0]
        assert dets == []

    def test_none_content(self):
        msgs = [{"role": "user", "content": None}]
        result, dets = self.engine.mask_messages(msgs)
        assert result[0] is msgs[0]

    def test_cok_mesaj(self):
        msgs = [
            {"role": "system", "content": "Sen bir asistansın."},
            {"role": "user", "content": "password=gizlisifre123"},
            {"role": "assistant", "content": "Anlıyorum."},
        ]
        result, dets = self.engine.mask_messages(msgs)
        assert len(result) == 3
        assert len(dets) > 0
        assert "gizlisifre123" not in result[1]["content"]


# ─────────────────────────────────────────────────────────────────────────────
# Singleton & yardımcı fonksiyonlar
# ─────────────────────────────────────────────────────────────────────────────

class TestDLPSingleton:
    """get_dlp_engine(), mask_pii(), mask_messages() testleri."""

    def setup_method(self):
        self.mod = _fresh()
        self.mod._ENGINE = None  # Singleton sıfırla

    def test_get_dlp_engine_singleton(self):
        a = self.mod.get_dlp_engine()
        b = self.mod.get_dlp_engine()
        assert a is b

    def test_get_dlp_engine_tipi(self):
        e = self.mod.get_dlp_engine()
        assert isinstance(e, self.mod.DLPEngine)

    def test_mask_pii_kolaylik(self):
        self.mod._ENGINE = self.mod.DLPEngine()
        result = self.mod.mask_pii("user@example.com gönder")
        assert "user@example.com" not in result

    def test_mask_messages_kolaylik(self):
        self.mod._ENGINE = self.mod.DLPEngine()
        msgs = [{"role": "user", "content": "sk-abcdefghijklmnopqrstuvwxyz"}]
        result = self.mod.mask_messages(msgs)
        assert isinstance(result, list)

    def test_dlp_disabled_env(self, monkeypatch):
        monkeypatch.setenv("DLP_ENABLED", "false")
        self.mod._ENGINE = None
        engine = self.mod.get_dlp_engine()
        # Devre dışı motor hiçbir şeyi maskelemez
        result, dets = engine.mask("password=gizli123")
        assert "password=gizli123" in result
        assert dets == []

    def test_dlp_log_detections_env(self, monkeypatch):
        monkeypatch.setenv("DLP_LOG_DETECTIONS", "true")
        monkeypatch.setenv("DLP_ENABLED", "true")
        self.mod._ENGINE = None
        engine = self.mod.get_dlp_engine()
        assert engine.log_detections is True