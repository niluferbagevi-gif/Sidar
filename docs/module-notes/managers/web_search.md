# managers/web_search.py Teknik Notu

`WebSearchManager`, dış web arama ve URL içerik çekme akışını yönetir.

## Sorumluluklar
- Arama motoru seçimi (`auto/duckduckgo/tavily/google`)
- Sonuçları normalize etme ve özetleme
- URL fetch + içerik kırpma/temizleme

## Bağlantılar
- Ayar kaynağı: `config.py` (`SEARCH_ENGINE`, API key’ler, timeout/char limit)
- Tüketen: `SidarAgent`, `AutoHandle`

## Not
- Sağlayıcı bazlı hata sınıflandırması güçlendirilirse gözlemlenebilirlik artar.
