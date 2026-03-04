# Proje Dokümantasyon Dosyaları Notu

Bu not, operasyon ve kullanıcı yönlendirmesi sağlayan üst düzey dokümanları kapsar:
- `README.md`
- `SIDAR.md`
- `CLAUDE.md`

## Rolü
- Kullanıcı onboarding, ajan davranış kontratı ve proje içi talimat hiyerarşisini tanımlar.

## Öne Çıkan Nokta
- `SidarAgent` talimat dosyalarını hiyerarşik (mtime-cache) okuduğu için bu dosyalar runtime davranışını doğrudan etkiler.

## İyileştirme Alanı
- Versiyon/komut drift’ini azaltmak için bu üç dosya arasında düzenli çapraz senkron kontrolü yapılmalıdır.
