# 3.12 `managers/code_manager.py` — Kod Yöneticisi (805 satır)

**Amaç:** Güvenli dosya I/O, sözdizimi denetimi ve Docker tabanlı kod yürütmeyi yönetir.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/code_manager.py` çıktısına göre **805** olarak ölçülmüştür.

**Zero-Trust Sandbox (v3.0):**
- `execute_code()` akışı varsayılan olarak Docker izolesinde çalışır; çıktı `stdout/stderr` ayrıştırılarak geri döndürülür.
- `network_mode="none"` ile varsayılan ağ erişimi kapalıdır (`DOCKER_NETWORK_DISABLED=true`).
- `mem_limit` ve `nano_cpus` ile konteyner kaynakları sınırlandırılır.
- `DOCKER_MICROVM_MODE` + `DOCKER_ALLOWED_RUNTIMES` ile `runsc`/`kata-runtime` gibi mikro-VM runtime'larına uyumlu çalışır.
- Çalıştırma süresi `DOCKER_EXEC_TIMEOUT` ile zorlanır; timeout durumunda konteyner kill edilerek sonsuz döngü riski sınırlandırılır.
- Docker erişilemezse `execute_code_local()` ile kontrollü ve zaman-aşımlı yerel fallback devreye girer.

**Yazma Öncesi Kod Doğrulama:**
- Python dosyaları için `write_file()` / `patch_file()` akışlarında `ast.parse()` ile sözdizimi doğrulaması yapılır.
- `SyntaxError` durumunda değişiklik diske yazılmadan işlem güvenli şekilde reddedilir.

**Akıllı Encoding Fallback:**
- Okuma akışında UTF-8 başarısız olursa `chardet` ile encoding tespiti yapılarak `UnicodeDecodeError` kaynaklı kırılmalar azaltılır.

**Gelişmiş Arama Araçları:**
- `glob_search(pattern, base_path)` ile desen/uzantı bazlı dosya keşfi.
- `grep_files(regex, path, file_glob, context)` ile regex destekli içerik araması ve bağlam satırı döndürme.

**SecurityManager ile Sıkı Entegrasyon:**
- Tüm dosya okuma/yazma yolları `self.security_manager.check_read()` ve `check_write()` kararlarına bağlıdır.
- Güvenlik onayı alınmadan dosya erişimi veya yazma yapılmaz.

**Temel Yetenekler:**
- Güvenli dosya okuma/yazma ve path doğrulama
- Syntax kontrolü / proje denetimi (`audit_project`)
- Docker yoksa güvenlik seviyesine göre kontrollü fallback davranışı

---
