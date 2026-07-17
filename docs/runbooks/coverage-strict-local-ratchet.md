# Coverage strict-local ratchet runbook

Sidar'ın günlük local/CI coverage kalite kapısı bilinçli olarak `pyproject.toml`
`[tool.coverage.report].fail_under = 99` tabanını ve varsayılan
`COVERAGE_RATCHET_MAX_GATE=99` tavanını kullanır. Bu, tam kapsam ölçümü
stabil olsa bile refactor, platform farkı veya tek satırlık branch dalgalanması
nedeniyle oluşabilecek `%0.x` oynama için bir puanlık operasyonel tampondur.

Bu varsayılan bir hata değildir; üretim öncesi veya olgun runnerlarda `%100`
regresyon kapısını denemek için açık opt-in gerekir.

## Ne zaman `COVERAGE_STRICT_LOCAL_RATCHET=1` kullanılır?

Aşağıdaki koşullar sağlanıyorsa strict-local ratchet açılabilir:

1. Aynı runner üzerinde art arda birkaç tam `./run_tests.sh` koşusu `%100.00`
   line/branch coverage üretmiştir.
2. Coverage düşüşü flaky test, platform farkı veya geçici dış bağımlılık kaynaklı
   değildir.
3. Ekibin hedefi günlük local gate'i de `%100` seviyesine yükseltmeyi denemektir;
   yalnızca campaign raporu almak isteniyorsa `COVERAGE_CAMPAIGN=1` tercih edilir.

## Komutlar

Günlük varsayılan tamponlu gate:

```bash
./run_tests.sh
```

Strict local ratchet opt-in — ratchet tavanını `%100` seviyesine açar:

```bash
COVERAGE_STRICT_LOCAL_RATCHET=1 ./run_tests.sh
```

Aynı davranışı açık tavanla zorlamak için:

```bash
COVERAGE_RATCHET_MAX_GATE=100 ./run_tests.sh
```

Coverage kampanyası profili — `%100` aspirasyonel hedef için:

```bash
COVERAGE_CAMPAIGN=1 ./run_tests.sh
```

## Karar kaydı

- Varsayılan local/CI cap: `%99`.
- Strict opt-in cap: `%100` (`COVERAGE_STRICT_LOCAL_RATCHET=1` veya
  `COVERAGE_RATCHET_MAX_GATE=100`).
- Campaign cap: `%100` (`COVERAGE_CAMPAIGN=1` veya
  `AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign`).

Bu ayrım, günlük kalite kapısının geliştirici akışını gereksiz yere kırmamasını
sağlarken, gerçekten stabil `%100` ölçümlerde regresyonları yakalamak isteyen
runnerlara fail-closed bir strict seçenek verir.
