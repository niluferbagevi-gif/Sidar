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

#### 2.1.1 Kaynak dosya haritası ve senkronizasyon kuralı

Bu rehber mimari davranışın operasyonel özetidir; aşağıdaki kaynak dosyalarla birlikte
senkron tutulmalıdır:

- **Yerleşik roller ve capability kayıtları**: `agent/roles/__init__.py`,
  `agent/registry.py`, `agent/roles/*_agent.py`
- **Rol iş tanımları ve araç sınırları**: `agent/roles/coder_agent.py`,
  `agent/roles/researcher_agent.py`, `agent/roles/reviewer_agent.py`,
  `agent/roles/qa_agent.py`, `agent/roles/coverage_agent.py`,
  `agent/roles/poyraz_agent.py`
- **Supervisor/Swarm koordinasyonu**: `agent/core/supervisor.py`, `agent/swarm.py`,
  `agent/core/event_stream.py`, `agent/core/event_backends/`
- **Self-healing ve otonom döngüler**: `agent/auto_handle.py`, `scripts/auto_heal.py`,
  `autonomous_loop.sh`
- **Geliştirme ortamı/model standardı**: `README.md`, `install_sidar.sh`,
  `pyproject.toml`, `config.py`, `.env.example`
- **Multimodal/vision/voice yetenekleri**: `core/multimodal.py`, `core/vision.py`,
  `core/voice.py`, `managers/browser_manager.py`

Senkronizasyon kuralı: Bir ajanın `SYSTEM_PROMPT`, class/module docstring'i,
`@AgentCatalog.register(...)` capability listesi, kayıtlı tool seti, `run_task` akışı,
supervisor/swarm routing'i veya multimodal/self-heal davranışı değişirse aynı PR içinde
`AGENTS.md` de güncellenmelidir. Docstring'ler kısa özet olarak kalabilir; ancak bu
rehberdeki rol sınırları, onay kuralları ve güvenlik beklentileriyle çelişmemelidir.

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

### 2.3 Roller ve temel yetenekler

- **coder** (`CoderAgent`):
  - `code_generation`, `file_io`, `shell_execution`, `code_review`
- **researcher** (`ResearcherAgent`):
  - `web_search`, `rag_search`, `summarization`
- **reviewer** (`ReviewerAgent`):
  - `code_review`, `security_audit`, `quality_check`
- **qa** (`QAAgent`):
  - `test_generation`, `ci_remediation`
- **coverage** (`CoverageAgent`):
  - `coverage_analysis`, `pytest_output_analysis`, `autonomous_test_generation`
- **poyraz** (`PoyrazAgent`):
  - `marketing_strategy`, `seo_analysis`, `campaign_copy`, `audience_ops`

### 2.4 Rol sorumlulukları, araç sınırları ve devir kuralları

Bu bölüm, kısa capability listesini operasyonel görev paylaşımıyla tamamlar.
Capability listelerinin doğruluk kaynağı ajan dekoratörleri; görev sınırlarının doğruluk
kaynağı ise ilgili ajanın `SYSTEM_PROMPT`, kayıtlı araçları ve `run_task` akışıdır.

- **coder**:
  - Kod yazma/değiştirme, dosya okuma-yazma, patch uygulama, güvenli shell/test
    çalıştırma ve hedefli paket/proje inceleme işlerini üstlenir.
  - İnceleme veya kalite kapısı gerektiğinde `request_review|...` ile `reviewer` ajanına
    P2P devir isteği oluşturabilir.
  - QA/reviewer reddi geldiğinde `qa_feedback|...` girdisini rework sinyali olarak ele
    almalı; başarısız test özetini ve remediation notlarını düzeltme planına katmalıdır.
- **researcher**:
  - Kod değiştirmez; web, URL ve RAG/doküman aramasıyla doğrulanabilir araştırma
    çıktısı üretir.
  - Kaynak toplama, teknik/ürün araştırması, doküman karşılaştırması ve pazarlama
    girdisi hazırlama işleri `researcher` ajanına devredilmelidir.
  - Araştırma çıktısı kod değişikliğine dönüşecekse `coder`/`reviewer`; pazarlama
    çıktısına dönüşecekse `poyraz` devam etmelidir.
- **reviewer**:
  - Kod kalitesi, güvenlik, regresyon riski, semantik etki ve test yeterliliği kalite
    kapısıdır.
  - Yüksek riskli kod/test değişikliklerinde nihai uygulama öncesi reviewer kontrolü
    beklenir; reddedilen değişiklikler `qa_feedback|decision=reject...` biçimiyle
    `coder` ajanına geri döndürülebilir.
  - Coverage ajanının ürettiği yeni test önerileri özellikle kırılganlık, dış servis
    bağımlılığı ve yanlış assertion riski açısından reviewer tarafından incelenmelidir.
