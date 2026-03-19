# Sürüm Geçmişi (Changelog)

> **Not:** Bu dosya yalnızca sürümler arası farkları, kısa düzeltme notlarını ve teknik borç kapanışı özetlerini içerir. Ayrıntılı çözüm geçmişi `docs/archive/` altında tutulur.

---

## [4.3.0] - 2026-03-19
Repo metrikleri, sürüm numaraları ve üst seviye dokümantasyon mevcut takipli kod tabanı ile senkronize edildi.

### ✅ Dokümantasyon ve Sürüm Senkronizasyonu
**Dosyalar:** `config.py`, `pyproject.toml`, `sidar_project.egg-info/PKG-INFO`, `helm/sidar/Chart.yaml`, `README.md`, `PROJE_RAPORU.md`, `AUDIT_REPORT_v4.0.md`, `TEKNIK_REFERANS.md`, `SIDAR.md`, `CLAUDE.md`
- Runtime, paket ve dağıtım yüzeyi `v4.3.0` sürüm çizgisine taşındı; README, teknik referans, proje raporu ve geliştirici rehberleri aynı baseline ile hizalandı.
- Takipli depo ölçümleri yeniden doğrulandı: **58** üretim Python dosyası / **20.582** satır, **151** test dosyası / **39.147** satır, toplam takipli Python **209** dosya / **59.729** satır, Web UI toplamı **6.105** satır ve REST endpoint envanteri **60** olarak raporlara işlendi.
- Teknik referans turunda API/DB/env sözleşmeleri tekrar kontrol edildi; bu sürümde yeni endpoint, tablo veya config anahtarı eklenmediği için envanter korunurken başlık ve senkronizasyon notları güncellendi.

### ✅ Çözülen Bulgular
**Dosyalar:** `scripts/audit_metrics.sh`, `scripts/collect_repo_metrics.sh`, `tests/test_release_version_bump.py`
- Repo metrik betikleri Git deposu içinde öncelikle `git ls-files` kullanacak şekilde düzeltilerek `.venv`, `node_modules` ve benzeri takip dışı içeriklerin satır sayılarını şişirmesi engellendi.
- Sürüm doğrulama testi, yeni `v4.3.0` baseline ve güncel proje raporu/changelog/SIDAR talimatlarıyla uyumlu hale getirildi.

---

### Teknik Borç Kapanışı
- Repo metrik betikleri Git-takipli dosya ölçümüne alınarak rapor şişmesi üreten ölçüm drift'i kapatıldı.
- Sürüm doğrulama testi ve üst seviye dokümantasyon aynı release çizgisine hizalandı.

---

## [4.0.0] - 2026-03-19
Runtime sürümü ve üst seviye proje raporları, v4 kurumsal mimari omurgasıyla senkronize edildi.

### ✅ Sürüm ve Mimari Senkronizasyonu
**Dosyalar:** `config.py`, `pyproject.toml`, `sidar_project.egg-info/PKG-INFO`, `PROJE_RAPORU.md`, `README.md`
- Runtime ve paket sürümleri `3.0.0` / `0.0.0` seviyelerinden `4.0.0` değerine yükseltildi; böylece config, paket metadata'sı ve v4 audit anlatısı aynı sürüm çizgisine taşındı.
- React tabanlı `web_ui_react/` arayüzünün standart kullanıcı deneyimi olduğu, legacy `web_ui/` klasörünün ise geriye dönük uyumluluk/fallback amacıyla korunduğu dokümante edildi.
- SQLite'tan PostgreSQL + `pgvector` altyapısına geçiş, Alembic migration zinciri ve kurumsal deployment yüzeyinin (Docker Compose + Helm/Redis/Jaeger/OTel) proje raporlarında daha açık biçimde özetlenmesi sağlandı.
- Multi-agent swarm mimarisinin Coder/Researcher/Reviewer uzman rolleri, reviewer QA döngüsü ve token/maliyet gözlemlenebilirliğiyle birlikte ana dokümantasyonda öne çıkarılması tamamlandı.

---

### Teknik Borç Kapanışı
- v4 kurumsal mimari geçişinde sürüm ve rapor baseline farkları kapatıldı.
- Aktif teknik borç kaydı bırakılmadan dokümantasyon tek sürüm çizgisine toplandı.

---

## [v4.2.1] - 2026-03-19
FAZ-10 sonrası dokümantasyon, paketleme ve cutover doğrulama yüzeyi mevcut repo durumu ile senkronize edildi.

### ✅ Dokümantasyon ve Operasyon Senkronizasyonu
**Dosyalar:** `pyproject.toml`, `.github/workflows/migration-cutover-checks.yml`, `README.md`, `RFC-MultiAgent.md`, `TEKNIK_REFERANS.md`, `runbooks/production-cutover-playbook.md`, `PROJE_RAPORU.md`, `AUDIT_REPORT_v4.0.md`
- `pyproject.toml` paket sürümü `config.py` içindeki runtime sürümüyle uyumlu olacak şekilde `3.0.0` olarak düzeltildi.
- PostgreSQL cutover workflow'undan diskte bulunmayan `requirements.txt` bağımlılığı kaldırıldı; migration provası artık `requirements-dev.txt + asyncpg` ile çalışır.
- README, React/Vite geliştirme akışı, SPA öncelikli servisleme modeli, güncel proje ağacı ve 149 test modülü / 151 test dosyası gerçekliğiyle yenilendi.
- RFC ve teknik referans, Supervisor/Coder/Researcher/Reviewer sorumluluklarını ve reviewer'ın dinamik QA/sandbox regresyon rolünü yansıtacak şekilde güncellendi.
- Production cutover ve audit raporları prompt registry, DLP, observability dashboard'ları, migration provası ve `%99.9` coverage hard gate detaylarıyla güçlendirildi.

### Teknik Borç Kapanışı
- Cutover workflow içindeki `requirements.txt` drift'i kaldırıldı.
- Operasyon ve audit dokümantasyonu mevcut repo gerçekliğiyle yeniden hizalandı.

---

## [v4.2.0] - 2026-03-19
FAZ-10 — Autonomous LLMOps kapanış anlatısı kurumsal operasyon seviyesiyle eşitlendi.

### ✅ FAZ-10 — Faz 4 Operasyonel Olarak Kapatıldı
**Dosyalar:** `PROJE_RAPORU.md`, `RFC-MultiAgent.md`, `AUDIT_REPORT_v4.0.md`, `README.md`
- Faz 4; aktif öğrenme, vision, cost-aware routing ve dış sistem orkestrasyonunu kapsayan birleşik **Autonomous LLMOps** katmanı olarak yeniden çerçevelendi.
- Audit trail ve direct `p2p.v1` handoff doğrulamaları bu kabiliyetlerin sadece mevcut değil, denetlenebilir ve rollout'a hazır olduğunu gösterecek şekilde dokümante edildi.
- Proje raporu ve RFC tarafında `v4.2.0` operasyonel kapanış dili, audit ve README tarafında da görünür hâle getirildi.

### Teknik Borç Kapanışı
- Faz 4 kapanışına ait operasyonel belirsizlikler tek kurumsal anlatıda konsolide edildi.

---

## [v3.2.0] - 2026-03-19
FAZ-10 — Autonomous LLMOps ürün anlatısı konsolide edildi.

### ✅ FAZ-10 — Faz 4 Ürün Hikâyesi Tek Çatı Altında Toplandı
**Dosyalar:** `PROJE_RAPORU.md`, `README.md`
- Active Learning/LoRA, Vision Pipeline, cost-aware routing ve Slack/Jira/Teams orkestrasyonu birlikte Faz 4 ürün hikâyesi olarak yeniden yazıldı.
- Faz 4 artık tekil özellik listesi yerine kapalı döngü öğrenme + çok modlu üretim + otonom entegrasyon yönetimi ekseninde anlatılıyor.

### Teknik Borç Kapanışı
- Ayrı bir yeni teknik borç kapanışı yok; Faz 4 ürün hikâyesi borç sonrası ürünleştirme diline taşındı.

---

## [v3.0.31] - 2026-03-19
FAZ-9 — Kurumsal audit trail ve doğrudan P2P handoff rollout'u raporlarla senkronize edildi.

### ✅ FAZ-9 — Tenant RBAC Audit Trail Kayıtları Operasyonel Olarak Doğrulandı
**Dosyalar:** `core/db.py`, `migrations/versions/0003_audit_trail.py`, `web_server.py`, `tests/test_rbac_policy_runtime.py`
- `audit_logs` tablosu Alembic migration `0003_audit_trail` ile şemaya eklendi; kullanıcı/zaman damgası indeksleri hazırlandı.
- `core/db.py` içine `record_audit_log()` ve `list_audit_logs()` yardımcıları eklenerek hem SQLite hem PostgreSQL yollarında denetim kaydı okunur/yazılır hale geldi.
- `web_server.py::access_policy_middleware` artık RBAC kararlarından sonra `user_id`, `tenant_id`, `action`, `resource`, `ip_address` ve `allowed` alanlarını audit trail'e asenkron olarak yazıyor.
- `tests/test_rbac_policy_runtime.py` hem DB round-trip'ini hem de middleware'in izin verilen erişimleri audit tablosuna kaydettiğini doğruluyor.

### ✅ FAZ-9 — Direct Agent Handoff Protokolü Swarm Katmanına Taşındı
**Dosyalar:** `agent/core/contracts.py`, `agent/base_agent.py`, `agent/core/supervisor.py`, `agent/swarm.py`, `tests/test_swarm_orchestrator.py`, `tests/test_supervisor_agent.py`
- `P2PMessage` / `DelegationRequest` sözleşmeleri `handoff_depth`, `protocol` ve `meta.reason` alanlarıyla kurumsal direct handoff protokolünü standartlaştırdı.
- `BaseAgent.delegate_to(...)` ve `SupervisorAgent._route_p2p(...)`, sender/receiver bağlamını ve hop sayısını koruyarak fail-closed P2P delegasyonu sürdürüyor.
- `SwarmOrchestrator._direct_handoff(...)` aynı sözleşmeyi runtime orchestration akışına taşıdı; coder → reviewer → coder zincirinde bağlam kaybı olmadan uzmanlar arası el değiştirme mümkün hale geldi.
- İlgili testler sender/receiver, `p2p_reason`, `p2p_protocol` ve `handoff_depth` alanlarının korunduğunu doğruluyor.

