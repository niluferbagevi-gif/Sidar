# Self-hosted benchmark runner süreklilik planı

## Amaç

`Benchmark compare gate`, kararlı latency karşılaştırması için bilinçli olarak
`[self-hosted, linux, benchmark]` runner üzerinde çalışır. GitHub-hosted runner'a otomatik
fallback yapılmaz; uygun runner offline ise production readiness fail-closed kalır.

Saatlik `Benchmark Runner Capacity Watchdog`, pull request açıldıktan sonra job'ın uzun süre
queue'da kalmasını beklemeden en az bir uygun online runner bulunmadığını bildirir. GitHub
runner metadata okuma yetkili, dar kapsamlı `BENCHMARK_RUNNER_MONITOR_TOKEN` repository secret'ı
tanımlanmalıdır. Yerel veya fixture doğrulaması:

```bash
uv run python scripts/ci/check_benchmark_runner_capacity.py \
  --repo niluferbagevi-gif/Sidar \
  --token "$BENCHMARK_RUNNER_MONITOR_TOKEN" \
  --minimum-online 1
```

Watchdog yalnız kapasite erken uyarısıdır; benchmark compare sonucunun veya incelenmiş baseline
kanıtının yerine geçmez. Runner yeniden online olduktan sonra watchdog'u ve bekleyen benchmark
job'ını yeniden çalıştırın. Baseline cache bulunamazsa documented seed workflow kullanılmalı;
compare kapısı gevşetilmemeli veya GitHub-hosted donanıma taşınmamalıdır.

Baseline cache yokluğunu PR'dan önce bildirme ve iki seed yolunu ortak bir `workflow_call`
workflow'una çıkarma işleri ayrı, gerçek benchmark runner üzerinde doğrulanacak takip işidir.
