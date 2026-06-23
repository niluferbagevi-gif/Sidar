# tests/ klasörü özeti

Bu not, **mevcut depo durumunu** (2026-04-09) yansıtır ve eski “coverage push” döneminden kalan
tek seferlik/geçici dosya adlarını referans almaz.

## Güncel metrikler

- `test_*.py` desenine uyan toplam test dosyası: **90**
- Katman dağılımı:
  - `tests/unit`: **77**
  - `tests/integration`: **7**
  - `tests/quality`: **2**
  - `tests/smoke`: **2**
  - `tests/e2e`: **1**
  - `tests/performance`: **1**

## Mimari kural: anti-fragmentation

- Test dosyaları modül bazlı isimlendirilir: `tests/unit/<modul>/test_<davranis>.py`
- Geçici/acele coverage dosyaları (`test_quick_*`, `test_*_improvements`, `test_*_runtime` gibi)
  kalıcı test mimarisine dahil edilmez.
- Aynı modül için tekrar eden test dosyaları yerine tek odaklı dosya kullanılır.

## Sidar agent özel notu

- Sidar davranış testleri tek bir dosyada toplanmıştır:
  - `tests/unit/agent/test_sidar_agent.py`
- Eski parçalı adlandırma örnekleri (`test_sidar.py`, `test_sidar_improvements.py`,
  `test_sidar_md_improvements.py`, `test_sidar_agent_runtime.py`) güncel test ağacında yoktur.

## Operasyonel takip

- Bu doküman sprint başında test ağacından yeniden üretilmeli/güncellenmelidir.
- Yeni test eklerken önce modül klasörü belirlenmeli, sonra mevcut dosyaya genişletme
  mümkünse yeni dosya açılmamalıdır.


## CI servis kimlik bilgileri

- `.github/workflows/ci.yml` içindeki PostgreSQL servis parolası (`POSTGRES_PASSWORD=sidar`)
  yalnız GitHub Actions'ın ephemeral test servisi içindir. Production `.env` örnekleri, installer
  çıktıları veya deploy runbook'ları için referans parola olarak kullanılmamalıdır.
- CI test veritabanı `sidar_test` her koşuda yeniden oluşturulur; bu değerlerin amacı yalnız
  `uv sync --frozen --all-extras` sonrası migration/test akışını deterministik çalıştırmaktır.

## Docker sandbox test imajı hazırlığı

- `CodeManager`, açık bir `DOCKER_TEST_IMAGE` verilmemişse yerel Docker daemon'da önce
  `sidar:latest` ve uyumlu proje tag'lerini arar. İmaj yoksa kalıcı çözüm proje imajını
  `docker build -t sidar:latest .` ile hazırlamaktır.
- `run_tests.sh`, pahalı ve ağ/disk tüketebilen Docker build işlemini varsayılan olarak başlatmaz.
  Yerel veya CI ortamında bilinçli otomatik hazırlık için
  `AUTO_BUILD_DOCKER_TEST_IMAGE=1 DOCKER_TEST_IMAGE=sidar:latest bash run_tests.sh` kullanın.
  Farklı build context gerekiyorsa `DOCKER_TEST_IMAGE_BUILD_CONTEXT` değerini açıkça verin.
- `python:3.11-slim`, genel sandbox fallback imajıdır; proje test imajının yerine geçirilmemelidir.
  Proje test akışları `uv`, pytest ve extras bağımlılıklarını içeren `sidar:latest` imajını kullanmalıdır.

## Shell testleri ve bağımlılık güvenlik taraması

