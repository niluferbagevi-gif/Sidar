# `core/config_observability.py` — Tracing/Metrics/Dashboard Ayarları

- **Kaynak dosya:** `core/config_observability.py`
- **Not dosyası:** `docs/module-notes/core/config_observability.py.md`

**Amaç:** OpenTelemetry tracing, metrics token'ı, Grafana URL'i ve DLP tespit
loglaması gibi observability ayarlarını `ObservabilitySettings` frozen
dataclass'ı olarak yükler.

**Özellikler:**
- `ObservabilitySettings` — `metrics_token`, `enable_tracing`,
  `otel_exporter_endpoint`, `otel_service_name`, `otel_instrument_fastapi`,
  `otel_instrument_httpx`, `grafana_url`, `dlp_log_detections`.
- `load_observability_settings()` — `get_bool_env` ile bayrakları, `os.getenv`
  ile URL/token değerlerini okur.
- `DEPENDENCY_AUTO` — `init_telemetry()`'nin "çağıran bu bağımlılığı
  vermedi, gerçek OpenTelemetry paketini otomatik import et" durumunu açık
  `None` ("bu bağımlılık kullanılamıyor, fail-closed dön") durumundan ayırt
  eden sentinel; `config.py`'nin `config._DEPENDENCY_AUTO` re-export'uyla
  aynı nesne kimliğini paylaşır.
- `init_telemetry(...)` — OpenTelemetry tracing + opsiyonel FastAPI/HTTPX
  enstrümantasyonunu başlatır. `config.Config.init_telemetry`'den (önceden
  Config sınıfının ~95 satırlık bir metodu) buraya taşındı — config.py'deki
  kalan büyük mantık bloklarını `core/config_*.py` desenine taşıma
  çalışmasının ilk adımı (bkz. `docs/module-notes/config.py.md`). `Config`
  sınıfının kendi `ENABLE_TRACING`/`OTEL_*` class attribute'larına (testlerin
  doğrudan monkeypatch ettiği canlı değerler) bağımlı değildir — bunlar
  `Config.init_telemetry` sarmalayıcısı tarafından çözülüp keyword argüman
  olarak geçirilir.
