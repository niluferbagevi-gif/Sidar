"""Cost-Aware Model Routing (v5.0)

Sorgu karmaşıklığını analiz ederek lokal (Ollama) veya bulut (cloud) modele
otomatik olarak yönlendirir. Günlük bütçe aşımında otomatik lokal-fallback uygular.

Kullanım:
    router = CostAwareRouter(config)
    provider, model = router.select(messages, default_provider, default_model)
"""

from __future__ import annotations

import importlib
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from redis import Redis as _SyncRedisClient
else:  # pragma: no cover - yalnızca type-checking için
    _SyncRedisClient = Any

_SyncRedisClass: Any
try:
    from redis import Redis as _SyncRedisClass
except Exception:  # pragma: no cover - opsiyonel bağımlılık
    _SyncRedisClass = None

SyncRedis: type[_SyncRedisClient] | None = cast(type[_SyncRedisClient] | None, _SyncRedisClass)


# ──────────────────────────────────────────────────────────────────────────────
# Karmaşıklık Analizörü
# ──────────────────────────────────────────────────────────────────────────────


class QueryComplexityAnalyzer:
    """LLM çağrısından önceki karmaşıklık skoru (0.0–1.0) hesaplar."""

    # Kod üretimi / teknik gerektiren anahtar kelimeler
    _CODE_KEYWORDS = frozenset(
        [
            "def ",
            "class ",
            "import ",
            "async ",
            "await ",
            "lambda ",
            "function ",
            "return ",
            "yield ",
            "raise ",
            "try:",
            "except ",
            "```",
            "```python",
            "```javascript",
            "```typescript",
        ]
    )

    # Derin akıl yürütme / analiz gerektiren ifadeler
    _REASONING_KEYWORDS = frozenset(
        [
            "explain",
            "analyze",
            "compare",
            "evaluate",
            "describe in detail",
            "açıkla",
            "karşılaştır",
            "analiz et",
            "değerlendir",
            "detaylı anlat",
            "refactor",
            "optimize",
            "architect",
            "design pattern",
            "algorithm",
            "complexity",
            "tradeoff",
            "best practice",
        ]
    )

    # Basit / kısa cevap gerektiren ifadeler
    _SIMPLE_KEYWORDS = frozenset(
        [
            "what is",
            "ne demek",
            "kısaca",
            "briefly",
            "in one sentence",
            "yes or no",
            "true or false",
            "define ",
            "tanımla",
        ]
    )

    _MAX_SCORE = 1.0
    _DEFAULT_CHAR_BUDGET = 800
    _CHAR_BUDGET_ENV = "SIDAR_ROUTER_CHAR_BUDGET"

    @classmethod
    def _char_budget(cls) -> int:
        raw = os.getenv(cls._CHAR_BUDGET_ENV, str(cls._DEFAULT_CHAR_BUDGET))
        try:
            parsed = int(str(raw).strip())
        except (TypeError, ValueError):
            return cls._DEFAULT_CHAR_BUDGET
        return parsed if parsed > 0 else cls._DEFAULT_CHAR_BUDGET

    def score(self, messages: list[dict[str, str]]) -> float:
        """0.0 (basit) → 1.0 (karmaşık) aralığında skor döner."""
        combined = " ".join(
            (m.get("content") or "") for m in messages if m.get("role") == "user"
        ).lower()

        if not combined:
            return 0.0

        score = 0.0

        # Uzunluk bazlı (0.0–0.35)
        char_count = len(combined)
        score += min(0.35, (char_count / self._char_budget()) * 0.35)

        # Kod anahtar kelimeleri (0.0–0.30)
        code_hits = sum(1 for kw in self._CODE_KEYWORDS if kw in combined)
        score += min(0.30, code_hits * 0.06)

        # Akıl yürütme anahtar kelimeleri (0.0–0.25)
        reason_hits = sum(1 for kw in self._REASONING_KEYWORDS if kw in combined)
        score += min(0.25, reason_hits * 0.08)

        # Çoklu soru işaretleri veya madde listeleri (0.0–0.10)
        multi_q = len(re.findall(r"\?", combined))
        score += min(0.10, multi_q * 0.03)

        # Basit ifade penaltisi
        if any(kw in combined for kw in self._SIMPLE_KEYWORDS):
            score *= 0.5

        return min(self._MAX_SCORE, round(score, 4))