---

### Teknik Borç Kapanışı
- Tenant RBAC audit trail omurgası kurumsal doğrulama eksiklerini kapattı.
- Direct `p2p.v1` handoff zinciri bağlam korumalı hale getirildi.

---

## [v3.0.30] - 2026-03-19
FAZ-8 — Son düşük öncelikli kalite borçları kapatıldı; Zero Debt doğrulama turu tamamlandı.

### ✅ FAZ-8 — D-8..D-14 Kapanış Doğrulaması
**Dosyalar:** `core/entity_memory.py`, `core/cache_metrics.py`, `core/judge.py`, `core/vision.py`, `core/active_learning.py`, `core/hitl.py`, `core/llm_client.py`, `web_server.py`
- **D-8 Çözüldü:** `core/entity_memory.py` içindeki no-op / dead-code satırı kaldırıldı; `get_entity_memory()` artık yalnızca gerçek `db_url` çözümlemesi yapıyor.
- **D-9 Çözüldü:** `core/cache_metrics.py` içine modül düzeyinde public `record_cache_hit()`, `record_cache_miss()` ve `record_cache_skip()` sarmalayıcıları eklendi; `core/llm_client.py` private singleton yerine bu public API'yi kullanıyor.
- **D-10 Çözüldü:** `core/judge.py` içinde `Config()` nesnesi `LLMJudge.__init__()` içine alındı; `_call_llm()` artık aynı config örneğini yeniden kullanıyor.
- **D-11 Çözüldü:** `core/vision.py` içindeki görsel okuma akışı `await asyncio.to_thread(p.read_bytes)` ile event loop'u bloklamayacak şekilde güncellendi.
- **D-12 Çözüldü:** `core/active_learning.py` içindeki `IN (...)` SQL güncellemesi named placeholder (`:id_0`, `:id_1`, ...) yaklaşımına taşındı; veri bind parametreleriyle geçiriliyor.
- **D-13 Çözüldü:** `core/hitl.py` içindeki `_HITLStore` kilidi event loop dışında oluşturulmak yerine `None` ile başlatılıp ilk kullanımda lazy-init ediliyor.
- **D-14 Çözüldü:** `core/hitl.py` içine public `notify()` wrapper'ı eklendi; `web_server.py` artık private `_notify()` yerine bu public arayüzü çağırıyor.

**🏁 Zero Debt Sonucu:** Audit kapsamındaki tüm bulgular (`K-1..K-2`, `Y-1..Y-6`, `O-1..O-8`, `D-1..D-14`) kapatıldı. Açık kritik, yüksek, orta veya düşük öncelikli bulgu kalmadı; güvenlik/operasyon puanı **10.0/10** olarak teyit edildi.

---

### Teknik Borç Kapanışı
- `D-8..D-14` kümesinin tamamı kapatıldı.
- Proje denetim kapsamındaki tüm açık bulgular sıfırlanarak `Zero Debt` durumuna geçti.

---

## [v3.0.26] - 2026-03-18
FAZ-7 — Slack entegrasyonu ve audit çapraz-doğrulama turu tamamlandı.

### ✅ FAZ-7 — O-8 Düzeltme: SlackManager Senkron Blokajı Giderildi
**Dosya:** `managers/slack_manager.py`
- `_init_client()` içindeki senkron `auth_test()` çağrısı kaldırıldı.
- Token doğrulaması asenkron `initialize()` fonksiyonuna taşındı ve `asyncio.to_thread(...)` ile event loop bloklaması önlendi.
- Doğrulama: `managers/slack_manager.py:47-95`

### ✅ FAZ-7 — D-7 Düzeltme: Judge Prometheus Gauge Tekrar Kayıt Riski Giderildi
**Dosya:** `core/judge.py`
- `_prometheus_gauges` modül düzeyi önbelleği eklendi.
- `_inc_prometheus()` aynı metrik adını yeniden kaydetmek yerine mevcut Gauge nesnesini tekrar kullanıyor.
- Doğrulama: `core/judge.py:49-63`

### ✅ FAZ-7 — Önceden Kapatılan Entegrasyon Bulguları Yeniden Doğrulandı
**Dosyalar:** `core/llm_client.py`, `web_server.py`
- Y-6 için `record_routing_cost()` çağrısının aktif olduğu yeniden doğrulandı.
- O-7 için Vision / EntityMemory / FeedbackStore / Slack / Jira / Teams endpoint'lerinin HTTP katmanına gerçekten bağlandığı yeniden doğrulandı.

### ⚠️ FAZ-7 — Açık Kalan Düşük Öncelikli Bulgular
**Dosyalar:** `core/entity_memory.py`, `core/cache_metrics.py`, `core/judge.py`, `core/vision.py`, `core/active_learning.py`, `core/hitl.py`, `web_server.py`
- `D-8` açık: `core/entity_memory.py` içinde `db_url = db_url` no-op satırı hâlâ mevcut.
- `D-9` açık: `core/cache_metrics.py` yalnızca sınıf içi `record_*` metodlarına sahip; modül düzeyi public wrapper fonksiyonlar eklenmediği için `llm_client.py` private `_cache_metrics` nesnesini doğrudan kullanmaya devam ediyor.
- `D-10` açık: `core/judge.py::_call_llm()` içinde `Config()` hâlâ her çağrıda yeniden oluşturuluyor.
- `D-11` açık: `core/vision.py::load_image_as_base64()` hâlâ senkron `read_bytes()` kullanıyor.
- `D-12`, `D-13`, `D-14` açık: önceki audit raporundaki durum değişmedi.

---

### Teknik Borç Kapanışı
- `O-8` Slack senkron blokajı ve `D-7` Prometheus tekrar kayıt riski kapatıldı.
- Önceki `Y-6` ve `O-7` kapanışları yeniden doğrulanarak entegrasyon drift'i temizlendi.

---

## [v3.0.18] - 2026-03-18
FAZ-6 Düşük Öncelikli Son Bulgu — D-6 kapatıldı. Tüm bulgular tamamlandı.

### ✅ FAZ-6 — D-6 Düzeltme: DB `_run_sqlite_op` Gereksiz Lazy Lock Kontrolü
**Dosya:** `core/db.py`
- `_run_sqlite_op` içindeki erişilemez `if self._sqlite_lock is None: raise RuntimeError(...)` bloğu `assert self._sqlite_lock is not None` ile değiştirildi.
- `_connect_sqlite()` her zaman `_sqlite_lock = asyncio.Lock()` oluşturduğundan ve `_sqlite_conn is None` kontrolü üstte yapıldığından ikinci kontrol dead-code'du.
- `assert` ile hem gereksiz dal kaldırıldı hem de lock varlığı belgesi tutuldu.
- Doğrulama: `core/db.py:189`

**🏁 Denetim Tamamlandı:** Tüm K-1..K-2, Y-1..Y-5, O-1..O-6, D-1..D-6 bulguları kapatıldı. Güvenlik puanı: **10.0 / 10**.

---

### Teknik Borç Kapanışı
- `D-6` DB lazy-lock dead-code borcu kapatıldı.

---

## [v3.0.17] - 2026-03-18
FAZ-5 Orta Öncelikli Güvenlik Hardening — Tüm O-1..O-6 bulgular kapatıldı.

### ✅ FAZ-5 — O-1 Doğrulama: Tüm Kilitleri `_app_lifespan`'da Başlat
**Dosya:** `web_server.py`
- `_agent_lock`, `_redis_lock`, `_local_rate_lock` tümü `_app_lifespan` içinde event loop başlatıldıktan hemen sonra oluşturuluyor. Lazy init anti-pattern yok.
- Doğrulama: `web_server.py:289-293`

### ✅ FAZ-5 — O-2 Düzeltme: `add_document_from_file` Base Directory Kısıtlaması
**Dosya:** `core/rag.py`
- `file.is_relative_to(Config.BASE_DIR)` sınır kontrolü eklendi. Proje kök dizini dışındaki tüm dosyalara erişim engellendi.
- Boş uzantı (`""`) `_TEXT_EXTS` whitelist'inden zaten kaldırılmıştı; `_BLOCKED_PARTS` koruması da eklendi.
- Doğrulama: `core/rag.py:635-637`

### ✅ FAZ-5 — O-3 Düzeltme: `DOCKER_REQUIRED` Bayrağı
**Dosyalar:** `config.py`, `managers/code_manager.py`, `.env.example`
- `DOCKER_REQUIRED: bool = get_bool_env("DOCKER_REQUIRED", False)` alanı config.py'ye eklendi.
- `execute_code` fonksiyonunda Docker erişilemezken `Config.DOCKER_REQUIRED` kontrol ediliyor; `True` ise yerel subprocess fallback engelleniyor.
- `.env.example`'a `DOCKER_REQUIRED=false` belgesi eklendi.

### ✅ FAZ-5 — O-4 Doğrulama: Senkron Ollama Check `asyncio.to_thread` ile Sarıldı
**Dosya:** `web_server.py`
- `Config.validate_critical_settings()` zaten `await asyncio.to_thread(Config.validate_critical_settings)` ile sarılmış durumda.
- Doğrulama: `web_server.py:295`

### ✅ FAZ-5 — O-5 Doğrulama: WebSocket Token `Sec-WebSocket-Protocol` Başlığından Okunuyor
**Dosya:** `web_server.py`
- WebSocket handshake sırasında `sec-websocket-protocol` başlığından token okunuyor; JSON payload fallback ikincil konuma düşürüldü.
- Doğrulama: `web_server.py:1076-1103`

### ✅ FAZ-5 — O-6 Düzeltme: `run_shell` Tehlikeli Komut Blocklist
**Dosya:** `managers/code_manager.py`
- `allow_shell_features=True` yoluna yıkıcı komut kalıpları için blocklist eklendi (`rm -rf /`, fork bomb, disk silme, vb.).
- Blocklist `shell=True` subprocess çağrısından önce uygulanıyor.
- Doğrulama: `managers/code_manager.py:551-560`

---

### Teknik Borç Kapanışı
- `O-1..O-6` güvenlik hardening maddeleri kapatıldı.

---

