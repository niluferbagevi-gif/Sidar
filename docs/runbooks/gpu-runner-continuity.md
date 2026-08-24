# Self-hosted GPU CI runner süreklilik planı

## Runner host bootstrap ön koşulları

Bu runbook, runner'ın zaten kurulu ve online olduğunu varsayar. Sıfırdan bir host hazırlarken
`./config.sh` öncesi `sudo ./bin/installdependencies.sh` çalıştırılmalıdır (GitHub Actions
runner ikilisinin, .NET Core 6 tabanlı olduğu için gerektirdiği `libicu` vb. bağımlılıklar için) —
ayrıntı ve gerekçe: `benchmark-runner-continuity.md` → "Runner host bootstrap ön koşulları".

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
API'sini sorgular; iki uygun online runner veya kuyruktaki yeni işi alabilecek en az bir idle
runner bulunmadığında kırmızı olur. Her `CI` workflow'u requested durumuna geçtiğinde de aynı
kontrol hemen tetiklenir; böylece label/service/kapasite sorunu saatlik schedule beklemez.
Repository secret olarak runner metadata
okuma yetkili, dar kapsamlı `GPU_RUNNER_MONITOR_TOKEN` tanımlanmalıdır. Yerel/fixture kontrolü:

```bash
uv run python scripts/ci/check_gpu_runner_capacity.py \
  --repo owner/Sidar --token "$GPU_RUNNER_MONITOR_TOKEN" \
  --minimum-online 2 --minimum-idle 1
```

Bu watchdog merge kanıtının yerine geçmez; arızayı GPU işi kuyrukta süresiz beklemeden önce
görünür kılan erken uyarıdır.

Başarısız watchdog koşusu aynı başlıklı açık uyarı issue'sunu günceller veya yoksa oluşturur.
Hata çıktısındaki `envanter` alanı her runner için online/offline, busy/idle ve eksik zorunlu
etiketleri gösterir; token veya runner credential bilgisi yazdırılmaz.

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

## Üç aylık tatbikat

Primary runner servisini kontrollü durdurun, bir GPU gate'inin standby üzerinde tamamlandığını
ve watchdog'un tek-runner durumunu yakaladığını doğrulayın. Tatbikat sırasında branch protection
ve `ENABLE_GPU_BENCH_GATE` gevşetilemez. Standby başarısızsa release dondurulur; geçici CPU veya
operatör onayıyla yeşil sonuç üretilmez.