# ──────────────────────────────────────────────────────────────────────────────
# Bütçe İzleyici
# ──────────────────────────────────────────────────────────────────────────────


class _DailyBudgetTracker:
    """Günlük bulut maliyeti takibini process-içi tutar (yeniden başlatmada sıfırlanır)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day_start: float = time.time()
        self._daily_cost: float = 0.0

    def _reset_if_new_day(self) -> None:
        now = time.time()
        if now - self._day_start >= 86400:
            self._daily_cost = 0.0
            self._day_start = now

    def add(self, cost_usd: float) -> None:
        with self._lock:
            self._reset_if_new_day()
            self._daily_cost += max(0.0, cost_usd)

    def daily_usage(self) -> float:
        with self._lock:
            self._reset_if_new_day()
            return self._daily_cost

    def exceeded(self, limit_usd: float) -> bool:
        return self.daily_usage() >= limit_usd


_budget_tracker: _DailyBudgetTracker | _SqliteDailyBudgetTracker | _RedisDailyBudgetTracker = (
    _DailyBudgetTracker()
)
_TIKTOKEN_ENCODER = None


def _read_optional_string(config: object, attr_name: str) -> str:
    """Config üzerindeki opsiyonel string alanları güvenli şekilde normalize eder."""
    value = getattr(config, attr_name, "")
    if value is None:
        return ""
    if isinstance(value, Mock):
        return ""
    return str(value).strip()


def _configure_budget_tracker(config: object) -> None:
    """Global tracker'ı config'e göre seçer; gereksiz sıfırlama yapmaz."""
    global _budget_tracker

    shared_budget_db_path = _read_optional_string(config, "COST_ROUTING_SHARED_BUDGET_DB_PATH")
    if shared_budget_db_path:
        _budget_tracker = _SqliteDailyBudgetTracker(shared_budget_db_path)
        return

    shared_budget_redis_url = _read_optional_string(config, "COST_ROUTING_REDIS_BUDGET_URL")
    if shared_budget_redis_url:
        _budget_tracker = _RedisDailyBudgetTracker(shared_budget_redis_url)
        return

    if not isinstance(_budget_tracker, _DailyBudgetTracker):
        _budget_tracker = _DailyBudgetTracker()


class _SqliteDailyBudgetTracker:
    """Günlük maliyeti SQLite üzerinde processler arası paylaşarak takip eder."""

    _TABLE_NAME = "cost_routing_daily_budget"

    def __init__(self, db_path: str) -> None:
        self._db_path = str(db_path).strip()
        if not self._db_path:
            raise ValueError("db_path cannot be empty")
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=2.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE_NAME} (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    day_epoch INTEGER NOT NULL,
                    daily_cost REAL NOT NULL
                )
                """
            )

    @staticmethod
    def _current_day_epoch(now: float | None = None) -> int:
        ts = int(now if now is not None else time.time())
        return ts - (ts % 86400)

    def _upsert_usage(self, delta: float = 0.0) -> None:
        day_epoch = self._current_day_epoch()
        increment = max(0.0, float(delta or 0.0))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT day_epoch, daily_cost FROM {self._TABLE_NAME} WHERE id = 1"
                # nosec B608 - _TABLE_NAME sabit iç tanımlı değerdir, kullanıcı girdisi değildir.
            ).fetchone()
            if row is None or int(row[0]) != day_epoch:
                conn.execute(
                    f"INSERT INTO {self._TABLE_NAME} (id, day_epoch, daily_cost) VALUES (1, ?, ?)"
                    # nosec B608 - _TABLE_NAME sabit iç tanımlı değerdir, kullanıcı girdisi değildir.
                    " ON CONFLICT(id) DO UPDATE SET day_epoch=excluded.day_epoch, daily_cost=excluded.daily_cost",
                    (day_epoch, increment),
                )
            elif increment > 0.0:
                conn.execute(
                    f"UPDATE {self._TABLE_NAME} SET daily_cost = daily_cost + ? WHERE id = 1",
                    # nosec B608 - _TABLE_NAME sabit iç tanımlı değerdir, kullanıcı girdisi değildir.
                    (increment,),
                )
            conn.execute("COMMIT")

    def add(self, cost_usd: float) -> None:
        self._upsert_usage(delta=cost_usd)

    def daily_usage(self) -> float:
        self._upsert_usage(delta=0.0)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT daily_cost FROM {self._TABLE_NAME} WHERE id = 1"
                # nosec B608 - _TABLE_NAME sabit iç tanımlı değerdir, kullanıcı girdisi değildir.
            ).fetchone()
            return float(row[0]) if row else 0.0

    def exceeded(self, limit_usd: float) -> bool:
        return self.daily_usage() >= limit_usd


