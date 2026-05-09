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
