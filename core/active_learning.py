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
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text as sql_text
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

    def __init__(self, database_url: str = "sqlite+aiosqlite:///data/sidar.db", config=None) -> None:
        self._db_url = database_url
        self._engine: Optional[Any] = None
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
        tags: Optional[List[str]] = None,
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
                    "uid": user_id, "sid": session_id,
                    "p": prompt, "r": response, "cor": correction,
                    "rat": int(rating), "tags": tags_str,
                    "prov": provider, "mdl": model, "now": now,
                },
            )
        logger.debug("FeedbackStore.record: rating=%d uid=%s", rating, user_id)
        return True

    async def get_pending_export(self, min_rating: Optional[int] = None, limit: int = 10000) -> List[Dict]:
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

    async def mark_exported(self, ids: List[int]) -> None:
        """Verilen ID'leri export edildi olarak işaretle."""
        if not ids or not self._engine:
            return
        now = time.time()
        async with self._engine.begin() as conn:
            for chunk in _chunked(ids, 500):
                placeholders = ",".join(str(i) for i in chunk)
                await conn.execute(
                    sql_text(
                        f"UPDATE finetune_feedback SET exported_at = :now WHERE id IN ({placeholders})"
                    ),
                    {"now": now},
                )

    async def stats(self) -> Dict[str, int]:
        """Feedback istatistiklerini döner."""
        if not self.enabled or not self._engine:
            return {}
        async with self._engine.connect() as conn:
            total = (await conn.execute(sql_text("SELECT COUNT(*) FROM finetune_feedback"))).scalar() or 0
            pos = (await conn.execute(sql_text("SELECT COUNT(*) FROM finetune_feedback WHERE rating > 0"))).scalar() or 0
            neg = (await conn.execute(sql_text("SELECT COUNT(*) FROM finetune_feedback WHERE rating < 0"))).scalar() or 0
            pending = (await conn.execute(sql_text("SELECT COUNT(*) FROM finetune_feedback WHERE exported_at IS NULL"))).scalar() or 0
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
    ) -> Dict[str, Any]:
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
        lines: List[str] = []
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

    def __init__(self, config=None) -> None:
        self.enabled: bool = bool(getattr(config, "ENABLE_LORA_TRAINING", False))
        self.base_model: str = str(getattr(config, "LORA_BASE_MODEL", "") or "")
        self.lora_rank: int = int(getattr(config, "LORA_RANK", 8) or 8)
        self.lora_alpha: int = int(getattr(config, "LORA_ALPHA", 16) or 16)
        self.lora_dropout: float = float(getattr(config, "LORA_DROPOUT", 0.05) or 0.05)
        self.output_dir: str = str(getattr(config, "LORA_OUTPUT_DIR", "data/lora_adapters") or "data/lora_adapters")
        self.epochs: int = int(getattr(config, "LORA_EPOCHS", 3) or 3)
        self.batch_size: int = int(getattr(config, "LORA_BATCH_SIZE", 4) or 4)
        self.use_4bit: bool = bool(getattr(config, "LORA_USE_4BIT", True))  # QLoRA flag
        self._peft_available: Optional[bool] = None

    def _check_peft(self) -> bool:
        if self._peft_available is None:
            try:
                import peft  # noqa: F401
                import transformers  # noqa: F401
                import datasets  # noqa: F401
                self._peft_available = True
            except ImportError:
                logger.warning("LoRATrainer: peft/transformers/datasets kurulu değil. Fine-tuning devre dışı.")
                self._peft_available = False
        return self._peft_available

    def train(self, dataset_path: str) -> Dict[str, Any]:
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

        try:
            return self._run_training(dataset_path)
        except Exception as exc:
            logger.error("LoRATrainer.train hatası: %s", exc, exc_info=True)
            return {"success": False, "reason": str(exc)}

    def _run_training(self, dataset_path: str) -> Dict[str, Any]:
        """PEFT LoRA/QLoRA eğitim döngüsü."""
        from peft import LoraConfig, get_peft_model, TaskType  # type: ignore
        from transformers import (  # type: ignore
            AutoModelForCausalLM, AutoTokenizer,
            TrainingArguments, Trainer, DataCollatorForSeq2Seq,
        )
        from datasets import load_dataset  # type: ignore

        logger.info("LoRATrainer: Eğitim başlatılıyor — model=%s", self.base_model)

        # Tokenizer
        tokenizer = AutoTokenizer.from_pretrained(self.base_model, trust_remote_code=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        # Model yükleme (4-bit QLoRA veya normal)
        model_kwargs: Dict[str, Any] = {"trust_remote_code": True}
        if self.use_4bit:
            try:
                from transformers import BitsAndBytesConfig  # type: ignore
                import torch
                bnb_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.float16,
                )
                model_kwargs["quantization_config"] = bnb_config
                logger.info("LoRATrainer: QLoRA (4-bit) modu aktif.")
            except ImportError:
                logger.warning("LoRATrainer: bitsandbytes kurulu değil, 4-bit modu devre dışı.")

        model = AutoModelForCausalLM.from_pretrained(self.base_model, **model_kwargs)

        # LoRA adaptörü
        lora_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=self.lora_rank,
            lora_alpha=self.lora_alpha,
            lora_dropout=self.lora_dropout,
            bias="none",
            target_modules=["q_proj", "v_proj"],
        )
        model = get_peft_model(model, lora_config)
        model.print_trainable_parameters()

        # Dataset
        dataset = load_dataset("json", data_files=dataset_path, split="train")

        def _tokenize(example):
            prompt = example.get("instruction", example.get("prompt", ""))
            output = example.get("output", example.get("completion", ""))
            full = f"{prompt}\n\n{output}"
            enc = tokenizer(full, truncation=True, max_length=512, padding="max_length")
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

def _chunked(lst: List, size: int):
    for i in range(0, len(lst), size):
        yield lst[i: i + size]


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────

_feedback_store: Optional[FeedbackStore] = None
_store_lock = threading.Lock()


def get_feedback_store(config=None) -> FeedbackStore:
    global _feedback_store
    with _store_lock:
        if _feedback_store is None:
            from config import Config
            cfg = config or Config()
            db_url = str(getattr(cfg, "DATABASE_URL", "sqlite+aiosqlite:///data/sidar.db") or "")
            _feedback_store = FeedbackStore(database_url=db_url, config=cfg)
    return _feedback_store