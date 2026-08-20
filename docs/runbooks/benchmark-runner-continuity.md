# Self-hosted benchmark runner süreklilik planı

## Amaç

`Benchmark compare gate`, kararlı latency karşılaştırması için bilinçli olarak
`[self-hosted, linux, benchmark]` runner üzerinde çalışır. GitHub-hosted runner'a otomatik
fallback yapılmaz; uygun runner offline ise production readiness fail-closed kalır.

Primary ve farklı bir arıza alanındaki warm-standby host aynı
`self-hosted`, `linux`, `benchmark` etiketlerini taşır. Saatlik `Benchmark Runner Capacity
Watchdog`, iki uygun online runner ve yeni işi alabilecek en az bir idle runner bulunmadığını
bildirir. Her `CI` workflow'u requested olduğunda da kontrol hemen çalışır; queue sorunu bir
sonraki saatlik schedule'ı beklemez. GitHub
runner metadata okuma yetkili, dar kapsamlı `BENCHMARK_RUNNER_MONITOR_TOKEN` repository secret'ı
tanımlanmalıdır. Yerel veya fixture doğrulaması:

```bash
uv run python scripts/ci/check_benchmark_runner_capacity.py \
  --repo niluferbagevi-gif/Sidar \
  --token "$BENCHMARK_RUNNER_MONITOR_TOKEN" \
  --minimum-online 2 \
  --minimum-idle 1
```

Watchdog yalnız kapasite erken uyarısıdır; benchmark compare sonucunun veya incelenmiş baseline
kanıtının yerine geçmez. Başarısız koşu aynı başlıklı GitHub issue'sunu oluşturur veya günceller;
çıktı online/offline, busy/idle ve eksik label teşhisini içerir. Runner yeniden online olduktan
sonra watchdog'u ve bekleyen benchmark
job'ını yeniden çalıştırın. Baseline cache bulunamazsa documented seed workflow kullanılmalı;
compare kapısı gevşetilmemeli veya GitHub-hosted donanıma taşınmamalıdır.

## Host başına baseline hazırlığı

Benchmark cache anahtarı kasıtlı olarak `${{ runner.name }}` içerir; bu nedenle yalnız ikinci
runner'ı online yapmak gerçek failover sağlamaz. Primary ve warm-standby hostların her birinde
reviewed baseline ayrı ayrı seed edilmelidir. Seed workflow'unu ilgili runner üzerinde çalıştırın,
ardından aynı hostta strict compare çalıştırıp cache/artifact kanıtını doğrulayın. Runner yeniden
adlandırılır veya değiştirilirse o hostun baseline'ı tekrar seed edilmeden release yapılmaz.

Üç aylık tatbikatta primary servisini durdurun; benchmark compare'ın standby üzerinde strict
baseline ile geçtiğini, watchdog'un tek online runner durumunu kırmızı raporladığını ve primary
döndüğünde iki-online/bir-idle politikasının yeniden sağlandığını doğrulayın.

Baseline cache yokluğunu PR'dan önce bildirme ve iki seed yolunu ortak bir `workflow_call`
workflow'una çıkarma işleri ayrı, gerçek benchmark runner üzerinde doğrulanacak takip işidir.
