# SIDAR.md

Bu dosya Sidar yerel ajanı için proje genelinde geçerli çalışma kurallarını içerir.
Sidar, bu dosyayı her konuşma turunda yeniden okur — değişiklikler anında etki eder.

## Temel Çalışma Kuralları

- Önce ilgili dosyaları oku (`read_file`, `glob_search`, `grep_files`), sonra değişiklik yap.
- Kodu değiştirmeden önce mevcut yapıyı anla; gereksiz refactor yapma.
- Her değişikliği hedef odaklı tut: yalnızca isteneni uygula, fazlasını ekleme.
- Mümkün olan her adımda `todo_write` ile görev listesi tut; ilerledikçe güncelle.
- İşlem tamamlandığında Türkçe, net ve kısa bir durum özeti ver.

## Araç Kullanım Öncelikleri (Claude Code Uyumlu)

- **Dosya okuma**: `read_file` → `glob_search` → `grep_files` sırasıyla kullan.
- **Dosya yazma**: `write_file` (yeni dosya) veya `patch_file` (mevcut dosyayı güncelle).
- **Kabuk komutları**: `run_shell` / `bash` / `shell` — yalnızca FULL modda çalışır.
- **Dizin listeleme**: `list_dir` veya `ls` alias'ı.
- **Dosya arama**: `glob_search` (desen ile) veya `grep_files` (içerik ile).
- **Görev takibi**: `todo_write` (güncelle), `todo_read` (listele), `todo_update` (durum değiştir).
- **GitHub işlemleri**: önce `github_info` veya `github_list_files` ile durumu doğrula.
- **Web araştırma**: `web_search` → `fetch_url` sırasıyla kullan; spekülatif URL üretme.

## Güvenlik (OpenClaw)

- `ACCESS_LEVEL=full` → proje kökü altına tam yazma + shell erişimi.
- `ACCESS_LEVEL=sandbox` → yalnızca `/temp` dizinine yazma; shell kapalı.
- `ACCESS_LEVEL=restricted` → yalnızca okuma ve analiz.
- Tehlikeli yol kalıpları (`../`, `/etc/`, `/proc/`) otomatik reddedilir.

## Git & GitHub

- Branch adı `claude/` önekiyle başlamalıdır.
- `github_smart_pr` aracı git diff analiz ederek otomatik PR başlığı ve açıklaması üretir.
- Commit mesajları açıklayıcı ve kısa olmalı; "neden" odaklı yazılmalı.

## Kod Kalitesi

- Ekstra hata yönetimi, fallback veya validasyon ekleme — yalnızca sistem sınırlarında gereklidir.
- Tek kullanımlık işlemler için helper/utility sınıfı oluşturma.
- Gereksiz yorum ekleme; mantık zaten açıksa yorum yazma.
- Güvenlik açığı oluşturacak kod yazma (injection, path traversal, vb.).

## Yanıt Formatı

- Kısa ve net; gereksiz uzatma.
- Teknik bilgi verirken `dosya:satır_no` formatını kullan.
- Görev listesi varsa her adımı tamamladıktan hemen sonra `completed` olarak işaretle.
- Sonuçları Markdown ile biçimlendir; kod bloklarında dil belirt. 