from pathlib import Path


def test_create_or_update_file_handles_not_found_without_swallowing_other_errors():
    src = Path("managers/github_manager.py").read_text(encoding="utf-8")
    assert "def _is_not_found_error" in src
    assert "if _is_not_found_error(exc):" in src
    assert "return False, f\"GitHub dosya okuma hatası: {exc}\"" in src


def test_list_repos_uses_account_type_instead_of_exception_driven_fallback():
    src = Path("managers/github_manager.py").read_text(encoding="utf-8")
    assert "account = self._gh.get_user(owner)" in src
    assert "account_type = str(getattr(account, \"type\", \"\")).lower()" in src
    assert "repo_type = \"all\" if account_type == \"organization\" else \"owner\"" in src

def test_github_manager_adds_limits_and_fail_closed_token_guard():
    src = Path("managers/github_manager.py").read_text(encoding="utf-8")
    assert "def list_commits(self, limit: int = 30" in src
    assert "limit = max(1, min(int(limit), 100))" in src
    assert "def list_branches(self, limit: int = 30)" in src
    assert "get_branches()[:limit]" in src
    assert "def list_pull_requests(" in src
    assert "HATA: GitHub araçları aktif ancak GITHUB_TOKEN bulunamadı" in src


def test_smart_pr_truncates_large_diff_before_llm_prompt():
    src = Path("agent/sidar_agent.py").read_text(encoding="utf-8", errors="replace")
    assert "git diff --no-color HEAD" in src
    assert "max_diff_chars = 10000" in src
    assert "Diff çok büyük olduğu için geri kalanı kırpıldı" in src