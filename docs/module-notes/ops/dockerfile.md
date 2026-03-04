# Dockerfile Teknik Notu

## Rolü
- Uygulamanın container image üretimini yönetir (CPU varsayılan + GPU build desteği).
- `environment.yml` içinden pip bağımlılıklarını çıkarıp kurar.
- Non-root kullanıcıyla çalışma, healthcheck ve varsayılan entrypoint davranışı tanımlar.

## Öne Çıkan Noktalar
- `LABEL version="2.7.0"` güncel metadata kullanır.
- GPU için `TORCH_INDEX_URL` argümanı ile `cu124` wheel akışı desteklenir.
- Healthcheck `/status` endpoint’i üzerinden web modunu doğrular.

## İyileştirme Alanı
- Üst yorum bloğundaki eski sürüm ifadesi (`2.6.1`) güncel metadata ile tamamen senkron tutulmalıdır.
