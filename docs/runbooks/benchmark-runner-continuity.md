# Self-hosted benchmark runner süreklilik planı

## Amaç

`Benchmark compare gate`, kararlı latency karşılaştırması için bilinçli olarak
`[self-hosted, linux, benchmark]` runner üzerinde çalışır. GitHub-hosted runner'a otomatik
fallback yapılmaz; uygun runner offline ise production readiness fail-closed kalır.

Saatlik `Benchmark Runner Capacity Watchdog`, pull request açıldıktan sonra job'ın uzun süre
queue'da kalmasını beklemeden en az iki uygun online runner bulunmadığını bildirir (GPU
gate'teki aynı redundancy deseni — bkz. aşağıdaki hedef mimari). GitHub runner metadata okuma
yetkili, dar kapsamlı `BENCHMARK_RUNNER_MONITOR_TOKEN` repository secret'ı tanımlanmalıdır.
Yerel veya fixture doğrulaması:

```bash
uv run python scripts/ci/check_benchmark_runner_capacity.py \
  --repo niluferbagevi-gif/Sidar \
  --token "$BENCHMARK_RUNNER_MONITOR_TOKEN" \
  --minimum-online 2
```

Watchdog yalnız kapasite erken uyarısıdır; benchmark compare sonucunun veya incelenmiş baseline
kanıtının yerine geçmez. Runner yeniden online olduktan sonra watchdog'u ve bekleyen benchmark
job'ını yeniden çalıştırın. Baseline cache bulunamazsa documented seed workflow kullanılmalı;
compare kapısı gevşetilmemeli veya GitHub-hosted donanıma taşınmamalıdır.

Baseline cache yokluğunu PR'dan önce bildirme ve iki seed yolunu ortak bir `workflow_call`
workflow'una çıkarma işleri ayrı, gerçek benchmark runner üzerinde doğrulanacak takip işidir.

## Hedef mimari: primary + warm-standby (kısmen uygulandı)

GPU gate'te olduğu gibi tek host'a bağımlılığı kaldırmak için hedef, aynı repository runner
grubunda farklı arıza alanlarında en az iki bağımsız host'tur:

- `sidar-benchmark-primary`: normal kapasite, mevcut incelenmiş baseline cache'inin sahibi;
- `sidar-benchmark-standby`: farklı güç/host arıza alanında sıcak yedek;
- ikisinde de `self-hosted`, `linux`, `benchmark` etiketleri ve aynı kilitli toolchain bulunur.

**GPU redundancy'sinden temel fark:** GPU runner'ları birbirinden bağımsız çalışır — her host
kendi TTFT/latency ölçümünü sabit bütçelere (`≤200ms`/`≤250ms`) karşı test eder, hiçbir
host-arası veri paylaşımı gerekmez. Benchmark runner'ları böyle değildir: baseline cache
key'i `${{ runner.name }}` içerir, yani standby'ın primary'nin baseline'ını otomatik
"görmesi" mümkün değildir. Standby gerçek bir yedek sayılmadan önce üç şey ayrıca
tamamlanmalıdır:

1. Standby'da `seed_benchmark_baseline=true` ile **kendi** incelenmiş baseline'ı seed
   edilmeli. GitHub aynı etiketli iki runner'dan hangisinin işi alacağını seçtiremediği için,
   ilk seed sırasında ya primary geçici olarak durdurulmalı ya da standby'a işi zorlayacak
   ayrı bir geçici etiket/`runs-on` hedefi kullanılmalı.
2. `benchmark-baseline-keepalive.yml`'ın Pazartesi/Perşembe cadence'i standby'ı da gerçekten
   kapsadığı doğrulanmalı — GitHub idle runner'lar arasında rastgele seçim yaptığı için bu
   varsayılan olarak garanti değildir.
3. Standby'a düşen bir `benchmark-compare` job'ının kendi seed edilmiş baseline'ını bulup
   karşılaştırmayı doğru şekilde tamamladığı en az bir gerçek PR'da doğrulanmalı.

Bu üç adım tamamlanana kadar watchdog'un `--minimum-online 2` istemesi doğru bir hedef
sinyalidir, ama tek başına yeterli değildir — ikinci host online görünse bile üzerinde
seed edilmiş bir baseline yoksa o host'a düşen iş yine fail-closed olur.

## Failover prosedürü

1. Primary offline ise standby servisinin online olduğunu ve kendi seed edilmiş baseline'ının
   var olduğunu doğrulayın (bkz. yukarıdaki adım 1) — salt "online" görünmesi yeterli değildir.
2. Standby aynı ortak etiketleri taşıdığı için bekleyen GitHub işi otomatik ona atanır; workflow
   veya required-check adını değiştirmeyin.
3. `benchmark-compare` job'ını yeniden çalıştırın ve karşılaştırma sonucunu/artifact'ını
   doğrulayın. İncelenmiş baseline kanıtı oluşmadan `production-readiness` bypass edilmez.
4. Primary host'u karantinaya alın; toolchain/driver drift'ini giderin ve canary karşılaştırma
   geçmeden tekrar runner havuzuna eklemeyin.
5. İki runner tekrar online olduğunda watchdog'u manuel çalıştırın ve olay kaydına kök neden ile
   kullanılan artifact run ID'sini yazın.

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
