# tests/test_sidar.py Teknik Notu

`tests/test_sidar.py`, projedeki birim + entegrasyon + async davranışların ana regresyon test dosyasıdır.

## 1) Kapsam

- Config ve agent fixture’ları ile izole test ortamı kurar.
- Code manager, Pydantic doğrulama, web search fallback, RAG chunking, session yönetimi ve güvenlik kontrollerini test eder.
- Rate limiter yarış koşulu (TOCTOU), JSON decoder dayanıklılığı, UTF-8 boundary ve manager davranışlarını kapsar.

## 2) Teknik Özellikler

- `pytest-asyncio` ile async testler (`@pytest.mark.asyncio`) kullanılır.
- Testlerde `tmp_path` ve monkeypatch ile yan etkiler izole edilir.
- Bazı testler config değerlerini runtime’da override ederek deterministic senaryolar üretir.

## 3) Operasyon Notu

- Bu ortamda `pydantic` bağımlılığı yoksa test collection aşamasında durur.
- CI/doğrulama ortamında bağımlılık seti tam kurularak çalıştırılması önerilir.

## 4) İyileştirme Alanı

- Senaryoları dosya bazlı modüler yapıya bölmek (`unit / integration / security`) bakım maliyetini düşürür.