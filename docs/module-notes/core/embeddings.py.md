# `core/embeddings.py` — Embedding Model Yükleme/Önbellekleme

- **Kaynak dosya:** `core/embeddings.py`
- **Not dosyası:** `docs/module-notes/core/embeddings.py.md`

**Amaç:** `sentence-transformers` embedding modellerini zaman aşımı korumalı
biçimde yükler, process-içi önbellekler ve semantic cache için metin
embed eder; HuggingFace Hub cache dizinlerini tespit ederek yerel-dosya-only
yükleme kararı verir (ağ erişimi olmayan ortamlarda güvenli davranış).

**Özellikler:**
- `EmbeddingModelLoadTimeout(TimeoutError)` — model yükleme zaman aşımında
  fırlatılır.
- `_construct_sentence_transformer_with_timeout(...)` — model yüklemeyi
  ayrı thread'de zaman aşımı sınırıyla çalıştırır.
- `clear_model_cache()` — process-içi `_MODEL_CACHE`'i temizler.
- `sentence_transformer_device_from_config(cfg)` — CPU/GPU cihaz seçimini
  config'ten çözer.
- `_hf_hub_cache_roots()`, `_hf_model_cache_dir_names(model_name)`,
  `hf_model_cache_exists(model_name)`, `sentence_transformer_local_files_only(cfg, model_name)`
  — model zaten yerel cache'te varsa ağ erişimini atlama kararı.
- `embed_texts_for_semantic_cache(...)`, `get_sentence_transformer_model(...)`
  — semantic cache'in kullandığı üst düzey embed/model erişim API'si.
