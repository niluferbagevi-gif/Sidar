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

- **Ürün adı:** Güncel ürün adı **Sidar**'dır. Eski ürün adı yalnızca
  geriye dönük migrasyon (örn. legacy `DATABASE_URL` yakalama) için teknik yakalama
  desenlerinde tutulabilir; yeni dokümantasyon, log mesajı veya kullanıcıya görünen
  çıktıda eski ad **kullanılmaz**.
- **Yerel coding model standardı:** Varsayılan ve önerilen yerel coding modeli
  `qwen2.5-coder:7b`'dir. Düşük donanım fallback'leri yeni varsayılan değer veya
  dokümantasyon standardı olarak yazılmamalı; tüm yeni örnekler `qwen2.5-coder:7b`
  üzerinden verilmelidir.
- **Paket/komut standardı:** Tüm Python bağımlılık ve komut yönetimi `uv` üzerinden yapılır.
  Kurulum `uv sync`, çalıştırma `uv run`, ek paket kurulumu `uv pip install` ile yürütülür;
  standart pip tabanlı doğrudan kurulum komutları kullanılmamalıdır.
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
  çıktısına dönüştürür. `search_docs` çağrılarında Poyraz önce RAG entity extraction
  pipeline'ının ürettiği ilişkisel GraphRAG belleğini (kampanya -> hedef kitle ->
  marka dili/kanal) kullanmalı, ardından vektörel/BM25 kanıtla desteklemelidir.
  Teknik landing page veya entegrasyon gerekiyorsa `coder` ile, marka/güvenlik/kalite
  kontrolü gerekiyorsa `reviewer` ile çalışır.

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
  `AUTO_HEAL_ON_FAILURE=1` açıkça verildiğinde mypy başarısızlığı için `scripts.auto_heal`
  döngüsünü tetikler; varsayılan akış mypy hatasını raporlar ancak yerel modelle zorunlu patch
  planı üretmeye çalışarak kalite kapısını bloke etmez. Açıkça opt-in yapılan mypy self-heal
  çalıştırmalarında `AUTO_HEAL_BATCH_RETRIES=0` varsayılanı kullanılır; daha fazla yerel model
  patch-plan denemesi yalnız bilinçli override ile açılmalıdır.
- **Uzun otonom döngü:** `autonomous_loop.sh`, önce tam `./run_tests.sh` kalite
  kapısını çalıştırır; varsayılan `AUTONOMOUS_LOOP_REMEDIATION_MODE=hybrid` modunda sonraki
  otonom tekrar/remediation testlerinde `RUN_STATIC_ANALYSIS=0 AUTO_HEAL_ON_FAILURE=0 ./run_tests.sh`
  kullanır ve `AUTONOMOUS_LOOP_RUN_STATIC_ANALYSIS=1` override değerini yok sayar. Böylece
  `run_tests.sh` içindeki mypy kapısı başlangıç doğrulaması olarak korunur, fakat
  uzun döngü qwen2.5-coder:7b ile tekrar tekrar mypy patch planı üretmeye çalışmak yerine
  hata veren pytest senaryolarını onarmaya ve coverage artırmaya odaklanır. Zorunlu statik analiz
  tekrarı yalnız bilinçli `AUTONOMOUS_LOOP_REMEDIATION_MODE=full-static` profiliyle açılmalıdır.
  Test çıkışı, coverage JSON okunamaması, `AUTONOMOUS_LOOP_COVERAGE_TARGET` altında
  kalma veya mutasyon testi gate'inin davranış değişikliklerini öldürememesi durumunda
  iyileştirme döngüsüne girer.
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

