# AGENTS.md

Bu dosya, `/workspace/Sidar` deposunda çalışan ajanlar için operasyonel rehberdir.
Kapsam: Bu dosyanın bulunduğu dizin ve tüm alt dizinler.

## 1) Amaç ve kapsam

`AGENTS.md` iki farklı ama tamamlayıcı alanı dokümante eder:

1. **Repo içi çalışma ajanları (multi-agent mimarisi)**
   - Kod, araştırma, inceleme, QA ve coverage gibi rol bazlı ajanlar.
2. **Codex skill kullanımı (çalıştırma yardımcıları)**
   - `SKILL.md` tabanlı sistem skill’lerinin ne zaman ve nasıl uygulanacağı.

> Not: Önceki sürümlerde içerik ağırlıklı olarak skills tarafını anlatıyordu. Bu sürümde
> repo içi gerçek ajan mimarisi de eklenmiştir.

### 1.1 Geliştirme ortamı ve terminoloji standardı

Bu repo için tek doğruluk kaynağı olan operasyonel kabuller:

- **Ürün adı:** Güncel ürün adı **Sidar**'dır. Eski "Lotus" / "LotusAI" referansları yalnızca
  geriye dönük migrasyon (örn. legacy `DATABASE_URL` yakalama) için tutulur; yeni
  dokümantasyon, log mesajı veya kullanıcıya görünen çıktıda eski ad **kullanılmaz**.
- **Yerel coding model standardı:** Varsayılan ve önerilen yerel coding modeli
  `qwen2.5-coder:7b`'dir. `qwen2.5-coder:3b` yalnızca düşük donanım fallback'idir; yeni
  varsayılan değerler ve dokümantasyon `qwen2.5-coder:7b` üzerinden yazılmalıdır.
- **Paket/komut standardı:** Tüm Python bağımlılık ve komut yönetimi `uv` üzerinden yapılır.
  Kurulum `uv sync`, çalıştırma `uv run`, ek paket kurulumu `uv pip install` ile yürütülür;
  doğrudan `pip install` veya `python -m pip install` kullanılmamalıdır.
- **Dev bağımlılıkları:** `dev` extras varsayılan kurulum akışına dahildir. Geliştirici
  ortamı, CI ve ekip paritesi için tam kurulum komutu `uv sync --all-extras` olmalıdır;
  yalnız test araçları gerektiğinde `uv sync --extra dev` yeterlidir.

---

## 2) Repo içi ajan mimarisi

### 2.1 Yerleşik ajan rolleri

`agent/roles/__init__.py` içinde dışa açılan yerleşik roller:

- `CoderAgent`
- `ResearcherAgent`
- `ReviewerAgent`
- `PoyrazAgent`
- `QAAgent`
- `CoverageAgent`

> Kaynak doğrulama notu: Bu listedeki rollerin **tek doğruluk kaynağı**
> `agent/roles/__init__.py` ve dekoratör kayıtlarıdır.

### 2.2 AgentCatalog kayıt sistemi

Ajanlar çalışma zamanında `agent/registry.py` içindeki `AgentCatalog` ile yönetilir.

- Dekoratör tabanlı kayıt:
  - `@AgentCatalog.register(capabilities=[...], description=..., version=..., is_builtin=...)`
  - Yeni yerleşik roller için `is_builtin=True` açıkça verilmelidir; decorator
    varsayılanı `False` olduğu için bu alan unutulursa rol metadata'sı yerleşik
    olmayan ajan gibi oluşur.  
- Programatik kayıt:
  - `AgentCatalog.register_type(...)`
  - Programatik kayıt varsayılanı geriye dönük uyumluluk nedeniyle `is_builtin=True`
    değerini kullanır; harici/çalışma zamanı eklenti rollerinde `is_builtin=False`
    açıkça verilmelidir.
- Keşif/üretim:
  - `AgentCatalog.get(role_name)`
  - `AgentCatalog.find_by_capability(capability)`
  - `AgentCatalog.list_all()`
  - `AgentCatalog.create(role_name, **kwargs)`

