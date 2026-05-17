import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def _dockerfile_env_values() -> dict[str, str]:
    dockerfile = _read(".devcontainer/Dockerfile")
    env_values: dict[str, str] = {}

    for match in re.finditer(r"(?ms)^ENV\s+(.+?)(?=^\S|\Z)", dockerfile):
        env_block = match.group(1).replace("\\\n", " ")
        for token in env_block.split():
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            env_values[key] = value

    return env_values


def test_devcontainer_build_env_matches_non_secret_container_env_defaults():
    devcontainer = json.loads(_read(".devcontainer/devcontainer.json"))
    container_env = devcontainer["containerEnv"]
    dockerfile_env = _dockerfile_env_values()

    for name, value in container_env.items():
        assert dockerfile_env.get(name) == value, name


def test_devcontainer_image_installs_shellcheck_os_package():
    dockerfile = _read(".devcontainer/Dockerfile")

    assert "shellcheck \\" in dockerfile
    assert dockerfile.index("portaudio19-dev") < dockerfile.index("shellcheck")
    assert dockerfile.index("shellcheck") < dockerfile.index("install -m 0755 -d /etc/apt/keyrings")

def test_devcontainer_generated_log_directory_is_gitignored():
    gitignore = _read(".gitignore").splitlines()

    assert ".devcontainer/logs/" in gitignore


def test_devcontainer_starts_ollama_with_keep_alive_default():
    setup_script = _read(".devcontainer/setup-codespaces.sh")

    assert 'OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}" nohup ollama serve' in setup_script


def test_devcontainer_bootstraps_pyright_lsp_tool_with_uv_tool_install():
    setup_script = _read(".devcontainer/setup-codespaces.sh")

    assert "ensure_pyright_lsp_tool" in setup_script
    assert "uv tool install pyright" in setup_script
    assert "pyright-langserver" in setup_script
    assert "${REPO_ROOT}/${UV_PROJECT_ENVIRONMENT}/bin" in setup_script
    assert "${HOME}/.local/bin" in setup_script
