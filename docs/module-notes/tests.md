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

## Performance benchmark baseline yönetimi

- `tests/performance` altında bulunan benchmark testleri için düzenli baseline kaydı alın.
- Önerilen komut:
  - `pytest tests/performance/ --benchmark-save=baseline_master`
- Yeni performans değişikliklerinde karşılaştırma için:
  - `pytest tests/performance/ --benchmark-compare=baseline_master`
- İsimlendirme önerisi:
  - Ana dal için `baseline_master`
  - Sürüm/sprint için `baseline_<release_tag>` (ör. `baseline_v5_2_0`)

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
  - `GPU_BENCH_TTFT_BUDGET=0.1 pytest tests/performance/test_gpu_benchmark.py -k test_gpu_time_to_first_token`
- Token/sn taban çizgisini yükseltmek için:
  - `GPU_BENCH_MIN_TOKENS_PER_SEC=10 pytest tests/performance/test_gpu_benchmark.py -k test_gpu_tokens_per_second`
