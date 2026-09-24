# `core/config_gpu.py` — GPU/CUDA Ayarları

- **Kaynak dosya:** `core/config_gpu.py`
- **Not dosyası:** `docs/module-notes/core/config_gpu.py.md`

**Amaç:** GPU/CUDA sabitlerini ve donanım profili yardımcılarını tutar. `core/config_gpu_detect.py`'deki
`detect_gpu`, `normalize_gpu_memory_fractions` ve `resolve_adaptive_gpu_pool_size`
yardımcılarını tek yüzeyde toplar; `config.py` bunları re-export eder.

**Özellikler:**
- `PYTORCH_STABLE_CUDA_WHEEL_TAGS`, `PYTORCH_RECOMMENDED_CUDA_WHEEL_TAG`,
  `PYTORCH_RECOMMENDED_CUDA_INDEX_URL`, `PYTORCH_RECOMMENDED_CUDA_INSTALL_COMMAND` —
  önerilen PyTorch CUDA wheel kaynağı.
- `gpu_mixed_precision_default()` — `GPU_MIXED_PRECISION` varsayılanını çözer.