- **qa**:
  - Test üretimi, CI/remediation ve başarısız test çıktılarının sınıflandırılması için
    kullanılır.
  - QA çıktısı düzeltme gerektiriyorsa supervisor/P2P akışında `coder` ajanına rework
    döngüsü başlatır; tekrar sayısı `MAX_QA_RETRIES` sınırına tabidir.
- **coverage**:
  - Pytest ve coverage artefaktlarını okuyarak coverage gap, eksik branch/senaryo ve
    düşük kapsama bulgularını tespit eder.
  - Deterministik, ağ erişimsiz pytest testleri önerir/üretir; üretilen testlerin
    onay durumu varsayılan olarak `pending_reviewer_or_human` kabul edilmelidir.
  - Coverage odaklı işler doğrudan `coverage` ajanına; coverage ajanı yoksa geriye
    dönük uyumluluk için `qa` ajanına yönlendirilir.
- **poyraz**:
  - Pazarlama stratejisi, SEO, kampanya mesajı, funnel optimizasyonu, landing page,
    sosyal yayınlama ve audience operation çıktılarından sorumludur.
  - Kaynak gerektiren pazarlama işlerinde önce `researcher` bulguları alınmalı; Poyraz
    bu bulguları uygulanabilir kampanya/operasyon çıktısına çevirmelidir.
  - Kod veya güvenlik etkisi olan pazarlama otomasyonları `coder`/`reviewer` kalite
    kapısından geçmelidir.

### 2.5 Supervisor ve P2P etkileşim kuralları

- Supervisor, görev niyetine göre `researcher`, `reviewer`, `poyraz`, `coverage`/`qa`
  veya varsayılan `coder` yönlendirmesini yapar.
- Uzman ajanlar `DelegationRequest` ile P2P devir isteği oluşturabilir; isteklerde
  `reply_to`, `target_agent` ve `payload` alanları boş olmamalıdır.
- P2P döngüleri `MAX_TURNS`, QA rework döngüleri `MAX_QA_RETRIES` ile sınırlandırılır;
  sınır aşımı circuit-breaker olarak ele alınmalıdır.
- Normal kod geliştirme kalite kapısı: `coder -> reviewer -> qa/rework` akışıdır.
  Coverage iyileştirmeleri bu akışa `coverage -> reviewer/QA -> coder` döngüsüyle
  bağlanır.
- `CLI_FAST_MODE` açıkken reviewer kalite kapısı atlanabilir; bu mod yalnızca hızlı CLI
  geri bildirimi için kullanılmalı, kalıcı/riski yüksek değişikliklerde kapatılmalıdır.

### 2.6 Koordinasyon mimarisi: Supervisor, Swarm ve event bus

Sidar'da koordinasyon iki tamamlayıcı katmanda ele alınır: supervisor merkezli
niyet yönlendirme ve swarm tabanlı çoklu ajan orkestrasyonu. Bu bölüm, role
capability listesinin ötesindeki çalışma zamanı mimarisini özetler.

- **SupervisorAgent (`agent/core/supervisor.py`)**:
  - `researcher`, `coder`, `reviewer`, `poyraz`, `qa` ve mümkünse `coverage`
    ajanlarını aktif registry'ye kaydeder; `coverage` kurulamazsa geriye dönük
    uyumluluk için `qa` fallback'i kullanılır.
  - Görev niyetini `research`, `review`, `marketing`, `coverage` veya varsayılan
    `code` olarak sınıflandırır ve ilgili ajana yönlendirir.
  - Kod geliştirme akışında önce `coder`, ardından `reviewer` kalite/test kapısı
    çalışır; revizyon sinyali varsa `coder` rework döngüsüne alınır.
  - P2P isteklerinde `DelegationRequest` doğrulanır; `MAX_TURNS` ve
    `MAX_QA_RETRIES` circuit-breaker sınırları sonsuz delegasyon/retry döngülerini
    engellemek için kullanılır.
