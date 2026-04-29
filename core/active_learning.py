"""Active Learning + LoRA/QLoRA Fine-tuning Döngüsü (v6.0)

Kullanıcı geri bildirimlerini (thumbs-up/down, correction) toplayarak
LoRA/QLoRA fine-tuning için dataset üretir ve isteğe bağlı HuggingFace
PEFT eğitimini tetikler.

Bağımlılıklar (opsiyonel — yoksa graceful degrade):
    peft, transformers, bitsandbytes, datasets, torch

Kullanım:
    store = FeedbackStore()
    await store.initialize()
    await store.record(user_id="u1", prompt="...", response="...", rating=1)
    exporter = DatasetExporter(store)
    path = await exporter.export_jsonl("data/finetune/dataset.jsonl")
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import typing
from pathlib import Path
from typing import Any  # Model/API çıktılarında heterojen tip desteği

logger = logging.getLogger(__name__)

try:
    from sqlalchemy import text as sql_text
    from sqlalchemy.ext.asyncio import create_async_engine

    _SA_AVAILABLE = True
except ImportError:
    _SA_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────────────────
# DDL
# ──────────────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS finetune_feedback (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT    NOT NULL DEFAULT '',
    session_id   TEXT    NOT NULL DEFAULT '',
    prompt       TEXT    NOT NULL,
    response     TEXT    NOT NULL,
    correction   TEXT    NOT NULL DEFAULT '',
    rating       INTEGER NOT NULL DEFAULT 0,
    tags         TEXT    NOT NULL DEFAULT '[]',
    provider     TEXT    NOT NULL DEFAULT '',
    model        TEXT    NOT NULL DEFAULT '',
    created_at   REAL    NOT NULL,
    exported_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_ftfb_user    ON finetune_feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_ftfb_rating  ON finetune_feedback(rating);
CREATE INDEX IF NOT EXISTS idx_ftfb_exported ON finetune_feedback(exported_at);
"""


# ──────────────────────────────────────────────────────────────────────────────
# FeedbackStore
# ──────────────────────────────────────────────────────────────────────────────


