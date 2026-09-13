# `managers/image_resolver.py` — Docker Image Adı Çözümleme

- **Kaynak dosya:** `managers/image_resolver.py`
- **Not dosyası:** `docs/module-notes/managers/image_resolver.py.md`

**Amaç:** Docker sandbox image adlarının küçük, bağımsız çözümleme
yardımcıları; `managers/code/docker.py`'nin legacy/GPU image adlandırma
kararlarını merkezileştirir.

**Özellikler:**
- `canonical_project_image_alias(image, *, legacy_prefixes)` — eski
  (legacy) Sidar image adlarını `legacy_prefixes` eşlemesi üzerinden
  kanonik repository etiketine çevirir; eşleşme yoksa `None` döner.
- `is_gpu_project_image(image)` — repository adı `sidar-gpu` ile
  başlıyorsa `True` döner; sandbox'ın GPU runtime image'i mi seçeceğine
  karar vermek için kullanılır.
