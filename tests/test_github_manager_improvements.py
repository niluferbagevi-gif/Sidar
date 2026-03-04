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