Yerleşik roller, `agent/registry.py` içindeki `_import_builtin_roles()` ile import edilerek
otomatik kaydedilir.

> Operasyonel kural: Yeni bir rol eklendiğinde hem `agent/roles/__init__.py` hem de
> `_import_builtin_roles()` listesi birlikte güncellenmelidir.

### 2.3 Roller, iş tanımları ve yetki sınırları

Bu bölümdeki rol sözleşmeleri, ilgili ajan dosyalarındaki
`@AgentCatalog.register(capabilities=[...])`, `SYSTEM_PROMPT` ve kayıtlı araçlarla
tutarlı tutulmalıdır. Kısa capability listesi tek başına yeterli değildir; her rol için
iş tanımı, kullanabileceği araç/yetki alanı ve diğer ajanlarla beklenen etkileşim
aşağıda belirtilir.

#### 2.3.1 `coder` — `CoderAgent`

- **İş tanımı:** Kod üretimi, dosya okuma/yazma, terminal destekli düzeltme ve teknik
  tasarım uygulama işlerinden sorumludur.
- **Temel yetenekler:** `code_generation`, `file_io`, `shell_execution`, `code_review`.
- **Yetki sınırı:** Üretim kodu ve test dosyalarında değişiklik yapabilir; riskli veya
  kapsamı belirsiz değişikliklerde reviewer/QA geri bildirimi beklenir.
- **Etkileşim:** `researcher` bulgularını uygulamaya dönüştürür; çıktısı
  `reviewer -> qa` akışından geçmelidir. Coverage açığı varsa `coverage` tarafından
  önerilen deterministik testleri projeye uyarlar.

#### 2.3.2 `researcher` — `ResearcherAgent`

- **İş tanımı:** Web, URL ve RAG/doküman kaynaklarından doğrulanabilir bilgi toplar;
  bulguları özetleyerek kod, pazarlama veya inceleme ekiplerine aktarır.
- **Temel yetenekler:** `web_search`, `rag_search`, `summarization`.
- **Araç/yetki alanı:** `web_search`, `fetch_url`, `search_docs` ve `docs_search`
  araçlarıyla araştırma yapar. Kod yazma/değiştirme rolü değildir; kaynak, tarih,
  belirsizlik ve varsayımları açıkça belirtmelidir.
- **Etkileşim:** Teknik karar gerektiren araştırmalarda `coder` ve `reviewer` için
  kaynaklı bağlam üretir. Kampanya, SEO veya hedef kitle çalışmaları için ham
  araştırmayı `poyraz` ajanına devreder.

#### 2.3.3 `reviewer` — `ReviewerAgent`

- **İş tanımı:** Kod kalitesi, güvenlik, mimari tutarlılık ve değişiklik kapsamı
  açısından inceleme yapar.
- **Temel yetenekler:** `code_review`, `security_audit`, `quality_check`.
- **Yetki sınırı:** Üretim değişikliğini onaylama/geri çevirme niteliğinde bulgu
  üretir; doğrudan uygulama rolü değildir.
- **Etkileşim:** `coder` çıktısını inceler, `qa` ve `coverage` bulgularının üretim
  davranışını bozmadığını doğrular. Pazarlama çıktılarında marka/güvenlik riski
  kontrolü için `poyraz` sonrasında çalışabilir.

#### 2.3.4 `qa` — `QAAgent`

- **İş tanımı:** Test stratejisi, CI hatası analizi ve kalite kapısı iyileştirmelerinden
  sorumludur.
- **Temel yetenekler:** `test_generation`, `ci_remediation`.
- **Yetki sınırı:** Test kapsamını genişletir ve CI düzeltmeleri önerir; coverage
  hedefleri için `coverage` ajanından gelen hotspot/finding listesini kullanır.
- **Etkileşim:** `coder` değişikliklerinden sonra smoke/unit/integration doğrulamayı
  planlar; kalıcı başarısızlıkları `reviewer` ve `coder` geri bildirimine dönüştürür.

#### 2.3.5 `coverage` — `CoverageAgent`