## [v3.0.16] - 2026-03-18
FAZ-4 Yüksek Öncelikli Güvenlik Hardening — Tüm Y-1..Y-5 bulgular doğrulandı ve kapatıldı.

### ✅ FAZ-4 — Y-1 Doğrulama: `/set-level` Admin Kısıtlaması
**Dosya:** `web_server.py`
- `set_level_endpoint` zaten `_require_admin_user` Depends dependency'si ile korunuyor. Kod doğrulamasında bulgu önceden çözülmüş olarak tespit edildi.
- Doğrulama: `web_server.py:1865` — `async def set_level_endpoint(request: Request, _user=Depends(_require_admin_user))`

### ✅ FAZ-4 — Y-2 Doğrulama: RAG Upload Boyut Limiti
**Dosya:** `web_server.py`
- Upload endpoint'i zaten `await file.read(max_bytes + 1)` ile diske yazmadan önce boyut kontrolü yapıyor; aşımda HTTP 413 döndürüyor.
- Doğrulama: `web_server.py:1756-1762`

### ✅ FAZ-4 — Y-3 Doğrulama: `_summarize_memory` Async Çağrısı
**Dosya:** `agent/sidar_agent.py`
- `docs.add_document` zaten `await self.docs.add_document(...)` ile doğru şekilde çağrılıyor; `asyncio.to_thread` anti-pattern yok.
- Doğrulama: `agent/sidar_agent.py:497`

### ✅ FAZ-4 — Y-4 Doğrulama: X-Forwarded-For TRUSTED_PROXIES
**Dosya:** `web_server.py`
- `_get_client_ip()` zaten `Config.TRUSTED_PROXIES` whitelist kontrolü yapıyor; XFF başlığı yalnızca güvenilir proxy IP'lerinden geliyorsa okunuyor.
- Doğrulama: `web_server.py:945-955`

### ✅ FAZ-4 — Y-5 Düzeltme: REDIS_URL get_system_info'dan Kaldırıldı
**Dosya:** `config.py`
- `get_system_info()` dönüş sözlüğünden `redis_url` alanı tamamen kaldırıldı. Kısmi şifre maskeleme yetersiz görüldüğünden (host/port da ifşa oluyordu) alan bütünüyle çıkarıldı.
- Artık kullanılmayan `import re` de kaldırıldı.
- Doğrulama: `config.py:561` — alan mevcut değil.

---

### Teknik Borç Kapanışı
- `Y-1..Y-5` yüksek öncelikli güvenlik bulguları kapatıldı.

---

## [v3.0.15] - 2026-03-18
FAZ-3 Düşük Öncelikli Teknik Borç Temizliği — Tüm D-1..D-5 bulgular ve §11.2 refactor kalıntıları kapatıldı.

### ✅ FAZ-3-1 — web_server.py Dead-Code Temizliği (§11.2 / YN3-O-3 Kapatma)
**Dosya:** `web_server.py`
- `/auth/register` endpoint'inde `hasattr(payload, "username")` + `payload.get("username", "")` dead-code deseni kaldırıldı; `payload.username.strip()` ile doğrudan Pydantic model alanına erişildi.
- `/auth/login` endpoint'inde aynı pattern temizlendi; `payload.username.strip()` / `payload.password` doğrudan kullanım.
- `_RegisterRequest` ve `_LoginRequest` Pydantic modelleri zaten tüm doğrulamayı yapmaktadır; `hasattr`/`.get()` artık gerekmiyordu.

### ✅ FAZ-3-2 — Açık Metrik Endpoint Auth Koruması (D-3)
**Dosyalar:** `web_server.py`, `config.py`, `.env.example`
- `/metrics`, `/metrics/llm`, `/metrics/llm/prometheus`, `/api/budget` endpoint'leri `open_paths` whitelist'inden çıkarıldı.
- `_require_metrics_access(request, user)` Depends dependency eklendi: admin kullanıcı **veya** `METRICS_TOKEN` Bearer token ile erişim.
- `config.py`'ye `METRICS_TOKEN: str = os.getenv("METRICS_TOKEN", "")` alanı eklendi.
- `.env.example`'a `METRICS_TOKEN=` belgesi ve açıklaması eklendi.

### ✅ FAZ-3-3 — Test Altyapısı Standardizasyonu (§11.2 Yol Haritası)
**Dosyalar:** `tests/conftest.py`, `pytest.ini`, `.github/workflows/ci.yml`
- `conftest.py`: Deprecated `event_loop` session fixture override kaldırıldı; `asyncio` import temizlendi.
- `pytest.ini`: `asyncio_default_fixture_loop_scope = session` eklendi (pytest-asyncio ≥ 0.21 standart yolu); `slow` ve `pg_stress` marker tanımları eklendi.
- `ci.yml`: `pg-stress` job eklendi — PostgreSQL 16 service container, `alembic upgrade head` migration adımı ve `pytest -m pg_stress` bağlantı havuzu stres testi otomatikleştirildi.

### ✅ FAZ-3-4a — config.py GPU Fraction Yorum Düzeltmesi (D-1)
**Dosya:** `config.py`
- GPU bellek fraksiyonu hata mesajı: `"(0.1–1.0 bekleniyor)"` → `"(0.1–0.99 bekleniyor, 1.0 dahil değil)"` — `frac < 1.0` validation kuralıyla tutarlı hale getirildi.
- Satır 332 yorum da güncellendi: `# Embedding ve model yüklemeleri için VRAM fraksiyonu (0.1–0.99 bekleniyor, 1.0 dahil değil)`

### ✅ FAZ-3-4b — main.py Port Validasyonu (D-2)
**Dosya:** `main.py`
- `--port` argümanı için `parse_args()` sonrasına 1–65535 aralık doğrulayıcısı eklendi.
- Aralık dışı değer için `parser.error(f"--port değeri 1-65535 arasında...")` ile kullanıcı dostu hata mesajı.

### ✅ FAZ-3-4c — core/rag.py bleach HTML Sanitizasyonu (D-4)
**Dosyalar:** `core/rag.py`, `pyproject.toml`
- `bleach` kütüphanesi opsiyonel import olarak eklendi (`try/except ImportError`).
- `_clean_html()` metodu güncellendi: `bleach` varsa `bleach.clean(html, tags=[], strip=True, strip_comments=True)` ile DOM tabanlı sanitizasyon; yoksa mevcut regex fallback korunur.
- `pyproject.toml` çekirdek bağımlılıklarına `"bleach~=6.1.0"` eklendi.

### ✅ FAZ-3-4d — agent/sidar_agent.py Prompt Injection Koruması (D-5)
**Dosya:** `agent/sidar_agent.py`
- `BASE_DIR` tam dosya sistemi yolu `_build_context()` içinde LLM'e artık gönderilmiyor; `"[proje dizini]"` placeholder kullanılıyor.
- `GITHUB_REPO` tam URL yerine `owner/repo` formatına indirgendi.
- `Son dosya` alanı tam yol yerine `Path(last_file).name` (basename) ile sınırlandırıldı.
- Kod bloğuna güvenlik açıklama yorumu eklendi.

---

### Teknik Borç Kapanışı
- `D-1..D-5` teknik borç kümesi kapatıldı.
- Coverage gate, test standardizasyonu ve auth/HTML/context güvenlik temizliği tamamlandı.

---

## [v3.0.12] - 2026-03-16
§13 kalan maddeler: Extras fine-tuning tamamlandı; Swarm + React UI temeli oluşturuldu.

### ✅ Bağımlılık Extras Grupları — Tamamlandı
**Dosya:** `pyproject.toml`, `requirements-dev.txt`, `uv.lock`
- Yeni extras: `[gemini]` (`google-generativeai`), `[anthropic]` (`anthropic`), `[gpu]` (`nvidia-ml-py`), `[sandbox]` (`docker`), `[gui]` (`eel`)
- `openai~=1.51.2` core'dan kaldırıldı — codebase httpx ile OpenAI API'yi doğrudan çağırıyor; SDK hiç kullanılmıyordu
- `opentelemetry-instrumentation-httpx~=0.50b0` `[telemetry]` extras'ına eklendi (web_server.py'de HTTPXClientInstrumentor kullanılıyor)
- `[all]` kolaylık profili eklendi: tek komutla tüm opsiyonel paketleri kurar
- `requirements-dev.txt` → `-e .[all,dev]` olarak güncellendi
- `uv.lock` yeniden oluşturuldu (openai kaldırıldı, otel-httpx eklendi)

### 🔄 Agent Swarm + Marketplace Temeli
**Dosyalar:** `agent/registry.py`, `agent/swarm.py`
- **`AgentRegistry`**: Çalışma zamanı ajan keşfi ve eklenti kaydı. `@AgentRegistry.register()` dekoratörü veya `register_type()` ile yeni ajan tipleri eklenir. `find_by_capability()` intent bazlı arama sağlar.
- **`AgentSpec`**: `role_name`, `capabilities`, `description`, `version`, `is_builtin` meta verisi ile ajan tanımı
- **`SwarmOrchestrator`**: `run()` (tek görev), `run_parallel()` (eş zamanlı, semafore kısıtlı), `run_pipeline()` (sıralı, context aktarımlı) modları
- **`TaskRouter`**: `_INTENT_CAPABILITY_MAP` üzerinden intent → yetenek → ajan spec yönlendirmesi; yeni kayıtlı ajanlar otomatik keşfedilir
- Yerleşik 3 rol (coder, researcher, reviewer) otomatik kayıtlı

### 🔄 React Frontend Scaffold
**Dizin:** `web_ui_react/`
- Vite + React 18 + Zustand tabanlı modern SPA
- **`useWebSocket`**: FastAPI `/ws/{session_id}` endpoint'i ile tam uyumlu; streaming chunks, `[DONE]` sinyali, JSON zarf ve ham metin chunk desteği
- **`useChatStore`**: Zustand ile mesaj geçmişi, akış tamponu, hata durumu
- **Bileşenler:** `ChatWindow` (auto-scroll), `ChatMessage` (react-markdown + rehype-highlight), `ChatInput` (Enter gönder, Shift+Enter satır), `StatusBar` (WS durum + yeni oturum)
- Vite proxy: `/api`, `/ws`, `/admin`, `/sessions` → `localhost:7860`; `npm run dev` ile hazır çalışır
- Build çıktısı `web_ui_built/` → FastAPI mount'u için hazır yapı