class FeedbackStore:
    """
    Kullanıcı geri bildirimlerini SQLite/PostgreSQL'de saklar.

    rating: +1 = olumlu, -1 = olumsuz, 0 = nötr
    correction: kullanıcı tarafından düzeltilmiş ideal yanıt (varsa)
    """

    def __init__(
        self, database_url: str = "sqlite+aiosqlite:///data/sidar.db", config: Any | None = None
    ) -> None:
        self._db_url = database_url
        self._engine: Any | None = None
        cfg = config
        self.enabled: bool = bool(getattr(cfg, "ENABLE_ACTIVE_LEARNING", True))
        self.min_rating_for_train: int = int(getattr(cfg, "AL_MIN_RATING_FOR_TRAIN", 1))

    async def initialize(self) -> None:
        if not self.enabled or not _SA_AVAILABLE:
            return
        self._engine = create_async_engine(self._db_url, echo=False, future=True)
        async with self._engine.begin() as conn:
            for stmt in _DDL.strip().split(";"):
                s = stmt.strip()
                if s:
                    await conn.execute(sql_text(s))
        logger.debug("FeedbackStore başlatıldı.")

    async def record(
        self,
        prompt: str,
        response: str,
        rating: int = 0,
        correction: str = "",
        user_id: str = "",
        session_id: str = "",
        provider: str = "",
        model: str = "",
        tags: list[str] | None = None,
    ) -> bool:
        """Tek bir geri bildirim kaydı ekle. True = başarılı."""
        if not self.enabled or not self._engine:
            return False
        now = time.time()
        tags_str = json.dumps(tags or [], ensure_ascii=False)
        async with self._engine.begin() as conn:
            await conn.execute(
                sql_text(
                    "INSERT INTO finetune_feedback"
                    " (user_id, session_id, prompt, response, correction,"
                    "  rating, tags, provider, model, created_at)"
                    " VALUES (:uid, :sid, :p, :r, :cor, :rat, :tags, :prov, :mdl, :now)"
                ),
                {
                    "uid": user_id,
                    "sid": session_id,
                    "p": prompt,
                    "r": response,
                    "cor": correction,
                    "rat": int(rating),
                    "tags": tags_str,
                    "prov": provider,
                    "mdl": model,
                    "now": now,
                },
            )
        logger.debug("FeedbackStore.record: rating=%d uid=%s", rating, user_id)
        return True

    async def flag_weak_response(
        self,
        prompt: str,
        response: str,
        score: int,
        reasoning: str,
        *,
        user_id: str = "",
        session_id: str = "judge:auto",
        provider: str = "",
        model: str = "",
        tags: list[str] | None = None,
    ) -> bool:
        """Düşük puanlı yanıtı Active Learning havuzuna yazar."""
        if not self.enabled:
            return False
        if self._engine is None:
            await self.initialize()
        if self._engine is None:
            return False

        merged_tags = list(tags or [])
        merged_tags.extend(
            [
                "judge:auto",
                "weak_response",
                f"score:{max(1, min(10, int(score or 0)))}",
            ]
        )
        if reasoning:
            merged_tags.append("judge_reasoning")

        return await self.record(
            user_id=user_id,
            session_id=session_id,
            prompt=prompt,
            response=response,
            rating=-1,
            correction=(reasoning or "").strip(),
            provider=provider,
            model=model,
            tags=merged_tags,
        )

    async def get_pending_export(
        self, min_rating: int | None = None, limit: int = 10000
    ) -> list[dict[str, Any]]:
        """Henüz export edilmemiş kayıtları döner."""
        if not self.enabled or not self._engine:
            return []
        threshold = min_rating if min_rating is not None else self.min_rating_for_train
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                sql_text(
                    "SELECT id, prompt, response, correction, rating, user_id, provider, model"
                    " FROM finetune_feedback"
                    " WHERE rating >= :rat AND exported_at IS NULL"
                    " ORDER BY created_at DESC LIMIT :lim"
                ),
                {"rat": threshold, "lim": limit},
            )
            return [dict(r._mapping) for r in rows.fetchall()]

    async def get_pending_signals(self, limit: int = 10000) -> list[dict[str, Any]]:
        """Sürekli öğrenme için henüz export edilmemiş tüm geri bildirim sinyallerini döner."""
        if not self.enabled or not self._engine:
            return []
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                sql_text(
                    "SELECT id, prompt, response, correction, rating, user_id, session_id,"
                    " provider, model, tags, created_at"
                    " FROM finetune_feedback"
                    " WHERE exported_at IS NULL"
                    " ORDER BY created_at DESC LIMIT :lim"
                ),
                {"lim": limit},
            )
            items = [dict(r._mapping) for r in rows.fetchall()]
        for item in items:
            raw_tags = item.get("tags", "[]")
            try:
                item["tags"] = (
                    json.loads(raw_tags) if isinstance(raw_tags, str) else list(raw_tags or [])
                )
            except Exception:
                item["tags"] = []
        return items

    async def mark_exported(self, ids: list[int]) -> None:
        """Verilen ID'leri export edildi olarak işaretle."""
        if not ids or not self._engine:
            return
        now = time.time()
        async with self._engine.begin() as conn:
            for chunk in _chunked(ids, 500):
                params = {"now": now}
                placeholders = []
                for idx, feedback_id in enumerate(chunk):
                    param_name = f"id_{idx}"
                    placeholders.append(f":{param_name}")
                    params[param_name] = int(feedback_id)
                await conn.execute(
                    sql_text(
                        "UPDATE finetune_feedback"
                        f" SET exported_at = :now WHERE id IN ({', '.join(placeholders)})"  # nosec B608
                    ),
                    params,
                )

    async def stats(self) -> dict[str, int]:
        """Feedback istatistiklerini döner."""
        if not self.enabled or not self._engine:
            return {}
        async with self._engine.connect() as conn:
            total = (
                await conn.execute(sql_text("SELECT COUNT(*) FROM finetune_feedback"))
            ).scalar() or 0
            pos = (
                await conn.execute(
                    sql_text("SELECT COUNT(*) FROM finetune_feedback WHERE rating > 0")
                )
            ).scalar() or 0
            neg = (
                await conn.execute(
                    sql_text("SELECT COUNT(*) FROM finetune_feedback WHERE rating < 0")
                )
            ).scalar() or 0
            pending = (
                await conn.execute(
                    sql_text("SELECT COUNT(*) FROM finetune_feedback WHERE exported_at IS NULL")
                )
            ).scalar() or 0
        return {"total": total, "positive": pos, "negative": neg, "pending_export": pending}

    async def close(self) -> None:
        if self._engine:
            await self._engine.dispose()
            self._engine = None


