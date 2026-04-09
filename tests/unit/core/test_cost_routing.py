"""Tests for core.router (CostAwareRouter + QueryComplexityAnalyzer).

Kapsam:
  - Yönlendirme devre dışı → varsayılan korunur
  - Günlük bütçe aşımı → lokal modele fail-closed
  - Karmaşıklık eşiği (lokal / bulut kararı)
  - Bulut sağlayıcısı eksikse varsayılan korunur
  - QueryComplexityAnalyzer: boş mesaj, kod anahtar kelimeleri,
    basit ifade penaltisi, çoklu soru, uzunluk üst sınırı
  - record_routing_cost birikimli maliyet kayıt
  - frozen_time ile 24 saatlik bütçe sıfırlaması
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import core.router as router_module
from core.router import CostAwareRouter, QueryComplexityAnalyzer, record_routing_cost


# ─────────────────────────────────────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────────────────────────────────────

def _cfg(**overrides: object) -> SimpleNamespace:
    base = {
        "ENABLE_COST_ROUTING": True,
        "COST_ROUTING_COMPLEXITY_THRESHOLD": 0.60,
        "COST_ROUTING_LOCAL_PROVIDER": "ollama",
        "COST_ROUTING_LOCAL_MODEL": "llama3",
        "COST_ROUTING_CLOUD_PROVIDER": "openai",
        "COST_ROUTING_CLOUD_MODEL": "gpt-4o",
        "COST_ROUTING_DAILY_BUDGET_USD": 10.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _reset_budget_tracker():
    """Her testten önce/sonra global bütçe izleyiciyi sıfırlar."""
    router_module._budget_tracker._daily_cost = 0.0
    router_module._budget_tracker._day_start = time.time()
    yield
    router_module._budget_tracker._daily_cost = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Eşik bazlı yönlendirme (mevcut testler)
# ─────────────────────────────────────────────────────────────────────────────

def test_cost_routing_threshold_prefers_local_for_simple_query() -> None:
    router = CostAwareRouter(_cfg(COST_ROUTING_COMPLEXITY_THRESHOLD=0.90))

    provider, model = router.select(
        [{"role": "user", "content": "kısaca açıkla"}],
        default_provider="openai",
        default_model="gpt-4o-mini",
    )

    assert (provider, model) == ("ollama", "llama3")


def test_cost_routing_threshold_prefers_cloud_for_complex_query() -> None:
    router = CostAwareRouter(_cfg(COST_ROUTING_COMPLEXITY_THRESHOLD=0.20))

    provider, model = router.select(
        [
            {
                "role": "user",
                "content": (
                    "Please analyze and compare algorithm complexity tradeoff and "
                    "design pattern choices with examples?"
                ),
            }
        ],
        default_provider="ollama",
        default_model="llama3",
    )

    assert (provider, model) == ("openai", "gpt-4o")


def test_cost_routing_fail_closed_when_cloud_provider_missing() -> None:
    router = CostAwareRouter(_cfg(COST_ROUTING_COMPLEXITY_THRESHOLD=0.10, COST_ROUTING_CLOUD_PROVIDER=""))

    provider, model = router.select(
        [{"role": "user", "content": "analyze algorithm tradeoff in detail?"}],
        default_provider="anthropic",
        default_model="claude-3-5-sonnet",
    )

    # Fail-closed: bulut provider konfigürasyonu yoksa varsayılan korunur.
    assert (provider, model) == ("anthropic", "claude-3-5-sonnet")


# ─────────────────────────────────────────────────────────────────────────────
# Devre dışı yönlendirme
# ─────────────────────────────────────────────────────────────────────────────

def test_cost_routing_disabled_always_returns_default() -> None:
    """ENABLE_COST_ROUTING=False olduğunda router devreye girmez, default döner."""
    router = CostAwareRouter(SimpleNamespace(
        ENABLE_COST_ROUTING=False,
        COST_ROUTING_COMPLEXITY_THRESHOLD=0.10,  # etkin olsaydı cloud'a giderdi
        COST_ROUTING_CLOUD_PROVIDER="openai",
        COST_ROUTING_CLOUD_MODEL="gpt-4o",
    ))

    provider, model = router.select(
        [{"role": "user", "content": "analyze and compare algorithms in detail"}],
        default_provider="anthropic",
        default_model="claude-3",
    )

    assert (provider, model) == ("anthropic", "claude-3")


# ─────────────────────────────────────────────────────────────────────────────
# Günlük bütçe aşımı
# ─────────────────────────────────────────────────────────────────────────────

def test_cost_routing_budget_exceeded_forces_local_regardless_of_complexity() -> None:
    """Günlük bütçe aşıldığında karmaşık sorgu bile lokal modele yönlendirilir."""
    router = CostAwareRouter(_cfg(
        COST_ROUTING_COMPLEXITY_THRESHOLD=0.10,  # neredeyse her şeyi cloud'a gönderir
        COST_ROUTING_DAILY_BUDGET_USD=0.01,
    ))
    record_routing_cost(0.02)  # 0.02 > 0.01 → bütçe aşıldı

    provider, model = router.select(
        [{"role": "user", "content": "analyze complex algorithm tradeoffs in detail"}],
        default_provider="openai",
        default_model="gpt-4o",
    )

    assert provider == "ollama"
    assert model == "llama3"


def test_record_routing_cost_accumulates_and_triggers_budget_exceeded() -> None:
    """record_routing_cost birden fazla çağrıda birikir ve bütçe eşiğini aşar."""
    router = CostAwareRouter(_cfg(COST_ROUTING_DAILY_BUDGET_USD=0.10))

    record_routing_cost(0.06)
    record_routing_cost(0.06)  # toplam 0.12 > 0.10

    provider, _ = router.select(
        [{"role": "user", "content": "analyze complex algorithms"}],
        default_provider="openai",
    )

    assert provider == "ollama"


def test_cost_routing_budget_not_exceeded_still_routes_to_cloud() -> None:
    """Bütçe aşılmadığı sürece karmaşık sorgu cloud'a yönlendirilir."""
    router = CostAwareRouter(_cfg(
        COST_ROUTING_COMPLEXITY_THRESHOLD=0.10,
        COST_ROUTING_DAILY_BUDGET_USD=1.00,
    ))
    record_routing_cost(0.05)  # 0.05 < 1.00 → bütçe aşılmadı

    provider, model = router.select(
        [{"role": "user", "content": "analyze complex algorithm tradeoffs"}],
        default_provider="ollama",
    )

    assert provider == "openai"
    assert model == "gpt-4o"


