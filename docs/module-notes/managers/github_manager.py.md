# 3.13 `managers/github_manager.py` — GitHub Yöneticisi (644 satır)

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** PyGithub üzerinden GitHub API entegrasyonu.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/github_manager.py` çıktısına göre **644** olarak ölçülmüştür.

**Kurumsal Koruma Katmanları:**
- **Binary dosya koruması (OOM savunması):** `read_remote_file()` içinde `SAFE_TEXT_EXTENSIONS` ve `SAFE_EXTENSIONLESS` kontrolleriyle metin dışı içerikler reddedilir; binary/bozuk içeriklerde güvenli hata mesajı döndürülür.
- **Branch adı doğrulama:** `_BRANCH_RE` ile yalnızca güvenli karakter setindeki dal adlarına izin verilir.
- **404 güvenli yakalama:** `_is_not_found_error()` ile not-found durumları kontrollü işlenir (sert çökme yerine anlamlı dönüş).

**Ölçeklenebilir Veri Çekme Sınırları (Pagination/Limit):**
- `list_commits(limit)`: istenen değer güvenli aralıkta sınırlandırılır (`1..100`); yüksek isteklerde kullanıcıya kısıtlama uyarısı verilir.
- `list_branches(limit)`, `list_pull_requests(limit)`, `list_issues(limit)`, `list_repos(limit)`: benzer şekilde limitli/paginated çağrılarla kaynak kullanımı kontrol altında tutulur.
- `search_code()`: sonuçlar ilk 10 kayıtla sınırlandırılır.

**PR ve Branch Yönetimi:**
- `list_commits(n)`, `get_repo_info()`, `list_files(path)`, `read_remote_file(path)`
- `write_file()`, `create_branch()`, `create_pr()`, `list_pull_requests()`
- `get_pull_request()`, `comment_pr()`, `close_pr()`, `get_pr_files()`
- `get_pull_request_diff(pr_number)` — PR diff metnini döndürür; patch olmayan dosyalar için binary olasılığına dair güvenli not üretir.
- `search_code(query)`, `github_smart_pr()` — LLM ile otomatik PR başlığı/açıklaması
- `get_pull_requests_detailed()`, `list_repos(owner_filter)` — yeni eklenti

**Issue Yönetimi (v2.9.0 — §14.5.2):**
- `list_issues(state, limit)`: Issue listesi (open/closed/all)
- `create_issue(title, body)`: Yeni issue açar
- `comment_issue(issue_number, body)`: Issue'ya yorum ekler
- `close_issue(issue_number)`: Issue'yu kapatır

**Not (Kapsam):** Mevcut sürümde açık bir exponential backoff yardımcı fonksiyonu bulunmaz; hata toleransı çoğunlukla limitli çağrı + kontrollü exception mesajları üzerinden sağlanır.

---
