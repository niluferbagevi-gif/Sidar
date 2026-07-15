# 3.19 `github_upload.py` — GitHub Yükleme Aracı

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** Projeyi otomatik olarak GitHub'a yükler/yedekler.

> Not: Satır sayısı hızlı değiştiği için bu not artık sabit LOC iddiası tutmaz; davranış sözleşmesi aşağıdaki güvenlik ve kurtarma akışlarıdır.

**Güvenlik Katmanı (`FORBIDDEN_PATHS`):**
- `.env`, `sessions/`, `chroma_db/`, `__pycache__/`, `.git/`, `logs/`, `models/`
- Binary/UTF-8 okunamayan dosyalar da engellenir

**Otomasyon ve Dayanıklılık Özellikleri:**
- **Repo/remote doğrulama:** Çalıştırma başında `.git` varlığı ve `origin` remote kontrol edilir; eksikse yönlendirici/otomatik kurulum adımları uygulanır.
- **Zaman damgalı commit mesajı:** Kullanıcı mesaj vermezse `datetime.now().strftime(...)` ile otomatik commit başlığı üretilir.
- **Push-rejected kurtarma akışı:** `git push` reddedildiğinde (`rejected`/`fetch first`/`non-fast-forward`) güvenli `pull` + merge stratejisi (`--rebase=false --allow-unrelated-histories --no-edit -X ours`) ile senkronizasyon denenir ve push tekrar edilir.
- **Merge conflict rehberi (v2.3+):** Dış branch çekilirken `CONFLICT (add/add)` gibi hata alınırsa araç çakışan dosyaları listeler, `git status --short`, `git checkout --ours/--theirs`, `git add -- ...`, `git commit` ve ardından `uv run python github_upload.py` adımlarını basar. Terminal başlığında hâlâ `(v2.2)` görünüyorsa eski araç çalışıyordur; çakışma durumunda önce `git status --short` ile dosyaları çözün, merge commit'i alın ve güncel araçla tekrar deneyin.
- **GitHub Push Protection farkındalığı:** secret scanning/push protection hataları algılanır ve kullanıcıya düzeltme yönlendirmesi verilir.

**Hata Yönetimi:**
- `subprocess.CalledProcessError` yakalanarak anlaşılır terminal çıktısı üretilir; ağ/auth/çatışma senaryolarında sessiz çökme engellenir.

---
