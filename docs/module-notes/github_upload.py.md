# 3.19 `github_upload.py` — GitHub Yükleme Aracı

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** Projeyi otomatik olarak GitHub'a yükler/yedekler.

**Güvenlik Katmanı (`FORBIDDEN_PATHS`):**
- `.env`, `.sidar_keys.env*`, `sessions/`, `chroma_db/`, `__pycache__/`, `.git/`, `logs/`, `models/`
- Binary/UTF-8 okunamayan dosyalar da engellenir

**Otomasyon ve Dayanıklılık Özellikleri:**
- **Repo/remote doğrulama:** Çalıştırma başında `.git` varlığı ve `origin` remote kontrol edilir; eksikse yönlendirici/otomatik kurulum adımları uygulanır.
- **Zaman damgalı commit mesajı:** Kullanıcı mesaj vermezse `datetime.now().strftime(...)` ile otomatik commit başlığı üretilir.
- **PR-first yayın:** Normal yükleme `sidar/upload-*` dalını push edip `gh pr create` ile `main` hedefli PR açar; doğrudan `main` push yalnız `SIDAR_GITHUB_UPLOAD_DIRECT_MAIN=1` açık opt-in'iyle mümkündür.
- **Lease kontrollü rollback:** Geri alma yolu başka bir kullanıcının yeni remote commit'ini sessizce ezmemek için `--force-with-lease` kullanır.
- **Push-rejected kurtarma akışı:** `git push` reddedildiğinde (`rejected`/`fetch first`/`non-fast-forward`) güvenli `pull` + merge stratejisi (`--rebase=false --allow-unrelated-histories --no-edit -X ours`) ile senkronizasyon denenir ve push tekrar edilir.
- **GitHub Push Protection farkındalığı:** secret scanning/push protection hataları algılanır ve kullanıcıya düzeltme yönlendirmesi verilir.

**Hata Yönetimi:**
- `subprocess.CalledProcessError` yakalanarak anlaşılır terminal çıktısı üretilir; ağ/auth/çatışma senaryolarında sessiz çökme engellenir.

---