- **SwarmOrchestrator (`agent/swarm.py`)**:
  - Dinamik çoklu ajan orkestrasyon motorudur; görevi intent/role bilgisine göre
    route eder, tek görev çalıştırma (`run`), paralel çalışma (`run_parallel`) ve
    sıralı pipeline (`run_pipeline`) modlarını destekler.
  - Paralel modda `max_concurrency` semaforu ile eşzamanlılık sınırlandırılır; pipeline
    modunda başarılı adımların özetleri sonraki görevin context'ine aktarılır.
  - Ajan çıktısı `DelegationRequest` ise swarm bunu hedef role yeni görev olarak
    yönlendirebilir ve handoff zinciri/derinliğiyle döngü riskini izler.
  - Dağıtık delegasyon için `configure_delegation_backend(...)` ile broker backend'i
    enjekte edilir; `dispatch_distributed(...)` görev zarfını `TaskEnvelope` ve
    `BrokerTaskEnvelope` formatına çevirip backend'e dispatch eder.
- **Event bus ve transport backend'leri (`agent/core/event_stream.py`)**:
  - `AgentEventBus`, ajan durum mesajlarını önce process-içi subscriber'lara fanout
    eder; yapılandırılmış remote backend uygunsa aynı event'i remote transport'a da
    yayınlar.
  - Backend stratejileri `redis`, `rabbitmq` ve `kafka` olarak yüklenebilir; ilgili
    sınıflar `agent/core/event_backends/` altında tutulur.
  - Remote publish başarısızlıklarında local fallback, dead-letter kaydı ve
    Redis/Kafka için remote circuit-breaker mantığı devrededir.
- **Kullanım ve bakım kuralları**:
  - Yeni ajan eklenirken yalnızca `agent/roles/` ve `AgentCatalog` kaydı değil,
    supervisor intent routing, swarm route/capability eşlemesi, P2P payload sözleşmesi
    ve event görünürlüğü de değerlendirilmelidir.
  - Cross-agent workflow eklenirse beklenen akış `AGENTS.md` içinde belgelenmeli ve
    mümkünse supervisor/swarm için smoke test veya statik tutarlılık kontrolü
    eklenmelidir.
  - Dağıtık delegasyon backend'i kullanılacaksa broker zarfı, correlation id, retry
    davranışı ve remote fallback stratejisi operasyonel runbook'ta açıkça belirtilmelidir.

### 2.7 Self-healing ve otonom remediation döngüsü

Self-healing, yerel kalite kapısı çıktısını veya CI/test/coverage başarısızlığını
yapılandırılmış remediation planına çeviren kontrollü bir iyileştirme döngüsüdür.
Bu mekanizma otomatik analiz ve düzeltme önerisi/uygulaması yapabilir; ancak
**tamamen onaysız** kabul edilmemelidir. Riskli planlarda HITL (human-in-the-loop)
onayı istenebilir ve CI/otonom kullanımda onay açık bir opt-in ile verilmelidir.

- **CLI kısa yolu (`.heal <log_dosyası>`)**:
  - `agent/auto_handle.py`, `.heal` komutunu yakalar, log dosyasını okur,
    `build_local_failure_context(...)` ve `build_ci_remediation_payload(...)` ile
    yerel self-heal analiz özeti üretir.
  - Bu kısa yol plan/kapsam/doğrulama bilgisini kullanıcıya gösterir; doğrudan
    patch uygulayan ana mekanizma değildir.
- **Yerel self-heal köprüsü (`scripts/auto_heal.py`)**:
  - Statik analiz logunu okur, local failure context ve remediation payload oluşturur,
    `ENABLE_AUTONOMOUS_SELF_HEAL=True` ile `SidarAgent` üzerinden autonomous
    self-heal denemesi başlatır.
  - `--batch-size` ile scope queue dosya gruplarına bölünür; `--batch-retries` ile
    her batch için ek deneme yapılabilir.
  - Çıktı statüleri `applied`, `partial` veya `failed` olabilir; `partial` başarılı
    batch olduğunu ama tüm kapsamın kapanmadığını belirtir.
  - Riskli planlarda `--hitl-approve` verilmezse etkileşimli insan onayı sorulabilir.
    CI/otonom döngülerde `--hitl-approve yes` yalnızca bilinçli opt-in olarak kullanılmalıdır.
- **Otonom kalite döngüsü (`autonomous_loop.sh`)**:
  - `github_upload.py`, `run_tests.sh`, coverage metriği ve remediation adımlarını
    döngüsel olarak çalıştırır.
  - Varsayılan otonom coverage hedefi `%100` olup `AUTONOMOUS_LOOP_COVERAGE_TARGET`
    ile değiştirilebilir; metrik varsayılan olarak `coverage.json` içinden okunur.
  - Test başarısızlığı, coverage metriğinin okunamaması veya coverage hedefinin
    tutmaması durumunda `CoverageAgent`, `scripts/coverage_hotspots.py` ve uygun
    mypy logu varsa `scripts/auto_heal.py` devreye girer.
  - Retry sayısı `AUTONOMOUS_LOOP_REMEDIATION_RETRIES` ile ayarlanır ve sonsuz döngü
    riskini azaltmak için üst sınır uygulanır.
