"""
tests/test_core_router.py
=========================
core/router.py — Cost-Aware Model Router modülünün birim testleri.
"""

from __future__ import annotations

import importlib
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _fresh():
    sys.modules.pop("core.router", None)
    return importlib.import_module("core.router")


# ─────────────────────────────────────────────────────────────────────────────
# QueryComplexityAnalyzer
# ─────────────────────────────────────────────────────────────────────────────

class TestQueryComplexityAnalyzer:
    """QueryComplexityAnalyzer.score() testleri."""

    def setup_method(self):
        mod = _fresh()
        self.Analyzer = mod.QueryComplexityAnalyzer

    def _make_msg(self, text: str) -> list:
        return [{"role": "user", "content": text}]

    def test_bos_mesaj_sifir_doner(self):
        a = self.Analyzer()
        assert a.score([]) == 0.0

    def test_bos_icerik_sifir_doner(self):
        a = self.Analyzer()
        assert a.score([{"role": "user", "content": ""}]) == 0.0

    def test_kisa_basit_metin_dusuk_skor(self):
        a = self.Analyzer()
        score = a.score(self._make_msg("hi"))
        assert score < 0.5

    def test_uzun_metin_yuksek_skor(self):
        a = self.Analyzer()
        long_text = "a " * 500  # 1000 karakter
        score = a.score(self._make_msg(long_text))
        assert score > 0.1

    def test_kod_anahtar_kelime_artirir(self):
        a = self.Analyzer()
        plain = a.score(self._make_msg("bana yardım et"))
        code_msg = a.score(self._make_msg("def function class import async ```python"))
        assert code_msg > plain

    def test_reasoning_anahtar_kelime_artirir(self):
        a = self.Analyzer()
        score = a.score(self._make_msg("explain analyze compare evaluate algorithm best practice"))
        assert score > 0.2

    def test_soru_isareti_artirir(self):
        a = self.Analyzer()
        multi_q = a.score(self._make_msg("bu ne? o neden? bu nasıl? bunun anlamı ne?"))
        single_q = a.score(self._make_msg("bu ne"))
        assert multi_q > single_q

    def test_basit_keyword_penalti(self):
        a = self.Analyzer()
        simple = a.score(self._make_msg("what is python"))
        complex_q = a.score(self._make_msg("python nedir ve nasıl çalışır"))
        # "what is" penaltisi uygulanır
        assert simple <= complex_q

    def test_skor_aralik_0_1(self):
        a = self.Analyzer()
        messages = [{"role": "user", "content": "def " * 100 + " explain " * 50}]
        score = a.score(messages)
        assert 0.0 <= score <= 1.0

    def test_sistem_mesajlari_sayilmaz(self):
        a = self.Analyzer()
        # Sistem mesajındaki içerik sayılmamalı
        msgs = [
            {"role": "system", "content": "def class import async await lambda " * 10},
            {"role": "user", "content": "hi"},
        ]
        score = a.score(msgs)
        assert score < 0.5

    def test_coklu_kullanici_mesaj(self):
        a = self.Analyzer()
        msgs = [
            {"role": "user", "content": "def func():"},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "explain analyze compare"},
        ]
        score = a.score(msgs)
        assert score > 0.1


# ─────────────────────────────────────────────────────────────────────────────
# _DailyBudgetTracker
# ─────────────────────────────────────────────────────────────────────────────

class TestDailyBudgetTracker:
    """_DailyBudgetTracker testleri."""

    def setup_method(self):
        mod = _fresh()
        self.Tracker = mod._DailyBudgetTracker

    def test_bos_kullanim(self):
        t = self.Tracker()
        assert t.daily_usage() == pytest.approx(0.0)

    def test_add_maliyet_ekler(self):
        t = self.Tracker()
        t.add(1.5)
        assert t.daily_usage() == pytest.approx(1.5)

    def test_negatif_maliyet_eklenmez(self):
        t = self.Tracker()
        t.add(-1.0)
        assert t.daily_usage() == pytest.approx(0.0)

    def test_exceeded_false(self):
        t = self.Tracker()
        t.add(1.0)
        assert t.exceeded(5.0) is False

    def test_exceeded_true(self):
        t = self.Tracker()
        t.add(6.0)
        assert t.exceeded(5.0) is True

    def test_exceeded_esit(self):
        t = self.Tracker()
        t.add(5.0)
        assert t.exceeded(5.0) is True

    def test_yeni_gun_sifirlanir(self):
        t = self.Tracker()
        t.add(3.0)
        # Günü manuel olarak geçmişe ayarla (86400 saniye geçmis)
        t._day_start = time.time() - 90000
        # Sonraki erişimde sıfırlanmalı
        assert t.daily_usage() == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# record_routing_cost
# ─────────────────────────────────────────────────────────────────────────────

class TestRecordRoutingCost:
    def setup_method(self):
        self.mod = _fresh()
        # Tracker'ı sıfırla
        self.mod._budget_tracker = self.mod._DailyBudgetTracker()

    def test_maliyet_kaydedilir(self):
        self.mod.record_routing_cost(2.0)
        assert self.mod._budget_tracker.daily_usage() == pytest.approx(2.0)