- `scripts/install_ci_system_deps.sh`, Debian/Ubuntu geliştirme ve CI ortamlarında `bats`,
  `shellcheck` ve `portaudio19-dev` paketlerini idempotent biçimde kurar. CI profilinde
  `RUN_BATS_TESTS=1` varsayılanı korunur: BATS eksikse shell testleri sessizce atlanmaz ve eksik
  altyapı hata olarak raporlanır. Ana `install_sidar.sh` apt tabanlı yerel kurulumda `bats` paketini
  temel sistem bağımlılıklarıyla birlikte hazırlar. Yerel profilde `RUN_BATS_TESTS=auto` varsayılanı
  kullanılır: BATS PATH üzerinde bulunursa shell testleri otomatik etkinleştirilir; paket yoksa hızlı
  akış atlanır. Açık opt-out için `RUN_BATS_TESTS=0`, CI paritesini zorlamak için
  `RUN_BATS_TESTS=1 bash run_tests.sh` kullanılabilir. Script, root
  olmayan kullanıcılarda interaktif parola istemez; `sudo -n` kullanılamıyorsa net bir hatayla durur.
  Eksik yerel bağımlılıklar için `run_tests.sh` başlangıç uyarısında ortak kurulum scriptini ve
  parolasız sudo ortamlarına uygun opt-in otomatik kurulum komutunu gösterir.
- BATS shell testleri `run_tests.sh` içinde `--report-formatter junit` ile çalışır ve varsayılan olarak
  `artifacts/bats/report.xml` üretir. Rapor dizini güvenli temizleme için yalnız `artifacts/` altında
  kalmak koşuluyla `BATS_REPORT_DIR` ile değiştirilebilir. Yeni shell
  davranışları için deterministik black-box BATS testleri eklenmelidir; `kcov` tabanlı satır kapsamı
  zorunlu kapıya alınmadan önce Debian/Ubuntu ve CI runner paritesi ayrıca doğrulanmalıdır.
- `pip-audit` çağrıları `--skip-editable` kullanır. Böylece PyPI üzerinde yayınlanmayan yerel
  editable `sidar` paketi tarama dışında kalır; kurulu üçüncü taraf bağımlılıkların CVE taraması
  çalışmaya devam eder.

## Frontend Playwright E2E flake yönetimi

- Playwright runner yalnız başarısız testleri yerelde bir, CI'da iki kez yeniden dener. Bu test-seviyesi retry,
  cold-start kaynaklı tekil flake'leri tüm paketi baştan çalıştırmadan absorbe eder.
- Chat websocket E2E senaryoları seri yürür ve tek bir frontend/backend test sunucusu çiftini paylaşır. Test
  Vite sunucusu sabit port yerine işletim sisteminden dinamik port alır; readiness kontrolü SPA köküyle birlikte
  dönüştürülmüş giriş modülünü bekler. Böylece eski süreçlerden kalan portlar ve cold-start dependency optimize
  süresi DOM doğrulamalarına yanlış negatif olarak yansımaz.
- `run_tests.sh`, etkin Playwright E2E fazı Playwright retry'ları sonrasında başarısız olduğunda varsayılan olarak
  bir kez stage retry yapar. Canonical ayar `FRONTEND_E2E_RETRY_ON_FAIL=1`, kısa uyumluluk alias'ı
  `RETRY_ON_FAIL=1` değeridir; namespaced ayar verilirse önceliklidir.
