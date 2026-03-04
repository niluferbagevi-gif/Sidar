# core/memory.py Teknik Notu

`ConversationMemory`, konuşma geçmişini kalıcı şekilde saklayan ve opsiyonel şifreleme desteği sunan bellek katmanıdır.

## 1) Sorumluluklar

- Kullanıcı/asistan mesajlarını sıralı biçimde kaydetmek.
- Maksimum tur (`MAX_MEMORY_TURNS`) sınırına göre belleği budamak.
- Bellek dosyasında bozulma durumlarında toleranslı okuma ve karantina yaklaşımı uygulamak.
- İsteğe bağlı `MEMORY_ENCRYPTION_KEY` ile içerik şifreleme desteği sağlamak.

## 2) Dayanıklılık Özellikleri

- Thread-safe erişim için kilit mekanizması.
- Hatalı JSON veya yarım yazım durumlarına karşı güvenli fallback.
- Dosya I/O maliyetini azaltmak için çağıran katmanda (`SidarAgent`) `asyncio.to_thread` kullanımıyla non-blocking çalışma.

## 3) Bağlantılı Dosyalar

- Tüketen: `agent/sidar_agent.py`
- Ayar kaynağı: `config.py` (`MEMORY_FILE`, `MAX_MEMORY_TURNS`, `MEMORY_ENCRYPTION_KEY`)
- Test kapsayan: `tests/test_sidar.py`

## 4) İyileştirme Alanı

- Büyük oturumlarda tam-dosya rewrite maliyetini düşürmek için segment/append tabanlı format değerlendirilebilir.