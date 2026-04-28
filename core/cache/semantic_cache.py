from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from core.cache_metrics import (
    observe_cache_redis_latency,
    record_cache_circuit_open_bypass,
    record_cache_eviction,
    record_cache_hit,
    record_cache_miss,
    record_cache_redis_error,
    record_cache_skip,
    set_cache_items,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedisClient
else:  # pragma: no cover - yalnızca type-checking için
    AsyncRedisClient = Any

try:
    from redis.asyncio import Redis as _AsyncRedisClass
except ImportError:
    _AsyncRedisClass = None

Redis: type[AsyncRedisClient] | None = _AsyncRedisClass

logger = logging.getLogger(__name__)


def _setting(config: Any, key: str, default: Any) -> Any:
    return getattr(config, key, default)


def _default_semantic_embedding_fn(texts: list[str], *, cfg: Any = None) -> list[list[float]]:
    from core.embeddings import embed_texts_for_semantic_cache

    return cast(list[list[float]], embed_texts_for_semantic_cache(texts, cfg=cfg))


class SemanticCacheManager:
    """Redis tabanlı semantik LLM yanıt önbelleği."""

    def __init__(
        self,
        config: Any,
        embedding_fn: Callable[..., list[list[float]]] | None = None,
    ) -> None:
        self.config = config
        self.enabled = bool(getattr(config, "ENABLE_SEMANTIC_CACHE", False))
        self.threshold = max(0.0, float(_setting(config, "SEMANTIC_CACHE_THRESHOLD", 0.90)))
        self.ttl = max(1, int(_setting(config, "SEMANTIC_CACHE_TTL", 3600)))
        self.max_items = max(1, int(_setting(config, "SEMANTIC_CACHE_MAX_ITEMS", 500)))
        self.redis_cb_fail_threshold = max(
            1, int(_setting(config, "SEMANTIC_CACHE_REDIS_CB_FAIL_THRESHOLD", 3))
        )
        self.redis_cb_cooldown_seconds = max(
            1, int(_setting(config, "SEMANTIC_CACHE_REDIS_CB_COOLDOWN_SECONDS", 30))
        )
        self.index_key = "sidar:semantic_cache:index"
        self._embedding_fn = embedding_fn or _default_semantic_embedding_fn
        self._redis: AsyncRedisClient | None = None
        self._redis_init_lock = asyncio.Lock()
        self._redis_failures = 0
        self._redis_circuit_open_until = 0.0

    def _redis_circuit_open(self) -> bool:
        if self._redis_circuit_open_until <= 0.0:
            return False
        if time.monotonic() >= self._redis_circuit_open_until:
            self._redis_circuit_open_until = 0.0
            self._redis_failures = 0
            return False
        return True

    def _mark_redis_failure(self) -> None:
        self._redis_failures += 1
        if self._redis_failures >= self.redis_cb_fail_threshold:
            self._redis_circuit_open_until = time.monotonic() + float(
                self.redis_cb_cooldown_seconds
            )
            logger.warning(
                "Semantic cache circuit breaker açıldı (failures=%d, cooldown=%ss).",
                self._redis_failures,
                self.redis_cb_cooldown_seconds,
            )

    def _mark_redis_success(self) -> None:
        self._redis_failures = 0
        self._redis_circuit_open_until = 0.0

    async def _get_redis(self) -> AsyncRedisClient | None:
        if not self.enabled or Redis is None:
            return None
        if self._redis_circuit_open():
            record_cache_circuit_open_bypass()
            record_cache_skip()
            return None
        if self._redis is not None:
            return self._redis
        async with self._redis_init_lock:
            if self._redis_circuit_open():
                record_cache_circuit_open_bypass()
                record_cache_skip()
                return None
            if self._redis is not None:
                return self._redis

            started = time.perf_counter()
            try:
                redis_client = Redis.from_url(
                    getattr(self.config, "REDIS_URL", "redis://localhost:6379/0"),
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=max(1, int(_setting(self.config, "REDIS_MAX_CONNECTIONS", 50))),
                )
                ping_timeout = max(
                    0.1, float(_setting(self.config, "SEMANTIC_CACHE_REDIS_PING_TIMEOUT", 1.0))
                )
                await asyncio.wait_for(redis_client.ping(), timeout=ping_timeout)
                self._redis = redis_client
                self._mark_redis_success()
                observe_cache_redis_latency((time.perf_counter() - started) * 1000.0)
                return self._redis
            except Exception as exc:
                logger.debug("Semantic cache Redis bağlantısı kurulamadı: %s", exc)
                record_cache_redis_error()
                self._mark_redis_failure()
                self._redis = None
                return None

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        an = math.sqrt(sum(x * x for x in a))
        bn = math.sqrt(sum(y * y for y in b))
        if an == 0 or bn == 0:
            return 0.0
        return dot / (an * bn)

    def _embed_prompt(self, prompt: str) -> list[float]:
        try:
            vectors = self._embedding_fn([prompt], cfg=self.config)
            if vectors:
                return [float(v) for v in vectors[0]]
        except Exception as exc:
            logger.debug("Semantic cache embedding hatası: %s", exc)
        return []

    async def get(self, prompt: str) -> str | None:
        redis = await self._get_redis()
        if redis is None or not prompt:
            return None

        query_vector = self._embed_prompt(prompt)
        if not query_vector:
            return None

        started = time.perf_counter()
        try:
            keys = await redis.lrange(self.index_key, 0, -1)
            if not keys:
                set_cache_items(0)
                observe_cache_redis_latency((time.perf_counter() - started) * 1000.0)
                return None
            set_cache_items(len(keys))

            best_sim = -1.0
            best_response: str | None = None
            for key in keys:
                raw = await redis.hgetall(key)
                if not raw:
                    continue
                try:
                    emb = json.loads(raw.get("embedding", "[]"))
                except Exception:
                    continue
                sim = self._cosine_similarity(query_vector, emb)
                if sim > best_sim:
                    best_sim = sim
                    best_response = raw.get("response")

            if best_response is not None and best_sim >= self.threshold:
                logger.info("Semantic cache HIT (similarity=%.4f)", best_sim)
                record_cache_hit()
                self._mark_redis_success()
                observe_cache_redis_latency((time.perf_counter() - started) * 1000.0)
                return best_response
            logger.debug("Semantic cache MISS (best_similarity=%.4f)", max(best_sim, 0.0))
            record_cache_miss()
            self._mark_redis_success()
            observe_cache_redis_latency((time.perf_counter() - started) * 1000.0)
            return None
        except Exception as exc:
            logger.debug("Semantic cache okuma hatası: %s", exc)
            record_cache_redis_error()
            self._mark_redis_failure()
            self._redis = None
            return None

    async def set(self, prompt: str, response: str) -> None:
        redis = await self._get_redis()
        if redis is None or not prompt or not response:
            return

        vector = self._embed_prompt(prompt)
        if not vector:
            return

        item_key = f"sidar:semantic_cache:item:{hashlib.sha256(prompt.encode('utf-8')).hexdigest()}"
        payload = {
            "prompt": prompt,
            "response": response,
            "embedding": json.dumps(vector),
            "created_at": str(time.time()),
        }
        started = time.perf_counter()
        try:
            keys_before = await redis.lrange(self.index_key, 0, self.max_items - 1)
            had_existing = item_key in keys_before
            async with redis.pipeline(transaction=True) as pipe:
                pipe.hset(item_key, mapping=payload)
                pipe.expire(item_key, self.ttl)
                pipe.lrem(self.index_key, 0, item_key)
                pipe.lpush(self.index_key, item_key)
                pipe.ltrim(self.index_key, 0, self.max_items - 1)
                await pipe.execute()
            current_items = await redis.llen(self.index_key)
            set_cache_items(current_items)
            if not had_existing and len(keys_before) >= self.max_items:
                record_cache_eviction()
            self._mark_redis_success()
            observe_cache_redis_latency((time.perf_counter() - started) * 1000.0)
        except Exception as exc:
            logger.debug("Semantic cache yazma hatası: %s", exc)
            record_cache_redis_error()
            self._mark_redis_failure()
            self._redis = None