class _RedisDailyBudgetTracker:
    """Günlük maliyeti Redis üzerinde processler/podlar arası merkezi takip eder."""

    _KEY_PREFIX = "sidar:cost_routing:daily_budget"

    def __init__(self, redis_url: str) -> None:
        if SyncRedis is None:
            raise RuntimeError("Redis budget tracker için redis bağımlılığı gerekli.")
        self._redis_url = str(redis_url).strip()
        if not self._redis_url:
            raise ValueError("redis_url cannot be empty")
        self._redis = SyncRedis.from_url(self._redis_url, decode_responses=True)
        self._fallback = _DailyBudgetTracker()

    @staticmethod
    def _day_key(now: datetime | None = None) -> tuple[str, int]:
        current = now or datetime.now(UTC)
        day = current.strftime("%Y-%m-%d")
        midnight = datetime(current.year, current.month, current.day, tzinfo=UTC)
        next_midnight = midnight + timedelta(days=1)
        return f"{_RedisDailyBudgetTracker._KEY_PREFIX}:{day}", int(next_midnight.timestamp())

    def add(self, cost_usd: float) -> None:
        value = max(0.0, float(cost_usd or 0.0))
        if value <= 0.0:
            return
        key, expire_at = self._day_key()
        try:
            with self._redis.pipeline(transaction=True) as pipe:
                pipe.incrbyfloat(key, value)
                pipe.expireat(key, expire_at)
                _ = pipe.execute()  # type: ignore[no-untyped-call]
            return
        except Exception as exc:
            logger.debug("Redis budget tracker yazımı başarısız, in-memory fallback: %s", exc)
        self._fallback.add(value)

    def daily_usage(self) -> float:
        key, expire_at = self._day_key()
        try:
            raw = self._redis.get(key)
            if raw is None:
                return 0.0
            value = float(cast(Any, raw))
            self._redis.expireat(key, expire_at)
            return max(0.0, value)
        except Exception as exc:
            logger.debug("Redis budget tracker okuması başarısız, in-memory fallback: %s", exc)
            return self._fallback.daily_usage()

    def exceeded(self, limit_usd: float) -> bool:
        return self.daily_usage() >= limit_usd


def record_routing_cost(cost_usd: float) -> None:
    """Dışarıdan maliyet kaydı eklemek için yardımcı fonksiyon."""
    _budget_tracker.add(cost_usd)


# ──────────────────────────────────────────────────────────────────────────────
# Ana Router
# ──────────────────────────────────────────────────────────────────────────────


