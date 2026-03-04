# managers/code_manager.py Teknik Notu

`CodeManager`, dosya işlemleri, patch/yazma, shell yürütme, dosya arama ve proje denetimi gibi geliştirme odaklı araçları sağlar.

## Sorumluluklar
- Güvenlik katmanıyla birlikte dosya okuma/yazma/patch
- Docker izole kod çalıştırma (`execute_code`) ve fallback davranışı
- `glob_search` / `grep_files` gibi geliştirici araçları
- Basit sözdizimi doğrulama ve audit özetleri

## Bağlantılar
- `SecurityManager`: yol/erişim doğrulaması
- `config.py`: docker image ve timeout ayarları
- `agent/sidar_agent.py`: tool çağrıları üzerinden tüketim

## Not
- Docker erişimi olmayan ortamlarda özelliklerin bir kısmı degrade çalışabilir; loglar bu durumu açıkça raporlar.