- Coverage eşikleri operasyonel olarak üç ayrı profilde izlenir; aynı eşik
  değerini her yere bağlamak (`pyproject.toml [tool.coverage.report].fail_under = 100` gibi) geliştirme
  hızını gereksiz yere kırar:
    - **Local profile (`TEST_PROFILE=local`)** — günlük geliştirici kapısı.
      `pyproject.toml [tool.coverage.report].fail_under` ratchet ile yönetilen
      güncel `%99` baseline'ını tutar; önceki düşük başlangıç anlatısı artık
      geçerli değildir. `coverage_ratchet.py` ölçülen coverage arttıkça bu
      değeri yalnızca yukarı taşır; `COVERAGE_FAIL_UNDER_LOCAL` envi ile profil
      bazında üstüne yazılabilir, `run_tests.sh` profile göre eşiği
      `COVERAGE_FAIL_UNDER` değişkenine yazar.
    - **CI profile (`TEST_PROFILE=ci`)** — pre-merge/zorunlu kapı.
      `.github/workflows/ci.yml` artık ayrı bir sabit `COVERAGE_FAIL_UNDER_CI`
      değeri bindirmez; local profille aynı ratchet edilmiş `pyproject.toml`
      tabanını kullanır. `COVERAGE_FAIL_UNDER_CI` envi hâlâ desteklenir ve
      ad-hoc olarak daha sıkı bir pre-merge eşiği vermek için kullanılabilir.
    - **Coverage campaign profile** — aspirasyonel `%100` hedefi.
      `COVERAGE_CAMPAIGN=1` veya `AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign`
      ile devreye girer; `COVERAGE_FAIL_UNDER_CAMPAIGN` envi varsayılan
      `100`'ü override edebilir.
- `coverage_ratchet.py` `pyproject.toml` üzerindeki `[tool.coverage.report].fail_under` değerini
  yalnızca yukarı taşır; `COVERAGE_RATCHET_STEP` varsayılanı `%1`'dir ve
  local/CI profilleri için `COVERAGE_RATCHET_MAX_GATE` varsayılan olarak
  `99`'dur (1 puanlık tampon), coverage campaign profilinde `100`'e açılır.
  Açık `COVERAGE_FAIL_UNDER` her zaman tüm profillerin önüne geçer (geri
  uyumluluk).
- `autonomous_loop.sh` ise varsayılan `%99.8` değerini **otonom iyileştirme
  hedefi** olarak izler. `%99.8` altında kalmak, testler ve local gate
  geçiyorsa CI/local başarısızlığı değil CoverageAgent döngüsünün devam
  edeceği anlamına gelir.
- `autonomous_loop.sh`, kalite kapısı veya otonom iyileştirme hedefi sağlanmazsa
  `CoverageAgent` ile `coverage.xml` analizini çalıştırır, `scripts/coverage_hotspots.py`
  ile düşük coverage dosyalarını listeler ve gerekiyorsa eksik test önerisi üretir.
  Otonom test üretimi mikro kapsamla sınırlandırılır: varsayılan
  `AUTONOMOUS_LOOP_COVERAGE_AGENT_LIMIT=3`,
  `AUTONOMOUS_LOOP_COVERAGE_AGENT_BATCH_SIZE=1`,
  `AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_LINES=25`,
  `AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_BRANCHES=10` ve
  `AUTONOMOUS_LOOP_EXCLUDE_FILES=web_server.py,main.py,gui_launcher.py,cli.py` değerleri tek döngüde
  ajan bağlamına çok geniş coverage boşluğu veya yan etkili launcher/API giriş noktası
  yüklenmesini engeller; bu liste dosya adı, repo-göreli yol, dizin prefix'i ve glob
  deseni kabul eder. `%5` gibi geniş
  artışlar tek ajan denemesi hedefi olarak kullanılmamalı; `%0.5-%1` aralığı
  normal otonom ilerleme, `%0.1` ise `%99+` kritik eşiklerde kontrollü coverage
  kampanyası için tercih edilmelidir.
- Coverage hedefi sağlandığında otonom döngü ayrıca `mutmut` tabanlı mutasyon testi
  gate'ini çalıştırır (`AUTONOMOUS_LOOP_MUTATION_ENABLED`,
  `AUTONOMOUS_LOOP_MUTATION_MAX_CHILDREN`, `AUTONOMOUS_LOOP_MUTATION_COMMAND`).
  `AUTONOMOUS_LOOP_MUTATION_MAX_CHILDREN` verilmezse lokal otonom döngü 8 paralel mutmut
  child süreciyle mutasyon kampanyasını hızlandırır; haftalık GitHub Actions mutasyon
  kampanyası runner kaynak dengesini korumak için `--max-children 4` kullanır.
  Mutasyon testi başarısızsa coverage %100 olsa bile test kalitesi yetersiz kabul edilir;
  örn. aritmetik operatör, branch koşulu veya hata yolu mutasyonu testler tarafından
  öldürülmüyorsa döngü davranış odaklı test üretimi için fail-closed devam eder.
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