class CostAwareRouter:
    """
    Sorgu karmaşıklığı + günlük bütçeye göre lokal / bulut model seçer.

    Seçim mantığı:
    1. ENABLE_COST_ROUTING=false ise karar vermez, varsayılana bırakır.
    2. Günlük bütçe aşıldıysa → lokal.
    3. Karmaşıklık skoru eşiğin altındaysa → lokal.
    4. Aksi hâlde → bulut (config.COST_ROUTING_CLOUD_PROVIDER).
    """

    def __init__(self, config: object) -> None:
        self.config = config
        _configure_budget_tracker(config)
        self._analyzer = QueryComplexityAnalyzer()
        self.enabled: bool = bool(getattr(config, "ENABLE_COST_ROUTING", False))
        self.complexity_threshold: float = float(
            getattr(config, "COST_ROUTING_COMPLEXITY_THRESHOLD", 0.55) or 0.55
        )
        local_provider = getattr(config, "COST_ROUTING_LOCAL_PROVIDER", "ollama")
        self.local_provider: str = str(local_provider).strip() if local_provider is not None else ""
        self.cloud_provider: str = str(getattr(config, "COST_ROUTING_CLOUD_PROVIDER", "") or "")
        self.daily_budget_usd: float = float(
            getattr(config, "COST_ROUTING_DAILY_BUDGET_USD", 1.0) or 1.0
        )
        self.local_model: str = str(getattr(config, "COST_ROUTING_LOCAL_MODEL", "") or "")
        self.cloud_model: str = str(getattr(config, "COST_ROUTING_CLOUD_MODEL", "") or "")
        self.token_threshold: int = max(
            0, int(getattr(config, "COST_ROUTING_TOKEN_THRESHOLD", 0) or 0)
        )

    def select(
        self,
        messages: list[dict[str, str]],
        default_provider: str,
        default_model: str | None = None,
    ) -> tuple[str, str | None]:
        """
        (provider, model) çifti döner.
        Router devre dışıysa veya karar verilemiyorsa (default_provider, default_model) döner.
        """
        if not self.enabled:
            return default_provider, default_model

        # Bütçe aşımı → lokal
        if _budget_tracker.exceeded(self.daily_budget_usd):
            logger.info(
                "CostRouter: Günlük bütçe (%.2f USD) aşıldı, lokal modele yönlendiriliyor.",
                self.daily_budget_usd,
            )
            return self._local_result(default_provider, default_model)

        estimated_tokens = self._estimate_tokens(messages)
        if self.token_threshold > 0 and estimated_tokens >= self.token_threshold:
            logger.info(
                "CostRouter: Token eşiği (%d) aşıldı (tahmini=%d), lokal modele yönlendiriliyor.",
                self.token_threshold,
                estimated_tokens,
            )
            return self._local_result(default_provider, default_model)

        # Karmaşıklık skoru hesapla
        score = self._analyzer.score(messages)
        logger.debug(
            "CostRouter: karmaşıklık skoru=%.4f eşik=%.4f", score, self.complexity_threshold
        )

        if score < self.complexity_threshold:
            logger.debug("CostRouter: Basit sorgu → lokal model")
            return self._local_result(default_provider, default_model)

        # Karmaşık sorgu → bulut
        if not self.cloud_provider:
            logger.debug("CostRouter: Bulut sağlayıcısı ayarlanmamış, varsayılan korunuyor.")
            return default_provider, default_model

        logger.debug("CostRouter: Karmaşık sorgu → bulut: %s", self.cloud_provider)
        return self.cloud_provider, self.cloud_model or default_model

    def _local_result(
        self, default_provider: str, default_model: str | None
    ) -> tuple[str, str | None]:
        """Lokal provider/model çifti döner; lokal provider ayarlanmamışsa varsayılana bırakır."""
        if not self.local_provider:
            return default_provider, default_model
        return self.local_provider, self.local_model or None

    def complexity_score(self, messages: list[dict[str, str]]) -> float:
        """Test/debug için karmaşıklık skorunu doğrudan döner."""
        return self._analyzer.score(messages)

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, str]]) -> int:
        """
        Provider bağımsız yaklaşık token hesabı.
        Öncelik: tiktoken `cl100k_base` encoder.
        Fallback: Türkçe içerik için daha korumacı ~3 karakter ≈ 1 token yaklaşımı.
        """
        combined = " ".join((m.get("content") or "") for m in messages)
        if not combined:
            return 0
        global _TIKTOKEN_ENCODER
        try:
            if _TIKTOKEN_ENCODER is None:
                tiktoken = importlib.import_module("tiktoken")
                _TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
            return len(_TIKTOKEN_ENCODER.encode(combined))
        except Exception:
            return max(1, (len(combined) + 2) // 3)
