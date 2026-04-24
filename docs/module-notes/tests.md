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

### CI quality gate (TTFT <= 200ms)

- GitHub Actions içinde isteğe bağlı bir GPU kalite kapısı tanımlıdır: `gpu-ttft-quality-gate`.
- Bu job yalnızca repo değişkeni `ENABLE_GPU_BENCH_GATE=true` olduğunda çalışır.
- Runner gereksinimi: `self-hosted`, `linux`, `gpu` etiketli runner.
- Quality gate komutu:
  - `bash scripts/ci/run_ttft_quality_gate.sh`
- Varsayılan eşik:
  - `GPU_BENCH_TTFT_BUDGET=0.2` (200 ms)
- Kapı davranışı:
  - TTFT testi fail ederse job fail olur.
  - Test skip olursa (GPU/Ollama hazır değilse) job yine fail olur; böylece PR onayı için gerçek benchmark zorunlu tutulur.