- **Güvenlik ve kalite sınırları**:
  - Self-heal patch'leri minimal scope ile üretilmeli; geniş kapsamlı refactor veya
    güvenlik etkisi olan değişiklikler reviewer/QA kalite kapısından geçmelidir.
  - Coverage ajanının ürettiği testler trivial assertion, dış servis bağımlılığı ve
    deterministik olmayan davranış açısından reviewer onayı olmadan kalıcı kabul
    edilmemelidir.
  - Otonom döngü başarısız olursa çıktılar remediation raporu olarak ele alınmalı;
    manuel inceleme, reviewer ve QA geri bildirimiyle devam edilmelidir.

### 2.8 Geliştirme ortamı, model standardı ve terminoloji

Repo içi ajan ve Codex çalıştırma ortamlarında aşağıdaki operasyon standartları
esas alınmalıdır:

- **Paket yöneticisi / çalışma ortamı**:
  - Birincil geliştirme standardı `uv sync --all-extras` ile tam ortam senkronizasyonudur;
    komutlar mümkünse `uv run ...` ile çalıştırılmalıdır.
  - `python -m pip install -e ".[dev]"` yalnızca minimum/alternatif test-tooling
    kurulumu olarak kullanılmalıdır; repo paritesi için `uv sync --all-extras` önceliklidir.
  - `pyproject.toml` temel bağımlılık listesi pytest, ruff, mypy, bandit, safety gibi
    geliştirme/test araçlarını standart kurulum akışına dahil eder; bu nedenle temiz
    checkout doğrulamalarında eksik tooling görülürse önce ortam senkronizasyonu kontrol
    edilmelidir.
- **Yerel kod modeli standardı**:
  - Kodlama ve remediation odaklı ajanlar için varsayılan yerel kod modeli standardı
    `qwen2.5-coder:7b` kabul edilir.
  - Farklı donanım veya sağlayıcı gereksinimlerinde model `CODING_MODEL` env/config
    değeriyle override edilebilir; düşük VRAM ortamlarında daha küçük Qwen Coder varyantı
    bilinçli tercih olarak kullanılabilir.
  - Model değişikliği yapılırsa reviewer/QA/self-heal çıktılarında deterministiklik,
    patch kalitesi ve test üretimi yeniden smoke doğrulamasından geçirilmelidir.
- **Terminoloji ve eski isimlendirme**:
  - Dokümantasyon, script ve config dosyalarında ürün/ajan sistemi adı olarak `Sidar`
    kullanılmalıdır.
  - Eski ürün adı veya dış proje kalıntısı olabilecek terminoloji yeni içerikte
    kullanılmamalı; böyle bir kalıntı bulunursa ilgili dosyada Sidar terminolojisine
    taşınmalıdır.

### 2.9 Multimodal ve ses operasyon kuralları

Sidar, medya girdilerini doğrudan ajan prompt'una serbest biçimde eklemek yerine önce
normalize edilmiş, kaynaklanabilir ve güvenlik sınırları belli bir bağlama dönüştürmelidir.

- **Medya türü tespiti ve normalizasyon**:
  - Görsel, ses ve video girdilerinde ilk ayrım `core/multimodal.py::detect_media_kind(...)`
    ile MIME tipi veya dosya yolu üzerinden yapılmalıdır.
  - Desteklenen medya girdileri önce `MultimodalPipeline` üzerinden ortak LLM bağlamına
    çevrilmeli; büyük/uzak medya kaynaklarında boyut, süre ve timeout limitleri
    uygulanmalıdır.
  - `ENABLE_MULTIMODAL=False` ise ajanlar medya içeriğini varsaymamalı; kullanıcıya
    multimodal katmanın devre dışı olduğunu açık reason ile bildirmelidir.
- **Görsel / screenshot akışı**:
  - Görseller `core/vision.py::VisionPipeline` ile `image_path` veya `image_bytes`
    girdisinden analiz edilmelidir; desteklenmeyen MIME tipleri reddedilmelidir.
  - Frontend, browser veya görsel QA işlerinde screenshot sinyalleri tek başına nihai
    karar sayılmamalı; browser/screenshot drift özeti reviewer/QA akışına context olarak
    bağlanmalıdır.
  - Görselden kod üretimi veya UI değişikliği yapılacaksa `coder -> reviewer -> qa`
    kalite kapısı korunmalı; screenshot tabanlı bulgular regresyon testiyle
    doğrulanmalıdır.
