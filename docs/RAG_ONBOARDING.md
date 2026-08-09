# RAG ve pgvector onboarding

Sidar kurulumunda repo belgeleri başlangıç bilgi tabanı olarak kullanılır. Geliştirici
modunda başarılı Alembic migrasyonundan sonra `AUTO_SEED_RAG_METADATA=true` varsayılanıyla
`scripts.seed_rag --metadata-only` çalışır. Bu hızlı adım yerel index, BM25 ve GraphRAG
entity projection verisini hazırlar; Chroma veya pgvector embedding üretmez. Tam Docker
modundaki `AUTO_SEED_RAG_DOCKER_WARMUP=true` akışı ise container içinde tam seed çalıştırır.

## İlk doğrulama

```bash
uv run python -m core.doctor artifacts/install/doctor.json
```

`rag_index_ready` ve `graphrag_entity_memory_ready` geçmiyorsa metadata seed'i yeniden
çalıştırın:

```bash
uv run python -m scripts.seed_rag --metadata-only
```

Vektör backend'i de doldurmak veya mevcut belgeleri yeniden indekslemek için tam seed
kullanın:

```bash
uv run python -m scripts.seed_rag
```

Otomatik seed istenmiyorsa kurulumu
`AUTO_SEED_RAG_METADATA=false AUTO_SEED_RAG_DOCKER_WARMUP=false ./install_sidar.sh`
ile başlatabilirsiniz.

## pgvector gerçekten etkin mi?

`.env` içinde `RAG_VECTOR_BACKEND=pgvector` bulunması yalnız tercih edilen backend'i
belirtir; pgvector'ın başarıyla başladığını garanti etmez. PostgreSQL, `vector` extension,
Python bağımlılıkları veya embedding modeli hazır değilse Sidar uyarı logu üreterek BM25
fallback ile çalışmaya devam eder.

Şu sırayla doğrulayın:

1. Doctor raporunda `database_env`, `database_connectivity` ve `pgvector_ready`
   kontrollerinin geçtiğini doğrulayın.
2. `uv sync --all-extras` ile PostgreSQL/pgvector bağımlılıklarını kurun.
3. `docker compose up -d postgres` ardından tam seed komutunu çalıştırın.
4. Uygulama logunda `pgvector backend başlatıldı` kaydını arayın. `pgvector pasif, BM25
   fallback aktif` uyarısı varsa aynı uyarıdaki veritabanı teşhisini giderin.

Özel kaynaklar tekrarlanabilir `--include` parametresiyle eklenebilir:

```bash
uv run python -m scripts.seed_rag --include 'docs/*.md' --include README.md
uv run python cli.py -c "belge ekle <url>"
```