- **İş tanımı:** Pytest ve coverage çıktısını analiz ederek eksik senaryoları, kaçan
  branch/line noktalarını ve test hotspotlarını belirler; %100 coverage hedefine
  yaklaşmak için deterministik pytest testleri üretir.
- **Temel yetenekler:** `coverage_analysis`, `pytest_output_analysis`,
  `autonomous_test_generation`.
- **Araç/yetki alanı:** `run_pytest`, `analyze_pytest_output`,
  `analyze_coverage_report`, `analyze_test_artifacts`, `generate_missing_tests` ve
  `write_missing_tests` araçlarını kullanır. Dış servis/ağ bağımlılığına dayalı test
  üretmemeli; ürettiği testler reviewer onayına sunulabilecek şekilde deterministik
  olmalıdır.
- **Etkileşim:** `qa` ile coverage açığı kapatma döngüsünde çalışır; `coder` üretim
  davranışını bozmadan eksik testleri entegre eder; `reviewer` üretilen testlerin
  değerini, kırılganlığını ve güvenliğini kontrol eder.

#### 2.3.6 `poyraz` — `PoyrazAgent`

- **İş tanımı:** Dijital pazarlama, SEO, kampanya metni, funnel optimizasyonu, hedef
  kitle operasyonları, sosyal medya yayınlama ve içerik varlığı üretimi için uzman
  ajandır.
- **Temel yetenekler:** `marketing_strategy`, `seo_analysis`, `campaign_copy`,
  `audience_ops`.
- **Araç/yetki alanı:** `web_search`, `fetch_url`, `search_docs`, sosyal yayın
  araçları (`publish_social`, `publish_instagram_post`, `publish_facebook_post`,
  `send_whatsapp_message`), kampanya/landing page araçları
  (`build_landing_page`, `generate_campaign_copy`, `create_marketing_campaign`,
  `store_content_asset`) ve operasyon planlama araçlarını kullanır. Harici yayınlama
  veya müşteri iletişimi etkisi olan adımlarda konfigürasyon, onay ve platform
  kısıtları dikkate alınmalıdır.
- **Etkileşim:** `researcher` tarafından doğrulanan pazar/SEO bulgularını kampanya
  çıktısına dönüştürür. Teknik landing page veya entegrasyon gerekiyorsa `coder` ile,
  marka/güvenlik/kalite kontrolü gerekiyorsa `reviewer` ile çalışır.

### 2.4 Önerilen temel iş akışları

- Kod geliştirme akışı:
  - `researcher` (gerekiyorsa bağlam) -> `coder -> reviewer -> qa`
  - Coverage açığı varsa `coverage -> coder -> reviewer -> qa` iyileştirme döngüsü
    uygulanır.
- Araştırma tabanlı üretim akışı:
  - `researcher -> coder/reviewer`
- Pazarlama operasyon akışı:
  - `researcher -> poyraz -> reviewer`
  - Teknik kampanya/landing page değişikliği gerekiyorsa akışa `coder` ve `qa` eklenir.

### 2.5 Otonom operasyonlar / Self-healing döngüsü

Self-healing akışı, lint/type-check/test/coverage hatalarını manuel kod müdahalesi olmadan
tespit edip düşük riskli düzeltmeleri sınırlı kapsamda uygulamak için tasarlanmıştır.
Bu mekanizma **kontrolsüz otomatik commit** anlamına gelmez; kapsam, doğrulama komutları,
retry limiti ve HITL (human-in-the-loop) güvenlik kapılarıyla çalışır.

#### 2.5.1 Tetikleyiciler ve giriş noktaları

- **Yerel kalite kapısı:** `run_tests.sh`, statik analizde önce `ruff check .`
  çalıştırır, ardından `mypy` çıktısını `artifacts/mypy_errors.log` dosyasına yazar.
  `AUTO_HEAL_ON_FAILURE=1` olduğunda mypy başarısızlığı için `scripts.auto_heal`
  döngüsünü tetikler.
