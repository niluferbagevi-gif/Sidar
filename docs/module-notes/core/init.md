# core/__init__.py Teknik Notu

`core` paketinin public API yüzeyini ve sürüm bilgisini tanımlar.

## Dışa Aktarılanlar

- `ConversationMemory`
- `LLMClient`
- `DocumentStore`
- `__version__`

## Rolü

- Üst katmanların (`from core import ...`) kararlı import yapmasını sağlar.
- Çekirdek bileşenlerin tek noktadan dışa açılmasını ve sürüm bilgisinin merkezi görünmesini sağlar.
