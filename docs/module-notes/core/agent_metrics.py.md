# `core/agent_metrics.py` — Ajan Delegasyon/Step Metrikleri (Prometheus)

- **Kaynak dosya:** `core/agent_metrics.py`
- **Not dosyası:** `docs/module-notes/core/agent_metrics.py.md`

**Amaç:** `agent/core/supervisor.py`'nin `_delegate()`/`_route_p2p()`
çağrılarından üretilen gecikme (latency)/sayaç verilerini process-içi
saklar; `web/routes/metrics.py`'nin `/metrics/llm/prometheus` uç noktası
bu verileri Prometheus formatında döndürür.

**Özellikler:**
- `_BUCKETS`, `_AUTH_HASH_BUCKETS` — histogram bucket sınırları (saniye).
- `_DelegationHistogram` — dahili histogram implementasyonu.
- `AgentMetricsCollector` — delegasyon/step süresi ve sayaç metriklerini
  toplayan ana sınıf.
- `get_agent_metrics_collector()` — process-wide singleton erişimi.