# ──────────────────────────────────────────────────────────────────────────────
# DatasetExporter
# ──────────────────────────────────────────────────────────────────────────────


class DatasetExporter:
    """
    FeedbackStore'daki kayıtları fine-tuning formatına dönüştürür.

    Desteklenen formatlar:
    - jsonl: Her satır {"prompt": "...", "completion": "..."} (OpenAI / Axolotl uyumlu)
    - alpaca: {"instruction": "...", "input": "", "output": "..."}
    - sharegpt: {"conversations": [{"from": "human", ...}, {"from": "gpt", ...}]}
    """

    SUPPORTED_FORMATS = ("jsonl", "alpaca", "sharegpt")

    def __init__(self, store: FeedbackStore) -> None:
        self.store = store

    async def export(
        self,
        output_path: str,
        fmt: str = "alpaca",
        min_rating: int = 1,
        mark_done: bool = True,
    ) -> dict[str, Any]:
        """
        Kayıtları belirtilen formata dönüştürüp dosyaya yazar.
        Döner: {"path": str, "count": int, "format": str}
        """
        fmt = fmt.lower()
        if fmt not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Desteklenmeyen format: {fmt}. Seçenekler: {self.SUPPORTED_FORMATS}")

        rows = await self.store.get_pending_export(min_rating=min_rating)
        if not rows:
            logger.info("DatasetExporter: Export için kayıt bulunamadı.")
            return {"path": output_path, "count": 0, "format": fmt}

        out = Path(output_path)

        # Veriyi önce belleğe dönüştür, ardından asyncio.to_thread ile disk yazımı yap.
        # Bulgu D: async fonksiyon içinde senkron open/write event loop'u bloklar.
        ids = []
        lines: list[str] = []
        for row in rows:
            completion = row["correction"] if row["correction"] else row["response"]
            prompt = row["prompt"]

            if fmt == "jsonl":
                obj = {"prompt": prompt, "completion": completion}
            elif fmt == "alpaca":
                obj = {"instruction": prompt, "input": "", "output": completion}
            else:  # sharegpt
                obj = {
                    "conversations": [
                        {"from": "human", "value": prompt},
                        {"from": "gpt", "value": completion},
                    ]
                }
            lines.append(json.dumps(obj, ensure_ascii=False) + "\n")
            ids.append(row["id"])

        content = "".join(lines)

        def _write_file() -> None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content, encoding="utf-8")

        await asyncio.to_thread(_write_file)

        if mark_done and ids:
            await self.store.mark_exported(ids)

        logger.info("DatasetExporter: %d kayıt → %s (%s)", len(ids), output_path, fmt)
        return {"path": str(out.resolve()), "count": len(ids), "format": fmt}


