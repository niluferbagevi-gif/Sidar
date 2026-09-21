# `core/config_rag_entity.py` — RAG LLM Entity Extraction Ayarları

- **Kaynak dosya:** `core/config_rag_entity.py`
- **Not dosyası:** `docs/module-notes/core/config_rag_entity.py.md`

**Amaç:** `core/rag/__init__.py`'nin LLM tabanlı entity extraction
(`RAG_LLM_ENTITY_*`) için kullandığı 4 alanı
(`ENABLE_RAG_LLM_ENTITY_EXTRACTION`, `RAG_LLM_ENTITY_PROVIDER`,
`RAG_LLM_ENTITY_MODEL`, `RAG_LLM_ENTITY_REVIEW_TARGET`) `RagEntitySettings`
frozen dataclass'ı olarak yükler; `config.Config` bunu `rag_entity_settings`
olarak expose eder ve aynı 4 alanı geriye dönük uyumlu `Config.FOO` class
attribute'larına delege eder (`docs/REFACTOR_PLAN.md`'nin `config.py`
maddesinde otonomi servisi webhook diliminden sonra işaretlenen sıradaki
düşük riskli dilim). Bu dilim kasıtlı olarak yalnız LLM tabanlı entity
extraction alanlarını kapsar; genel (non-LLM) `ENABLE_RAG_ENTITY_EXTRACTION`/
`RAG_ENTITY_MAX_PER_DOC` ve GraphRAG `ENABLE_GRAPH_RAG`/`GRAPH_RAG_MAX_FILES`
alanları farklı bir kapsam olduğundan bu dilimin dışında bırakıldı.
`core/rag/__init__.py`'nin `getattr(self.cfg,
"ENABLE_RAG_LLM_ENTITY_EXTRACTION", False)` gibi mevcut alan adlarıyla
tüketmesi değişmeden korunur.

**Özellikler:**
- `RagEntitySettings` — `enable_rag_llm_entity_extraction`,
  `rag_llm_entity_provider`, `rag_llm_entity_model`,
  `rag_llm_entity_review_target`.
- `load_rag_entity_settings()` — her alanı kendi ortam değişkeninden okur;
  boolean alan (`get_bool_env()`) katı "true"/"false" ayrıştırması
  kullanır.
