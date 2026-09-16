# `core/judge.py` — LLM-as-a-Judge Kalite Değerlendirme Modülü

- **Kaynak dosya:** `core/judge.py`
- **Not dosyası:** `docs/module-notes/core/judge.py.md`

**Amaç:** RAG sonuçlarını ve ajan yanıtlarını asenkron olarak LLM tabanlı
değerlendirir; ana akışı bloklamadan arka planda çalışır.

**Özellikler:**
- RAG sorgu-belge alaka değerlendirmesi (relevance, 0.0–1.0) ve yanıt
  tutarlılığı/halüsinasyon riski tahmini (0.0 = düşük risk, 1.0 = yüksek).
- Prometheus metrik çıktısı: `sidar_rag_relevance_score`,
  `sidar_hallucination_risk_score`.
- Örnekleme oranı (`JUDGE_SAMPLE_RATE`, varsayılan `0.2` — her 5 yanıttan
  birini değerlendirir) `random.SystemRandom()` (`_SAMPLING_RANDOM`) ile
  belirlenir; her yanıtı değerlendirmek maliyetli olduğu için bilinçli bir
  örnekleme tercih edilmiştir.

**Yapılandırma (.env):** `JUDGE_ENABLED=true`, `JUDGE_MODEL` (değerlendirme
modeli, `JUDGE_PROVIDER`'dan bağımsız olarak seçilebilir),
`JUDGE_PROVIDER=ollama`, `JUDGE_SAMPLE_RATE=0.2`.