# ─────────────────────────────────────────────────────────────────────────────
# CostAwareRouter
# ─────────────────────────────────────────────────────────────────────────────

def _make_config(**kwargs) -> SimpleNamespace:
    defaults = {
        "ENABLE_COST_ROUTING": True,
        "COST_ROUTING_COMPLEXITY_THRESHOLD": 0.55,
        "COST_ROUTING_LOCAL_PROVIDER": "ollama",
        "COST_ROUTING_CLOUD_PROVIDER": "openai",
        "COST_ROUTING_DAILY_BUDGET_USD": 10.0,
        "COST_ROUTING_LOCAL_MODEL": "qwen2.5-coder:7b",
        "COST_ROUTING_CLOUD_MODEL": "gpt-4o",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestCostAwareRouter:
    """CostAwareRouter.select() testleri."""

    def setup_method(self):
        self.mod = _fresh()
        self.mod._budget_tracker = self.mod._DailyBudgetTracker()

    def test_devre_disi_varsayilana_doner(self):
        cfg = _make_config(ENABLE_COST_ROUTING=False)
        router = self.mod.CostAwareRouter(cfg)
        provider, model = router.select([{"role": "user", "content": "hi"}], "ollama", "qwen")
        assert provider == "ollama"
        assert model == "qwen"

    def test_butce_asiminda_lokale_yonlendirir(self):
        cfg = _make_config(COST_ROUTING_DAILY_BUDGET_USD=0.0)
        router = self.mod.CostAwareRouter(cfg)
        self.mod._budget_tracker.add(1.0)  # Bütçeyi aş
        provider, model = router.select([{"role": "user", "content": "def func():"}], "openai")
        assert provider == "ollama"

    def test_basit_sorgu_lokale_gider(self):
        cfg = _make_config()
        router = self.mod.CostAwareRouter(cfg)
        provider, model = router.select([{"role": "user", "content": "hi"}], "ollama")
        assert provider == "ollama"

    def test_karmasik_sorgu_buluta_gider(self):
        # Eşiği düşük tut (0.05 > 0 olduğu için "or 0.55" koşulunu atlar),
        # score ~0.1475 > 0.05 → buluta yönlendirir
        cfg = _make_config(
            COST_ROUTING_COMPLEXITY_THRESHOLD=0.05,
            COST_ROUTING_DAILY_BUDGET_USD=999.0,
        )
        router = self.mod.CostAwareRouter(cfg)
        self.mod._budget_tracker._daily_cost = 0.0
        provider, model = router.select(
            [{"role": "user", "content": "def " * 50}], "ollama"
        )
        assert provider == "openai"
        assert model == "gpt-4o"

    def test_bulut_saglayici_yok_varsayilana_doner(self):
        cfg = _make_config(
            COST_ROUTING_COMPLEXITY_THRESHOLD=0.05,
            COST_ROUTING_CLOUD_PROVIDER="",
            COST_ROUTING_DAILY_BUDGET_USD=999.0,
        )
        router = self.mod.CostAwareRouter(cfg)
        self.mod._budget_tracker._daily_cost = 0.0
        provider, model = router.select(
            [{"role": "user", "content": "def " * 50}], "ollama", "local_model"
        )
        assert provider == "ollama"
        assert model == "local_model"

    def test_lokal_provider_bos_ollama_fallback_doner(self):
        # local_provider="" → "or 'ollama'" → "ollama" kullanılır
        cfg = _make_config(
            COST_ROUTING_LOCAL_PROVIDER="",
            COST_ROUTING_DAILY_BUDGET_USD=0.001,
            COST_ROUTING_LOCAL_MODEL="",
        )
        router = self.mod.CostAwareRouter(cfg)
        # local_provider="" → router "ollama" kullanır (fallback)
        assert router.local_provider == "ollama"
        # Bütçeyi aş → lokal (ollama) ile döner
        self.mod._budget_tracker._daily_cost = 0.0
        self.mod._budget_tracker.add(10.0)
        provider, model = router.select([], "gemini", "gemini-flash")
        assert provider == "ollama"
        assert model is None  # local_model="" → None

    def test_lokal_model_bos_ise_none_doner(self):
        cfg = _make_config(COST_ROUTING_LOCAL_MODEL="")
        router = self.mod.CostAwareRouter(cfg)
        # Bütçeyi aş → lokal model None döner
        self.mod._budget_tracker.add(100.0)
        provider, model = router.select([], "ollama", "fallback")
        assert provider == "ollama"
        assert model is None

    def test_complexity_score_dogrudan(self):
        cfg = _make_config()
        router = self.mod.CostAwareRouter(cfg)
        score = router.complexity_score([{"role": "user", "content": "def func(): pass"}])
        assert 0.0 <= score <= 1.0

    def test_config_attributeler_eksik_varsayilan(self):
        # Config nesnesi bazı attribute'lara sahip değilse
        cfg = SimpleNamespace(ENABLE_COST_ROUTING=True)
        router = self.mod.CostAwareRouter(cfg)
        assert router.local_provider == "ollama"
        assert router.complexity_threshold == pytest.approx(0.55)