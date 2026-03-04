from pathlib import Path


def test_run_shell_defaults_to_safe_tokenized_mode_with_explicit_shell_override():
    src = Path("managers/code_manager.py").read_text(encoding="utf-8")
    assert "allow_shell_features: bool = False" in src
    assert "args = shlex.split(command)" in src
    assert "shell=False" in src
    assert "if uses_shell_features and not allow_shell_features:" in src


def test_audit_project_supports_exclusions_and_file_limit():
    src = Path("managers/code_manager.py").read_text(encoding="utf-8")
    assert "exclude_dirs: Optional[List[str]] = None" in src
    assert "max_files: int = 5000" in src
    assert "for cur_root, dirs, files in os.walk(target):" in src
    assert "dirs[:] = [d for d in dirs if d not in exclude_set]" in src
