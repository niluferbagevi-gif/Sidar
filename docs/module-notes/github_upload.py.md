# 3.19 `github_upload.py` — GitHub Yükleme Aracı

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** Projeyi otomatik olarak GitHub'a yükler/yedekler.

**Güvenlik Katmanı (`FORBIDDEN_PATHS`):**
- `.env`, `.sidar_keys.env*`, `sessions/`, `chroma_db/`, `__pycache__/`, `.git/`, `logs/`, `models/`
- Binary/UTF-8 okunamayan dosyalar da engellenir

**Otomasyon ve Dayanıklılık Özellikleri:**
- **Repo/remote doğrulama:** Çalıştırma başında `.git` varlığı ve `origin` remote kontrol edilir; eksikse yönlendirici/otomatik kurulum adımları uygulanır.
- **Zaman damgalı commit mesajı:** Kullanıcı mesaj vermezse `datetime.now().strftime(...)` ile otomatik commit başlığı üretilir.
- **PR-first yayın:** Normal yükleme `sidar/upload-*` dalını push edip `main` hedefli PR açar. Kuruluysa `gh pr create`, `gh` bulunmuyorsa doğrulanmış `origin` adresi ve secret overlay'den gelen token ile GitHub HTTPS API kullanılır; doğrudan `main` push yalnız `SIDAR_GITHUB_UPLOAD_DIRECT_MAIN=1` açık opt-in'iyle mümkündür.
- **Tracked silme senkronizasyonu:** `git ls-files -d` ile bulunan yerel silmeler kullanıcıya tek tek gösterilir; yalnız açık onaydan sonra `git rm --ignore-unmatch -- :(literal)<path>` ile stage edilir ve normal akışta deletion commit'i `sidar/upload-*` PR dalına taşınır. Onaylanmayan silmeler GitHub'a gönderilmez.
- **Merge görünürlüğü:** Başarılı PR-first akış PR URL'sini yazdırır ve değişikliklerin henüz `main` üzerinde olmadığını, zorunlu kontrollerden sonra GitHub'da merge edilmesi gerektiğini açıkça belirtir.
- **Lease kontrollü rollback:** Geri alma yolu başka bir kullanıcının yeni remote commit'ini sessizce ezmemek için `--force-with-lease` kullanır.
- **Push-rejected kurtarma akışı:** `git push` reddedildiğinde (`rejected`/`fetch first`/`non-fast-forward`) güvenli `pull` + merge stratejisi (`--rebase=false --allow-unrelated-histories --no-edit -X ours`) ile senkronizasyon denenir ve push tekrar edilir.
- **GitHub Push Protection farkındalığı:** secret scanning/push protection hataları algılanır ve kullanıcıya düzeltme yönlendirmesi verilir.
- **Orijinal dala geri dönüş:** Araç farklı bir daldan çalıştırılırsa akışı sürdürmek için otomatik `main`e geçer (`switch_back_to_original_branch()`). Commit/push'a hiç ulaşmadan biten her erken çıkışta (çözülmemiş çakışma, push-öncesi kalite kapısı hatası, upload dalı oluşturulamaması, dosya stage/commit hatası, "yüklenecek değişiklik yok") kullanıcı otomatik olarak başladığı dala geri döndürülür; böylece kullanıcı fark etmeden `main`de (veya ondan türetilmiş boş bir upload dalında) bırakılmaz. Commit sonrası başarısız olan kalite kapıları bu otomatik geri dönüşün KAPSAMI DIŞINDADIR — orada gerçek çalışma bilerek korunur ve elle geri dönüş talimatı (`describe_post_commit_gate_failure`) verilir.

**Hata Yönetimi:**
- `subprocess.CalledProcessError` yakalanarak anlaşılır terminal çıktısı üretilir; ağ/auth/çatışma senaryolarında sessiz çökme engellenir.

---
