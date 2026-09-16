# Self-hosted benchmark runner süreklilik planı

## Runner host bootstrap ön koşulları

Bu runbook, `[self-hosted, linux, benchmark]` etiketli runner'ın **zaten kurulu ve online**
olduğunu varsayar (aşağıdaki bölümler kapasite/watchdog/failover ile ilgilenir, ilk kurulumla
değil). Sıfırdan bir host hazırlarken şu adım atlanırsa `./config.sh` veya runner servisi
belirsiz bir `libicu`/`.NET Core 6` bağımlılık hatasıyla başarısız olur — bu Sidar'ın kendi
kodundan değil, GitHub Actions runner ikilisinin (.NET Core 6 tabanlı) kendi gereksinimidir:

```bash
# actions-runner paketini açtıktan sonra, ./config.sh çalıştırmadan ÖNCE:
sudo ./bin/installdependencies.sh
```

Bu betik dağıtıma göre değişen `libicu`/ICU paketlerini ve diğer .NET çalışma zamanı
bağımlılıklarını kurar. Aynı gereksinim `gpu-runner-continuity.md`'deki
`[self-hosted, linux, x64, gpu, cuda]` runner için de geçerlidir.

## Amaç

`Benchmark compare gate`, kararlı latency karşılaştırması için bilinçli olarak
`[self-hosted, linux, benchmark]` runner üzerinde çalışır. GitHub-hosted runner'a otomatik
fallback yapılmaz; uygun runner offline ise production readiness fail-closed kalır.

> **Mevcut kabul edilen durum (tek host):** `sidar-gpu-primary` ve `sidar-gpu-standby` şu an
> **aynı fiziksel makinede** kayıtlı — isim çağrışımının aksine gerçek bir arıza-alanı
> redundancy'si sağlamıyorlardı (üretimde doğrulandı: 2026-09-15, tek bir ağ kopması ikisini de
> eşzamanlı düşürdü). Operatör bunu kabul etmiş ve standby'yi kaldırmıştır; watchdog artık
> `--minimum-online 1` ile çalışır. Tek host arızalanırsa `Benchmark compare gate` de düşer — bu
> beklenen davranıştır, gevşetilmez veya GitHub-hosted donanıma kaydırılmaz.

Gerçek arıza-alanı redundancy'si isteniyorsa, ikinci runner **ayrı bir fiziksel makinede veya
bağımsız bir cloud host'ta** (farklı güç/ağ kaynağı) kurulmalı ve aynı `self-hosted`, `linux`,
`benchmark` etiketlerini taşımalıdır; o noktada watchdog `--minimum-online 2`'ye geri alınmalı.

Saatlik `Benchmark Runner Capacity Watchdog`, yapılandırılan asgari sayıda uygun online runner
bulunmadığını bildirir. Her `CI` workflow'u requested olduğunda da kontrol hemen çalışır; queue
sorunu bir sonraki saatlik schedule'ı beklemez.

> **Neden `--minimum-idle` kullanılmıyor:** Betik `--minimum-idle` bayrağını hâlâ destekler
> (gerçek çoklu-host redundancy kurulursa kullanılabilir), ama tek host'ta watchdog bunu
> geçirmez — `types: [requested]` tetikleyicisi yeni iş kuyruğa girer girmez ateşlenir ve tek
> runner o anda başka bir işi bitiriyor olabilir; bu sağlıksız değildir. `--minimum-idle 1`
> dayatmak, runner meşgulken (aktif CI trafiğinde sürekli) sahte kırmızı/issue-spam üretir.

GitHub runner metadata okuma yetkili, dar kapsamlı `BENCHMARK_RUNNER_MONITOR_TOKEN`
repository secret'ı tanımlanmalıdır. Yerel veya fixture doğrulaması:

```bash
uv run python scripts/ci/check_benchmark_runner_capacity.py \
  --repo niluferbagevi-gif/Sidar \
  --token "$BENCHMARK_RUNNER_MONITOR_TOKEN" \
  --minimum-online 1
```

Watchdog yalnız kapasite erken uyarısıdır; benchmark compare sonucunun veya incelenmiş baseline
kanıtının yerine geçmez. Başarısız koşu aynı başlıklı GitHub issue'sunu oluşturur veya günceller;
çıktı online/offline, busy/idle ve eksik label teşhisini içerir. Runner yeniden online olduktan
sonra watchdog'u ve bekleyen benchmark
job'ını yeniden çalıştırın. Baseline cache bulunamazsa documented seed workflow kullanılmalı;
compare kapısı gevşetilmemeli veya GitHub-hosted donanıma taşınmamalıdır.

## Host başına baseline hazırlığı

Benchmark cache anahtarı kasıtlı olarak `${{ runner.name }}` içerir; gerçek çoklu-host bir
kurulumda yalnız ikinci runner'ı online yapmak yeterli failover sağlamaz — her host için ayrı
reviewed baseline seed edilmelidir. Seed workflow'unu ilgili runner üzerinde çalıştırın, ardından
aynı hostta strict compare çalıştırıp cache/artifact kanıtını doğrulayın. Runner yeniden
adlandırılır veya değiştirilirse o hostun baseline'ı tekrar seed edilmeden release yapılmaz.

**Tek host kesintisi (mevcut kurulum):** Host'un ağı koparsa (WSL2'de bilinen semptom:
`Runner connect error: Resource temporarily unavailable`), çalışan job "Abandoned" olur. Host'ta
`sudo systemctl status actions.runner.*` ile servisi kontrol edin, gerekirse
`sudo ./svc.sh stop && sudo ./svc.sh start` ile yeniden başlatın, GitHub'da runner'ın **Idle**
olduğunu doğrulayıp başarısız job'ları yeniden tetikleyin.

Üç aylık tatbikat (yalnızca gerçek çoklu-host kurulumunda geçerli): primary servisini durdurun;
benchmark compare'ın standby üzerinde strict baseline ile geçtiğini, watchdog'un tek online runner
durumunu kırmızı raporladığını ve primary döndüğünde iki-online/bir-idle politikasının yeniden
sağlandığını doğrulayın. Tek host'ta bu tatbikat uygulanamaz; ikinci bağımsız host kurulana kadar
askıdadır.

Baseline cache yokluğunu PR'dan önce bildirme ve iki seed yolunu ortak bir `workflow_call`
workflow'una çıkarma işleri ayrı, gerçek benchmark runner üzerinde doğrulanacak takip işidir.