### Güvenlik (önceki commit)
**Dosyalar:** `config.py`, `tests/test_security_warnings.py`
- `MEMORY_ENCRYPTION_KEY` boşken `logger.critical()` (JWT_SECRET_KEY pattern'i ile tutarlı)
- Redis rate limit fallback testleri (10 test)

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.11] - 2026-03-16
§13 v4.0 Kurumsal Yol Haritası iyileştirmeleri uygulandı.

### ✅ OTel Span Enstrümantasyonu — OpenAI ve LiteLLM Sağlayıcıları
**Dosya:** `core/llm_client.py`
Ollama ve Gemini sağlayıcılarında mevcut olan OpenTelemetry span enstrümantasyonu eksik olan iki sağlayıcıya eklendi:
- **OpenAI client:** `llm.openai.chat` span; `sidar.llm.provider`, `sidar.llm.model`, `sidar.llm.stream`, `sidar.llm.total_ms` attribute'ları; streaming için `start_span`, non-streaming için `start_as_current_span` pattern'i uygulandı; her iki `except` bloğuna `span_cm.__exit__` eklendi.
- **LiteLLM client:** `llm.litellm.chat` span; `sidar.llm.provider`, `sidar.llm.model`, `sidar.llm.stream`, `sidar.llm.total_ms` attribute'ları; fallback model döngüsü kapsamında hata yolları dahil tüm çıkış noktaları kapatıldı.
- **Sonuç:** Tüm 5 LLM sağlayıcısı (Ollama, Gemini, OpenAI, Anthropic, LiteLLM) artık `sidar.llm.*` attribute'larıyla tam kapsamlı OTel izlemeye sahip.

### ✅ OTel Span Enstrümantasyonu — RAG Arama Katmanı
**Dosya:** `core/rag.py`
- `opentelemetry` paketinin opsiyonel import'u eklendi (`try/except` — paket yoksa `None`).
- `search()` async metodu `rag.search` span ile sarıldı; `sidar.rag.mode`, `sidar.rag.session_id`, `sidar.rag.query_len`, `sidar.rag.success` attribute'ları eklendi.
- `asyncio.to_thread()` ile çağrılan `_search_sync` için span async sınırda (`search()` içinde) oluşturuldu — context propagation korundu.

### ✅ Prompt Registry Admin UI
**Dosyalar:** `web_ui/index.html`, `web_ui/app.js`
- `index.html` admin paneline "Prompt Registry" bölümü eklendi: istatistik kartları (aktif rol, toplam sayım), rol filtresi, yenile/yeni prompt butonları, ID/Rol/Versiyon/Durum/Güncellenme/İşlem sütunlarından oluşan tablo, prompt oluşturma/düzenleme formu (rol seçici, etkinleştirme checkbox'ı, textarea).
- `app.js`'e 5 yeni fonksiyon eklendi: `loadPromptRegistry()` (GET /admin/prompts), `showPromptForm()`, `hidePromptForm()`, `savePrompt()` (POST /admin/prompts), `activatePrompt(id)` (POST /admin/prompts/activate).
- `showAdminPanel()` fonksiyonu `loadPromptRegistry()` çağrısını içerecek şekilde güncellendi.

### ✅ `.env.example` Genişletildi
**Dosya:** `.env.example`
Eksik v4.0 konfigürasyon değişkenleri için yeni bölümler eklendi:
- **LiteLLM Gateway:** `LITELLM_GATEWAY_URL`, `LITELLM_API_KEY`, `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `LITELLM_TIMEOUT`
- **Anlamsal Önbellekleme:** `ENABLE_SEMANTIC_CACHE`, `SEMANTIC_CACHE_THRESHOLD`, `SEMANTIC_CACHE_TTL`, `SEMANTIC_CACHE_MAX_ITEMS`
- **pgvector RAG:** `RAG_VECTOR_BACKEND`, `PGVECTOR_TABLE`, `PGVECTOR_EMBEDDING_DIM`, `PGVECTOR_EMBEDDING_MODEL`
- **Event Bus:** `SIDAR_EVENT_BUS_CHANNEL`, `SIDAR_EVENT_BUS_GROUP`
- **OTel genişletme:** `OTEL_SERVICE_NAME`, `OTEL_INSTRUMENT_FASTAPI`, `OTEL_INSTRUMENT_HTTPX`

### ✅ PROJE_RAPORU.md v3.0.11 Güncellendi
- §13'te Anlamsal Önbellekleme: 🟡 Kısmen → ✅ Tamamlandı (Redis + cosine similarity + LRU)
- §13'te Dinamik Prompt ve Model Yönetimi: pending → ✅ Tamamlandı (migration 0002 + 4 API endpoint + Admin UI)
- §13'te Dağıtık İzlenebilirlik: sınırlı → ✅ Tamamlandı (5 LLM sağlayıcısı + RAG OTel span)
- v4.0 özet bloğuna 3 yeni tamamlama maddesi eklendi.

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.9] - 2026-03-16
YN3 serisi kapatma — v3.0.7 doğrulama turunda tespit edilen 6 bulgunun tamamı giderildi.

### ✅ YN3-O-4 — Yanlış Pozitif Teyit Edildi
`agent/sidar_agent.py:96,321` — `threading.Lock()` `_load_instruction_files()` sync metodunda doğru kullanılıyor; metot `asyncio.to_thread()` ile thread pool'da çalışıyor. `asyncio.Lock()` thread-safe olmadığından değişiklik gerekmez.

### ✅ YN3-O-1 — `_ANYIO_CLOSED` Artık Kullanılıyor
**Dosya:** `web_server.py`
`_ANYIO_CLOSED` WebSocket handler dış `except` bloğuna eklendi. `anyio.ClosedResourceError` artık `WebSocketDisconnect` ile eşdeğer biçimde işleniyor; beklenmedik diğer istisnalar ise `logger.warning` ile iletilir.

### ✅ YN3-O-2 — `_rate_lock` Dead Code Kaldırıldı
**Dosyalar:** `web_server.py`, `tests/test_targeted_coverage_additions.py`, `tests/test_sidar.py`
* `_rate_lock: asyncio.Lock | None = None` satırı kaldırıldı (`web_server.py:467`).
* Test dosyalarındaki `web_server._rate_lock = asyncio.Lock()` ifadeleri (6 adet, 2 dosya) `web_server._local_rate_lock = asyncio.Lock()` olarak güncellendi. Artık testler üretim kodunun gerçekten kullandığı kilidi sıfırlıyor; test izolasyonu tamamlandı.
* `_rate_data` alias'ı korundu — `_local_rate_limits` sözlüğü için geçerli test temizleme noktası.

### ✅ YN3-O-3 — `isinstance(payload, dict)` Redundant Kaldırıldı
**Dosya:** `web_server.py` — `/auth/register` (satır 365-366) ve `/auth/login` (satır 382-383)
FastAPI Pydantic doğrulaması `payload`'ı her zaman model örneği olarak sağlar; `isinstance(payload, dict)` dalı hiçbir zaman `True` olmuyordu. `payload.username` / `payload.password` doğrudan kullanılıyor.

### ✅ YN3-D-1 — JWT_SECRET_KEY Config'e Taşındı + Kritik Uyarı Eklendi
**Dosyalar:** `config.py`, `web_server.py`, `.env.example`
* `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_TTL_DAYS` `config.py` `Web Arayüzü` bölümüne eklendi.
* `web_server.py`'de `_get_jwt_secret()` yardımcı fonksiyonu oluşturuldu; `JWT_SECRET_KEY` boşsa `logger.critical(...)` ile açık uyarı verilir.
* `.env.example`'a JWT bölümü ve güvenlik notu eklendi.

### ✅ YN3-D-2 — Grafana URL Dinamik Injection
**Dosyalar:** `config.py`, `web_server.py`, `web_ui/index.html`, `.env.example`
* `GRAFANA_URL` env değişkeni `config.py`'ye eklendi (varsayılan: `http://localhost:3000`).
* `index()` route'u artık `window.__SIDAR_CONFIG__ = {"grafanaUrl": "..."}` config script'ini `<head>` içine inject ediyor.
* `web_ui/index.html:286` Grafana butonu `window.__SIDAR_CONFIG__.grafanaUrl` değerini kullanıyor; fallback olarak yine `http://localhost:3000` korunuyor.
* `.env.example`'a `GRAFANA_URL` ve açıklaması eklendi.

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.8] - 2026-03-16
YN2 serisi kapatma — v3.0.6 doğrulama turunda tespit edilen her iki operasyonel uyumsuzluk giderildi.

### ✅ YN2-Y-1 Kapatıldı — CI Kurulum Adımı Düzeltildi

**[YN2-Y-1 Çözüldü] `.github/workflows/ci.yml` — `pip install -r requirements.txt` satırı kaldırıldı**
* **Kök neden:** `ci.yml` `Install dependencies` adımı var olmayan `requirements.txt` dosyasını yüklemeye çalışıyordu. Bu, CI kurulumunu hata ile sonlandırıyor ve `pytest-asyncio` hiç yüklenmiyordu. `pytest.ini:4` `asyncio_mode = auto` ayarı aktif olmasına rağmen plugin eksikliği nedeniyle async testler çalışamıyordu.
* **Uygulanan düzeltme:** `pip install -r requirements.txt` satırı kaldırıldı. `requirements-dev.txt` zaten `-e .[rag,postgres,telemetry,dev]` komutuyla `pyproject.toml[dev]`'daki `pytest-asyncio>=0.23.0` dahil tüm bağımlılıkları yükler.
* **Değişen dosya:** `.github/workflows/ci.yml` satır 22 (eski satır silindi)
* **Doğrulama zinciri:** `requirements-dev.txt:3` → `pyproject.toml:40` `pytest-asyncio>=0.23.0`

### ✅ YN2-O-1 Kapatıldı — Mock Varlığı Doğrulandı

