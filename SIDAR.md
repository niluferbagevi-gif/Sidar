# SIDAR.md

Bu dosya Sidar yerel ajanı için proje genelinde geçerli çalışma kurallarını içerir.
Sidar, bu dosyayı her konuşma turunda yeniden okur — değişiklikler anında etki eder.

## Temel Çalışma Kuralları

- Önce ilgili dosyaları oku (ör. `read_mcp_resource`, `exec_command` + `rg`), sonra değişiklik yap.
- Kodu değiştirmeden önce mevcut yapıyı anla; gereksiz refactor yapma.
- Her değişikliği hedef odaklı tut: yalnızca isteneni uygula, fazlasını ekleme.
- Mümkün olduğunda plan/todo adımlarını güncel tut; ilerledikçe durumları güncelle.
- İşlem tamamlandığında Türkçe, net ve kısa bir durum özeti ver.

## Araç Kullanım Öncelikleri (Ortamdan Bağımsız)

- **Dosya okuma**: Önce ilgili dosyayı doğrudan oku; geniş arama için `rg` kullan (ör. `rg -n`, `rg --files`).
- **Dosya yazma**: Mevcut düzenleme yöntemini kullan; gereksiz toplu yeniden yazımdan kaçın.
- **Kabuk komutları**: Komutları en az yetki ve en dar kapsamla çalıştır; önce güvenli/okuma odaklı komutları tercih et.
- **Dizin listeleme**: Büyük depolarda pahalı taramalardan kaçın; hedefli listeleme ve `rg --files` tercih et.
- **Dosya arama**: Desen ve içerik araması için `rg` kullan; `ls -R` / `grep -R` gibi pahalı yaklaşımlardan kaçın.
- **Görev takibi**: Kullanılan plan/todo mekanizmasında adımları `pending/in_progress/completed` şeklinde net tut.
- **GitHub işlemleri**: Yazma işlemlerinden önce repo/branch durumunu doğrula (`git status`, uzak repo bilgisi vb.).
- **Web araştırma**: Önce yerel kaynakları ve mevcut repo dosyalarını kullan; gerekli değilse dış kaynağa çıkma.

## Güvenlik (OpenClaw)

- `ACCESS_LEVEL=full` → proje kökü altına tam yazma + shell erişimi.
- `ACCESS_LEVEL=sandbox` → yalnızca `/temp` dizinine yazma; shell kapalı.
- `ACCESS_LEVEL=restricted` → yalnızca okuma ve analiz.
- Tehlikeli yol kalıpları (`../`, `/etc/`, `/proc/`) otomatik reddedilir.

## Git & GitHub

- Branch adı ekip kuralına uygun olmalı; tek bir zorunlu önek dayatılmaz (örn. `feature/`, `fix/`, `chore/`).
- PR başlığı ve açıklaması yapılan değişikliği, motivasyonu ve test sonuçlarını açıkça yansıtmalıdır.
- Commit mesajları açıklayıcı ve kısa olmalı; "neden" odaklı yazılmalı.

## Kod Kalitesi

- Ekstra hata yönetimi, fallback veya validasyon ekleme — yalnızca sistem sınırlarında gereklidir.
- Tek kullanımlık işlemler için helper/utility sınıfı oluşturma.
- Gereksiz yorum ekleme; mantık zaten açıksa yorum yazma.
- Güvenlik açığı oluşturacak kod yazma (injection, path traversal, vb.).

## Yanıt Formatı

- Kısa ve net; gereksiz uzatma.
- Teknik bilgi verirken dosya ve satır referansı ver (örn. `dosya:satır`).
- Görev listesi varsa her adımı tamamladıktan hemen sonra `completed` olarak işaretle.
- Sonuçları Markdown ile biçimlendir; kod bloklarında dil belirt.