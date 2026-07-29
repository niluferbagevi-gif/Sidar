# 3.19 `github_upload.py` — GitHub Yükleme Aracı (1.418 satır)

## Güncel davranış (PR 2 — GitHub yükleme güvenliği)

**Amaç:** Projeyi otomatik olarak GitHub'a yükler/yedekler.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l github_upload.py`
> çıktısına göre **1.418** olarak ölçülmüştür.

Araç artık varsayılan olarak `main`'e doğrudan push YAPMAZ:

- **Varsayılan akış:** Değişiklikler `sidar-upload/<zaman damgası>` dalına commit
  edilir, push edilir ve `create_pull_request_via_api()` (stdlib `urllib`, ek
  bağımlılık yok) ile GitHub'da bir **draft PR** açılır. PR API çağrısı
  başarısız olursa (ağ/izin) araç manuel `compare/main...<dal>` bağlantısı
  yazdırır; dal zaten güvenle push edilmiştir.
- **Opt-in doğrudan-main:** `--direct-main` bayrağı eski davranışı açar; branch
  protection durumunu en iyi çaba ile sorgular (`check_branch_protection_best_effort()`),
  ve kullanıcının tam olarak `DIRECT-MAIN` yazmasını ister
  (`require_direct_main_confirmation()`) — basit y/n onayı yeterli değildir.
- **Çakışma çözümü artık `-X ours` KULLANMAZ:** Push reddedilip otomatik
  birleştirme denendiğinde (`rejected`/`fetch first`/`non-fast-forward`), plain
  `git pull --no-rebase --allow-unrelated-histories --no-edit` çalışır. Gerçek
  bir içerik çakışması varsa merge fail-closed olarak durur (`abort_in_progress_merge()`
  + çıkış kodu 1); yerel sürüm otomatik olarak uzaktaki değişikliklerin üzerine
  yazılmaz.
- **Rollback varsayılanı artık `git revert`:** `python github_upload.py -N`
  son `N` commit'i `git revert --no-edit HEAD~N..HEAD` ile geri alır ve normal
  (force olmayan) push yapar; geçmiş yeniden yazılmaz. Eski `reset --hard` +
  `git push --force` davranışı yalnızca `python github_upload.py -N --force-rollback`
  ile açılır ve kullanıcının **mevcut HEAD commit SHA'sını tam olarak yazmasını**
  ister (basit "evet"/"yes" yetmez); ayrıca hâlâ `backup/pre-rollback-<zaman damgası>`
  kurtarma tag'i oluşturur.

Ayrıntılar için `docs/CI_REQUIRED_CHECKS.md` → "Autonomous/direct push
guardrails" bölümüne bakınız.

**Güvenlik Katmanı (`FORBIDDEN_PATHS`):**
- `.env`, `sessions/`, `chroma_db/`, `__pycache__/`, `.git/`, `logs/`, `models/`
- Binary/UTF-8 okunamayan dosyalar da engellenir

**Otomasyon ve Dayanıklılık Özellikleri:**
- **Repo/remote doğrulama:** Çalıştırma başında `.git` varlığı ve `origin` remote kontrol edilir; eksikse yönlendirici/otomatik kurulum adımları uygulanır.
- **Zaman damgalı commit mesajı:** Kullanıcı mesaj vermezse `datetime.now().strftime(...)` ile otomatik commit başlığı üretilir.
- **GitHub Push Protection farkındalığı:** secret scanning/push protection hataları algılanır ve kullanıcıya düzeltme yönlendirmesi verilir.

**Hata Yönetimi:**
- `subprocess.CalledProcessError` yakalanarak anlaşılır terminal çıktısı üretilir; ağ/auth/çatışma senaryolarında sessiz çökme engellenir.

---