**[YN2-O-1 Doğrulandı] `tests/test_code_manager_runtime.py:280-285` — socket mock'ları zaten mevcut**
* `os.stat()` ve `stat.S_ISSOCK()` satır satır incelemeyle tam mock'lanmış olduğu teyit edildi.
* Rapor, mevcut mock'ları gözden kaçırmıştı; test deterministik olduğu onaylandı.
* Ek kod değişikliği gerektirmedi.

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.7] - 2026-03-16
Tam kaynak denetimi (v3.0.7) — tüm kaynak dosyalar yeniden satır satır incelendi; YN2-O-1 kapatıldı; YN2-Y-1 hâlâ açık; 6 yeni bulgu (YN3 serisi) kayıt altına alındı.

### ✅ YN2-O-1 Kapatıldı

**[YN2-O-1 Çözüldü] `managers/code_manager.py` — Docker socket fallback test mock'ları doğrulandı**
* `tests/test_code_manager_runtime.py:281-285` satırlarında `os.stat()` `st_mode=0` döndüren sahte nesneyle, `stat.S_ISSOCK()` her zaman `True` döndürecek şekilde tam mock'lanmıştır.
* Test artık WSL2 socket fallback akışını deterministik biçimde doğrulamaktadır.
* Referans: `tests/test_code_manager_runtime.py:238-285`

### 🟠 YN2-Y-1 Hâlâ Açık

**[YN2-Y-1 Devam Ediyor] `pytest.ini` / `pyproject.toml` — async test plugin bağımlılık uyumsuzluğu**
* `pytest.ini:4` içinde `asyncio_mode = auto` aktif. `pytest-asyncio>=0.23.0` yalnızca `pyproject.toml[dev]` extras'ında tanımlı.
* `environment.yml` `-e .[rag,postgres,telemetry,dev]` ile conda ortamında dev dahil ediliyor.
* Bare `pip install -e .` ile kurulan ortamlarda (`dev` extras olmadan) `pytest-asyncio` yüklenmez ve async testler `"async def functions are not natively supported"` hatası verir.
* **Öneri:** `pytest-asyncio` ve `anyio[trio]` paketlerini `pyproject.toml` ana `dependencies`'den değil, CI workflow'da `pip install -e ".[dev]"` ile zorunlu kılarak çözmek veya CI adımına eklemek.

### ✅ YN3 Serisi — Yeni Tespit Edilen Bulgular

| # | Dosya | Satır | Ciddiyet | Açıklama |
|---|-------|-------|----------|----------|
| YN3-O-4 | `agent/sidar_agent.py` | `96`, `321` | 🟠 ORTA | `threading.Lock()` async fonksiyon içinde kullanılıyor; event loop'u anlık bloklama riski. `asyncio.Lock()` ile değiştirilmeli. |
| YN3-O-1 | `web_server.py` | `32-35` | 🟡 ORTA | `_ANYIO_CLOSED` dead code — import ediliyor ama hiç kullanılmıyor. |
| YN3-O-2 | `web_server.py` | `466-467` | 🟡 ORTA | `_rate_data` ve `_rate_lock` dead code — `_local_rate_lock` kullanılırken bu değişkenler tanımlı ama işlevsiz. |
| YN3-O-3 | `web_server.py` | `365-366`, `382-383` | 🟡 ORTA | `isinstance(payload, dict)` redundant — FastAPI Pydantic validation sonrası `payload` her zaman model örneğidir; `.get()` çalışmaz. |
| YN3-D-1 | `web_server.py` | `196`, `207` | 🟡 DÜŞÜK | `"sidar-dev-secret"` hardcoded JWT fallback — production'da `JWT_SECRET_KEY` set edilmezse imzalar tahmin edilebilir. |
| YN3-D-2 | `web_ui/index.html` | `286` | 🟡 DÜŞÜK | `http://localhost:3000` hardcoded Grafana URL — container ortamında düzgün çalışmayabilir. |

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.6] - 2026-03-16
Doğrulama turu — v3.0.4/v3.0.5 bulguları kod üzerinde yeniden teyit edildi; 2 yeni operasyonel uyumsuzluk tespit edildi (YN2-Y-1, YN2-O-1).

_(Ayrıntılar PROJE_RAPORU.md §11.3'te kayıtlıdır.)_

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.5] - 2026-03-16
Tam kaynak denetimi (v3.0.5) — v3.0.4 tüm bulgular doğrulandı/kapatıldı; 5 yeni bulgu tespit edilip giderildi.

### ✅ v3.0.4 Bulgularının Doğrulanması ve Kapatılması

Aşağıdaki bulgular satır satır kaynak incelemesiyle doğrulanmıştır.

| Bulgu | Dosya | Durum |
|-------|-------|-------|
| K-1 — `.env`/`.example` `_SAFE_EXTENSIONS`'dan kaldırıldı | `web_server.py:876` | ✅ Doğrulandı |
| K-2 — `container.wait()` dict dönüş tipi | `managers/code_manager.py:393` | ✅ Yanlış Pozitif Teyit |
| Y-1 — Test kodu enjeksiyonu `repr()` ile giderildi | `agent/roles/reviewer_agent.py:52` | ✅ Doğrulandı |
| Y-2 — asyncpg `endswith("1")` → `int(...split()[-1]) > 0` | `core/db.py:516–519` | ✅ Doğrulandı |
| Y-3 — `handle()` blocking çağrıları `asyncio.to_thread` | `agent/auto_handle.py:93,96,108` | ✅ Doğrulandı |
| Y-4 — `add_document_from_file` sync | `core/rag.py:427` | ✅ Yanlış Pozitif Teyit |
| Y-5 — `_root = Path(__file__).parent.resolve()` | `web_server.py:838,879,1105` | ✅ Doğrulandı |
| O-1 — ReDoS: `.{0,200}` + 2000 karakter guard | `agent/auto_handle.py:56,72` | ✅ Doğrulandı |
| O-2 — `re.IGNORECASE` zaten mevcut | `managers/security.py:30` | ✅ Yanlış Pozitif Teyit |
| O-3 — `logger.warning()` webhook secret eksikliği | `web_server.py:1294` | ✅ Doğrulandı |
| O-4 — `__exit__(*sys.exc_info())` — 5 lokasyon | `core/llm_client.py:304,383,542,705,890` | ✅ Doğrulandı |
| O-5 — `_init_lock = asyncio.Lock()` pre-created | `agent/sidar_agent.py:101` | ✅ Doğrulandı |
| O-6 — `asyncio.wait_for(..., timeout=REACT_TIMEOUT)` | `agent/core/supervisor.py:86` | ✅ Doğrulandı |
| O-7 — `stat.S_ISSOCK()` WSL2 socket doğrulaması | `managers/code_manager.py:173` | ✅ Doğrulandı |
| D-1 — `async def` shim'ler `def`'e dönüştürüldü | `agent/core/memory_hub.py:45` | ✅ Doğrulandı |
| D-2 — `Version()` sürüm karşılaştırması | `managers/package_info.py:176` | ✅ Doğrulandı |
| D-3 — `daily_usage_usd` vs `total_usage_usd` ayrıldı | `core/llm_metrics.py:188` | ✅ Doğrulandı |
| D-4 — `self._tasks = []` __init__'te başlatılıyor | `managers/todo_manager.py:65` | ✅ Yanlış Pozitif Teyit |
| D-5 — Açıklayıcı `KeyError` mesajı | `agent/core/registry.py:19` | ✅ Doğrulandı |
| D-6 — FTS read `_write_lock` ile korundu | `core/rag.py:661` | ✅ Doğrulandı |

### ✅ v3.0.5 Yeni Bulgular — Giderilen

**[YN-K-1 Çözüldü] `core/rag.py` — `.env`/`.example` `_TEXT_EXTS`'den kaldırıldı (K-1 bypass)**
* `add_document_from_file` içindeki `_TEXT_EXTS` kümesinden `.env` ve `.example` uzantıları çıkarıldı.
* Artık `{"path": ".env"}` ile `/rag/add-file` endpoint'i üzerinden gizli dosyalar RAG deposuna indekslenemiyor.
* Referans: `core/rag.py:446`

**[YN-Y-1 Çözüldü] `agent/sidar_agent.py` — `_lock` lazy None init giderildi**
* `self._lock = None` → `self._lock = asyncio.Lock()` (`__init__` içinde).
* `respond()` içindeki `if self._lock is None:` guard kaldırıldı.
* O-5'te `_init_lock` için uygulanan aynı pattern `_lock` için de tamamlandı.
* Referans: `agent/sidar_agent.py:53`

**[YN-Y-2 Çözüldü] `core/rag.py` — `add_document_from_url` SSRF koruması eklendi**
* `_validate_url_safe()` statik metodu eklendi:
  - Yalnızca `http`/`https` şemalarına izin verilir.
  - IP adresi private/loopback/link-local/reserved ise `ValueError` fırlatır.
  - `localhost`, `169.254.169.254`, `metadata.google.internal` hostname'leri engellendi.
* `max_redirects=5` sınırı eklendi.
* `urllib.parse` ve `ipaddress` modülleri import edildi.
* Referans: `core/rag.py:411–431`

**[YN-Y-3 Çözüldü] `managers/github_manager.py` — `.env`/`.example` `SAFE_TEXT_EXTENSIONS`'dan kaldırıldı**
* GitHub deposu dosyası okuma izninden `.env` ve `.example` uzantıları çıkarıldı.
* K-1 güvenlik gerekçesiyle (hassas ortam değişkeni dosyaları) tutarlı hale getirildi.
* Referans: `managers/github_manager.py:33`

**[YN-O-1 Çözüldü] `web_server.py` — Auth endpoint'leri Pydantic model kullanıyor**
* `_RegisterRequest` (`username` min_length=3/max_length=64, `password` min_length=6/max_length=128) modeli eklendi.
* `_LoginRequest` (`username` max_length=64, `password` max_length=128) modeli eklendi.
* `/auth/register` ve `/auth/login` endpoint'leri `payload: dict` yerine bu modelleri kullanıyor.
* FastAPI'nin otomatik doğrulaması devreye girdiğinden `str(None)` DB'ye ulaşamaz.
* Referans: `web_server.py:269–306`

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.4] - 2026-03-16
Tam kaynak denetimi — test istatistikleri güncellendi, kapsama kalite kapısı %99.9'a yükseltildi, 20 yeni güvenlik/işlevsellik bulgusu tespit edilip giderildi.

### ✅ Güvenlik Düzeltmeleri