- **Ses / STT / voice akışı**:
  - Ses girdileri mümkünse `WebRTCAudioIngress` ile MIME, boyut, sıra ve oturum bilgisi
    doğrulanarak normalize edilmelidir.
  - STT için MVP sağlayıcı `whisper` kabul edilir; Whisper CLI yoksa sistem açık reason
    ile başarısız dönmeli ve transkript varmış gibi işlem yapılmamalıdır.
  - Sesli komutlar transkript belirsizliği taşıdığı için dosya silme, patch uygulama,
    deployment, credential/secret işlemleri ve dış servis yayınlama gibi destructive
    veya geri dönüşü zor aksiyonlarda açık kullanıcı onayı gerektirir.
  - `core/voice.py::VoicePipeline`, WebSocket voice/TTS segmentleme ve enable flag
    kontrollerinden sorumludur; `ENABLE_MULTIMODAL` veya `VOICE_ENABLED` kapalıysa
    sesli yanıt üretimi zorlanmamalıdır.
- **Video akışı ve birleşik bağlam**:
  - Video girdilerinde mümkünse audio track çıkarılıp Whisper transkripsiyonu yapılmalı,
    seçili frame'ler `VisionPipeline` ile analiz edilmeli ve transcript + frame özetleri
    birleşik multimodal context olarak kullanılmalıdır.
  - Video veya sosyal medya insight çıktıları pazarlama amacı taşıyorsa `poyraz`; ürün/UI
    doğrulama amacı taşıyorsa `reviewer`/`qa`; kod değişikliği gerektiriyorsa `coder`
    devam etmelidir.
- **Güvenlik ve veri hassasiyeti**:
  - Medya dosyaları kişisel veri, yüz/ses izi, ekran görüntüsü, token veya müşteri verisi
    içerebilir; ajanlar gereksiz ham medya kopyalamamalı, özet/context paylaşımını
    minimum gerekli kapsamda tutmalıdır.
  - Transkript, OCR veya görsel analiz belirsizliği yüksekse ajan sonucu “kanıt” değil
    “sinyal” olarak etiketlemeli ve reviewer/QA/human confirmation istemelidir.

### 2.10 Önerilen temel iş akışları

- Kod geliştirme akışı:
  - `coder -> reviewer -> qa` (gerekirse `coverage` ile iyileştirme döngüsü)
- Araştırma tabanlı üretim akışı:
  - `researcher -> coder/reviewer`
- Pazarlama operasyon akışı:
  - `researcher -> poyraz -> reviewer`

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
5. Supervisor intent routing, swarm route/capability eşlemesi, P2P payload sözleşmesi ve
   event görünürlüğü etkilerini değerlendir.
6. Ajan medya girdisi tüketecekse multimodal/vision/voice enable flag'leri, MIME sınırları,
   onay gerektiren destructive sesli komutlar ve reviewer/QA doğrulama akışını tanımla.
7. Ajanın rol adı, capability seti, kullanım amacı ve koordinasyon/multimodal etkilerini dokümante et.
8. Testler ve entegrasyon kontrolleriyle kaydın çalıştığını doğrula (`AgentCatalog.list_all()` vb.).

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
döndürebilir. Bu durumda önce bağımlılıkları kurun/senkronlayın:

- Birincil repo standardı: `uv sync --all-extras`
- Komutları sanal ortamı aktive etmeden çalıştırmak için: `uv run <komut>`
- Alternatif/minimum test-tooling kurulumu: `python -m pip install -e ".[dev]"`

Not: `pyproject.toml` temel bağımlılık listesinde pytest, ruff, mypy, bandit ve safety
gibi geliştirme/test araçları standart kurulum akışına dahil edilmiştir. Yine de ekip/CI
paritesi için temiz checkout üzerinde önce `uv sync --all-extras` tercih edilmelidir.

Doğrulama adımları:

**1. Hızlı görünürlük/smoke kontrolü**

Aşağıdaki komut kullanılabilir; ancak yalnızca mevcut role adlarını basar ve tek
başına yeterli kabul edilmemelidir:

```bash
python -c "from agent.registry import AgentCatalog; print([s.role_name for s in AgentCatalog.list_all()])"
```

Çıktı `[]` ise öncelikle bağımlılık kurulumunu ve import uyarılarını kontrol edin.

**2. Fail-fast yerleşik rol doğrulaması**

Yerleşik rollerin eksiksiz yüklendiğini doğrulamak için aşağıdaki komut
çalıştırılmalıdır. Bu komut, boş liste veya eksik role durumlarını sessiz geçmez:

```bash
python - <<'PY'
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
python - <<'PY'
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
