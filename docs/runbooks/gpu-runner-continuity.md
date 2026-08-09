# Self-hosted GPU CI runner süreklilik planı

## Amaç ve SLO

GPU inference kalite kapısı fail-closed kalır; CPU emülasyonu veya checklist sonucu gerçek
TTFT/latency kanıtı yerine kullanılamaz. Tek makine arızasını kaldırmak için aynı repository
runner grubunda en az iki bağımsız host **online** tutulur:

- `sidar-gpu-primary`: normal kapasite;
- `sidar-gpu-standby`: farklı güç/host arıza alanında sıcak yedek;
- ikisinde de `self-hosted`, `linux`, `gpu` etiketleri ve aynı kilitli toolchain bulunur.

Hedef RTO 30 dakika, hedef RPO son başarılı benchmark artifact'ıdır. Standby runner haftalık
olarak gerçek `Nightly GPU Performance` işiyle döndürülmeli; yalnız kayıtlı görünmesi yeterli
değildir.

## Otomatik gözetim

`GPU Runner Capacity Watchdog` workflow'u saatlik olarak GitHub runner API'sini sorgular ve
iki uygun online runner bulunmadığında kırmızı olur. Repository secret olarak runner metadata
okuma yetkili, dar kapsamlı `GPU_RUNNER_MONITOR_TOKEN` tanımlanmalıdır. Yerel/fixture kontrolü:

```bash
uv run python scripts/ci/check_gpu_runner_capacity.py \
  --repo owner/Sidar --token "$GPU_RUNNER_MONITOR_TOKEN" --minimum-online 2
```

Bu watchdog merge kanıtının yerine geçmez; arızayı GPU işi kuyrukta süresiz beklemeden önce
görünür kılan erken uyarıdır.

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