- **Uzun otonom döngü:** `autonomous_loop.sh`, `github_upload.py -> ./run_tests.sh ->
  kalite kapısı` sırasını çalıştırır. Test çıkışı, coverage JSON okunamaması veya
  `AUTONOMOUS_LOOP_COVERAGE_TARGET` altında kalma durumunda iyileştirme döngüsüne girer.
- **CLI hızlı analiz:** `AutoHandle` içindeki `.heal <log_dosyası>` komutu logu okuyup
  `build_local_failure_context(...)` ve `build_ci_remediation_payload(...)` ile
  uygulanabilir scope/validation özeti üretir; bu yol patch uygulamaz, operatöre
  self-heal planının kapsamını gösterir.
- **Yerel self-heal köprüsü:** `scripts/auto_heal.py`, analiz logunu okuyarak
  `SidarAgent._attempt_autonomous_self_heal(...)` çağrısına bağlanır; batch, retry,
  model override ve HITL onay değerlerini CLI argümanlarıyla yönetir.

#### 2.5.2 Döngü adımları

1. **Tespit:** `ruff`, `mypy`, `pytest` ve coverage raporları hata/eksik kapsam
   sinyali üretir. Mypy logları `build_local_failure_context(...)` ile
   `suspected_targets`, `failure_summary`, `root_cause_hint` ve `log_excerpt` alanlarına
   dönüştürülür.
2. **Planlama:** `build_ci_remediation_payload(...)`, `remediation_loop` üretir. Bu
   loop; `scope_paths`, `validation_commands`, `bootstrap_commands`,
   `autonomous_batches`, `needs_human_approval`, `max_auto_attempts` ve adım
   durumlarını taşır.
3. **Kapsam daraltma:** `scripts/auto_heal.py`, hedef dosyaları batch'lere böler; her
   batch için sadece ilgili log satırlarını prompt'a ekler. `SidarAgent` tarafında
   `_resolve_self_heal_scope_batches(...)` ve `SELF_HEAL_AUTONOMOUS_BATCH_SIZE` aynı
   sınırlamayı runtime'da korur.
4. **Patch üretimi:** `SidarAgent._build_self_heal_plan(...)`, dosya snapshot'ları ve
   remediation loop ile LLM'den yalnızca JSON patch planı ister. Plan,
   `normalize_self_heal_plan(...)` ile scope dışı dosya, fazla operasyon ve geçersiz
   action açısından normalize edilir.
5. **Uygulama + doğrulama:** `_execute_self_heal_plan(...)`, patch öncesi dosya
   yedeği alır, `CodeManager.patch_file(...)` ile minimal patch uygular ve her
   `validation_commands` girdisini sandbox içinde çalıştırır. Doğrulama komutu yoksa
   işlem `blocked` olur.
6. **Rollback:** Patch veya sandbox doğrulaması başarısız olursa `_restore_self_heal_backups(...)`
   ile tüm değişiklikler geri alınır ve sonuç `reverted` olarak raporlanır.
7. **Tekrar:** `autonomous_loop.sh` en fazla `AUTONOMOUS_LOOP_REMEDIATION_RETRIES`
   denemesi yapar ve bu değer sonsuz döngü riskine karşı 2 ile sınırlandırılır.
   `scripts/auto_heal.py` tarafında `--batch-retries` her batch için ek plan/uygulama
   denemelerini yönetir.

#### 2.5.3 Onay, risk ve güvenlik sınırları

- `ENABLE_AUTONOMOUS_SELF_HEAL=False` ise runtime self-heal `disabled` döner ve patch
  uygulanmaz.
- `remediation_loop.status != "planned"` ise işlem `skipped` olur; plansız/eksik
  teşhisli döngüler otomatik patch'e geçemez.
- `needs_human_approval=True` olan riskli remediation planları onay yoksa
  `awaiting_hitl` durumunda bekler; `human_approval=False` verilirse `rejected` olur.
  Sadece açık `human_approval=True` veya CLI'da bilinçli `--hitl-approve yes` ile devam eder.
