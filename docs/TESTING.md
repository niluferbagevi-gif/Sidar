# Test çalıştırma rehberi

Sidar'da iki farklı test akışı vardır:

## Hızlı tekil test / debug

Tek bir test fonksiyonunu veya küçük bir dosya grubunu incelerken doğrudan pytest
kullanın. Coverage gate bu akışta varsayılan olarak çalışmaz; böylece fonksiyonel
olarak geçen tekil testler toplam repo coverage düşük çıktığı için yanıltıcı şekilde
başarısız görünmez.

```bash
uv run pytest tests/unit/core/test_rag.py::test_fetch_pgvector_returns_empty_when_query_embedding_empty -q
```

Geçici olarak coverage eklenecekse ve gate istenmiyorsa açıkça `--no-cov` verilebilir:

```bash
uv run pytest tests/unit/core/test_rag.py::test_fetch_pgvector_returns_empty_when_query_embedding_empty -q --no-cov
```

## Kalite kapısı / coverage doğrulaması

Merge/PR öncesi ana doğrulama yolu `run_tests.sh` betiğidir. Coverage raporları ve
`.coveragerc` tabanlı fail-under kontrolü bu betik tarafından yönetilir.

```bash
./run_tests.sh
```

CI profilinde coverage eşiği daha sıkı çalıştırılabilir:

```bash
CI=true TEST_PROFILE=ci ./run_tests.sh
```
