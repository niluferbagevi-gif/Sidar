# `core/config_continuous_learning.py` — Sürekli Öğrenme Bundle Ayarları

- **Kaynak dosya:** `core/config_continuous_learning.py`
- **Not dosyası:** `docs/module-notes/core/config_continuous_learning.py.md`

**Amaç:** Judge/feedback sinyallerinden sürekli öğrenme (continuous learning)
SFT/preference bundle üretim ayarlarını `ContinuousLearningSettings` frozen
dataclass'ı olarak yükler; `config.Config` bunu `continuous_learning_settings`
olarak expose eder ve aynı 7 alanı geriye dönük uyumlu `Config.FOO` class
attribute'larına delege eder (`docs/REFACTOR_PLAN.md`'nin `config.py`
maddesinde LoRA/QLoRA diliminden sonra işaretlenen sıradaki düşük riskli
dilim). `core/active_learning.py` bu ayarları `getattr(config,
"ENABLE_CONTINUOUS_LEARNING", ...)` gibi mevcut alan adlarıyla tüketmeye
devam eder.

**Özellikler:**
- `ContinuousLearningSettings` — `enable_continuous_learning`,
  `continuous_learning_min_sft_examples`,
  `continuous_learning_min_preference_examples`,
  `continuous_learning_max_pending_signals`,
  `continuous_learning_cooldown_seconds`, `continuous_learning_output_dir`,
  `continuous_learning_sft_format`.
- `load_continuous_learning_settings()` — her alanı kendi ortam
  değişkeninden okur; sayısal alanlar (`get_int_env()`) malformed
  girdilerde uyarı loglayıp varsayılana düşer.