# ─────────────────────────────────────────────────────────────────────────────
# Model seçim davranışları
# ─────────────────────────────────────────────────────────────────────────────

def test_cost_routing_cloud_model_takes_precedence_over_default_model() -> None:
    """Bulut yönlendirmesinde COST_ROUTING_CLOUD_MODEL varsa default_model yerine kullanılır."""
    router = CostAwareRouter(_cfg(COST_ROUTING_COMPLEXITY_THRESHOLD=0.10))

    provider, model = router.select(
        [{"role": "user", "content": "analyze complex algorithm tradeoffs"}],
        default_provider="ollama",
        default_model="llama3",
    )

    assert provider == "openai"
    assert model == "gpt-4o"  # default_model="llama3" değil, cloud_model


def test_cost_routing_local_model_empty_returns_none_model() -> None:
    """COST_ROUTING_LOCAL_MODEL boşken lokal yönlendirmede model=None döner."""
    router = CostAwareRouter(_cfg(
        COST_ROUTING_COMPLEXITY_THRESHOLD=0.90,
        COST_ROUTING_LOCAL_MODEL="",
    ))

    _, model = router.select(
        [{"role": "user", "content": "kısaca açıkla"}],
        default_provider="openai",
        default_model="gpt-4o-mini",
    )

    assert model is None


# ─────────────────────────────────────────────────────────────────────────────
# QueryComplexityAnalyzer — ayrıntılı skor testleri
# ─────────────────────────────────────────────────────────────────────────────

def test_complexity_score_empty_messages_returns_zero() -> None:
    """Boş mesaj listesi skor 0.0 döner."""
    assert QueryComplexityAnalyzer().score([]) == 0.0


def test_complexity_score_only_assistant_role_returns_zero() -> None:
    """Yalnızca assistant mesajları var; user içeriği yok → skor 0.0."""
    assert QueryComplexityAnalyzer().score(
        [{"role": "assistant", "content": "explain everything in detail"}]
    ) == 0.0


def test_complexity_score_code_keywords_increase_score() -> None:
    """def / class / import gibi kod anahtar kelimeleri skoru yükseltir."""
    analyzer = QueryComplexityAnalyzer()
    simple = analyzer.score([{"role": "user", "content": "merhaba"}])
    with_code = analyzer.score([
        {"role": "user", "content": "def my_func(): class MyClass: import os async def"}
    ])
    assert with_code > simple
    assert with_code >= 0.15


