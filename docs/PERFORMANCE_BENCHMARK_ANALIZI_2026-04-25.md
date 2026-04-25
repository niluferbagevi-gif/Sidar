# Performans Benchmark Analizi (25 Nisan 2026)

Bu rapor, paylaşılan `pytest-benchmark` çıktısındaki 7 performans testini proje koduyla eşleştirerek
iyileştirme/geliştirme önerileri sunar.

## 0) Uygulama durum güncellemesi (revizyon)

Aşağıdaki maddeler bu revizyonda uygulanmıştır:

- `tests/performance/test_gpu_benchmark.py` içinde benchmark döngülerinde
  tekrar tekrar `asyncio.run(...)` çağırmak yerine test başına tek event-loop
  yaklaşımına geçildi.
- `tests/performance/test_gpu_benchmark.py` içinde HTTP çağrıları için
  loop-başına paylaşılan `httpx.AsyncClient` kullanımı eklendi (keep-alive).
- VRAM örnekleme aralığı sabit `0.2s` yerine
  `GPU_BENCH_VRAM_SAMPLE_INTERVAL` ile konfigüre edilebilir hale getirildi
  (varsayılan `0.05s`).
- `core/db.py` içinde benchmark yükü için kullanılabilecek
  `create_users_bulk` ve `create_sessions_bulk` metotları eklendi.
- `tests/performance/test_benchmark.py` çoklu kullanıcı benchmark akışında
  tek tek create yerine bulk metotları kullanacak şekilde güncellendi.
- `tests/performance/test_benchmark.py` PostgreSQL benchmark koşumu için
  `PERF_BENCH_POSTGRES_DSN` destekli backend parametrelemesi eklendi.

## 1) Sonuç özeti

- **Toplam:** 7/7 test geçti.
- **En hızlı CPU testi:** `test_format_table_handles_large_dataset_quickly` (mean ~4.01 ms).
- **CPU tarafında dalgalı test:** `test_multi_user_session_message_workload_scales_with_concurrency`
  (mean ~10.45 ms, stddev ~3.21 ms, yüksek outlier).
- **GPU TTFT:** mean ~93.56 ms (iyi).
- **GPU tek istek latency:** mean ~112.66 ms (iyi).
- **GPU concurrency tur süresi:** mean ~597.44 ms.
- **GPU VRAM testi:** mean ~752.99 ms, **stddev ~104.31 ms** (en dalgalı metrik).
- **GPU TPS testi:** mean tur süresi ~808.44 ms; test içinde TPS doğrulaması mevcut.

## 2) Test bazlı teknik değerlendirme

### 2.1 `test_format_table_handles_large_dataset_quickly`

İlgili uygulama `scripts/coverage_hotspots.py::format_table` fonksiyonudur.
Fonksiyon, her satır için string append + join yapıyor ve O(n) karmaşıklıkla ilerliyor.
Mevcut performans (10.000 satırda ~4 ms) pratik olarak iyi seviyede.

**İyileştirme önceliği:** Düşük.

**Opsiyonel mikro-optimizasyonlar:**
- `rec.coverage_pct` hesaplamasını her satır yerine önceden cachelemek.
- Çok büyük veri kümelerinde `io.StringIO` ile karşılaştırmalı benchmark almak.

### 2.2 `test_multi_user_session_message_workload_scales_with_concurrency`

Test, çoklu kullanıcı/oturum/mesaj akışını SQLite üzerinde ölçüyor.
Kod akışında kullanıcı ve oturum eklemede tek tek commit yapılıyor; toplu mesaj tarafında bulk var.
Bu yaklaşım fonksiyonel olarak doğru ama varyansı artırabilir.

**Gözlenen risk:**
- StdDev/IQR diğer CPU testine göre yüksek; outlier sayısı fazla.
- Özellikle CI ortamında disk/IO jitter ile dalgalanma büyüyebilir.

**İyileştirme önerileri (yüksek etki):**
1. `create_user` ve `create_session` için **bulk + tek transaction** yolu ekleyin.
2. `add_messages_bulk` içinde her item için ayrı `datetime.now()` yerine tek tur timestamp stratejisi düşünün.
3. `messages(session_id, id)` için DB index doğrulaması yapın (özellikle `get_messages_for_sessions` sıralama/süzme için).
4. Benchmark için SQLite PRAGMA profili (özellikle test ortamına özel) tanımlayın.

### 2.3 GPU benchmark ailesi (`test_gpu_*`)

