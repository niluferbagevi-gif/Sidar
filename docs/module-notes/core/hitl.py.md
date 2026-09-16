# `core/hitl.py` — Human-in-the-Loop (HITL) Onay Geçidi

- **Kaynak dosya:** `core/hitl.py`
- **Not dosyası:** `docs/module-notes/core/hitl.py.md`

**Amaç:** Yıkıcı/kritik işlemlerin (dosya silme/üzerine yazma, GitHub PR
oluşturma, dal silme) gerçekleşmeden önce insan onayına sunulmasını sağlar.

**Mimari:** `HITLRequest` (onay bekleyen işlem kaydı — bellek içi `deque` +
opsiyonel DB) ve `HITLGate` (iş mantığı katmanı: request üretir, karar
bekler). `web_server.py`'nin `/api/hitl/request`, `/api/hitl/respond/{id}`,
`/api/hitl/pending` uç noktaları bu modülü kullanır. Entegrasyon noktaları:
`managers/code_manager.py` (dosya silme/üzerine yazma) ve
`managers/github_manager.py` (PR oluşturma, dal silme).

**Yapılandırma (.env):** `HITL_ENABLED=true` (güvenli varsayılan — yalnız
bilinçli local/test akışında `false`), `HITL_TIMEOUT_SECONDS=120`
(`_DEFAULT_TIMEOUT`). `HITLDecision` enum'u: `PENDING`/`APPROVED`/`REJECTED`/`TIMEOUT`;
`_MAX_QUEUE_SIZE=200` bellekte tutulan istek üst sınırı.