- Scope dışı dosya değişikliği yapılmamalıdır; patch planları `scope_paths` ile
  kısıtlanmalı ve `SELF_HEAL_MAX_PATCHES` üzerinde operasyon üretilmemelidir.
- `type: ignore` kullanımı son çare olmalı, çıplak `# type: ignore` yerine spesifik
  kodlu ve dar kapsamlı ignore tercih edilmelidir; `scripts/auto_heal.py` içindeki
  mypy quick-fix referansı bu kuralı prompt'a ekler.

#### 2.5.4 Coverage odaklı otonom iyileştirme

- `autonomous_loop.sh`, kalite kapısı sağlanmazsa `CoverageAgent` ile `coverage.xml`
  analizini çalıştırır, `scripts/coverage_hotspots.py` ile düşük coverage dosyalarını
  listeler ve gerekiyorsa eksik test önerisi üretir.
- Coverage kaynaklı test önerileri önce trivial assertion kontrolünden geçer
  (`assert True`, boş test vb.). Ardından `ReviewerAgent` semantik onayı alınmadan
  öneri uygulanabilir kabul edilmez.
- `CoverageAgent` deterministik pytest üretmelidir; ağ/dış servis bağımlılığı içeren
  testler reviewer/QA aşamasında reddedilmelidir.

#### 2.5.5 Operasyonel kullanım örnekleri

- Log kapsamını görmek için: `.heal artifacts/mypy_errors.log`
- Lokal mypy self-heal çalıştırmak için:
  `uv run python -m scripts.auto_heal --log artifacts/mypy_errors.log --source mypy`
- Otonom upload/test/iyileştirme döngüsünü çalıştırmak için: `./autonomous_loop.sh`

### 2.6 Swarm, Supervisor ve event-driven koordinasyon

Sidar ajanları yalnızca doğrusal `coder -> reviewer -> qa` pipeline'ı olarak çalışmaz.
Kod tabanında iki tamamlayıcı koordinasyon modeli bulunur: `Supervisor`, tek görev için
merkezi router/quality gate rolü üstlenir; `SwarmOrchestrator`, çoklu görevi intent ve
capability eşleşmesine göre paralel, pipeline veya P2P handoff ile dağıtır.

#### 2.6.1 Supervisor kontrol düzlemi

- **Görev analizi ve yönlendirme:** `agent/core/supervisor.py`, gelen prompt için intent
  belirler; research/review/marketing/coverage işleri doğrudan ilgili role, varsayılan
  kod işleri ise önce `coder` sonra `reviewer` kalite kapısına gider.
- **Aktif ajan ve bellek:** `ActiveAgentRegistry` runtime ajan örneklerini role göre
  tutar; `MemoryHub` global notları ve role özel notları paylaşarak sonraki
  delegasyonlara bağlam sağlar.
- **Event yayını:** Supervisor her önemli durumda `AgentEventBus.publish(...)` ile
  `supervisor` kaynaklı olay üretir (örn. “Researcher ajanına yönlendiriliyor...”,
  “Reviewer kontrolü tekrar çalıştırılıyor...”). UI/CLI veya dış gözlemciler bu olayları
  subscribe ederek akışı izler.
- **P2P handoff:** Ajan çıktısı `DelegationRequest` / `P2PMessage` biçimindeyse
  `_route_p2p(...)` hedef ajana doğrudan görev zarfı gönderir. `MAX_TURNS`,
  `MAX_QA_RETRIES` ve `REACT_TIMEOUT` circuit breaker değerleri loop/sonsuz devir
  riskini sınırlar.

#### 2.6.2 Swarm orkestrasyonu

- **Task modeli:** `SwarmTask` tekil hedefi, intent'i, context'i, task id'yi ve isteğe
  bağlı `preferred_agent` değerini taşır; `SwarmResult` sonuç, evidence, handoff
  zinciri ve graph/trace bilgisini döndürür.
- **Router:** `TaskRouter`, intent'i capability'ye çevirir ve `AgentCatalog` üzerinden
  uygun role ajanı seçer. Bu nedenle yeni ajan eklenirken capability kaydı doğruysa
  swarm tarafı role'ü otomatik keşfedebilir.