### 2.5.6 Kademeli dokümantasyon kampanyası

Ruff pydocstyle `D` kuralları açık kalır; ancak legacy yüzeydeki eksik ve stil olarak
uyumsuz docstring borcu kontrollü kapatılana kadar `pyproject.toml` içinde `D100-D107`
ve `D200-D417` ailesinden seçili kurallar geçici ignore edilir. Bu ignore'lar kalıcı
standart değildir; aşağıdaki tarihli kampanyaya bağlıdır:

- **2026-07-15 — Envanter freeze:** `scripts/coverage_hotspots.py` ve kritik ajan/DB/RAG
  modülleri için public module/class/function docstring eksikleri hotspot listesine
  dönüştürülür. Yeni dosyalar Google-style docstring olmadan kabul edilmez.
- **2026-08-15 — Core/agent public API kapısı:** `agent/`, `core/` ve `managers/code/`
  altında değişen public sınıf/fonksiyonlar için D100-D107 kapsamı PR bazında temizlenir;
  rol sözleşmeleri `tests/unit/agent/test_builtin_role_contracts.py` ile korunmaya devam eder.
- **2026-09-30 — Stil borcu kapanışı:** Google pydocstyle uyumsuzlukları (`D200-D417`)
  için kalan istisnalar azaltılır ve `pyproject.toml` ignore listesi daraltılır. Bu tarihten
  sonra yeni D200-D417 istisnası yalnız açık TODO, sahip ve expiry tarihiyle eklenebilir.

Operasyonel kural: Yeni veya anlamlı şekilde değiştirilen public API'lerde docstring eklemek
varsayılandır; ignore listesine yeni kural eklemek yerine ilgili modülde dokümantasyon borcu
hedeflenmelidir.

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

### 2.7 Çoklu modalite (multimodal): görüş ve ses yetenekleri

Sidar, salt metin ajanlarının ötesinde görsel (vision) ve ses (voice/STT/TTS)
girdilerini de işleyebilir. Bu yeteneklerin kaynak dosyaları `core/vision.py`,
`core/voice.py` ve `core/multimodal.py`'dir; agent rolleri bu modülleri doğrudan
import edip kullanabilir, ancak aşağıdaki operasyonel kurallar tüm ajanlar için
bağlayıcıdır.

#### 2.7.1 Feature flag ve devre dışı bırakma sözleşmesi

Multimodal yetenekler feature flag'lerle yönetilir; ortam değişkenleri tek doğruluk
kaynağıdır ve runtime'da `Config` üzerinden okunur:

- `ENABLE_VISION` (varsayılan `true`) — `VisionPipeline` ve görsel mesaj kurucuları
  yalnızca bu bayrak açıkken aktiftir. `False` ise `mockup_to_code` / `analyze`
  çağrıları `{"success": False, "reason": "ENABLE_VISION devre dışı"}` döner.
- `ENABLE_MULTIMODAL` (varsayılan `true`) — Video/ses indirme, frame çıkarma,
  Whisper STT ve WebRTC ses akışı bu bayrağa bağlıdır. `False` ise `VoicePipeline`
  `voice_disabled_reason="ENABLE_MULTIMODAL devre dışı."` ile kapanır.
- `VOICE_ENABLED` (varsayılan `true`) — TTS sentezi ve duplex akışı bağımsız
  olarak kapatılabilir; multimodal açık olsa bile bu kapalıyken ajanlar metin
  yanıtla yetinmelidir.
- `VISION_MAX_IMAGE_BYTES` (varsayılan 10 MB) ve `MULTIMODAL_MAX_FILE_BYTES`
  (varsayılan 50 MB) limitleri sıkı uygulanır; aşan girdiler `ValueError` ile
  reddedilir, ajanlar bu hatayı kullanıcıya açık metinle raporlamalıdır.