**[K-1 Çözüldü] `web_server.py` — `.env`/`.example` `/file-content` endpoint'inden engellendi**
* `_SAFE_EXTENSIONS` kümesinden `.env` ve `.example` kaldırıldı; bu uzantılara `415 Unsupported Media Type` döndürülüyor.
* Regresyon testi `tests/test_web_server_runtime.py::test_vendor_index_and_file_content_guard_paths`'e eklendi.

**[Y-1 Çözüldü] `agent/roles/reviewer_agent.py` — Test kodu enjeksiyonu engellendi**
* Triple-quote string embed → `repr()` ile tüm özel karakterler kaçışlandı.

**[Y-2 Çözüldü] `core/db.py` — asyncpg result `endswith("1")` kırılganlığı giderildi**
* `int(str(result).split()[-1]) > 0` ile "UPDATE 10+" senaryoları doğru işleniyor.

**[Y-3 Çözüldü] `agent/auto_handle.py` — Async bağlamda bloklayıcı senkron çağrılar**
* `handle()` içinde `_try_*` çağrıları `await asyncio.to_thread(...)` ile sarmalandı.

**[Y-5 Çözüldü] `web_server.py` — Symlink traversal tutarsızlığı**
* 3 endpoint'te `_root = Path(__file__).parent.resolve()` yapıldı.

### ✅ Asenkron / Yapısal Düzeltmeler

| Bulgu | Değişiklik |
|-------|-----------|
| O-1 ReDoS | `\bfirst\b.{0,200}\bthen\b` + 2000 karakter guard |
| O-3 Webhook | `logger.warning()` secret eksikliği için |
| O-4 `__exit__` | `sys.exc_info()` ile 5 lokasyon güncellendi |
| O-5 `_init_lock` | `asyncio.Lock()` pre-created in `__init__` |
| O-6 P2P timeout | `asyncio.wait_for(..., REACT_TIMEOUT)` |
| O-7 Docker socket | `stat.S_ISSOCK()` doğrulaması |

### ✅ Kalite / Mimari Düzeltmeler

| Bulgu | Değişiklik |
|-------|-----------|
| D-1 async shims | `async def` → `def` (4 metot) |
| D-2 Version | `packaging.version.Version()` karşılaştırması |
| D-3 daily/total | 24 saatlik pencere ayrımı |
| D-5 KeyError | Açıklayıcı hata mesajı |
| D-6 FTS read | `_write_lock` ile korundu |

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.1] - 2026-03-15
Teknik borç temizleme + tam repo denetimi yayını — tüm v3.0 nesil teknik borç kalemleri kapatıldı, Bölüm 11.2 tablosu sıfırlandı; satır sayımları güncellendi; `SANDBOX_*` env var dokümantasyon boşluğu kapatıldı.

### ✅ Ödenmiş Teknik Borçlar

