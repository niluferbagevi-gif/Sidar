from pathlib import Path


def test_github_upload_uses_shell_false_with_argument_lists():
    src = Path("github_upload.py").read_text(encoding="utf-8")
    assert "shell=False" in src
    assert "run_command([\"git\", \"push\", \"-u\", \"origin\", current_branch]" in src
    assert "git remote add origin" not in src  # string shell command path removed


def test_github_upload_validates_repo_url_format():
    src = Path("github_upload.py").read_text(encoding="utf-8")
    assert "def _is_valid_repo_url(url: str) -> bool" in src
    assert "normalized.startswith(\"https://github.com/\")" in src
    assert "normalized.startswith(\"git@github.com:\")" in src