> Operasyonel kural: Yeni multimodal kod yolları flag kontrolünü **erkene** çekmeli
> (pipeline başında); flag kapalıyken model çağrısı / ağ I/O yapılmamalıdır.

#### 2.7.2 Görüş (vision) kullanım kuralları

`VisionPipeline` (`core/vision.py`) UI mockup → frontend kodu üretimi ve genel
görsel analiz (general / accessibility / ux_review) sağlar. Ajanlar için kurallar:

- **Kabul edilen formatlar:** Yalnızca `image/jpeg`, `image/png`, `image/webp`,
  `image/gif`. Diğer MIME tipleri `ValueError` ile reddedilir; ajan dönüştürme
  yapmadan dosyayı doğrudan modele iletmemelidir.
- **Sağlayıcı çoğulluğu:** `build_vision_messages(...)` `openai`/`litellm`,
  `anthropic`, `gemini` ve Ollama (LLaVA / `llama3.2-vision`) için ayrı mesaj
  şemaları üretir. Ajanlar provider seçimini `LLMClient.provider` üzerinden
  yapmalı; manuel mesaj kurmaya çalışmamalıdır.
- **Frontend doğrulama akışı:** Tarayıcı otomasyonu (`managers/browser_manager.py`)
  ile alınan ekran görüntüleri `VisionPipeline.analyze(analysis_type="ux_review"
  veya "accessibility")` ile doğrulanır. `coder` ajanı UI değişikliği üretirse,
  `reviewer` veya `qa` ajanı render edilmiş ekran görüntüsünü vision pipeline'a
  beslemelidir; salt DOM diff'i kalite kapısı olarak yeterli kabul edilmez.
- **Visual drift + multimodal eskalasyon:** `BrowserManager.analyze_visual_drift(...)`
  önce baseline/current screenshot piksel farkını hesaplar; drift skoru
  `BROWSER_VISUAL_QA_MULTIMODAL_MARGIN` eşiği içinde belirsiz kalırsa
  `_analyze_screenshot_with_multimodal(...)` üzerinden `MultimodalPipeline.analyze_media(...)`
  çağrılır. Ajanlar bu sonucu `multimodal_check.triggered` ve varsa
  `multimodal_analysis.success/reason` alanlarıyla raporlamalıdır.
- **Erişilebilirlik kapısı:** Yeni veya değişen UI bileşenleri için
  `analysis_type="accessibility"` raporu, WCAG 2.1 sapmaları içeriyorsa
  reviewer/QA tarafından **engelleyici** sayılır.
- **PII/DLP:** Ekran görüntülerinde kullanıcı verisi olabilir; vision pipeline'a
  gönderilen görseller önce `core/dlp.py` redaksiyonundan geçirilmeli, log'a
  base64 payload yazılmamalıdır.

#### 2.7.3 Ses ve sesli komut algılama (voice/STT)

`VoicePipeline` ve `WebRTCAudioIngress` (`core/voice.py`) full-duplex sesli
asistan deneyimi sağlar; STT tarafı `core/multimodal.py` üzerinden Whisper
(`WHISPER_MODEL`, varsayılan `base`) ile çalışır.

- **Sesli komut algılama:** WebRTC üzerinden gelen paketler
  `WebRTCAudioIngress.decode_packet(...)` ile normalize edilir; yalnızca
  `SUPPORTED_MIME_TYPES` (`audio/webm`, `audio/ogg`, `audio/wav`, `audio/x-wav`,
  `audio/mp4`, `audio/mpeg`, `audio/mp3`) kabul edilir. `VOICE_WEBRTC_MAX_CHUNK_BYTES`
  (varsayılan 2 MB) limitini aşan paketler reddedilir.
- **VAD ve commit kararı:** `VoicePipeline.should_commit_audio(...)` yalnızca
  `VOICE_VAD_ENABLED=true` ve `event ∈ {speech_end, speech_ended, end_of_turn,
  silence, vad_commit}` ve buffer ≥ `VOICE_VAD_MIN_SPEECH_BYTES` koşullarında
  `True` döner. Ajanlar manuel "konuşma bitti" varsayımıyla STT tetiklememeli;
  bu kontrat tek karar noktasıdır.
