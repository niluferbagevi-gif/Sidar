# `core/config_gpu_detect.py` — GPU/CUDA Donanım Tespiti

- **Kaynak dosya:** `core/config_gpu_detect.py`
- **Not dosyası:** `docs/module-notes/core/config_gpu_detect.py.md`

**Amaç:** `core/config_hardware.py`'nin kullandığı donanım veri tiplerini
(`HardwareInfo`, `GpuMemoryBudget`) ve düşük seviyeli CUDA/GPU tespit
mantığını taşır; import anında ağır yan etki yaratmaması için saf veri/tespit
fonksiyonlarına ayrılmıştır.

**Özellikler:**
- `GpuMemoryBudget` (TypedDict) — `llm`/`rag`/`gpu`/`total`/`original_total`/
  `normalized` VRAM bütçesi alanları.
- `HardwareInfo` (dataclass) — `has_cuda`, `gpu_name`, `gpu_count`, `cpu_count`,
  `cuda_version`, `driver_version`, `gpu_vram_mb`.