- **Yürütme modları:**
  - `run(...)`: tek görevi otomatik role seçimiyle çalıştırır.
  - `run_parallel(...)`: birden fazla `SwarmTask` için `asyncio.Semaphore` ile
    `max_concurrency` sınırı uygulayarak paralel yürütür.
  - `run_pipeline(...)`: görevleri sırayla yürütür ve başarılı özetleri sonraki görevin
    context'ine `prev_<role>` anahtarıyla taşır.
- **P2P / recursive handoff:** Bir ajan `DelegationRequest` döndürürse `_direct_handoff(...)`
  yeni hedef role'e geçer; `SWARM_MAX_HANDOFF_HOPS`, `SWARM_LOOP_GUARD_MAX_REPEAT`,
  `SWARM_TASK_MAX_RETRIES` ve `SWARM_TASK_RETRY_DELAY_MS` ayarları tekrar/başarısızlık
  kontrolünü sağlar.
- **Dağıtık delegasyon:** `dispatch_distributed(...)`, `TaskEnvelope`'ı
  `BrokerTaskEnvelope` biçimine çevirip enjekte edilen `AsyncDelegationBackend` üzerinden
  broker/backplane'e gönderir. Varsayılan `InMemoryDelegationBackend` test/prototip
  içindir; gerçek Kafka/Rabbit/Redis iş kuyruğu entegrasyonları bu kontrata uymalıdır.

#### 2.6.3 Event bus ve backend stratejileri

- **Yerel fanout + uzak transport:** `AgentEventBus.publish(...)` olayı önce process içi
  subscriber kuyruklarına dağıtır, ardından seçili remote backend'e yayınlamayı dener.
  Remote backend başarısızsa local fallback korunur; Redis/Kafka için circuit breaker
  ardışık hatalarda remote yayını geçici olarak durdurur.
- **Backend seçimi:** `SIDAR_EVENT_BUS_BACKEND` `redis` (varsayılan), `rabbitmq` veya
  `kafka` olabilir. Strategy sınıfları `agent/core/event_backends/` altında yer alır:
  `RedisBackend`, `RabbitMQBackend`, `KafkaBackend`. Bu sınıflar ortak
  `BaseEventBusBackend.schedule_bootstrap()` ve `publish(evt)` kontratını uygular.
- **Redis:** `REDIS_URL`, `SIDAR_EVENT_BUS_CHANNEL`, `SIDAR_EVENT_BUS_GROUP` ve Redis
  timeout/max connection ayarlarıyla Redis Streams consumer group kullanır.
- **RabbitMQ:** `RABBITMQ_URL` ile `aio_pika` üzerinden durable queue publish/consume
  yapar. Paket veya broker yoksa debug log ile local fallback'e düşer.
- **Kafka:** `KAFKA_BOOTSTRAP_SERVERS`, `SIDAR_EVENT_BUS_KAFKA_TOPIC` ve
  `SIDAR_EVENT_BUS_KAFKA_GROUP` ile `aiokafka` producer/consumer kullanır. Paket veya
  broker yoksa local fallback korunur.
- **DLQ ve dayanıklılık:** Uzak publish/consume sırasında teslim edilemeyen veya parse
  edilemeyen olaylar DLQ kanalına ve process içi `dlq_buffer`'a alınabilir;
  `SIDAR_EVENT_BUS_DLQ_CHANNEL`, `SIDAR_EVENT_BUS_DLQ_MAXLEN` ve opsiyonel
  `SIDAR_EVENT_BUS_DLQ_PERSIST_PATH` ile kalıcılık yönetilir.

#### 2.6.4 Operasyonel kurallar

- Linear pipeline, supervisor ve swarm kavramları karıştırılmamalıdır: pipeline sıralı
  kalite akışıdır; supervisor merkezi yönlendirme ve P2P kontrolüdür; swarm ise çoklu
  görevi paralel/pipeline/dağıtık biçimde koordine eder.
- Yeni role/capability eklendiğinde `AgentCatalog` metadata'sı, `TaskRouter` intent
  eşleşmesi ve gerekirse supervisor intent yönlendirmesi birlikte güncellenmelidir.
