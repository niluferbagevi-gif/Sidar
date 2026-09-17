# `web/routes/project_ops.py` — Proje/Git/Oturum Yönetimi Rotaları

- **Kaynak dosya:** `web/routes/project_ops.py`
- **Not dosyası:** `docs/module-notes/web/routes/project_ops.py.md`

**Amaç:** Oturum listeleme, dosya gezgini, git bilgisi/dal işlemleri ve
GitHub repo/PR sorgulama rotalarını barındırır. Git komutları yalnızca
`_is_allowed_git_command()` allowlist'inden geçenler çalıştırılır ve dal
adları `managers/code/git_validation.py`'nin `is_valid_git_ref_name()`'i ile
doğrulanır (argument-injection savunması). Alt süreç çağrıları
`core/utils/trusted_subprocess.py`'nin `run_trusted_command()`'ı üzerinden
geçer — bu dosya bu session'ın Bandit B603 merkezileştirme çalışmasında
`check_output()`'tan bu wrapper'a taşınan dosyalardan biriydi.

**Özellikler:**
- `_is_allowed_git_command(cmd)`, `_execute_allowed_git_command(...)`,
  `_git_run(...)` — allowlist'li, doğrulanmış git alt süreç çalıştırma.
- `_extract_repo_from_remote(remote)` — `owner/repo` çıkarımı.
- `_resolve_web_server_helper(name, default)` — `web/routes/metrics.py`'deki
  aynı desen (test-time override'lara saygı).
- `build_project_ops_router(...)` — `GET /sessions`,
  `GET /sessions/{session_id}`, `POST /sessions/new`,
  `DELETE /sessions/{session_id}`, `GET /files`, `GET /file-content`,
  `GET /git-info`, `GET /git-branches`, `POST /set-branch`,
  `GET /github-repos`, `GET /github-prs`, `GET /github-prs/{number}`
  rotalarını kaydeder.
