# agent/__init__.py Teknik Notu

`agent` paketinin public API yüzeyini tanımlar.

## Dışa aktarılanlar

- `SidarAgent`
- `SIDAR_SYSTEM_PROMPT`
- `SIDAR_KEYS`
- `SIDAR_WAKE_WORDS`

## Neden önemli?

- Üst katmanların (`from agent import ...`) tek noktadan güvenli import yapmasını sağlar.
- Paket içi yeniden adlandırmalarda kırılmaları azaltır.
- `__all__` listesi, dış API sözleşmesini açıkça gösterir.