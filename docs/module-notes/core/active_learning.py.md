# `core/active_learning.py` — Active Learning + LoRA/QLoRA Fine-tuning Döngüsü

- **Kaynak dosya:** `core/active_learning.py`
- **Not dosyası:** `docs/module-notes/core/active_learning.py.md`

**Amaç:** Kullanıcı geri bildirimlerini (thumbs-up/down, düzeltme) toplayıp
LoRA/QLoRA fine-tuning için dataset üretir ve isteğe bağlı HuggingFace PEFT
eğitimini tetikler. `peft`/`transformers`/`bitsandbytes`/`datasets`/`torch`
bağımlılıkları opsiyoneldir — yoksa graceful degrade eder. Bu session'ın
Bandit B615 incelemesinde `load_dataset()` (yalnızca yerel JSON dosyası
okur) ve `from_pretrained()` (revizyon pini artık literal kwarg) sitelerinin
her biri ayrı ayrı değerlendirildi — bkz. `bandit-suppression-baseline.json`.

**Kullanım:**
```python
store = FeedbackStore()
await store.initialize()
await store.record(user_id="u1", prompt="...", response="...", rating=1)
exporter = DatasetExporter(store)
path = await exporter.export_jsonl("data/finetune/dataset.jsonl")
```

**Özellikler:**
- `FeedbackStore` — thumbs-up/down/düzeltme kayıtlarını saklar.
- `DatasetExporter` — kayıtları JSONL fine-tuning dataset'ine aktarır.
- `ContinuousLearningPipeline`, `LoRATrainer` — sürekli öğrenme döngüsünü ve
  (varsa) PEFT eğitimini yönetir.
- `get_feedback_store(config=None)`, `get_continuous_learning_pipeline(config=None)`,
  `schedule_continuous_learning_cycle(...)`, `flag_weak_response(...)` (async)
  — modül seviyesi singleton erişimi ve zamanlama.