**[Borç #2 Çözüldü] Vanilla JS UI ölçeklenme riski (`web_ui/*.js`)**
* `seedUIStore()` IIFE `app.js`'e eklenerek 12 paylaşımlı durum anahtarı (`isCurrentUserAdmin`, `isStreaming`, `msgCounter`, `currentRepo`, `currentBranch`, `defaultBranch`, `currentSessionId`, `attachedFileContent`, `attachedFileName`, `allSessions`, `cachedRepos`, `cachedBranches`) merkezi varsayılanlarla başlatıldı.
* Tüm dosya genelindeki `let` global değişkenleri kaldırıldı; `chat.js` 10 `let` bildirimi, `sidebar.js` `_cachedBranches`, `app.js` `isCurrentUserAdmin` tamamen UIStore'a taşındı.
* Çift yazma (double-write) anti-pattern'i kaldırıldı — `setUIState()` / `_setState()` tek ve yetkin kaynak oldu.
* `sidebar.js`'e `_getState` shim'i eklendi; dosyalar arası tüm koordinasyon `window.UIStore.state` üzerinden yürüyor.
* `app.js`: `loadGitInfo()` doğrudan global atamaları bıraktı, ESC kısayol ve DOMContentLoaded init UIStore okuyor.

**[Borç #3 Çözüldü] Sağlayıcılar arası tool-calling şema farkları (`core/llm_client.py`)**
* `SIDAR_TOOL_JSON_INSTRUCTION` paylaşımlı sabiti eklendi — Anthropic'teki dağınık inline string kaldırıldı; tüm sağlayıcılar aynı talimat metnini kullanıyor.
* `BaseLLMClient.json_mode_config()` soyut metodu eklendi — her alt sınıf kendi payload konfigürasyonunu kapsülüyor; `build_provider_json_mode_config()` dışarıdan string dispatch'e gerek kalmadı.
* `BaseLLMClient._inject_json_instruction()` statik yardımcısı: mevcut system mesajına talimatı birleştirir, yoksa başa ekler.
* `OllamaClient` → `{"format": SIDAR_TOOL_JSON_SCHEMA}` (değişmedi, metoda taşındı).
* `GeminiClient` → `response_mime_type: application/json` + system_text'e talimat enjeksiyonu.
* `OpenAIClient` → `json_object` yerine `json_schema` structured outputs (`strict: True`) + `_inject_json_instruction` ile system prompt enjeksiyonu.
* `AnthropicClient` → `json_mode_config()` `{}` döndürür; sistem talimatı `SIDAR_TOOL_JSON_INSTRUCTION` sabiti üzerinden enjekte edilir.

### 🔍 Çoklu Denetim Turu Bulguları

**Satır sayısı güncellemeleri (Borç #2 + #3 refaktörleri sonrası gerçek ölçüm):**
* `core/llm_client.py`: 860 → 898 satır (Borç #3 ilaveleri: `json_mode_config()`, `_inject_json_instruction()`, `SIDAR_TOOL_JSON_INSTRUCTION`)
* `web_ui/chat.js`: 721 → 708 satır (Borç #2: 10 `let` bildirimi kaldırıldı)
* `web_ui/sidebar.js`: 421 → 412 satır (Borç #2: `_cachedBranches` ve double-write kaldırıldı)
* `web_ui/app.js`: 710 → 733 satır (Borç #2: `seedUIStore()` IIFE ve `setUIState()` çağrıları eklendi)
* Web UI toplamı: 4.239 → 4.240 satır; Python kaynak toplamı: ~12.160 → 12.185 satır

**`SANDBOX_*` ortam değişkeni dokümantasyon boşluğu (kapatıldı):**
* `SANDBOX_MEMORY`, `SANDBOX_CPUS`, `SANDBOX_NETWORK`, `SANDBOX_PIDS_LIMIT`, `SANDBOX_TIMEOUT` değişkenleri `config.py::SANDBOX_LIMITS` sözlüğünde tanımlı olmasına rağmen `.env.example`'da ve PROJE_RAPORU.md §12.11'de yer almıyordu.
* Her iki dosyaya da eklenip belgelenmiştir.

**Denetim tespitleri (eylem gerektirmeyen / temiz):**
* 134 Python dosyasının tamamı sözdizimi hatası içermiyor (`ast.parse()` doğrulandı).
* Dairesel import riski yok; tüm iç bağımlılık grafiği tek yönlü DAG.
* Hardcoded secret/credential yok; tüm hassas değerler `os.getenv()` veya yardımcı sarmalayıcılar üzerinden okunuyor.
* `ENABLE_MULTI_AGENT` legacy bayrak olarak `config.py`'de `True` sabitine dönüştürüldü; `.env` üzerinden değiştirilemiyor (belgelendi).

**Bağımsız kod incelemelerinden gelen yeni açık teknik borçlar (§11.2'ye eklendi):**
* **Borç #4:** `inspect.isawaitable()` köprüsü — `memory.add()`/`memory.clear()` async olmasına rağmen `sidar_agent.py:432-434`, `397-399`'da wrapper mevcut.
* **Borç #5:** `ConversationMemory.__init__` `file_path` API kalıntısı — DB-first mimarisiyle çelişen `MEMORY_FILE` parametresi.
* **Borç #6:** RAG `DocumentStore` senkron blokajı — `add_document()` ve `search()` sync; `asyncio.to_thread()` ile wrap ediliyor.
* **Borç #7:** `requirements.txt` zorunlu ↔ runtime opsiyonel çelişkisi — `asyncpg`, `opentelemetry-*`, `chromadb` zorunlu listede ama `try/except` ile opsiyonel.
* **Borç #8 (kritik):** `ToolCall` Pydantic modeli `sidar_agent.py`'de tanımlı değil → `test_sidar.py` ImportError, `test_sidar_agent_runtime.py` AttributeError.
* **Borç #9 (kritik):** `_tool_subtask` metodu ve paralel ReAct kod parçacıkları `sidar_agent.py`'de yok → 8+ test kırık (`test_sidar_agent_runtime.py`, `test_parallel_react_improvements.py`, `test_agent_subtask.py`).
* **Borç #10:** `main.py` `DummyConfig` fail-fast sorunu — `config.py` yoksa sahte ayarlarla devam edilmesi.
* **§7.2/7.4:** `asyncpg`, `opentelemetry-*`, `chromadb` bağımlılık statüsü ⚠ notu ile güncellendi.
* **§13:** JWT stateless auth ve dependency extras grupları v4.0 yol haritasına eklendi.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.0] - 2026-03-11
Bu sürüm, SİDAR'ın kurumsal/SaaS odaklı v3.0 kapanış sürümüdür.

### ✅ Öne çıkanlar
* **Kurumsal veri katmanı:** Alembic migration zinciri, SQLite→PostgreSQL cutover rehberi ve CI dry-run/prova kapıları.
* **Multi-Agent varsayılan mimari:** Supervisor + Coder + Researcher + Reviewer akışının üretim odağında olgunlaştırılması.
* **Güvenlik ve erişim:** Bearer auth, admin panel, WebSocket auth-handshake ve graceful session-expiry UX.
* **Gözlemlenebilirlik:** Prometheus metrikleri + Grafana provisioning/dashboard ile maliyet/hata/kullanıcı görünürlüğü.
* **Sandbox operasyonu:** gVisor/Kata host runtime otomasyon scripti ve rollout dokümantasyonu.

### ✅ Final doğrulama kayıtları (Audit #8–#11)
* **Güvenlik:** WebSocket zorunlu Auth Handshake ve ConversationMemory fail-closed (`MemoryAuthError`) sertleştirmesi eklendi.
* **QA:** ReviewerAgent ile dinamik unit test üretimi ve `MAX_QA_RETRIES=3` devre kesici (circuit-breaker) mekanizması devreye alındı.
* **Operasyon:** SQLite'tan PostgreSQL'e geçiş için `migrate_sqlite_to_pg.py` scripti ve Alembic migration zinciri standardize edildi.
* **Kalite:** Test coverage alt sınırı %95'e çıkarıldı ve CI üzerinde bloklayıcı hale getirildi.

### Added (Eklenenler)
* **[Veritabanı Altyapısı]:** Kalıcılık katmanı JSON modelinden async PostgreSQL + Alembic migration temeline taşındı.
* **[Web Arayüzü]:** WebSocket destekli gerçek zamanlı Web UI üretim akışına alındı.
* **[Güvenli Kod Çalıştırma]:** Zero-Trust Docker REPL sandbox entegrasyonu ile ajan kod yürütme yolu izole edildi.
* **[Telemetri ve İzleme]:** Prometheus + Grafana hattı ile token/maliyet/gecikme görünürlüğü üretim seviyesine çıkarıldı.

### ✅ Ödenmiş teknik borçlar (v3.0 kapanış)
* **[Çözüldü] JSON tabanlı bellek kırılganlığı:** Kalıcılık DB katmanına taşındı; kullanıcı/oturum verileri UUID ve zaman damgası odaklı kayıt modeliyle yönetiliyor.
* **[Çözüldü] Senkron darboğazlar:** Kritik çağrı yolları async modele geçirildi (`httpx`/async servis akışları) ve blocking etkisi azaltıldı.
* **[Çözüldü] Tek ajan sınırı:** Supervisor-first çoklu ajan (Coder/Researcher/Reviewer) + P2P delegasyon/QA döngüsü üretim akışına alındı.
* **[Çözüldü] İzolasyon-güvenlik açığı:** Docker sandbox, path/symlink/blacklist kontrolleri ve auth katmanı sertleştirmeleri ile Zero-Trust çizgisi güçlendirildi.
* **[Çözüldü] Test/CI kalite eşiği:** GitHub Actions kalite kapıları, migration kontrolleri ve coverage hard gate (%95) operasyonel standarda bağlandı.

#### Önceki Denetimlerde (Audit) Çözüldüğü Doğrulanan Diğer Maddeler
| Madde | Doğrulama | Dosya / Referans |
|-------|-----------|-----------------|
| CLI `asyncio.Lock` lifetime hatası | ✅ `_interactive_loop_async()` tek async fonksiyon; `asyncio.run()` döngü dışında | `cli.py:1` |
| RAG oturum izolasyonu | ✅ `session_id` filtresi ChromaDB `where=` ve SQLite `WHERE` clause | `rag.py:_fetch_chroma`, `_fetch_bm25` |
| RRF hibrit sıralama | ✅ `_rrf_search()` k=60, her iki motordan bağımsız getirme | `rag.py:_rrf_search` |
| Sliding window özetleme | ✅ `apply_summary()` son `keep_last`=4 mesajı korur | `memory.py:apply_summary` |
| Web UI modülarizasyonu | ✅ 6 ayrı dosya; `StaticFiles` mount aktif | `web_server.py`, `web_ui/` |
| Bearer Token Auth | ✅ `basic_auth_middleware` + `auth_tokens` doğrulaması | `web_server.py`, `core/db.py` |
| DDoS rate limit | ✅ `ddos_rate_limit_middleware` 120 istek/60 sn; `/static/` muaf | `web_server.py` |
| LLM istemci yeniden yapılandırma | ✅ `BaseLLMClient` ABC + 3 concrete impl | `llm_client.py` |
| DuckDuckGo timeout koruması | ✅ `asyncio.wait_for` + doğru except sırası | `web_search.py` |
| GitHub Issue yönetimi | ✅ list/create/comment/close; 4 metod + 4 ajan aracı | `github_manager.py`, `tooling.py` |
| PR diff aracı | ✅ `get_pull_request_diff(pr_number)` + `github_pr_diff` ajan aracı | `github_manager.py` |
| `scan_project_todos` | ✅ `TodoManager.scan_project_todos()` + `ScanProjectTodosSchema` | `todo_manager.py`, `tooling.py` |
| Non-root Docker kullanıcısı | ✅ `sidaruser` uid=10001 | `Dockerfile` |
| Docker health check | ✅ web modunda `/status`, CLI'de PID 1 kontrol | `Dockerfile` |
| RAG pre-cache | ✅ `PRECACHE_RAG_MODEL=true` build-arg ile `all-MiniLM-L6-v2` önceden indirilir | `Dockerfile` |
| SQLite FTS5 disk tabanlı BM25 | ✅ `_init_fts()` PersistentClient; `unicode61 remove_diacritics 1` tokenizer | `rag.py:_init_fts` |
| Prometheus metrikleri | ✅ `update_prometheus_metrics()` + lazy Gauge init | `system_health.py` |
| OpenAI istemci | ✅ `OpenAIClient` + `response_format: json_object` | `llm_client.py` |
| Drag-drop dosya yükleme | ✅ `/api/rag/upload` endpoint; temp dizin temizleme | `web_server.py` |
| Coverage zorunluluğu (global %70 + kritik modüller %80) | ✅ `run_tests.sh` içinde iki aşamalı `pytest --cov` kapısı tanımlı | `run_tests.sh` |
| Performans benchmark baseline'ları | ✅ `tests/test_benchmark.py` ile ChromaDB/BM25/regex hedef eşikleri doğrulanıyor | `tests/test_benchmark.py` |

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.10.8] - 2026-03-10
Bu sürümde RAG cold-start optimizasyonu tamamlandı ve Anthropic (Claude) sağlayıcı desteği eklendi.

### ✅ RAG Soğuk Başlangıç İyileştirmesi
* **Startup prewarm (`web_server.py`):** FastAPI lifespan başlangıcında `_prewarm_rag_embeddings()` görevi ile Chroma/embedding hazırlığı arka planda tetiklenir.
* **Kullanıcı deneyimi:** İlk RAG çağrısındaki model yükleme gecikmesi sunucu başlangıcına taşındı.

### ✅ Anthropic (Claude) Sağlayıcı Desteği
* **Yeni istemci (`core/llm_client.py`):** `AnthropicClient` eklendi; non-stream ve stream chat akışları desteklenir.
* **Yapılandırma (`config.py`, `.env.example`):** `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_TIMEOUT` değişkenleri eklendi.
* **Başlatıcı/UI/bağımlılıklar:** CLI ve launcher provider seçeneklerine `anthropic` eklendi; Web UI model seçim listesi güncellendi; `requirements.txt` ve `environment.yml` dosyalarına `anthropic` paketi eklendi.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.10.7] - 2026-03-08
Bu sürümde çoklu ortam (environment) yapılandırma desteği tamamlandı.

### ✅ Çevre Başına Konfigürasyon
* **Ortam bazlı dotenv yükleme (`config.py`):** `SIDAR_ENV` değişkeni ile `.env.development`, `.env.production`, `.env.test` gibi dosyalar temel `.env` üzerine `override=True` ile yüklenebilir hale getirildi.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.10.6] - 2026-03-08
Bu sürümde GitHub entegrasyonu pull modelden webhook tabanlı push modele genişletildi.

### ✅ GitHub Webhook Desteği
* **Webhook alıcısı (`web_server.py`):** Push, Pull Request ve Issue event'lerini dinleyen `POST /api/webhook` endpoint'i eklendi.
* **HMAC doğrulaması (`web_server.py`, `config.py`):** `X-Hub-Signature-256` başlığı `GITHUB_WEBHOOK_SECRET` ile doğrulanır; geçersiz imza istekleri `401` ile reddedilir.
* **Ajan belleği bildirimi (`web_server.py`):** Doğrulanan webhook event'leri `[GITHUB BİLDİRİMİ]` formatında konuşma belleğine asenkron olarak yazılır.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.10.5] - 2026-03-08
Bu sürümde güvenlik seviyesi geçişleri ajanın kalıcı sohbet belleğine işlenecek şekilde geliştirildi.

### ✅ Güvenlik Seviyesi Geçiş Logu
* **Runtime seviye değişimi (`managers/security.py`, `agent/sidar_agent.py`):** `SecurityManager.set_level(...)` ve `SidarAgent.set_access_level(...)` eklendi; seviye değişimleri `[GÜVENLİK BİLDİRİMİ]` formatında konuşma belleğine kalıcı olarak yazılıyor.
* **CLI ve Web entegrasyonu (`cli.py`, `web_server.py`):** CLI'da `.level <seviye>` komutu ile dinamik seviye değişimi desteklendi; Web API tarafına `POST /set-level` endpoint'i eklendi.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.10.4] - 2026-03-08
Bu sürümde Web API dokümantasyonu OpenAPI/Swagger standardına yükseltilmiştir.

### ✅ Web API Dokümantasyon İyileştirmeleri
* **OpenAPI Şema Belgelendirmesi (`web_server.py`):** FastAPI `/docs` ve `/redoc` arayüzleri aktif edildi. Kritik API uç noktalarına (`/status`, `/health`, `/sessions`, `/rag/search`, `/rag/add-file`, `/clear`) `summary`, `description` ve `responses` detayları eklendi.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.10.3] - 2026-03-08
Bu sürümde test kalite kapıları ve performans baseline ölçümleri CI/test akışına entegre edilmiştir.

### ✅ Test ve Kalite İyileştirmeleri
* **Test Coverage Hedefleri (`run_tests.sh`):** CI süreçleri için global `%70` (`--cov-fail-under=70`) ve kritik çekirdek modüller (`managers.security`, `core.memory`, `core.rag`) için `%80` (`--cov-fail-under=80`) kapsam zorunluluğu eklendi.
* **Performans Benchmark (`tests/test_benchmark.py`):** Kritik RAG (ChromaDB, BM25) ve AutoHandle regex yolları için `pytest-benchmark` tabanlı otomatik hız testleri sisteme entegre edildi.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.9.0] - 2026-03-08
Bu sürümde RAG motoru ve konuşma belleği katmanında izolasyon, sıralama kalitesi ve ölçeklenebilirlik odaklı iyileştirmeler tamamlanmıştır.

### ✅ Çözülen RAG ve Bellek İyileştirmeleri
* **Hibrit Sıralama (RRF) (`core/rag.py`):** `auto` modda ChromaDB ve BM25 sonuçları Reciprocal Rank Fusion (RRF) ile birleştirilerek daha tutarlı top-k geri çağırma sağlandı.
* **BM25 Disk Motoru (`core/rag.py`):** RAM içi `rank_bm25` akışı kaldırılarak SQLite FTS5 tabanlı kalıcı BM25 indeksine geçildi (`bm25_fts.db`, `bm25_index`).
* **Çok Oturumlu RAG İzolasyonu (`core/rag.py`, `agent/sidar_agent.py`, `web_server.py`):** `session_id` filtrelemesi ChromaDB/BM25/keyword yollarına ve RAG endpoint akışına taşındı; oturumlar arası veri sızıntısı engellendi.
* **Sliding-Window Bellek Özetleme (`core/memory.py`, `agent/sidar_agent.py`):** `apply_summary()` son mesajları koruyan pencere stratejisiyle güncellendi; `MEMORY_SUMMARY_KEEP_LAST` ile yapılandırılabilir hale getirildi.

### 🔎 PROJE_RAPORU §14.3 Eşlemesi (Referans)
* **14.3.1 Hibrit Sıralama (RRF)** → `core/rag.py` içinde `_rrf_search()` ve birleşik skor akışı aktif.
* **14.3.2 BM25 Corpus Ölçeklenebilirliği** → SQLite FTS5 tabanlı disk indeks (`bm25_index`) kullanımı aktif.
* **14.3.3 Çok Oturumlu RAG İzolasyonu** → `session_id` filtreleme ve endpoint geçişleri aktif.
* **14.3.4 Bellek Özetleme Stratejisi Seçimi** → `ConversationMemory.apply_summary()` sliding-window yaklaşımıyla çalışıyor.

### 🔎 PROJE_RAPORU §14.5 Eşlemesi (Referans)
* **14.5.2 Issue Yönetimi** → `managers/github_manager.py` içinde `list_issues/create_issue/comment_issue/close_issue` akışları ve ajan tarafında karşılık gelen `github_*_issue` araçları aktif.
* **14.5.3 Diff Analizi** → `managers/github_manager.py` içinde `get_pull_request_diff()` ve ajan tarafında `github_pr_diff` aracı aktif.

### 🔎 PROJE_RAPORU §14.6 Eşlemesi (Referans)
* **14.6.1 Docker Socket Riski Azaltma** → `docker-compose.yml` içinde `/var/run/docker.sock` yalnızca CLI/REPL servislerinde bırakıldı; web servislerinden kaldırıldı.
* **14.6.2 Denetim Logu (Audit Log)** → `agent/sidar_agent.py` içinde araç çağrıları `logs/audit.jsonl` dosyasına yapısal JSONL olarak yazılıyor.
* **14.6.3 Sandbox Çıktı Boyutu Limiti** → `managers/code_manager.py` içinde `max_output_chars=10000` limiti ile Docker/lokal/shell çıktıları kırpılıyor.

### 🔎 PROJE_RAPORU §14.7 Eşlemesi (Referans)
* **14.7.1 Entegrasyon Test Altyapısı** → `pytest.ini` ile keşif/asenkron mod standardize edildi, `environment.yml` içinde `pytest` + `pytest-asyncio` tanımlandı ve `run_tests.sh` ile tek komut çalıştırma akışı mevcut.
* **14.7.5 Otonom TODO/FIXME Tarama** → `TodoManager.scan_project_todos(...)` ile tarama, `ScanProjectTodosSchema` ile şemalı argüman doğrulama ve ajan tarafında `_tool_scan_project_todos` (non-blocking `asyncio.to_thread`) akışı aktif.

### 🔎 PROJE_RAPORU §14.8 Eşlemesi (Referans)
* **14.8.1 Sağlık Endpoint Genişletmesi** → `SystemHealthManager.get_health_summary()` + `GET /health` endpoint akışı aktif; yanıta `uptime_seconds` ekleniyor ve `AI_PROVIDER=ollama` + erişim yoksa `status=degraded` ile `503` dönülüyor.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.8.0] - 2026-03-08
Bu sürümde kurumsal düzeyde AI Ajan (Agent) mimarisine, çoklu model desteğine ve Model Context Protocol (MCP) standartlarına geçiş yapılmıştır.