- **Full-duplex barge-in:** `VOICE_DUPLEX_ENABLED=true` iken
  `should_interrupt_response(...)` `INTERRUPT_EVENTS` setinde bir olay görür ve
  buffer eşiği aşılırsa mevcut asistan turu **kesilir**. Ajan kendi yanıt
  akışını kesilebilir varsaymalı; `interrupt_assistant_turn(...)` çağrısından
  sonra `output_text_buffer` boşaltılır ve `assistant_turn_id` artırılır,
  yani "kayıp" segmentleri yeniden göndermek yerine yeni turdan üretmek
  gerekir.
- **TTS sözleşmesi:** `VOICE_TTS_PROVIDER` `auto`/`pyttsx3` (offline) veya
  `mock` (test) olabilir. `VoicePipeline.synthesize_text(...)` boş metin veya
  pipeline kapalıyken `success=False` ve insan-okunur `reason` döner; ajanlar
  bu cevapları sessizce yutmamalı, kullanıcıya görünür şekilde raporlamalıdır.
- **Segmentleme:** Streaming üretimde `extract_ready_segments(...)` cümle sınırı
  ve `VOICE_TTS_SEGMENT_CHARS` eşiği üzerinden segment çıkarır; ajanlar TTS'e
  karakter karakter göndermemeli, segment bazlı paketleri kullanmalıdır.

#### 2.7.4 Video/ses ingest ve transkript

`core/multimodal.py` lokal ve uzak medyayı işler:

- **Kaynak çözümleme:** `is_remote_media_source`, `detect_video_platform` ve
  `extract_youtube_video_id` ile platform belirlenir. YouTube için önce
  `fetch_youtube_transcript(...)` (yerleşik altyazı) denenmelidir; yoksa
  `yt-dlp` mevcutsa `download_remote_media(...)`, ardından FFmpeg ile frame /
  ses çıkarımı yapılır.
- **Boyut ve süre limitleri:** `MULTIMODAL_MAX_FILE_BYTES` (varsayılan 50 MB)
  ve `materialize_remote_media_for_ffmpeg(... max_duration_seconds=120.0 ...)`
  varsayılan 2 dakika kesim limiti uygulanır. Bu limitler ajan tarafında
  override edilmemelidir; daha uzun içerik için pipeline parçalı (chunked)
  STT akışı kullanmalıdır.
- **Subprocess güvenliği:** `_run_subprocess`/`_run_subprocess_capture` yalnızca
  iç kaynaklı komut listeleri ile çağrılır; ajanlar kullanıcı girdisini
  doğrudan komut dizisine **eklememelidir** (shell injection guard).
- **Bağlama dönüştürme:** STT çıktısı LLM'e verilirken `text` alanı yanında
  `segments` (start/duration) bilgisi de bağlama eklenmelidir; bu, sonraki
  ajan turlarında zaman damgalı atıf üretebilmek için gereklidir.

#### 2.7.5 Ajan-rol etkileşimi

- `coder` ajanı UI üretiminde `VisionPipeline.mockup_to_code(...)` çıktısını
  doğrudan dosyaya yazmadan önce `reviewer` semantik kontrolünden geçirmelidir;
  pipeline `framework`/`language` parametreleriyle deterministik çalışır.
- `reviewer` ve `qa` ajanları, frontend değişikliği için tarayıcı otomasyonu
  (Playwright/`browser_manager`) ile ekran görüntüsü alıp
  `VisionPipeline.analyze(...)` çağırmalıdır; sadece DOM/HTML diff yetersizdir.
- `researcher` ajanı, video/ses kaynaklı bilgi toplarken önce YouTube
  transkriptini, ardından Whisper STT'yi denemeli; her iki yol da
  başarısızsa `success=False` ve gerekçe ile rapor edilmelidir.
- Sesli arayüz (`VOICE_DUPLEX_ENABLED=true`) kullanıcısıyla çalışan supervisor
  akışları, kullanıcı barge-in olayında mevcut planı **iptal** etmeli ve yeni
  turu sıfırdan değerlendirmelidir; aksi takdirde paralel iki yanıt akışı
  oluşur.

#### 2.7.6 Ajan giriş yönlendirme matrisi

