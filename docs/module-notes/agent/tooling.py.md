# 3.7b `agent/tooling.py` — Araç Kayıt ve Şema Yöneticisi (266 satır)

**Amaç:** Araçların Pydantic şemalarını ve `build_tool_dispatch()` fonksiyonu aracılığıyla araç dispatch tablosunu merkezi olarak yönetir.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l agent/tooling.py` çıktısına göre **266** olarak ölçülmüştür.

**Kritik Bileşenler:**

| Bileşen | Açıklama |
|---------|----------|
| `WriteFileSchema` | `path` + `content` alanlarına sahip yazma şeması |
| `PatchFileSchema` | `path` + `old_text` + `new_text` alanlarına sahip yama şeması |
| `GithubListFilesSchema` | `path` + opsiyonel `branch` alanları |
| `GithubWriteSchema` | `path`, `content`, `commit_message`, opsiyonel `branch` |
| `GithubCreateBranchSchema` | `branch_name` + opsiyonel `from_branch` |
| `GithubCreatePRSchema` | `title`, `body`, `head`, opsiyonel `base` |
| `GithubListPRsSchema` | `state` (varsayılan: `"open"`) + `limit` (varsayılan: 10) |
| `GithubListIssuesSchema` | `state` (varsayılan: `"open"`) + `limit` (varsayılan: 10) |
| `GithubCreateIssueSchema` | `title` + `body` |
| `GithubCommentIssueSchema` | `number` (int) + `body` |
| `GithubCloseIssueSchema` | `number` (int) |
| `GithubPRDiffSchema` | `number` (int) |
| `ScanProjectTodosSchema` | opsiyonel `directory` + opsiyonel `extensions` (uzantı listesi) |
| `TOOL_ARG_SCHEMAS` | Araç adını şema sınıfına eşleyen sözlük (13 giriş) |
| `parse_tool_argument()` | JSON öncelikli, `|||` sınırlı legacy format fallback ile argüman ayrıştırma |
| `build_tool_dispatch()` | `SidarAgent` instance'ından araç adı → metod sözlüğü üretir |

**`parse_tool_argument()` İki Aşamalı Ayrıştırma Mantığı:**
1. **JSON öncelik:** `json.loads(text)` başarılıysa `schema.model_validate(dict)` ile Pydantic doğrulaması yapılır.
2. **Legacy format fallback:** `|||` ayırıcısı ile bölünmüş eski string formatı desteklenir. Bu, eski LLM çıktılarıyla geriye dönük uyumluluğu korur.

**`build_tool_dispatch()` Araç Tablosu (56 araç/alias eşlemesi):**

| Araç Adı | Alias | Metod |
|----------|-------|-------|
| `list_dir` | `ls` | `_tool_list_dir` |
| `read_file` | — | `_tool_read_file` |
| `write_file` | — | `_tool_write_file` |
| `patch_file` | — | `_tool_patch_file` |
| `execute_code` | — | `_tool_execute_code` |
| `run_shell` | `bash`, `shell` | `_tool_run_shell` |
| `glob_search` | — | `_tool_glob_search` |
| `grep_files` | `grep` | `_tool_grep_files` |
| `github_*` PR/Branch (16 araç) | — | `_tool_github_*` |
| `github_list_issues`, `github_create_issue`, `github_comment_issue`, `github_close_issue` | — | `_tool_github_*` |
| `github_pr_diff`, `github_list_repos` | — | `_tool_github_*` |
| `web_search`, `fetch_url`, `search_docs`, `search_stackoverflow` | — | `_tool_*` |
| `pypi`, `pypi_compare`, `npm`, `gh_releases`, `gh_latest` | — | `_tool_*` |
| `docs_search`, `docs_add`, `docs_add_file`, `docs_list`, `docs_delete` | — | `_tool_*` |
| `health`, `gpu_optimize`, `audit` | — | `_tool_*` |
| `todo_write`, `todo_read`, `todo_update`, `scan_project_todos` | — | `_tool_*` |
| `get_config` | `print_config_summary` | `_tool_get_config` |
| `subtask` | `agent` | `_tool_subtask` |

> **Not:** `parallel` aracı bu dispatch tablosunda yer almaz; `sidar_agent.py` içinde ReAct döngüsünde doğrudan `asyncio.gather` ile işlenir.

**Mimari Değer:** `tooling.py` sayesinde araç ekleme/değiştirme işlemleri `sidar_agent.py` içine dağılmaz; tek bir yerden yönetilir. Şema eklemek için yalnızca `TOOL_ARG_SCHEMAS` sözlüğüne yeni giriş yapılması yeterlidir.

---