### ✅ Çözülen LLM ve Ajan Katmanı İyileştirmeleri (Mimari Değişiklikler)
* **Çoklu LLM Sağlayıcı Genişletmesi (`core/llm_client.py`):** `BaseLLMClient` soyut sınıfı oluşturularak Nesne Yönelimli (OOP) yapıya geçildi. Ollama ve Gemini'nin yanına yapısal stream destekli **OpenAI (GPT-4o)** sağlayıcısı eklendi.
* **Yapısal Araç Şemaları ve MCP Uyumu (`agent/tooling.py`):** Araçların aldığı argümanlar güvensiz string ayrıştırmasından kurtarılarak Pydantic `BaseModel` şemalarına bağlandı. LLM çıktıları JSON Schema kullanılarak yapısal (Structured Output) hale getirildi.
* **Araç Tanımlarının Dışsallaştırılması (`agent/sidar_agent.py`):** Ajan içindeki hardcoded `_tools` sözlüğü dış modüle taşındı, modülerleştirildi ve Pydantic validasyon ağına (`ToolCall`) entegre edildi.
* **Paralel ReAct Adımları (`agent/sidar_agent.py`):** ReAct döngüsü, LLM'den gelen JSON listelerini (Array) yakalayacak şekilde güncellendi. Sadece güvenli okuma/sorgulama araçları filtre edilerek `asyncio.gather` ile tam paralel çalıştırılabilir hale getirildi. Hantal `parallel` aracı kullanımdan kaldırıldı.

### ✅ Çözülen Teknik Borçlar ve Stabilite İyileştirmeleri
* **Web Arama / DuckDuckGo Güvenliği (`managers/web_search.py`, `environment.yml`):** DuckDuckGo arama motoru (DDGS) paketi `6.2.13` sürümüne sabitlendi. Gelecek versiyonlardaki mimari API değişikliklerine karşı koruma sağlamak için dinamik `AsyncDDGS` kontrolü eklendi ve thread'lerin asılı kalmasını (hang) önlemek amacıyla arama işlemlerine `asyncio.wait_for` ile zaman aşımı (timeout) koruması getirildi.
* **Web UI Modülarizasyonu (`web_ui/index.html`, `web_server.py`):** 3.300+ satırlık devasa HTML dosyası parçalanarak `style.css`, `app.js`, `chat.js`, `sidebar.js` ve `rag.js` modüllerine ayrıldı. FastAPI `StaticFiles` ara katmanı (middleware) eklenerek statik asset'lerin performanslı ve güvenli bir şekilde sunulması sağlandı. Ön yüzün (frontend) test edilebilirliği ve sürdürülebilirliği kurumsal standartlara taşındı.

### 🔎 PROJE_RAPORU §14.4 Eşlemesi (Referans)
* **14.4.1 Web UI Modülarizasyonu** → UI katmanı `index.html + style.css + app.js + chat.js + sidebar.js + rag.js` olarak ayrıştırıldı ve `/static` mount ile servis ediliyor.
* **14.4.4 Kimlik Doğrulama** → Web katmanında `API_KEY` tabanlı HTTP Basic Auth middleware akışı aktif (`API_KEY` boşsa bypass, doluysa zorunlu kimlik doğrulama).

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.7.0] - 2026-03-07
Bu sürümde asenkron güvenlik, performans ve stabilite iyileştirmelerine odaklanılmıştır.

### ✅ Çözülen Yüksek Öncelikli Sorunlar
* **`core/rag.py` (Thread-Safety):** `_chunk_text()` içindeki geçici sınıf değişkeni değişimi lokal değişkenlere alınarak race condition engellendi. Sıfıra bölme ve sonsuz döngü koruması eklendi.
* **`core/rag.py` (Performans):** `_bm25_search()` içindeki skor hesaplaması `_write_lock` kapsamı dışına çıkarılarak thread bloklanması önlendi.
* **`agent/sidar_agent.py` (Cache Güvenliği):** `_instructions_cache` okuma/yazma işlemleri `threading.Lock` ile asenkron çakışmalara karşı koruma altına alındı.

### ✅ Çözülen Orta Öncelikli Sorunlar
* **`web_server.py` (Rate Limiting):** İstek sınırlandırması `defaultdict` yerine `cachetools.TTLCache` entegrasyonu ile kalıcı hale getirildi.
* **`core/memory.py` (Token Optimizasyonu):** Tahmini token hesabı yerine `tiktoken` kütüphanesi ile gerçek tokenizer entegrasyonu yapıldı.
* **`docker-compose.yml` (Güvenlik):** `sidar-web` ve `sidar-web-gpu` servislerinden `/var/run/docker.sock` erişimi kaldırılarak container escape zafiyeti giderildi.
* **`managers/github_manager.py` (API Güvenliği):** `list_commits` metodunda limit aşımlarında kullanıcıya açık uyarı dönecek şekilde düzenleme yapıldı.

### 🔎 PROJE_RAPORU §14.1 Eşlemesi (Referans)
* **14.1.1 Kalıcı Rate Limiting** → `web_server.py` üzerinde `TTLCache` tabanlı kalıcı pencere sınırlandırması uygulandı.
* **14.1.2 Gerçek Token Sayacı** → `core/memory.py` içinde `tiktoken` entegrasyonu aktif.
* **14.1.3 Talimat Cache Koruması** → `agent/sidar_agent.py` içinde `_instructions_cache` akışı `threading.Lock` ile korunuyor.
* **14.1.4 Thread-Safe Chunking** → `core/rag.py` içinde chunking adımında güvenli `step=max(1, size-overlap)` koruması mevcut.

### ✅ Çözülen Düşük Öncelikli / Teknik Borçlar
* **`agent/auto_handle.py`:** Çok adımlı regex kalıbına İngilizce bağlaçlar (`first`, `then`, `step`, vb.) eklendi.
* **`config.py`:** İçe aktarma anında çalışan dizin oluşturma komutları `__main__` koruması altına alınarak test ortamı izole edildi.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---