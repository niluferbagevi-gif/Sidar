# managers/security.py Teknik Notu

`SecurityManager`, dosya yolu ve komut güvenliği için merkezi kontrol katmanıdır.

## Sorumluluklar
- Erişim seviyesine göre (`restricted/sandbox/full`) okuma-yazma izinlerini yönetmek
- Path traversal ve tehlikeli kalıpları engellemek
- Güvenli yazma hedeflerini normalize etmek

## Bağlantılar
- Tüketen: `CodeManager`, `SidarAgent`
- Ayar kaynağı: `config.py` (`ACCESS_LEVEL`, `BASE_DIR`)

## Not
- Güvenlik raporlamasının kullanıcıya anlaşılır olması için status çıktıları düzenli tutulmalıdır.
