# Self-hosted GPU CI runner süreklilik planı

## Amaç ve SLO

GPU inference kalite kapısı fail-closed kalır; CPU emülasyonu veya checklist sonucu gerçek
TTFT/latency kanıtı yerine kullanılamaz. Tek makine arızasını kaldırmak için aynı repository
runner grubunda en az iki bağımsız host **online** tutulur:

- `sidar-gpu-primary`: normal kapasite;
- `sidar-gpu-standby`: farklı güç/host arıza alanında sıcak yedek;
- ikisinde de `self-hosted`, `linux`, `x64`, `gpu`, `cuda` etiketleri ve aynı kilitli toolchain bulunur.

Hedef RTO 30 dakika, hedef RPO son başarılı benchmark artifact'ıdır. Standby runner haftalık
olarak gerçek `Nightly GPU Performance` işiyle döndürülmeli; yalnız kayıtlı görünmesi yeterli
değildir.

## Otomatik gözetim

`GPU Runner Capacity Watchdog` workflow'u saatlik olarak önce repository variable
`ENABLE_GPU_BENCH_GATE` değerinin tam olarak `true` kaldığını doğrular, ardından GitHub runner
API'sini sorgular ve iki uygun online runner bulunmadığında kırmızı olur. Repository secret olarak runner metadata
okuma yetkili, dar kapsamlı `GPU_RUNNER_MONITOR_TOKEN` tanımlanmalıdır. Yerel/fixture kontrolü:

```bash
uv run python scripts/ci/check_gpu_runner_capacity.py \
  --repo owner/Sidar --token "$GPU_RUNNER_MONITOR_TOKEN" --minimum-online 2
```

Bu watchdog merge kanıtının yerine geçmez; arızayı GPU işi kuyrukta süresiz beklemeden önce
görünür kılan erken uyarıdır.

> Repository variable ve self-hosted runner kapasitesi Git içinde oluşturulamaz veya sürekli
> açık tutulamaz; bunlar GitHub repository/runner yönetim düzlemine aittir. Bu nedenle workflow
> herhangi birinin eksikliğini saatlik fail-closed sinyale dönüştürür. Gerçek release kanıtı yine
> her CI çalışmasındaki `GPU Inference Quality Gate` sonucudur; yerel benchmark kabul edilmez.

## Repository kontrol düzlemi kurulumu

Bu ayarlar repository yöneticisi tarafından GitHub kontrol düzleminde yapılır; workflow veya
`.env` içine değer gömülmez. Yetkili bir `gh` oturumuyla değişkeni etkinleştirin ve GitHub'dan
geri okuyarak yazma işlemini doğrulayın:

```bash
REPOSITORY=niluferbagevi-gif/Sidar
gh variable set ENABLE_GPU_BENCH_GATE --body true --repo "$REPOSITORY"
test "$(gh variable get ENABLE_GPU_BENCH_GATE --repo "$REPOSITORY")" = "true"
```

Ardından repository runner yönetim ekranında farklı arıza alanlarındaki iki hostun da
`self-hosted`, `linux`, `x64`, `gpu`, `cuda` etiketlerini taşıdığını ve online olduğunu
doğrulayın. `GPU_RUNNER_MONITOR_TOKEN` için Actions runner metadata okuma yetkili, dar kapsamlı
bir token tanımlandıktan sonra watchdog'u manuel çalıştırın:

```bash
gh workflow run gpu-runner-capacity-watchdog.yml --repo "$REPOSITORY"
gh run list --workflow gpu-runner-capacity-watchdog.yml --repo "$REPOSITORY" --limit 1
```

Son koşu yeşil olmadan ve aynı commit için `GPU Inference Quality Gate` artifact'ı oluşmadan
release kanıtı tamamlanmış sayılmaz. Değişkenin boş/`false` olması veya iki runner'dan birinin
offline kalması halinde release dondurulur; yerel GPU sonucu bu kontrolü bypass edemez.

## Failover prosedürü

1. Primary offline ise standby servisinde runner'ı ve `nvidia-smi` görünürlüğünü doğrulayın.
2. Standby aynı ortak etiketleri taşıdığı için bekleyen GitHub işi otomatik ona atanır; workflow
   veya required-check adını değiştirmeyin.
3. `GPU Inference Quality Gate` workflow'unu yeniden çalıştırın ve JUnit/benchmark artifact'ını
   doğrulayın. Kanıt oluşmadan `gpu-inference-policy-gate` bypass edilmez.
4. Primary host'u karantinaya alın; driver/CUDA/Ollama sürüm drift'ini giderin ve canary benchmark
   geçmeden tekrar runner havuzuna eklemeyin.
5. İki runner tekrar online olduğunda watchdog'u manuel çalıştırın ve olay kaydına RTO, kök neden
   ile kullanılan artifact run ID'sini yazın.

## ⚠️ Confirmed gap: watchdog hiçbir zaman gerçekten kapasite kontrolü yapmadı

Bir arkadaş kod incelemesi PR #2755'in `GPU Inference Quality Gate` job'ının `queued` kalmasını
sorgulaması üzerine GitHub Actions run geçmişi doğrudan kontrol edildi: `GPU Runner Capacity
Watchdog` kurulduğu günden bu yana incelenebilen **her çalıştırmasında** (saatlik, 326 run)
`ENABLE_GPU_BENCH_GATE` adımı geçiyor (repository variable doğru şekilde `true`), ama `Check
primary and warm-standby capacity` adımında `GPU_RUNNER_MONITOR_TOKEN` boş olduğu için
`GPU runner watchdog için --repo/GITHUB_REPOSITORY ve --token/GPU_RUNNER_MONITOR_TOKEN
gerekli.` hatasıyla `exit 2` ile başarısız olmuş. Repository secret'ı hiç oluşturulmamış.
Sonuç: bu watchdog **hiçbir zaman gerçekten GitHub runner API'sini sorgulayıp iki online GPU
runner olup olmadığını döndürmedi** — her saatlik çalıştırma aynı ön-kontrol hatasında
duruyor. `main` üzerinde şu an `sidar-gpu-primary`/`sidar-gpu-standby` gerçekten online mı, bu
runbook'taki hiçbir otomasyon tarafından teyit edilmemiştir; PR #2755'in `GPU Inference Quality
Gate` job'ının merge anında hâlâ `queued` olması ve `GPU Inference Required Evidence Gate`ın
takip eden CI çalışmalarında düzenli kırmızı olması bununla tutarlıdır. Kapatmak için
repository admin'i GitHub Settings → Actions → Runners'ı doğrudan açıp iki hostun
Idle/Online göründüğünü gözle doğrulamalı (watchdog bunu şu an teyit edemiyor), GitHub runner
metadata okuma yetkili bir PAT/App token oluşturup `GPU_RUNNER_MONITOR_TOKEN` secret'ı olarak
eklemeli, ardından watchdog'u `workflow_dispatch` ile manuel çalıştırıp ilk gerçek sonucu
almalıdır.

## Üç aylık tatbikat

Primary runner servisini kontrollü durdurun, bir GPU gate'inin standby üzerinde tamamlandığını
ve watchdog'un tek-runner durumunu yakaladığını doğrulayın. Tatbikat sırasında branch protection
ve `ENABLE_GPU_BENCH_GATE` gevşetilemez. Standby başarısızsa release dondurulur; geçici CPU veya
operatör onayıyla yeşil sonuç üretilmez.