- Event backend seçimi ortam değişkeniyle yapılmalı; broker erişilemediğinde sistemin
  local fallback ile çalışacağı, fakat cross-process gözlemlenebilirlik/koordinasyonun
  sınırlanacağı bilinmelidir.
- P2P/swarm handoff üreten ajanlar `reply_to`, `target_agent`, `payload`, `intent` ve
  `parent_task_id` alanlarını eksiksiz doldurmalı; circuit breaker limitlerini aşan
  döngüler fail-closed sonlanmalıdır.

---

## 3) Codex skills rehberi

Bu oturumdaki gerçek kullanılabilir skill listesi, çalışma zamanı tarafından sağlanan
`Available skills` bölümüdür. `AGENTS.md`, skill envanterinin tek doğruluk kaynağı
değildir; yalnızca `/workspace/Sidar` deposuna özel skill kullanım kurallarını,
tetikleme koşullarını ve bağlam hijyeni beklentilerini açıklar.

> Operasyonel kural: Belirli bir skill adı, yolu veya amacı dokümante edilecekse
> bilginin hızla bayatlayabileceği unutulmamalı; güncel kullanılabilirlik için her
> zaman oturumdaki `Available skills` çıktısı esas alınmalıdır.

### 3.1 Skill tetikleme kuralları

- Kullanıcı skill adını açıkça verirse (`$SkillName` veya düz metin) skill kullanılmalıdır.
- Kullanıcı isteği bir skill tanımıyla net eşleşiyorsa skill kullanılmalıdır.
- Birden fazla skill gerekiyorsa minimum gerekli set seçilmeli ve sıra belirtilmelidir.
- Skill bu turda tekrar anılmadıysa bir sonraki tura taşınmamalıdır.

### 3.2 Skill kullanım yöntemi (progressive disclosure)

1. İlgili `SKILL.md` dosyasını aç ve yalnızca gerekli kısmı oku.
2. Relative path’leri önce skill dizinine göre çöz.
3. `references/` gibi ek klasörlerden sadece gereken dosyaları yükle.
4. `scripts/` varsa uzun çıktıyı elle yazmak yerine script’i kullan.
5. `assets/templates` varsa yeniden üretmek yerine tekrar kullan.

### 3.3 Koordinasyon, bağlam hijyeni ve fallback

- Uzun metinleri kopyalamak yerine özetle; bağlamı küçük tut.
- Gereksiz derin referans zinciri açma.
- Skill uygulanamazsa sorunu kısa belirt ve en iyi alternatif yaklaşımı uygula.

---

## 4) Yeni ajan ekleme kısa rehberi

1. `agent/roles/` altında yeni ajan sınıfını oluştur.
2. `@AgentCatalog.register(...)` dekoratörüyle role/capability metadata’sını tanımla.
3. `agent/roles/__init__.py` içinde dışa aktar.
4. `agent/registry.py::_import_builtin_roles()` listesine yeni modülü ekle.
5. Ajanın rol adı, capability seti ve kullanım amacını dokümante et.
6. Testler ve entegrasyon kontrolleriyle kaydın çalıştığını doğrula (`AgentCatalog.list_all()` vb.).

Örnek şablon:

```python
from agent.base_agent import BaseAgent
from agent.registry import AgentCatalog

@AgentCatalog.register(
    capabilities=["example_capability"],
    description="Örnek uzman ajan",
    version="1.0.0",
    is_builtin=True,
)
class ExampleAgent(BaseAgent):
    ROLE_NAME = "example"
```

---

## 5) Doküman bakım notları

- Bu dosya **ajan + skill** kapsamını birlikte taşır; içerik adıyla uyumludur.
- Skill kullanılabilirliği için statik liste tutulmaz; güncel envanter çalışma zamanı `Available skills` çıktısından doğrulanmalıdır.
- Yeni role/capability eklendiğinde bu dosyanın 2. bölümünü güncelleyin.

### 5.1 Hızlı doğrulama checklist’i

