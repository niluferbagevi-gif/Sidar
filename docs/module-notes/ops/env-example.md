# .env.example Teknik Notu

## Rolü
- `config.py` tarafından beklenen env anahtarlarının dokümantasyon sözleşmesidir.

## Öne Çıkan Noktalar
- RAG (`RAG_FILE_THRESHOLD`) ve Docker sandbox (`DOCKER_PYTHON_IMAGE`, `DOCKER_EXEC_TIMEOUT`) anahtarlarını içerir.
- Provider/model, güvenlik seviyesi, web, arama, paket bilgi gibi ana eksenleri kapsar.

## İyileştirme Alanı
- Yeni config anahtarı eklendiğinde aynı committe `.env.example` güncellemesi zorunlu süreç haline getirilmeli.
