# Test Optimizasyon Planı (Sidar)

Bu plan, mevcut yüksek test hacmini (unit/integration/e2e/frontend) korurken çalıştırma süresini ve bakım maliyetini düşürmek için uygulanacak adımları içerir.

## 1) Hızlı Kazanımlar

1. `run_tests.sh` içinde `pytest-xdist` varsa paralel çalıştırma (`-n auto`) kullan.
2. Benchmark koşumunu `RUN_BENCHMARKS=0/1/auto` ile kontrol et.
3. Coverage quality gate (`fail_under=90`) korunurken flaky testler için ayrı quarantine listesi tut.

## 2) Piramit Disiplini

- Unit test: saf fonksiyon/sınıf davranışı (mock serbest).
- Integration test: gerçek bileşen iletişimi (örn. in-memory DB, local adapter).
- E2E test: yalnızca kritik kullanıcı akışları (tekrar eden detay assertion'lar unit'e taşınmalı).

## 3) Benchmark Kapsamı

`tests/test_benchmark.py` zamanla aşağıdaki kritik patikaları kapsamalı:

- RAG retrieval pipeline gecikmesi.
- DB pool altında eşzamanlı sorgu performansı.
- Agent routing + delegation latency.
- WebSocket broadcast throughput.

## 4) Coverage Agent Akışı

1. Coverage raporundan düşük kapsama dosyalarını çıkar.
2. Aynı davranışı tekrar test eden dosyaları işaretle.
3. `qa/coverage` ajanlarından hedefli test önerisi üret.
4. Üretilen testleri deterministik hale getir (network/random/time bağımlılıklarını izole et).

## 5) Operasyonel Öneri

- CI'da:
  - PR: hızlı smoke + kritik unit/integration seti
  - nightly: full suite + benchmark + mutation/smoke e2e
- Lokal geliştirmede:
  - `pytest -m "not e2e"` ile hızlı çevrim
  - dosya bazlı incremental test çalıştırma

