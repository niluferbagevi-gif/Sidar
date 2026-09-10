# `managers/code/docker_lifecycle.py` — Docker SDK Yaşam Döngüsü Adaptörü

- **Kaynak dosya:** `managers/code/docker_lifecycle.py`
- **Not dosyası:** `docs/module-notes/managers/code/docker_lifecycle.py.md`

**Amaç:** `CodeManager`'ın Docker SDK üzerinden container yaşam döngüsünü
(image seçimi, container başlatma/durdurma/temizleme) yöneten adaptör
sınıfı; `managers/code/docker.py`'deki sanitize edilmiş image adaylarını ve
`managers/image_resolver.py`'deki GPU/canonical image çözümünü kullanır.
Alt süreç çağrıları `core/utils/trusted_subprocess.py`'nin
`run_trusted_command()`'ı üzerinden geçer (Bandit B603 merkezileştirmesi;
kalan `subprocess  # nosec B404` yalnızca modül-seviyesi import işaretidir).

**Özellikler:**
- `DockerLifecycleAdapter` — container/image yaşam döngüsü durumunu tutan ana
  sınıf; `LEGACY_PROJECT_IMAGE_PREFIXES`/`PROJECT_TEST_IMAGE_CANDIDATES`'i
  kullanarak uygun sandbox image'ını seçer, `sanitize_docker_image()` ile
  doğrular.
