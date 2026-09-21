# `core/config_lora_training.py` — LoRA/QLoRA Fine-Tuning Ayarları

- **Kaynak dosya:** `core/config_lora_training.py`
- **Not dosyası:** `docs/module-notes/core/config_lora_training.py.md`

**Amaç:** LoRA/QLoRA fine-tuning hiperparametrelerini ve çıktı ayarlarını
`LoraTrainingSettings` frozen dataclass'ı olarak yükler; `config.Config` bunu
`lora_training_settings` olarak expose eder ve aynı 9 alanı geriye dönük
uyumlu `Config.FOO` class attribute'larına delege eder
(`docs/REFACTOR_PLAN.md`'nin `config.py` maddesinde cost-routing diliminden
sonra işaretlenen sıradaki düşük riskli dilim). `core/active_learning.py`
(`LoraTrainer` sınıfı) bu ayarları `getattr(config, "ENABLE_LORA_TRAINING",
...)` gibi mevcut alan adlarıyla tüketmeye devam eder.

**Kapsam dışı not:** `core/active_learning.py`, ayrıca `LORA_MODEL_REVISION`
adında bir `getattr(config, "LORA_MODEL_REVISION", "")` okuması yapar; bu
alan `config.py`'de hiç tanımlı değildir (yalnızca opsiyonel runtime
override/monkeypatch yüzeyi), bu yüzden bu modülün kapsamı dışında bırakıldı.

**Özellikler:**
- `LoraTrainingSettings` — `enable_lora_training`, `lora_base_model`,
  `lora_rank`, `lora_alpha`, `lora_dropout`, `lora_epochs`,
  `lora_batch_size`, `lora_use_4bit`, `lora_output_dir`.
- `load_lora_training_settings()` — her alanı kendi ortam değişkeninden
  okur; sayısal alanlar (`get_int_env()`/`get_float_env()`) malformed
  girdilerde uyarı loglayıp varsayılana düşer.
