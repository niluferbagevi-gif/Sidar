# managers/package_info.py Teknik Notu

`PackageInfoManager`, paket ekosistemi sorguları (PyPI, npm, GitHub release) için yardımcı katmandır.

## Sorumluluklar
- PyPI paket meta verisi ve sürüm karşılaştırması
- npm paket bilgisi
- GitHub release akışları

## Bağlantılar
- Ayar kaynağı: `config.py` (`PACKAGE_INFO_TIMEOUT`)
- Tüketen: `SidarAgent`, `AutoHandle`

## Not
- Sürüm parse/sıralama yollarında API tabanlı doğrulama arttıkça yanlış-pozitif azalır.