- Retry sonrası E2E başarısızlığı artık CI ve yerel profilde varsayılan `FRONTEND_E2E_ENFORCE_RESULT=1`
  (`ENFORCE_FRONTEND_E2E=1` kısa alias'ı desteklenir) ile hard-fail üretir. Geçici flake
  araştırmasında rapor-only davranış için `FRONTEND_E2E_ENFORCE_RESULT=0` verilebilir; bu değer kalıcı
  yerel varsayılan yapılmamalıdır.
- Vitest unit/coverage sonucu ayrı tutulur ve her profilde zorunlu kalite kapısı olmaya devam eder; E2E soft-fail
  sınıflandırması frontend unit veya coverage hatalarını maskelemez.

## Coverage ratchet eşik davranışı

- Güncel gate ve ratchet state `.coveragerc` içindeki `[report] fail_under` değeridir. Bu dosya
  repo'ya commitli kalmalıdır; `run_tests.sh` dosya yoksa veya gate beklenen minimumun altındaysa
  baseline kaybını önlemek için kalite akışını fail-closed durdurur. Ratchet yalnız başarılı
  birleşik coverage koşusundan sonra ve ölçüm bir sonraki basamağa gerçekten ulaştığında yükselir.
- Örneğin gate `%99` ise bir sonraki koşu doğrudan `%100` olmak zorunda değildir: `%99.x` ölçüm
  gate'i geçer ancak ratchet `%99` seviyesinde kalır. Gate yalnız ölçüm `%100` seviyesine ulaştığında
  `%100` olur.
- Varsayılan local/CI ratchet üst sınırı `%99` olarak kalır; bu, günlük geliştirme akışında tek satırlık
  coverage dalgalanmalarının tüm kalite kapısını kırmaması için bilinçli tampondur. `%100` gate'i
  zorlamak istediğiniz olgun/stabil yerel runnerlarda `COVERAGE_STRICT_LOCAL_RATCHET=1` kullanın veya
  daha açık kontrol için `COVERAGE_RATCHET_MAX_GATE=100` verin. Coverage campaign akışı
  (`COVERAGE_CAMPAIGN=1` / `AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign`) zaten ratchet cap'i
  `%100` olarak açar.
- Ölçüm `%100.00` olsa bile refactor dönemi günlük gate'inde ratchet cap `%99` korunur; örneğin
  `Coverage gate ratcheted: %90 -> %99 (measured=%100.00)` çıktısı doğru davranıştır, `%100` gate'e
  otomatik terfi sinyali değildir. `%100` yalnız coverage-campaign/strict-local opt-in ile denenmelidir.

## Performance benchmark baseline yönetimi

- `tests/performance` altında bulunan benchmark testleri için düzenli baseline kaydı alın.
- Repo kalite kapısının standart etiketi `baseline` değeridir. `bash run_tests.sh`,
  `.benchmarks` altındaki restore/seed edilmiş `*_baseline.json` dosyalarını version-sort ile sıralar ve
  bir sonraki koşuda en güncel kaydı karşılaştırma hedefi olarak kullanır. Baseline bulunduğunda
  karşılaştırma her profilde raporlanır. Profil-duyarlı `--benchmark-compare-fail` kalite kapısı CI profilinde
  varsayılan `BENCHMARK_ENFORCE_COMPARE=1` ve `mean:10%`, yerel profilde ise varsayılan
  `BENCHMARK_ENFORCE_COMPARE=1` ve `mean:15%` ile açıktır. İlk baseline artık
  `.benchmarks/Linux-CPython-3.11-64bit/0001_baseline.json` olarak seed edildiği için
  `BENCHMARK_COMPARE_REQUIRED=1` CI ve yerel profilde varsayılandır; yeni makine/bootstrap istisnasında
  `BENCHMARK_COMPARE_REQUIRED=0`, mevcut baseline ile geçici rapor-only karşılaştırma gerektiğinde
  `BENCHMARK_ENFORCE_COMPARE=0` açıkça verilmelidir.
  Eşik `BENCHMARK_COMPARE_FAIL` ile kontrollü biçimde override edilebilir. Benchmark fazının genel sonucu CI
  ve yerel profilde varsayılan `BENCHMARK_ENFORCE_RESULT=1` ile hard-fail üretir; geçici rapor-only
  araştırma için `BENCHMARK_ENFORCE_RESULT=0` açıkça verilmelidir.
  Benchmark komutu GC'yi kapatır ve kalibrasyon warmup'ını etkinleştirir.
- Yeni baseline üretmek için önerilen komut:
  - `uv run pytest tests/performance/ --benchmark-save=baseline`
- GPU baseline rebase işlemini yalnız temiz çalışma ağacında, aynı WSL2/driver/Ollama profiliyle ve
  artırılmış warmup turları tamamlandıktan sonra yapın. `commit_info.dirty=true` taşıyan veya tek koşu
  jitter'ını kalıcılaştıran JSON dosyalarını otomatik olarak promote etmeyin.
- `pytest-benchmark` baseline kayıtları donanım/runner profiline bağlıdır. Ana CI hattı artık
  `.benchmarks/` dizinini repoya commit etmek yerine GitHub Actions cache üzerinden restore eder ve
  `backend-quality-trend-artifacts` artifact'iyle review için yükler. Cache/artifact içinde
  `*_baseline.json` bulunduğunda `BENCHMARK_COMPARE_REQUIRED=1`, `BENCHMARK_ENFORCE_COMPARE=1` ve
  `BENCHMARK_COMPARE_FAIL=mean:10%` değerleriyle baseline eksikliği veya `mean` üzerinde `%10`
  regresyon hard-fail üretir. Cache boşsa ilk koşu seed baseline moduna alınır
  (`BENCHMARK_COMPARE_REQUIRED=0`) ve sonraki başarılı koşular için `.benchmarks/` cache/artifact
  adayı üretir. Yerel bootstrap komutu:
  `BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required ./run_tests.sh`; sonraki sıkı doğrulama
  komutu: `BENCHMARK_COMPARE_REQUIRED=1 BENCHMARK_ENFORCE_COMPARE=1 RUN_BENCHMARKS=required ./run_tests.sh`.
- Yeni artifact'i otomatik olarak doğru kabul etmeyin. Önce eski ve yeni JSON içindeki `mean`,
  `stddev`, örnek sayısı, donanım/driver profili ve `commit_info.dirty` alanını inceleyin.
  `.benchmarks/` çıktıları kalıcı kaynak dosya değil CI cache/artifact state'i olarak yönetilir;
  donanım/runner profili değiştiğinde cache seed koşusunun artifact'i ayrıca review edilmelidir.
- Tek metrikteki iyileşme tüm paketin hızlandığı anlamına gelmez. Özellikle auth hash/verify,
  PBKDF2 maliyeti nedeniyle bilerek pahalıdır. `SIDAR_PBKDF2_ITERATIONS` ile iş faktörü
  ortam bazında yükseltilebilir; değer güvenli minimumun altındaysa runtime minimuma
  clamp eder. `SIDAR_AUTH_HASH_SLO_MS` varsayılan `120` ms auth hash/verify SLO uyarı
  eşiğini belirler ve `/metrics` içindeki `sidar_auth_password_hash_*` metrikleriyle
  p95/p99 alarm kuralları üretilebilir.
  GPU TTFT/TPS ve çoklu kullanıcı workload sonuçlarını ayrı ayrı değerlendirin.
- 2026-06-22 performans değerlendirmesinde 13 benchmark'ın tamamı başarılı raporlandı ve ilk
  karşılaştırma kaydı `.benchmarks/Linux-CPython-3.11-64bit/0001_baseline.json` olarak seed edildi;
  `test_format_table_handles_large_dataset_quickly` yaklaşık `3.6 ms`,
  `test_user_authentication_password_verify_cpu_cost[postgresql]` yaklaşık `66.8 ms`,
  `test_gpu_concurrent_throughput` yaklaşık `6.96 s` ve
  `test_gpu_vram_peak_under_load` yaklaşık `2.24 s` seviyesinde gözlendi. Bu değerler tek başına
  yeni evrensel eşik değildir; ilgili runner/donanım profili için baseline seed gözlemidir. Sonraki
  koşularda varsayılan `BENCHMARK_COMPARE_REQUIRED=1` + `BENCHMARK_ENFORCE_COMPARE=1` değerleriyle
  otomatik regresyon karşılaştırması çalışır; GPU concurrent throughput gibi metriklerde `mean` sapması
  `%20+` seviyesine ulaşmadan önce yerel `mean:15%` / CI `mean:10%` kapıları regresyonu yakalar.
- Sürüm/sprint için ayrı karşılaştırma gerekiyorsa `baseline_<release_tag>` gibi açık bir etiket
  kullanın (ör. `baseline_v5_2_0`).

### StdDev odaklı izleme (VRAM + çoklu kullanıcı iş yükü)

- Benchmark raporunda standart sapma (stddev) değerlerini yalnızca `mean` ile birlikte okuyun.
- Özellikle aşağıdaki testler için yüksek dalgalanma, bellek tahsisi/jitter sinyali olabilir:
  - `test_gpu_vram_peak_under_load`
  - `test_multi_user_session_message_workload_scales_with_concurrency`
- Bu testlerde artan stddev görüldüğünde acil hata varsayımı yapmadan, canlı ortamda trend takibi başlatın:
  1. Prometheus üzerinden latency + bellek eğrilerini zaman serisi olarak toplayın.
  2. Grafana dashboard'larında p95/p99 gecikme ve RAM/VRAM göstergelerini aynı zaman penceresinde korele edin.
  3. Uzun süreli yükselen bellek trendi varsa olası memory leak için alarm eşiği tanımlayın.
- Operasyonel pratik:
  - Baseline karşılaştırmasını her sürümde tekrarlayın ve stddev değerini release notuna ekleyin.
  - Dalgalanma süreklilik kazanırsa yük profili (concurrency, warmup_rounds, model) sabitlenerek yeniden ölçüm alın.

### Çoklu kullanıcı oturum ölçekleme iyileştirme notu

- `test_multi_user_session_message_workload_scales_with_concurrency` metriği,
  webhook tabanlı kurumsal entegrasyonlarda (Jira/Slack/Teams) kritik bir erken sinyaldir.
- İyileştirme kontrol listesi:
  1. `asyncio.gather` ile kullanıcı/oturum oluşturma akışında gereksiz seri adımlar bırakmayın.
  2. PostgreSQL dağıtımlarında `DB_POOL_SIZE` değerini eşzamanlı istek profiline göre yükseltin.
  3. Sık okunan oturum geçmişleri için Redis/semantic cache katmanını aktif tutun.
  4. Benchmark ölçümünde schema init/bağlantı aç-kapat maliyetini workload dışında tutarak
     gerçek mesajlaşma throughput'unu ayrı izleyin.
- Doğrulama notu:
  - SQLite tarafında WAL modu ve `messages(session_id)` indeksinin varlığı
    `tests/unit/core/test_db.py` içinde güvence altına alınmıştır.

### GPU eşzamanlılık benchmark notu

- Runtime tarafında `OLLAMA_GPU_REQUEST_POOL_SIZE` boş bırakılırsa Sidar, tespit edilen
  GPU sayısı, VRAM ve CPU kapasitesine göre Ollama GPU isteklerini sınırlayan adaptive
  bir semaphore seçer. Düşük VRAM/WSL2 contention görülen hostlarda bu değer `1-2`
  aralığına manuel sabitlenerek concurrent throughput p95/p99 dalgalanması azaltılabilir.
- Aşağıdaki testler, gerçek paralellik doğrulaması için `OLLAMA_NUM_PARALLEL` değerinin
  `GPU_BENCH_CONCURRENCY` kadar (genellikle `4`) olmasını bekler:
  - `test_gpu_concurrent_throughput`
  - `test_gpu_vram_peak_under_load`
- Eşzamanlı throughput testi iki profile ayrılmıştır. Yerel/PR akışında varsayılan
  `RUN_GPU_BENCHMARKS=smoke`, pahalı paralel ölçümü `GPU_BENCH_CONCURRENT_WARMUP_ROUNDS=1` ve
  `GPU_BENCH_CONCURRENT_ROUNDS=10` ile sınırlar. Nightly GPU trend akışı `RUN_GPU_BENCHMARKS=full`
  kullanır ve stabil baseline için sırasıyla `8` ve `20` tur çalıştırır.
- Varyans stabilitesi için full profil önerileri:
  - `RUN_GPU_BENCHMARKS=full`
  - `GPU_BENCH_WARMUP_ROUNDS=8`
  - `GPU_BENCH_NUM_PREDICT=128`
- Test tarafında varsayılan fallback `OLLAMA_NUM_PARALLEL=GPU_BENCH_CONCURRENCY` olarak hizalanmıştır;
  yine de üretim-benzeri doğrulama için bu değişkeni servis başlatırken açıkça set edin.
- Nightly GPU trend geçmişi yalnız eşdeğer çalışma profillerini karşılaştırır. Profil anahtarı; model,
  quantization, mimari, driver, `GPU_BENCH_NUM_BATCH`, `GPU_BENCH_NUM_CTX`,
  `GPU_BENCH_NUM_PREDICT` ve `OLLAMA_KEEP_ALIVE` değerlerini içerir. Bu ayarlardan biri
  değişirse önce yeni profil baseline'ı oluşturulur; eski profil yanlış pozitif alarm üretmez.
- Trend alarm yönleri metrik semantiğine göre ayrıdır: TTFT/VRAM artışı ve token/sn düşüşü
  regresyondur. TTFT/VRAM düşüşü veya token/sn artışı iyileşme sayılır ve alarm üretmez.
- Örnek başlatma komutları:
  - Host/WSL2: `OLLAMA_NUM_PARALLEL=4 ollama serve`
  - Docker Compose: `OLLAMA_NUM_PARALLEL=4 docker compose up ollama`

### CI quality gate (TTFT + single inference latency)

- GitHub Actions içinde isteğe bağlı bir GPU kalite kapısı tanımlıdır: `gpu-inference-quality-gate`.
- Bu job yalnızca repo değişkeni `ENABLE_GPU_BENCH_GATE=true` olduğunda çalışır.
- Runner gereksinimi: `self-hosted`, `linux`, `gpu` etiketli runner.
- Quality gate komutu:
  - `bash scripts/ci/run_ttft_quality_gate.sh`
- Baseline referansı (2026-04):
  - TTFT: ~93 ms
  - Single inference latency: ~120 ms
- Varsayılan gate eşikleri:
  - `GPU_BENCH_TTFT_BUDGET=0.2` (200 ms)
  - `GPU_BENCH_LATENCY_BUDGET=0.25` (250 ms)
- Kapı davranışı:
  - TTFT veya single latency testi fail ederse job fail olur.
  - Test skip olursa (GPU/Ollama hazır değilse) job yine fail olur; böylece PR onayı için gerçek benchmark zorunlu tutulur.

### `warmup=False` uyarısı hakkında not

- `pytest-benchmark` başlık çıktısındaki `warmup=False` ifadesi global `benchmark()` varsayılanını gösterir.
- Bu depo için kritik benchmark testleri `benchmark.pedantic(..., warmup_rounds=1)` kullandığı için her turdan önce ısınma çalıştırılır.
- Pedantic warmup turları ölçüm istatistiklerine dahil edilmez; dolayısıyla global satır, test içi warmup davranışını geçersiz kılmaz.

### Eşiği sıkılaştırma örnekleri

- TTFT eşiğini 100ms'e çekmek için:
  - `GPU_BENCH_TTFT_BUDGET=0.1 uv run pytest tests/performance/test_gpu_benchmark.py -k test_gpu_time_to_first_token`
- Token/sn taban çizgisini yükseltmek için:
  - `GPU_BENCH_MIN_TOKENS_PER_SEC=10 uv run pytest tests/performance/test_gpu_benchmark.py -k test_gpu_tokens_per_second`
