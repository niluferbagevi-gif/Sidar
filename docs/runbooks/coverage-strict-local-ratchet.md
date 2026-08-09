# Coverage %100 ratchet runbook

## Varsayılan politika

Yerel ve CI profilleri `[tool.coverage.report].fail_under = 100` tabanını ve
`COVERAGE_RATCHET_MAX_GATE=100` tavanını kullanır. Varsayılan local/CI cap: `%100`.
Bu değer, doğrulanmış tam kapsam ölçümünü kalıcı merge tabanına çevirir; sonraki
`%99.x` ölçümleri final coverage raporunda fail-closed sonuçlanır.

## Doğrulama

Standart yerel kapıyı çalıştırın:

```bash
./run_tests.sh
```

Ratchet'in yalnız yukarı hareket ettiğini ayrıca doğrulamak için:

```bash
uv run pytest -q tests/unit/scripts/test_coverage_ratchet.py
```

`COVERAGE_FAIL_UNDER`, profil bazlı eşikler ve `COVERAGE_RATCHET_MAX_GATE` geriye
dönük uyumluluk ve kontrollü teşhis için desteklenir. Merge/release doğrulamasında
bu değerleri `%100` altına indirmek standart politika değildir; böyle bir çalıştırma
üretim readiness kanıtı olarak kullanılmamalıdır.
