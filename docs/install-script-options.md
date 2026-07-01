# install_sidar.sh seçenekleri ve smoke gate opt-out notları

Bu dosya, `install_sidar.sh` için operatörlerin bilinçli kullanması gereken
bayrak ve environment override'larını özetler. Varsayılan akış, geliştirici ve CI
paritesi için mümkün olduğunca tam doğrulama çalıştırır.

## Smoke test davranışı

- `--smoke-test`: Kurulum sonundaki smoke testleri zorunlu çalıştırır.
- `--skip-smoke-test`: Kurulum sonundaki smoke testleri ve lokal runtime'daki
  servis öncesi installer smoke gate'i atlar. Bu bayrak içeride
  `RUN_SMOKE_TESTS_MODE=never` değerine karşılık gelir.
- `RUN_SMOKE_TESTS_MODE=never`: Bayrak kullanmadan aynı opt-out davranışını
  environment üzerinden uygular. Bu değer yalnız geçici tanılama, kırık host
  ortamını izole etme veya zaten ayrı CI gate'leri çalışmış senaryolarda
  kullanılmalıdır.
- `SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=0`: Sadece lokal runtime'da Docker
  servisleri başlamadan önce çalışan pre-service installer smoke gate'i kapatır;
  kurulum sonu smoke test politikasını tek başına değiştirmez.
- `SIDAR_INSTALL_SMOKE_BASH_TIMEOUT=<saniye>`: Pre-service installer smoke
  gate'inin `bash` alt süreçlerine uyguladığı per-test timeout süresini
  değiştirir. Varsayılan `180` saniyedir. WSL2 + Windows Defender veya soğuk
  kernel cache gibi yavaş `fork()` ortamlarında `240` ya da daha yüksek bir
  değer verildiğinde installer bu değeri smoke gate'i çalıştıran `pytest`
  komutuna doğrudan aktarır. Geçerli değer pozitif tamsayı olmalıdır; boş,
  sıfır veya alfasayısal olmayan girişlerde installer bir uyarıyla `180`
  saniyelik varsayılana geri döner.

Önerilen normal kullanım smoke gate'leri açık bırakmaktır:

```bash
./install_sidar.sh --runtime-mode=local
```

Tanılama amaçlı geçici opt-out veya timeout artırma örnekleri:

```bash
./install_sidar.sh --skip-smoke-test
RUN_SMOKE_TESTS_MODE=never ./install_sidar.sh --runtime-mode=local
SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=0 ./install_sidar.sh --runtime-mode=local
SIDAR_INSTALL_SMOKE_BASH_TIMEOUT=240 ./install_sidar.sh --runtime-mode=local
```
