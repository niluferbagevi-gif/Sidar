# agent/definitions.py Teknik Notu

Bu dosya, ajan davranışını belirleyen sabit tanımları içerir:

- `SIDAR_KEYS`
- `SIDAR_WAKE_WORDS`
- `SIDAR_SYSTEM_PROMPT`

## 1) Rolü

- Ajanın kimlik/persona çerçevesini merkezi bir metinde toplar.
- Araç kullanım stratejileri, güvenlik prensipleri ve davranış kurallarını sistem prompt içinde tutar.
- Prompt içeriğini koddan ayırarak bakım ve güncellemeyi kolaylaştırır.

## 2) Dikkat Noktası

- Bu dosya çok uzun sistem talimatı barındırır; tool isimleri/alias’lar `sidar_agent.py` dispatcher ile birlikte güncel tutulmalıdır.
- Prompt drift’ini azaltmak için rapor/dokümantasyon güncellemeleri bu dosyayla çapraz kontrol edilmelidir.

## 3) Bağlantılar

- `agent/__init__.py` sabitleri dışa aktarır.
- `agent/sidar_agent.py` system prompt üretiminde bu sabitleri kullanır.