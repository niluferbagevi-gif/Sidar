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
  `shellcheck` ve `portaudio19-dev` paketlerini idempotent biçimde kurar. `RUN_BATS_TESTS=1`
  varsayılanında `run_tests.sh`, BATS eksikse shell testlerini sessizce atlamaz; eksik altyapıyı
  hata olarak raporlar. Bilinçli yerel atlama yalnız `RUN_BATS_TESTS=0` ile yapılmalıdır.
  Script, root olmayan kullanıcılarda interaktif parola istemez; `sudo -n` kullanılamıyorsa net bir
  hatayla durur. Parolasız `sudo` kullanılabilen yerel ortamlarda
  `AUTO_INSTALL_CI_SYSTEM_DEPS=1 bash run_tests.sh` eksik bağımlılıklar için aynı ortak kurulum
  scriptini opt-in biçimde çalıştırır; otomatik kurulum başarısız olursa fail-closed kalite kapısı korunur.
- BATS shell testleri `run_tests.sh` içinde `--report-formatter junit` ile çalışır ve varsayılan olarak
  `artifacts/bats/report.xml` üretir. Rapor dizini güvenli temizleme için yalnız `artifacts/` altında
  kalmak koşuluyla `BATS_REPORT_DIR` ile değiştirilebilir. Yeni shell
  davranışları için deterministik black-box BATS testleri eklenmelidir; `kcov` tabanlı satır kapsamı
  zorunlu kapıya alınmadan önce Debian/Ubuntu ve CI runner paritesi ayrıca doğrulanmalıdır.
- `pip-audit` çağrıları `--skip-editable` kullanır. Böylece PyPI üzerinde yayınlanmayan yerel
  editable `sidar` paketi tarama dışında kalır; kurulu üçüncü taraf bağımlılıkların CVE taraması
  çalışmaya devam eder.

## Coverage ratchet eşik davranışı

- Güncel gate `.coveragerc` içindeki `[report] fail_under` değeridir. Ratchet yalnız başarılı
  birleşik coverage koşusundan sonra ve ölçüm bir sonraki basamağa gerçekten ulaştığında yükselir.
- Örneğin gate `%99` ise bir sonraki koşu doğrudan `%100` olmak zorunda değildir: `%99.x` ölçüm
  gate'i geçer ancak ratchet `%99` seviyesinde kalır. Gate yalnız ölçüm `%100` seviyesine ulaştığında
  `%100` olur.

## Performance benchmark baseline yönetimi

- `tests/performance` altında bulunan benchmark testleri için düzenli baseline kaydı alın.
- Repo kalite kapısının standart etiketi `baseline` değeridir. `bash run_tests.sh`,
  `.benchmarks` altındaki takipli `*_baseline.json` dosyalarını version-sort ile sıralar ve
  bir sonraki koşuda en güncel kaydı karşılaştırma hedefi olarak kullanır.
- Yeni baseline üretmek için önerilen komut:
  - `uv run pytest tests/performance/ --benchmark-save=baseline`
- Yeni artifact'i otomatik olarak doğru kabul etmeyin. Önce eski ve yeni JSON içindeki `mean`,
  `stddev`, örnek sayısı, donanım/driver profili ve `commit_info.dirty` alanını inceleyin; yalnız
  kontrollü ölçümü `.benchmarks/<platform>/NNNN_baseline.json` olarak commit edin.
- Tek metrikteki iyileşme tüm paketin hızlandığı anlamına gelmez. Özellikle auth hash/verify,
  GPU TTFT/TPS ve çoklu kullanıcı workload sonuçlarını ayrı ayrı değerlendirin.
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

- Aşağıdaki testler, gerçek paralellik doğrulaması için `OLLAMA_NUM_PARALLEL` değerinin
  `GPU_BENCH_CONCURRENCY` kadar (genellikle `4`) olmasını bekler:
  - `test_gpu_concurrent_throughput`
  - `test_gpu_vram_peak_under_load`
- Varyans stabilitesi için önerilen benchmark varsayılanları:
  - `GPU_BENCH_WARMUP_ROUNDS=5`
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
