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

def test_code_manager_enforces_utf8_and_fail_closed_sandbox_execution():
    src = Path("managers/code_manager.py").read_text(encoding="utf-8")
    assert "with open(target, \"r\", encoding=\"utf-8\"" in src
    assert "with open(target, \"w\", encoding=\"utf-8\"" in src
    assert "if self.security.level == SANDBOX:" in src
    assert "yerel (unsafe) çalıştırma engellendi" in src




def test_code_manager_applies_standard_sandbox_cgroup_limits():
    src = Path("managers/code_manager.py").read_text(encoding="utf-8")
    assert "def _resolve_sandbox_limits" in src
    assert "\"pids_limit\": sandbox_limits[\"pids_limit\"]" in src
    assert "sandbox_limits[\"network_mode\"] == \"none\"" in src
    assert "timeout = int(sandbox_limits[\"timeout\"])" in src

def test_config_exposes_parametric_sandbox_limits():
    src = Path("config.py").read_text(encoding="utf-8")
    assert "SANDBOX_LIMITS = {" in src
    assert '"memory": os.getenv("SANDBOX_MEMORY", "256m")' in src
    assert '"cpus": os.getenv("SANDBOX_CPUS", "0.5")' in src
    assert '"pids_limit": get_int_env("SANDBOX_PIDS_LIMIT", 64)' in src
    assert '"network": os.getenv("SANDBOX_NETWORK", "none")' in src
    assert '"timeout": get_int_env("SANDBOX_TIMEOUT", 10)' in src

def test_code_manager_reads_docker_runtime_from_config_or_env():
    src = Path("managers/code_manager.py").read_text(encoding="utf-8")
    assert "os.getenv(\"DOCKER_IMAGE\", \"\")" in src
    assert "os.getenv(\"DOCKER_PYTHON_IMAGE\", \"python:3.11-alpine\")" in src
    assert "os.getenv(\"DOCKER_EXEC_TIMEOUT\", \"10\")" in src
    assert "timeout=self.docker_exec_timeout" in src

def test_code_manager_limits_output_size_for_sandbox_and_shell():
    src = Path("managers/code_manager.py").read_text(encoding="utf-8")
    assert "self.max_output_chars = 10000" in src
    assert "ÇIKTI KIRPILDI: Maksimum {self.max_output_chars} karakter sınırı aşıldı" in src
    assert "if len(logs) > self.max_output_chars:" in src
    assert "if len(output) > self.max_output_chars:" in src
    assert "if len(combined) > self.max_output_chars:" in src