def test_complexity_score_reasoning_keywords_increase_score() -> None:
    """'analyze' / 'compare' / 'tradeoff' gibi akıl yürütme kelimeler skoru yükseltir."""
    analyzer = QueryComplexityAnalyzer()
    base = analyzer.score([{"role": "user", "content": "hello"}])
    reasoned = analyzer.score([
        {"role": "user", "content": "analyze and compare the tradeoff algorithm"}
    ])
    assert reasoned > base


def test_complexity_score_simple_keyword_halves_result() -> None:
    """'briefly' / 'kısaca' gibi basit ifadeler skoru yarıya indirir."""
    analyzer = QueryComplexityAnalyzer()
    base = analyzer.score([
        {"role": "user", "content": "explain algorithm complexity tradeoff"}
    ])
    halved = analyzer.score([
        {"role": "user", "content": "briefly explain algorithm complexity tradeoff"}
    ])
    assert halved < base
    # 0.5x çarpanı uygulanmış olmalı (yuvarlama payı ±0.05)
    assert abs(halved - base * 0.5) < 0.05


def test_complexity_score_multiple_questions_add_incremental_score() -> None:
    """Çok sayıda soru işareti kümülatif puan ekler (0.03/? üst sınır 0.10)."""
    analyzer = QueryComplexityAnalyzer()
    single = analyzer.score([{"role": "user", "content": "what is this?"}])
    multi = analyzer.score([
        {"role": "user", "content": "what? how? why? when? where?"}
    ])
    assert multi > single


def test_complexity_score_long_text_caps_length_contribution_at_035() -> None:
    """Çok uzun metinler uzunluk katkısını 0.35'te durdurur."""
    analyzer = QueryComplexityAnalyzer()
    # Başka anahtar kelime yok; sadece uzunluk katkısı beklenir.
    long_msg = "lorem ipsum " * 300  # ~3600 karakter >> 800 eşiği
    score = analyzer.score([{"role": "user", "content": long_msg}])
    # Uzunluk 0.35 tavanını aşamaz; diğer katkı yok.
    assert score <= 0.35 + 0.01


def test_complexity_score_is_capped_at_one() -> None:
    """Birden fazla bileşenin toplamı 1.0'ı aşmaz."""
    analyzer = QueryComplexityAnalyzer()
    # Uzunluk + kod + akıl yürütme + çoklu soru → maksimum 1.0
    very_complex = (
        "def func(): class C: import os async await lambda "
        "analyze compare tradeoff explain refactor algorithm design pattern "
        "complexity optimize architect best practice evaluate? describe in detail? "
    ) * 5
    score = analyzer.score([{"role": "user", "content": very_complex}])
    assert score <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Bütçe 24 saatlik sıfırlanma — frozen_time ile
# ─────────────────────────────────────────────────────────────────────────────

def test_daily_budget_resets_after_24_hours(frozen_time) -> None:
    """frozen_time fixture ile 24 saat sonra günlük bütçenin sıfırlandığını doğrular."""
    # frozen_time başlangıcını (2026-04-01 12:00:00) izleyicinin referansı yap.
    router_module._budget_tracker._day_start = time.time()
    router_module._budget_tracker._daily_cost = 0.0

    record_routing_cost(0.50)  # budget aşıldı (limit 10 değil, düşük budget kullanalım)

    low_budget_router = CostAwareRouter(_cfg(
        COST_ROUTING_COMPLEXITY_THRESHOLD=0.10,
        COST_ROUTING_DAILY_BUDGET_USD=0.10,
    ))

    # Şu an bütçe aşıldı → lokal
    p1, _ = low_budget_router.select(
        [{"role": "user", "content": "analyze complex algorithms"}],
        default_provider="openai",
    )
    assert p1 == "ollama"

    # 25 saat ileri sar (frozen_time 2026-04-01 → 2026-04-02 13:00)
    frozen_time.move_to("2026-04-02 13:00:00")

    # _reset_if_new_day() 25 saat geçtiğini görür → daily_cost = 0.0
    p2, _ = low_budget_router.select(
        [{"role": "user", "content": "analyze complex algorithms"}],
        default_provider="openai",
    )
    assert p2 == "openai"
