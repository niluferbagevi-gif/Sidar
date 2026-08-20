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

## ⚠️ Confirmed gap: watchdog hiçbir zaman gerçekten kapasite kontrolü yapmadı

Bir arkadaş kod incelemesi PR #2755'in `Benchmark compare gate` job'ının `queued` kalmasını
sorgulaması üzerine GitHub Actions run geçmişi doğrudan kontrol edildi: `Benchmark Runner
Capacity Watchdog` kurulduğu günden bu yana incelenebilen **her çalıştırmasında** (saatlik,
142 run) `Check stable benchmark runner capacity` adımında `BENCHMARK_RUNNER_MONITOR_TOKEN`
boş olduğu için `--repo/GITHUB_REPOSITORY and BENCHMARK_RUNNER_MONITOR_TOKEN are required.`
hatasıyla `exit 2` ile başarısız olmuş. Repository secret'ı hiç oluşturulmamış. Sonuç: bu
watchdog **hiçbir zaman gerçekten GitHub runner API'sini sorgulayıp bir online benchmark
runner sayısı döndürmedi** — her saatlik çalıştırma aynı ön-kontrol hatasında duruyor. `main`
üzerinde şu an gerçekten uygun bir `[self-hosted, linux, benchmark]` runner online mı, bu
runbook'taki hiçbir otomasyon tarafından teyit edilmemiştir; PR #2755'in `Benchmark compare
gate` job'ının merge anında hâlâ `queued` olması bununla tutarlıdır. Kapatmak için repository
admin'i GitHub runner metadata okuma yetkili bir PAT/App token oluşturup
`BENCHMARK_RUNNER_MONITOR_TOKEN` secret'ı olarak eklemeli, ardından watchdog'u
`workflow_dispatch` ile manuel çalıştırıp ilk gerçek sonucu almalıdır.
