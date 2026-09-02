# agent/github/

- **Kaynak dizini:** `agent/github/` (`__init__.py`, `smart_pr.py`)
- **Not dosyası:** `docs/module-notes/agent/github.md`

## Amaç

`smart_pr.py::create_smart_pr(*, arg, code, github, max_diff_chars=10000)` —
`SidarAgent`'ın `.pr`/smart-PR aracının uygulaması. `arg`'ı `"|||"` ile
`title|||base|||notes` şeklinde ayrıştırır (hepsi opsiyonel, varsayılanları
"Otomatik PR" / repo'nun `default_branch`'i / boş not). Akış:

1. `github.is_available()` yanlışsa (token yok) erken çıkar.
2. `code.run_shell("git branch --show-current")` ile aktif branch'i bulur;
   yoksa erken çıkar.
3. `git status --short` ile bekleyen değişiklik yoksa erken çıkar (boş PR
   açmaz).
4. `git diff --no-color HEAD`'i alır, `max_diff_chars`'ı aşarsa kırpar; PR
   gövdesine commit listesi + diff özeti gömer.
5. `github.create_pull_request_hitl(title, body, head, base)`'i çağırır
   (`TimeoutError` ve genel `Exception` ayrı ayrı yakalanıp kullanıcıya
   okunabilir bir hata mesajına çevrilir).

`_CodeManagerLike`/`_GitHubManagerLike` (`Protocol`), gerçek `CodeManager`/
`GitHubManager`'ın bu fonksiyonun ihtiyaç duyduğu daraltılmış yüzeyini
tanımlar — test'te hafif stub'larla değiştirilebilir. Tüm kullanıcıya
gösterilen mesaj önekleri (`GITHUB_SMART_PR_*`) modül sabiti olarak dışa
açılır ki `agent/sidar_agent.py` ve testler aynı metni paylaşsın.

## Test kapısı

`tests/unit/agent/github/test_smart_pr.py`.
