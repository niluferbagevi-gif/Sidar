# docker-compose.yml Teknik Notu

## Rolü
- CLI ve web servisleri için CPU/GPU varyantlarını tek dosyada orkestre eder.
- Build argümanları, volume/port eşlemeleri ve environment overrides sağlar.

## Öne Çıkan Noktalar
- GPU profillerinde `TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124` ile uyum korunur.
- Host erişimi için `host.docker.internal` eşlemesi tanımlıdır.
- Web servislerinde `WEB_PORT` / `WEB_GPU_PORT` varyantı desteklenir.

## İyileştirme Alanı
- Servis bazlı sağlık/ready sinyallerini ayrılaştırmak (özellikle GPU cold-start) operasyonda görünürlüğü artırır.
