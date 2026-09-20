# `core/config_github_hf.py` — GitHub / Hugging Face Entegrasyon Ayarları

- **Kaynak dosya:** `core/config_github_hf.py`
- **Not dosyası:** `docs/module-notes/core/config_github_hf.py.md`

**Amaç:** GitHub token/repo/webhook ve Hugging Face Hub kimlik bilgisi/önbellek
ayarlarını `GitHubHuggingFaceSettings` frozen dataclass'ı olarak yükler;
`config.Config` bunu `github_huggingface_settings` olarak expose eder ve aynı
7 alanı geriye dönük uyumlu `Config.FOO` class attribute'larına delege eder
(`docs/REFACTOR_PLAN.md`'nin `config.py` maddesinde marketing/social ve
access-policy dilimlerinden sonra işaretlenen sıradaki düşük riskli dilim).

**Özellikler:**
- `GitHubHuggingFaceSettings` — `github_token`, `github_repo`,
  `github_webhook_secret`, `github_webhook_require_signature`, `hf_token`,
  `hf_hub_offline`, `hf_use_local_cache_only`.
- `load_github_huggingface_settings()` — her alanı kendi ortam değişkeninden
  okur; `github_webhook_require_signature`/`hf_use_local_cache_only` katı
  `get_bool_env()` (yalnız `"true"`/`"false"`, aksi halde `ValueError`)
  kullanırken, `hf_hub_offline` üçüncü parti kütüphane konvansiyonuna uygun
  `get_external_bool_env()` (`1`/`0`, `yes`/`no`, `on`/`off` vb.) kullanır —
  ikisi karıştırılmamalıdır.