- **Görsel/mockup girdisi:** `coder` yalnız `VisionPipeline.mockup_to_code(...)` ile
  kod önerisi üretmeli; çıktı doğrudan dosyaya yazılmadan önce `reviewer` semantik
  kontrolünden ve UI değişikliği ise `qa` görsel doğrulamasından geçmelidir.
- **Render edilmiş frontend screenshot'ı:** `reviewer`/`qa`, Playwright veya
  `BrowserManager.capture_screenshot(...)` çıktısını `VisionPipeline.analyze(...)` ya da
  `BrowserManager.analyze_visual_drift(...)` ile değerlendirmeli; erişilebilirlik veya
  UX bulgularını kalite kapısı olarak işaretlemelidir.
- **Sesli komut / WebRTC chunk'ı:** Supervisor veya web socket katmanı önce
  `WebRTCAudioIngress.decode_packet(...)` ile MIME/boyut doğrulaması yapmalı;
  `VoicePipeline.should_commit_audio(...)` `True` dönmeden Whisper STT çalıştırılmamalıdır.
- **Video/uzak medya girdisi:** `researcher` ve `poyraz`, URL/video kaynaklarında önce
  `MultimodalPipeline.analyze_media_source(...)` yolunu kullanmalı; YouTube transcript
  yoksa süre/boyut limitlerine uyan Whisper fallback'i devreye alınmalıdır.
- **Yanıt üretimi + TTS:** `VoicePipeline.extract_ready_segments(...)` segment üretmeden
  TTS çağrısı yapılmamalı; `success=False` dönen TTS/STT/vision sonuçları ajan
  çıktısında açık `reason` ile görünür olmalıdır.

#### 2.7.7 Operasyonel kurallar (özet)

- Multimodal kod yolları flag kapalıyken ağ/model I/O yapmamalı; her giriş
  noktasında erken kontrol uygulanmalıdır.
- Boyut/format/MIME limitleri ajan tarafında zorlanmalı, sessiz kırpma yapılmamalıdır.
- TTS/STT hata cevapları (`success=False`, `reason=...`) kullanıcıya görünür
  şekilde raporlanmalıdır; sessiz başarısızlık kabul edilmez.
- Vision/voice çıktıları log'a base64 payload olarak yazılmamalı; sadece özet
  metadata (boyut, mime, segment sayısı) loglanmalıdır.
- Yeni multimodal yetenek eklendiğinde hem `Config` ortam değişkeni eklenmeli
  hem de bu bölüm güncellenmeli; yetenek bir ajan rolüyle birlikte geliyorsa
  2.3 ve 4. bölümlerdeki kayıt adımları da uygulanmalıdır.

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
- Yeni multimodal yetenek (vision / voice / video / STT-TTS) eklendiğinde 2.7
  bölümü ve ilgili ortam değişkenleri (`ENABLE_VISION`, `ENABLE_MULTIMODAL`,
  `VOICE_*`, `WHISPER_MODEL`, `MULTIMODAL_MAX_FILE_BYTES`,
  `VISION_MAX_IMAGE_BYTES`) birlikte güncellenmelidir.

### 5.1 Hızlı doğrulama checklist’i

Ön koşul: Aşağıdaki çalışma zamanı doğrulamaları **bağımlılıkları kurulmuş** bir ortamda
çalıştırılmalıdır. Temiz/çıplak repo checkout ortamında `python-dotenv`,
`pydantic-settings` vb. proje bağımlılıkları henüz yoksa `agent.registry`, yerleşik rol
modüllerini import ederken başarısız olabilir ve `AgentCatalog.list_all()` boş liste
döndürebilir. Bu durumda önce bağımlılıkları `uv` ile kurun:

- `uv sync --all-extras` — geliştirme/test/CI paritesi için önerilen tam kurulum.
- Yalnız test/tooling araçları yeterliyse `uv sync --extra dev` kullanılabilir.
- İlk yerel benchmark koşusunda `.benchmarks` baseline yoksa `BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required ./run_tests.sh` ile baseline seed edin; CI profilinde `BENCHMARK_COMPARE_REQUIRED=1` fail-closed kalmalıdır.

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
