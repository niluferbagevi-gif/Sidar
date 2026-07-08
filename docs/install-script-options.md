# install_sidar.sh seçenekleri ve smoke gate opt-out notları

Bu dosya, `install_sidar.sh` için operatörlerin bilinçli kullanması gereken
bayrak ve environment override'larını özetler. Varsayılan akış, geliştirici ve CI
paritesi için smoke doğrulamaları otomatik çalıştırır; pahalı tam doğrulama ve
frontend kalite kapısı ise bilinçli opt-in gerektirir.

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

Önerilen normal kullanım smoke gate'leri açık bırakmaktır:

```bash
./install_sidar.sh --runtime-mode=local
```

Tanılama amaçlı geçici opt-out örnekleri:

```bash
./install_sidar.sh --skip-smoke-test
RUN_SMOKE_TESTS_MODE=never ./install_sidar.sh --runtime-mode=local
SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=0 ./install_sidar.sh --runtime-mode=local
```

## Frontend kalite kapısı ve tam doğrulama

Varsayılan development/local kurulum akışı React build ve smoke odaklıdır;
`run_tests.sh --stage all` veya frontend kalite kapısı otomatik başlatılmaz.
Kurulum sonunda frontend stage kullanıcıya manuel/opt-in doğrulama olarak sunulur;
loglarda `--with-integration verilmediği için frontend stage çalıştırılmadı` mesajı
beklenen bir durumdur. Bu mesaj, frontend testlerinin başarısız olduğu anlamına
gelmez; yalnızca pahalı lint/typecheck/Vitest coverage/Playwright smoke kapısının
başlangıç kurulumunda atlandığını gösterir.

Frontend kalite kapısını ayrıca çalıştırmak için:

```bash
RUN_FRONTEND_E2E=1 bash run_tests.sh --stage frontend
```

Tam doğrulamayı kurulum sırasında zorunlu yapmak için production readiness veya
CI full validation profili kullanılmalıdır:

```bash
./install_sidar.sh --production-readiness
# veya legacy CI alias'ı:
./install_sidar.sh --ci-full
```

Kurulum sonrası manuel tam doğrulama için kanonik komut:

```bash
RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all
```
