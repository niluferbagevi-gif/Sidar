"""
Sidar Project — LLM-as-a-Judge Kalite Değerlendirme Modülü
RAG sonuçları ve ajan yanıtlarını asenkron olarak LLM tabanlı değerlendirir.

Özellikler:
  - RAG sorgu-belge alaka değerlendirmesi (relevance 0.0–1.0)
  - Yanıt tutarlılığı / halüsinasyon riski tahmini (0.0 = düşük risk, 1.0 = yüksek)
  - Prometheus metrik çıktısı (sidar_rag_relevance_score, sidar_hallucination_risk_score)
  - Arka planda asenkron değerlendirme — ana akışı bloklamaz
  - Örnekleme oranı: JUDGE_SAMPLE_RATE (0.0–1.0)

Yapılandırma (.env):
  JUDGE_ENABLED=true
  JUDGE_MODEL=gemma2:9b          # değerlendirme modeli (JUDGE_PROVIDER'dan bağımsız)
  JUDGE_PROVIDER=ollama          # değerlendirme sağlayıcısı
  JUDGE_SAMPLE_RATE=0.2          # her 5 yanıttan 1'ini değerlendir
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

# ─── Sabitler ────────────────────────────────────────────────────────────────

_RELEVANCE_SYSTEM = (
    "Sen bir RAG kalite değerlendirme asistanısın. "
    "Sana bir kullanıcı sorgusu ve bir belge parçası verilecek. "
    "Belgenin sorguyla ne kadar alakalı olduğunu 0.0 ile 1.0 arasında bir ondalıklı sayı olarak döndür. "
    "Sadece sayıyı döndür, başka hiçbir şey yazma. Örnek: 0.85"
)

_HALLUCINATION_SYSTEM = (
    "Sen bir yanıt doğrulama asistanısın. "
    "Sana bir kullanıcı sorusu, bağlam belgeleri ve bir yapay zeka yanıtı verilecek. "
    "Yanıttaki iddialar bağlam belgelerinde desteklenmiyor veya çelişiyorsa risk yüksek. "
    "Halüsinasyon riskini 0.0 (düşük risk, bağlamla uyumlu) ile 1.0 (yüksek risk, bağlamdan sapma) "
    "arasında bir ondalıklı sayı olarak döndür. Sadece sayıyı döndür. Örnek: 0.15"
)


# ─── Prometheus sayaçları (opsiyonel) ─────────────────────────────────────────

def _inc_prometheus(metric_name: str, value: float) -> None:
    """Prometheus kütüphanesi kuruluysa metrikleri günceller."""
    try:
        from prometheus_client import Gauge
        gauge = Gauge(metric_name, metric_name.replace("_", " "))
        gauge.set(value)
    except Exception:
        pass


# ─── JudgeResult ─────────────────────────────────────────────────────────────

@dataclass
class JudgeResult:
    """Bir değerlendirme döngüsünün sonucu."""
    relevance_score: float       # 0.0 – 1.0 (1.0 = tam alakalı)
    hallucination_risk: float    # 0.0 – 1.0 (0.0 = güvenilir)
    evaluated_at: float
    model: str
    provider: str
    error: str = ""

    @property
    def passed(self) -> bool:
        """Kalite eşiğini geçti mi? (relevance ≥ 0.5 ve risk ≤ 0.5)"""
        return self.relevance_score >= 0.5 and self.hallucination_risk <= 0.5


# ─── LLMJudge ────────────────────────────────────────────────────────────────

class LLMJudge:
    """
    LLM tabanlı kalite değerlendirici.

    Async arka plan görevi olarak çalışır; ana ReAct döngüsünü bloklamaz.
    Değerlendirme sonuçları LLMMetricsCollector'a ve Prometheus'a yazılır.
    """

    def __init__(self) -> None:
        self.enabled = os.getenv("JUDGE_ENABLED", "false").lower() in ("1", "true", "yes")
        self.model = os.getenv("JUDGE_MODEL", "").strip() or None
        self.provider = os.getenv("JUDGE_PROVIDER", "ollama").strip().lower()
        self.sample_rate = max(0.0, min(1.0, float(os.getenv("JUDGE_SAMPLE_RATE", "0.2") or 0.2)))

    def _should_evaluate(self) -> bool:
        """Örnekleme oranına göre değerlendirme yapılıp yapılmayacağını belirle."""
        return self.enabled and random.random() < self.sample_rate

    async def _call_llm(self, system: str, user_message: str) -> Optional[float]:
        """Judge modelini çağır, 0.0–1.0 arası float döndür."""
        try:
            from config import Config
            from core.llm_client import LLMClient
            config = Config()
            model = self.model or getattr(config, "TEXT_MODEL", None) or getattr(config, "CODING_MODEL", None)
            client = LLMClient(provider=self.provider, config=config)
            response = await client.chat(
                messages=[{"role": "user", "content": user_message}],
                model=model,
                system_prompt=system,
                temperature=0.0,
                stream=False,
                json_mode=False,
            )
            if not isinstance(response, str):
                return None
            text = response.strip()
            # Yanıtta sadece sayı bekliyoruz; güvenli parse
            import re
            match = re.search(r"\b(0?\.\d+|[01](?:\.\d+)?)\b", text)
            if match:
                val = float(match.group(1))
                return max(0.0, min(1.0, val))
            return None
        except Exception as exc:
            logger.debug("Judge LLM çağrısı başarısız: %s", exc)
            return None

    async def evaluate_rag(
        self,
        query: str,
        documents: List[str],
        answer: Optional[str] = None,
    ) -> Optional[JudgeResult]:
        """
        RAG sorgusunu ve belgelerini değerlendir.

        Args:
            query:     Kullanıcı sorgusu
            documents: RAG'dan dönen belge parçaları
            answer:    Opsiyonel — oluşturulan yanıt (halüsinasyon tespiti için)

        Returns:
            JudgeResult veya None (örnekleme dışı / hata durumu)
        """
        if not self._should_evaluate():
            return None
        if not query or not documents:
            return None

        context_text = "\n---\n".join(documents[:5])  # İlk 5 belge
        started_at = time.time()
        model_used = self.model or "default"

        # Alaka puanı
        relevance_prompt = (
            f"Sorgu: {query}\n\n"
            f"Belge:\n{context_text[:2000]}"
        )
        relevance = await self._call_llm(_RELEVANCE_SYSTEM, relevance_prompt)
        if relevance is None:
            relevance = 0.5  # bilinmiyor → nötr

        # Halüsinasyon riski (yanıt mevcutsa)
        hallucination = 0.0
        if answer:
            hall_prompt = (
                f"Soru: {query}\n\n"
                f"Bağlam:\n{context_text[:1500]}\n\n"
                f"Yanıt:\n{answer[:500]}"
            )
            hall_val = await self._call_llm(_HALLUCINATION_SYSTEM, hall_prompt)
            if hall_val is not None:
                hallucination = hall_val

        result = JudgeResult(
            relevance_score=round(relevance, 4),
            hallucination_risk=round(hallucination, 4),
            evaluated_at=started_at,
            model=model_used,
            provider=self.provider,
        )

        # Prometheus güncelle
        _inc_prometheus("sidar_rag_relevance_score", result.relevance_score)
        _inc_prometheus("sidar_hallucination_risk_score", result.hallucination_risk)

        # LLMMetrics'e kaydet
        _record_judge_metrics(result)

        logger.debug(
            "Judge değerlendirmesi — relevance=%.3f, hallucination_risk=%.3f",
            result.relevance_score, result.hallucination_risk,
        )
        return result

    def schedule_background_evaluation(
        self,
        query: str,
        documents: List[str],
        answer: Optional[str] = None,
    ) -> None:
        """
        Değerlendirmeyi asyncio arka plan görevi olarak zamanla.
        Ana akışı bloklamaz; fire-and-forget yaklaşımı.
        """
        if not self._should_evaluate():
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self.evaluate_rag(query, documents, answer),
                name="sidar_judge_eval",
            )
        except RuntimeError:
            pass  # Event loop yok — sessizce atla


# ─── Metrics entegrasyonu ─────────────────────────────────────────────────────

def _record_judge_metrics(result: JudgeResult) -> None:
    """JudgeResult'ı LLMMetricEvent'e ek alan olarak logla."""
    try:
        from core.llm_metrics import get_llm_metrics_collector
        collector = get_llm_metrics_collector()
        # judge_score ve hallucination_risk kullanım izleme sinkine ilet
        if collector._usage_sink is not None:
            import inspect
            payload = {
                "type": "judge",
                "judge_score": result.relevance_score,
                "hallucination_risk": result.hallucination_risk,
                "model": result.model,
                "provider": result.provider,
                "evaluated_at": result.evaluated_at,
            }
            out = collector._usage_sink(payload)
            if inspect.isawaitable(out):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(out)
                except RuntimeError:
                    pass
    except Exception as exc:
        logger.debug("Judge metrik kaydı başarısız: %s", exc)


# ─── Singleton ────────────────────────────────────────────────────────────────

_JUDGE: Optional[LLMJudge] = None


def get_llm_judge() -> LLMJudge:
    """Süreç-geneli tek LLMJudge örneğini döndürür."""
    global _JUDGE
    if _JUDGE is None:
        _JUDGE = LLMJudge()
    return _JUDGE