Ön koşul: Aşağıdaki çalışma zamanı doğrulamaları **bağımlılıkları kurulmuş** bir ortamda
çalıştırılmalıdır. Temiz/çıplak repo checkout ortamında `python-dotenv`,
`pydantic-settings` vb. proje bağımlılıkları henüz yoksa `agent.registry`, yerleşik rol
modüllerini import ederken başarısız olabilir ve `AgentCatalog.list_all()` boş liste
döndürebilir. Bu durumda önce bağımlılıkları `uv` ile kurun:

- `uv sync --all-extras` — geliştirme/test/CI paritesi için önerilen tam kurulum.
- Yalnız test/tooling araçları yeterliyse `uv sync --extra dev` kullanılabilir.

Doğrulama komutları `python ...` yerine `uv run python ...` ile çalıştırılmalıdır;
böylece komutlar uv ortamından bağımsız bir global Python yorumlayıcısına düşmez.

Doğrulama adımları:

**1. Hızlı görünürlük/smoke kontrolü**

Aşağıdaki komut kullanılabilir; ancak yalnızca mevcut role adlarını basar ve tek
başına yeterli kabul edilmemelidir:

```bash
uv run python -c "from agent.registry import AgentCatalog; print([s.role_name for s in AgentCatalog.list_all()])"
```

Çıktı `[]` ise öncelikle bağımlılık kurulumunu ve import uyarılarını kontrol edin.

**2. Fail-fast yerleşik rol doğrulaması**

Yerleşik rollerin eksiksiz yüklendiğini doğrulamak için aşağıdaki komut
çalıştırılmalıdır. Bu komut, boş liste veya eksik role durumlarını sessiz geçmez:

```bash
uv run python - <<'PY'
from agent.registry import AgentCatalog

expected = {"coder", "researcher", "reviewer", "poyraz", "qa", "coverage"}
actual = {s.role_name for s in AgentCatalog.list_all()}
missing = expected - actual

if missing:
    raise SystemExit(f"Eksik built-in roller: {sorted(missing)}; actual={sorted(actual)}")

print("OK", sorted(actual))
PY
```

**3. Capability doğrulaması**

Capability listesinin dokümanla ve ajan dekoratörleriyle eşleştiğini doğrulamak
için aşağıdaki komut çalıştırılmalıdır:

```bash
uv run python - <<'PY'
from agent.registry import AgentCatalog

expected = {
    "coder": {"code_generation", "file_io", "shell_execution", "code_review"},
    "researcher": {"web_search", "rag_search", "summarization"},
    "reviewer": {"code_review", "security_audit", "quality_check"},
    "qa": {"test_generation", "ci_remediation"},
    "coverage": {
        "coverage_analysis",
        "pytest_output_analysis",
        "autonomous_test_generation",
    },
    "poyraz": {"marketing_strategy", "seo_analysis", "campaign_copy", "audience_ops"},
}

actual = {s.role_name: set(s.capabilities) for s in AgentCatalog.list_all()}

for role, capabilities in expected.items():
    if role not in actual:
        raise SystemExit(f"Eksik rol: {role}")
    if actual[role] != capabilities:
        raise SystemExit(
            f"Capability mismatch for {role}: "
            f"expected={sorted(capabilities)} actual={sorted(actual[role])}"
        )

print("OK")
PY
```

**4. Statik tutarlılık kontrolleri**

- `agent/roles/__init__.py` içindeki dışa açılan roller ile
  `agent/registry.py::_import_builtin_roles()` listesi tutarlı olmalıdır.
- `AGENTS.md` içindeki capability listeleri, ilgili ajan dosyalarındaki
  `@AgentCatalog.register(capabilities=[...])` ile eşleşmelidir.

### 5.2 Ayrıştırma (SoC) yol haritası

- Doküman boyutu büyüdüğünde `Codex skills` kurallarını ayrı bir `SKILLS.md` dosyasına taşıyın.
- `AGENTS.md` dosyasını repo içi multi-agent mimari ve operasyonel standartlara odaklı tutun.
