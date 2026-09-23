# `uploader/github_api.py` — GitHub PR API Yardımcıları

- **Kaynak dosya:** `uploader/github_api.py`
- **Not dosyası:** `docs/module-notes/uploader/github_api.py.md`

**Amaç:** Upload dalı için `main` hedefli PR'ı açar veya mevcut PR'ı yeniden kullanır. `gh` CLI yoksa doğrulanmış `origin` ve token ile GitHub REST API'ye düşer; geçici HTTP hatalarında sınırlı yeniden dener.

**Özellikler:**
- `GITHUB_PR_API_MAX_ATTEMPTS`, `GITHUB_PR_API_RETRY_BASE_SECONDS`, `GITHUB_PR_API_RETRYABLE_HTTP_CODES`.
- `github_repo_slug`, `github_api_request`, `find_existing_upload_pull_request`, `open_upload_pull_request_via_api`, `open_upload_pull_request`.