class ContinuousLearningPipeline:
    """
    Judge ve Active Learning sinyallerini SFT + preference dataset bundle'ına dönüştürür.

    Amaç:
    - İnsan düzeltmelerini LoRA/QLoRA için SFT dataseti'ne aktarmak
    - Negatif/iyileştirilmiş örneklerden DPO/RLHF tercih çifti üretmek
    - İsteğe bağlı olarak LoRA eğitimini arka planda tetiklemek
    """

    def __init__(
        self,
        store: FeedbackStore,
        *,
        trainer: LoRATrainer | None = None,
        config: Any | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.trainer = trainer or LoRATrainer(config=config)
        self.enabled = bool(getattr(config, "ENABLE_CONTINUOUS_LEARNING", False))
        self.output_dir = str(
            getattr(config, "CONTINUOUS_LEARNING_OUTPUT_DIR", "data/continuous_learning")
            or "data/continuous_learning"
        )
        self.min_sft_examples = int(
            getattr(config, "CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES", 20) or 20
        )
        self.min_preference_examples = int(
            getattr(config, "CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES", 10) or 10
        )
        self.max_pending_signals = int(
            getattr(config, "CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS", 5000) or 5000
        )
        self.cooldown_seconds = int(
            getattr(config, "CONTINUOUS_LEARNING_COOLDOWN_SECONDS", 3600) or 3600
        )
        self.sft_format = str(
            getattr(config, "CONTINUOUS_LEARNING_SFT_FORMAT", "alpaca") or "alpaca"
        ).lower()
        self._last_run_at = 0.0
        self._run_lock = asyncio.Lock()

    @staticmethod
    def _normalize_tags(tags: object) -> list[str]:
        if isinstance(tags, list):
            return [str(tag) for tag in tags if str(tag).strip()]
        if isinstance(tags, str):
            try:
                parsed = json.loads(tags)
            except Exception:
                return []
            if isinstance(parsed, list):
                return [str(tag) for tag in parsed if str(tag).strip()]
        return []

    @staticmethod
    def _is_judge_reasoning_signal(row: dict[str, Any]) -> bool:
        tags = ContinuousLearningPipeline._normalize_tags(row.get("tags"))
        return "judge_reasoning" in tags and "weak_response" in tags

    def _build_sft_examples(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        examples: list[dict[str, Any]] = []
        min_rating = int(getattr(self.store, "min_rating_for_train", 1))
        for row in rows:
            prompt = str(row.get("prompt", "") or "").strip()
            response = str(row.get("response", "") or "").strip()
            correction = str(row.get("correction", "") or "").strip()
            rating = int(row.get("rating", 0) or 0)
            if not prompt:
                continue
            if rating < min_rating:
                continue
            if self._is_judge_reasoning_signal(row):
                continue
            output = correction or response
            if not output:
                continue
            examples.append(
                {
                    "instruction": prompt,
                    "input": "",
                    "output": output,
                    "source": "correction" if correction else "response",
                    "feedback_id": row.get("id"),
                }
            )
        return examples

    def _build_preference_examples(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        examples: list[dict[str, Any]] = []
        for row in rows:
            prompt = str(row.get("prompt", "") or "").strip()
            response = str(row.get("response", "") or "").strip()
            correction = str(row.get("correction", "") or "").strip()
            rating = int(row.get("rating", 0) or 0)
            if not prompt or not response or not correction:
                continue
            if correction == response:
                continue
            if self._is_judge_reasoning_signal(row):
                continue
            if rating >= 1 or rating < 0:
                examples.append(
                    {
                        "prompt": prompt,
                        "chosen": correction,
                        "rejected": response,
                        "feedback_id": row.get("id"),
                    }
                )
        return examples

    @staticmethod
    def _serialize_sft_examples(rows: list[dict[str, Any]], fmt: str) -> list[dict[str, Any]]:
        fmt = str(fmt or "alpaca").lower()
        if fmt not in DatasetExporter.SUPPORTED_FORMATS:
            raise ValueError(f"Desteklenmeyen continuous learning SFT formatı: {fmt}")

        serialized: list[dict[str, Any]] = []
        for row in rows:
            prompt = str(row.get("instruction", "") or "").strip()
            output = str(row.get("output", "") or "").strip()
            if not prompt or not output:
                continue

            if fmt == "jsonl":
                serialized.append({"prompt": prompt, "completion": output})
            elif fmt == "alpaca":
                serialized.append(
                    {
                        "instruction": prompt,
                        "input": str(row.get("input", "") or ""),
                        "output": output,
                    }
                )
            else:
                serialized.append(
                    {
                        "conversations": [
                            {"from": "human", "value": prompt},
                            {"from": "gpt", "value": output},
                        ]
                    }
                )
        return serialized

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    async def build_dataset_bundle(self, output_dir: str | None = None) -> dict[str, Any]:
        """Bekleyen sinyallerden SFT/DPO bundle üretir; eğitimi başlatmaz."""
        rows = await self.store.get_pending_signals(limit=self.max_pending_signals)
        sft_examples = self._build_sft_examples(rows)
        serialized_sft_examples = self._serialize_sft_examples(sft_examples, self.sft_format)
        preference_examples = self._build_preference_examples(rows)
        triage_only = max(
            0,
            len(rows)
            - len(
                {
                    r.get("feedback_id")
                    for r in sft_examples + preference_examples
                    if r.get("feedback_id")
                }
            ),
        )

        root = Path(output_dir or self.output_dir)
        timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        bundle_dir = root / f"bundle-{timestamp}"
        sft_path = bundle_dir / f"sft.{self.sft_format}.jsonl"
        preference_path = bundle_dir / "preference.dpo.jsonl"
        manifest_path = bundle_dir / "manifest.json"

        await asyncio.to_thread(self._write_jsonl, sft_path, serialized_sft_examples)
        await asyncio.to_thread(self._write_jsonl, preference_path, preference_examples)

        manifest = {
            "created_at": time.time(),
            "bundle_dir": str(bundle_dir),
            "sft_path": str(sft_path),
            "preference_path": str(preference_path),
            "counts": {
                "signals": len(rows),
                "sft_examples": len(sft_examples),
                "preference_examples": len(preference_examples),
                "triage_only": triage_only,
            },
            "training_ready": {
                "sft": len(sft_examples) >= self.min_sft_examples,
                "preference": len(preference_examples) >= self.min_preference_examples,
            },
            "sft_format": self.sft_format,
        }
        await asyncio.to_thread(
            manifest_path.write_text,
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest

    async def run_cycle(self, *, reason: str = "manual") -> dict[str, Any]:
        """Bundle üretir ve yeterli veri varsa LoRA/QLoRA eğitimini tetikler."""
        if not self.enabled:
            return {"success": False, "scheduled": False, "reason": "continuous_learning_disabled"}

        async with self._run_lock:
            now = time.time()
            if self.cooldown_seconds > 0 and (now - self._last_run_at) < self.cooldown_seconds:
                return {
                    "success": False,
                    "scheduled": False,
                    "reason": "cooldown_active",
                    "retry_after": max(0, int(self.cooldown_seconds - (now - self._last_run_at))),
                }

            manifest = await self.build_dataset_bundle()
            counts = manifest.get("counts", {})
            if (
                counts.get("sft_examples", 0) < self.min_sft_examples
                and counts.get("preference_examples", 0) < self.min_preference_examples
            ):
                self._last_run_at = now
                return {
                    "success": False,
                    "scheduled": False,
                    "reason": "insufficient_signals",
                    "manifest": manifest,
                    "trigger_reason": reason,
                }

            training_result = {
                "success": False,
                "reason": "trainer_disabled_or_insufficient_sft",
            }
            if counts.get("sft_examples", 0) >= self.min_sft_examples and bool(
                getattr(self.trainer, "enabled", False)
            ):
                training_result = await asyncio.to_thread(self.trainer.train, manifest["sft_path"])

            self._last_run_at = now
            return {
                "success": True,
                "scheduled": True,
                "manifest": manifest,
                "training_result": training_result,
                "trigger_reason": reason,
            }

    def schedule_cycle(self, *, reason: str = "background") -> bool:
        """Event loop varsa sürekli öğrenme döngüsünü fire-and-forget biçimde planlar."""
        if not self.enabled:
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False

        async def _runner() -> None:
            try:
                await self.run_cycle(reason=reason)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("ContinuousLearningPipeline schedule hatası: %s", exc)

        loop.create_task(_runner(), name="sidar_continuous_learning")
        return True


# ──────────────────────────────────────────────────────────────────────────────
# LoRA/QLoRA Trainer (PEFT — opsiyonel)
# ──────────────────────────────────────────────────────────────────────────────


class LoRATrainer:
    """
    HuggingFace PEFT/LoRA ile yerel model fine-tuning tetikleyicisi.

    peft, transformers, bitsandbytes, datasets kütüphaneleri kurulu değilse
    sessizce devre dışı kalır.

    Tasarım notu: Fine-tuning CPU/GPU yoğun bir işlemdir; `train()` methodu
    asyncio.to_thread() ile çağrılmalıdır.
    """

    def __init__(self, config: Any | None = None) -> None:
        self.enabled: bool = bool(getattr(config, "ENABLE_LORA_TRAINING", False))
        self.base_model: str = str(getattr(config, "LORA_BASE_MODEL", "") or "")
        self.model_revision: str = str(getattr(config, "LORA_MODEL_REVISION", "") or "").strip()
        self.lora_rank: int = int(getattr(config, "LORA_RANK", 8) or 8)
        self.lora_alpha: int = int(getattr(config, "LORA_ALPHA", 16) or 16)
        self.lora_dropout: float = float(getattr(config, "LORA_DROPOUT", 0.05) or 0.05)
        self.output_dir: str = str(
            getattr(config, "LORA_OUTPUT_DIR", "data/lora_adapters") or "data/lora_adapters"
        )
        self.epochs: int = int(getattr(config, "LORA_EPOCHS", 3) or 3)
        self.batch_size: int = int(getattr(config, "LORA_BATCH_SIZE", 4) or 4)
        self.use_4bit: bool = bool(getattr(config, "LORA_USE_4BIT", True))  # QLoRA flag
        self._peft_available: bool | None = None

    def _check_peft(self) -> bool:
        if self._peft_available is None:
            try:
                import datasets  # noqa: F401
                import peft  # noqa: F401
                import transformers  # noqa: F401

                self._peft_available = True
            except ImportError:
                logger.warning(
                    "LoRATrainer: peft/transformers/datasets kurulu değil. Fine-tuning devre dışı."
                )
                self._peft_available = False
        return self._peft_available

    def train(self, dataset_path: str) -> dict[str, Any]:
        """
        Senkron fine-tuning başlatır.
        asyncio.to_thread(trainer.train, path) ile çağrılması önerilir.
        """
        if not self.enabled:
            return {"success": False, "reason": "LORA_TRAINING devre dışı"}
        if not self._check_peft():
            return {"success": False, "reason": "peft/transformers kurulu değil"}
        if not self.base_model:
            return {"success": False, "reason": "LORA_BASE_MODEL ayarlanmamış"}
        if not self.model_revision:
            return {
                "success": False,
                "reason": "LORA_MODEL_REVISION ayarlanmamış (güvenli sabit commit hash gerekli)",
            }

        try:
            return self._run_training(dataset_path)
        except Exception as exc:
            logger.error("LoRATrainer.train hatası: %s", exc, exc_info=True)
            return {"success": False, "reason": str(exc)}

    def _run_training(self, dataset_path: str) -> dict[str, Any]:
        """PEFT LoRA/QLoRA eğitim döngüsü."""
        from datasets import load_dataset
        from peft import LoraConfig, TaskType, get_peft_model
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            DataCollatorForSeq2Seq,
            Trainer,
            TrainingArguments,
        )

        logger.info("LoRATrainer: Eğitim başlatılıyor — model=%s", self.base_model)

        # Tokenizer
        tokenizer = typing.cast(Any, AutoTokenizer).from_pretrained(
            self.base_model,
            trust_remote_code=False,
            revision=self.model_revision,
        )
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        # Model yükleme (4-bit QLoRA veya normal)
        model_kwargs: dict[str, Any] = {
            "trust_remote_code": False,
            "revision": self.model_revision,
        }
        if self.use_4bit:
            try:
                import torch
                from transformers import BitsAndBytesConfig

                bnb_config = typing.cast(Any, BitsAndBytesConfig)(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.float16,
                )
                model_kwargs["quantization_config"] = bnb_config
                logger.info("LoRATrainer: QLoRA (4-bit) modu aktif.")
            except ImportError:
                logger.warning("LoRATrainer: bitsandbytes kurulu değil, 4-bit modu devre dışı.")

        model = AutoModelForCausalLM.from_pretrained(
            self.base_model, **model_kwargs
        )  # nosec B615

        # LoRA adaptörü
        lora_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=self.lora_rank,
            lora_alpha=self.lora_alpha,
            lora_dropout=self.lora_dropout,
            bias="none",
            target_modules=["q_proj", "v_proj"],
        )
        model = typing.cast(Any, get_peft_model(model, lora_config))
        model.print_trainable_parameters()

        # Dataset
        dataset = load_dataset(
            "json", data_files=dataset_path, split="train"
        )  # nosec B615

        def _tokenize(example: dict[str, Any]) -> dict[str, Any]:
            prompt = str(example.get("instruction", example.get("prompt", "")) or "")
            output = str(example.get("output", example.get("completion", "")) or "")
            if not prompt and not output:
                conversations = example.get("conversations")
                if isinstance(conversations, list):
                    human_turns = [
                        turn
                        for turn in conversations
                        if isinstance(turn, dict) and turn.get("from") == "human"
                    ]
                    assistant_turns = [
                        turn
                        for turn in conversations
                        if isinstance(turn, dict) and turn.get("from") == "gpt"
                    ]
                    if human_turns:
                        prompt = str(human_turns[0].get("value", "") or "")
                    if assistant_turns:
                        output = str(assistant_turns[0].get("value", "") or "")
            full = f"{prompt}\n\n{output}".strip()
            enc: dict[str, Any] = dict(
                tokenizer(full, truncation=True, max_length=512, padding="max_length")
            )
            enc["labels"] = enc["input_ids"].copy()
            return enc

        tokenized = dataset.map(_tokenize, remove_columns=dataset.column_names)

        # Training
        out_dir = Path(self.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        args = TrainingArguments(
            output_dir=str(out_dir),
            num_train_epochs=self.epochs,
            per_device_train_batch_size=self.batch_size,
            save_strategy="epoch",
            logging_steps=10,
            report_to="none",
            remove_unused_columns=False,
        )
        trainer = Trainer(
            model=model,
            args=args,
            train_dataset=tokenized,
            data_collator=DataCollatorForSeq2Seq(tokenizer, model=model, padding=True),
        )
        train_result = trainer.train()
        model.save_pretrained(str(out_dir))
        tokenizer.save_pretrained(str(out_dir))

        logger.info("LoRATrainer: Eğitim tamamlandı → %s", out_dir)
        return {
            "success": True,
            "output_dir": str(out_dir.resolve()),
            "train_loss": train_result.training_loss,
            "steps": train_result.global_step,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Yardımcı
# ──────────────────────────────────────────────────────────────────────────────


def _chunked(lst: list[Any], size: int) -> typing.Iterator[list[Any]]:
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────

_feedback_store: FeedbackStore | None = None
_store_lock = threading.Lock()
_pipeline_lock = threading.Lock()
_continuous_learning_pipeline: ContinuousLearningPipeline | None = None


def get_feedback_store(config: Any | None = None) -> FeedbackStore:
    global _feedback_store
    with _store_lock:
        if _feedback_store is None:
            from config import Config

            cfg = config or Config()
            db_url = str(getattr(cfg, "DATABASE_URL", "sqlite+aiosqlite:///data/sidar.db") or "")
            _feedback_store = FeedbackStore(database_url=db_url, config=cfg)
    return _feedback_store


def get_continuous_learning_pipeline(config: Any | None = None) -> ContinuousLearningPipeline:
    """Süreç-geneli sürekli öğrenme pipeline singleton'ını döndürür."""
    global _continuous_learning_pipeline
    if _continuous_learning_pipeline is not None:
        return _continuous_learning_pipeline

    with _pipeline_lock:
        if _continuous_learning_pipeline is None:
            from config import Config

            cfg = config or Config()
            store = get_feedback_store(cfg)
            _continuous_learning_pipeline = ContinuousLearningPipeline(
                store,
                trainer=LoRATrainer(config=cfg),
                config=cfg,
            )
    return _continuous_learning_pipeline


def schedule_continuous_learning_cycle(
    *, config: Any | None = None, reason: str = "background"
) -> bool:
    """Uygunsa sürekli öğrenme döngüsünü arka planda planlar."""
    pipeline = get_continuous_learning_pipeline(config)
    return pipeline.schedule_cycle(reason=reason)


async def flag_weak_response(
    prompt: str,
    response: str,
    score: int,
    reasoning: str,
    *,
    config: Any | None = None,
    user_id: str = "",
    session_id: str = "judge:auto",
    provider: str = "",
    model: str = "",
    tags: list[str] | None = None,
) -> bool:
    """Singleton FeedbackStore üzerinden düşük kaliteli yanıtı kaydeder."""
    store = get_feedback_store(config)
    return await store.flag_weak_response(
        prompt=prompt,
        response=response,
        score=score,
        reasoning=reasoning,
        user_id=user_id,
        session_id=session_id,
        provider=provider,
        model=model,
        tags=tags,
    )