GPU testleri genel olarak iyi tasarlanmış:
- Warmup var.
- Skip koşulları net.
- Budget tabanlı assertion mevcut.
- Ollama opsiyonları merkezi (`_ollama_options`).

Buna rağmen bazı teknik iyileştirme fırsatları bulunuyor.

#### A) Event loop ve HTTP client yeniden yaratma maliyeti

Birçok benchmark turunda `asyncio.run(...)` tekrar tekrar çağrılıyor.
Ayrıca `_chat_content` ve `_chat_with_metrics` her çağrıda yeni `httpx.AsyncClient` açıyor.
Bu, ölçümlere framework overhead’i katıp gerçek model/GPU sinyalini seyreltebilir.

**Öneri:**
- Modül/fixture seviyesinde tek event loop.
- Reusable `httpx.AsyncClient` (connection pooling + keep-alive).

#### B) VRAM testinde yüksek oynaklık

`test_gpu_vram_peak_under_load` stddev en yüksek test.
200ms örnekleme aralığı kısa süreli tepe kullanımını kaçırabilir veya gürültüyü artırabilir.

**Öneri:**
- Örnekleme aralığını konfigürasyona açın (`GPU_BENCH_VRAM_SAMPLE_MS`).
- Ek olarak P95/P99 peak raporlayın.
- Baseline’e göre yüzdesel değişim alarmı ekleyin.

#### C) TPS ölçüm doğruluğu

`test_gpu_tokens_per_second` içinde assertion son turdaki `result.tokens_per_second` üzerinden çalışıyor.
Bu, tek turun anomalisiyle kırılgan olabilir.

**Öneri:**
- `observed` listesindeki tüm tps değerlerinden median/P95 hesaplayıp gate uygulayın.
- CV hesabını benchmark tur süresi yerine doğrudan TPS serisi üzerinden üretin.

#### D) Warmup maliyeti ve tekrar sayısı

`_prepare_client` içinde ardışık + eşzamanlı ısınma turları var.
Bu iyi bir yaklaşım; ancak büyük CI matrislerinde toplam süreyi uzatabilir.

**Öneri:**
- CI ve lokal için ayrı preset (ör. `GPU_BENCH_PROFILE=ci|local`).
- CI’da daha az warmup + daha düşük round ile trend odaklı test.

## 3) Önceliklendirilmiş geliştirme planı

### P0 (hemen)
1. GPU benchmark’ta reusable AsyncClient + event loop fixture.
2. TPS gate’ini tek sonuç yerine dağılım (median/P95) tabanlı hale getirme.
3. Multi-user DB testinde kullanıcı/oturum için bulk insert yolu ekleme.

### P1 (kısa vade)
1. VRAM örnekleme granülerliğini çevresel değişkenle kontrol etme.
2. Benchmark çıktısına CV, P95, P99 ve baseline delta alanlarını ekleme.
3. `messages(session_id, id)` index doğrulaması + migration testi.

### P2 (orta vade)
1. Performans sonuçlarının tarihsel trendlenmesi (artifact/json saklama).
2. Tek çekirdek ve çok çekirdek karşılaştırmalı benchmark profilleri.
3. Donanım/sürücü metadata’sını her benchmark sonucuna zorunlu ekleme.

## 4) “Tüm dosyaları satır satır inceleme” talebine dair netlik

Repo genişliği nedeniyle tek yanıtta tüm dosyaları kelimenin tam anlamıyla satır satır dökümlemek
operasyonel olarak verimsiz olur. Bu raporda, paylaşılan benchmark çıktısıyla doğrudan ilgili
performans yolları (benchmark testleri, GPU smoke yardımcıları, ilgili utility ve DB akışları)
öncelikli ve proje uyumlu şekilde analiz edilmiştir.

Eğer isterseniz bir sonraki adımda bunu modül modül ilerletebilirim:
1) `core/` performans kritik yollar
2) `managers/` çağrı ve I/O maliyetleri
3) `agent/` orchestration gecikmeleri
4) `web_ui_react/` render/perf profili

## 5) Kısa karar

- Mevcut sonuçlar **başarılı ve üretim adayı** bir performans tabanına işaret ediyor.
- En yüksek kazanım alanları:
  - benchmark ölçüm saflığını artırmak (client/loop reuse),
  - DB tarafında transaction/bulk iyileştirmeleri,
  - TPS/VRAM gating’i daha istatistiksel hale getirmek.
