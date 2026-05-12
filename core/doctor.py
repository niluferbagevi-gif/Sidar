"""Installation/readiness doctor for Sidar.

The doctor intentionally performs lightweight, bounded checks so it can be used
both from `sidar doctor` and from installer subcommands without becoming another
opaque installation phase.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sidar_assets.paths import migrations_path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = BASE_DIR / "artifacts" / "install" / "doctor.json"


@dataclass
class DoctorCheck:
    name: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


WEAK_SECRET_VALUES = {
    "",
    "sidar",
    "admin",
    "password",
    "changeme",
    "change_me",
    "secret",
    "default",
    "test",
    "example",
    "postgres",
    "root",
    "123456",
    "12345678",
}


def _run_command(cmd: list[str], *, timeout: int = 20) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # nosec B603  # noqa: S603 - command list is internally constructed.
            cmd,
            cwd=BASE_DIR,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip()
    except FileNotFoundError as exc:
        return 127, str(exc)
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return 124, f"timeout after {timeout}s\n{output}".strip()


def _status_from_bool(ok: bool, warn: bool = False) -> str:
    if ok:
        return "pass"
    return "warn" if warn else "fail"


def _is_weak_secret(value: str | None) -> bool:
    normalized = (value or "").strip()
    return normalized.lower() in WEAK_SECRET_VALUES or len(normalized) < 24


def check_uv() -> DoctorCheck:
    uv_path = shutil.which("uv")
    if not uv_path:
        return DoctorCheck("uv", "fail", "uv executable not found on PATH")

    version_rc, version_out = _run_command([uv_path, "--version"])
    lock_rc, lock_out = _run_command([uv_path, "lock", "--check"], timeout=60)
    status = "pass" if version_rc == 0 and lock_rc == 0 else "fail"
    return DoctorCheck(
        "uv",
        status,
        "uv and uv.lock are ready" if status == "pass" else "uv lock validation failed",
        {"path": uv_path, "version": version_out, "lock_check": lock_out},
    )


def _is_postgres_url(parsed: Any) -> bool:
    return bool(parsed and str(parsed.scheme).startswith("postgresql"))


def _database_name(parsed: Any) -> str:
    return str(getattr(parsed, "path", "") or "").lstrip("/").split("/", 1)[0]


def _validate_postgres_env_sync(
    *,
    label: str,
    parsed: Any,
    postgres_user: str,
    postgres_password: str,
    postgres_db: str,
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    if not _is_postgres_url(parsed):
        return failures, warnings

    url_user = unquote(str(getattr(parsed, "username", "") or ""))
    url_password = unquote(str(getattr(parsed, "password", "") or ""))
    url_db = _database_name(parsed)

    if _is_weak_secret(url_password):
        failures.append(f"{label} contains an empty or weak database password")
    if postgres_user and url_user and url_user != postgres_user:
        failures.append(f"{label} user does not match POSTGRES_USER")
    if postgres_password and url_password and url_password != postgres_password:
        failures.append(
            f"{label} password does not match POSTGRES_PASSWORD; PostgreSQL may reject authentication"
        )
    if postgres_db and url_db and url_db != postgres_db:
        warnings.append(f"{label} database name does not match POSTGRES_DB")
    return failures, warnings


def check_database_env() -> DoctorCheck:
    database_url = os.getenv("DATABASE_URL", "").strip()
    container_url = os.getenv("SIDAR_CONTAINER_DATABASE_URL", "").strip()
    postgres_user = os.getenv("POSTGRES_USER", "").strip()
    postgres_password = os.getenv("POSTGRES_PASSWORD", "").strip()
    postgres_db = os.getenv("POSTGRES_DB", "").strip()
    parsed = urlparse(database_url) if database_url else None
    container_parsed = urlparse(container_url) if container_url else None

    failures: list[str] = []
    warnings: list[str] = []
    if not database_url:
        warnings.append("DATABASE_URL is not set; database readiness cannot be fully verified")
    else:
        sync_failures, sync_warnings = _validate_postgres_env_sync(
            label="DATABASE_URL",
            parsed=parsed,
            postgres_user=postgres_user,
            postgres_password=postgres_password,
            postgres_db=postgres_db,
        )
        failures.extend(sync_failures)
        warnings.extend(sync_warnings)
    if postgres_password and _is_weak_secret(postgres_password):
        failures.append("POSTGRES_PASSWORD is weak")
    if container_url:
        container_failures, container_warnings = _validate_postgres_env_sync(
            label="SIDAR_CONTAINER_DATABASE_URL",
            parsed=container_parsed,
            postgres_user=postgres_user,
            postgres_password=postgres_password,
            postgres_db=postgres_db,
        )
        failures.extend(container_failures)
        warnings.extend(container_warnings)
    if container_url and "sidar:sidar@" in container_url:
        failures.append("SIDAR_CONTAINER_DATABASE_URL uses the legacy default password")

    status = "fail" if failures else ("warn" if warnings else "pass")
    message = "; ".join(failures or warnings or ["database environment looks secure"])
    return DoctorCheck(
        "database_env",
        status,
        message,
        {
            "database_url_set": bool(database_url),
            "container_database_url_set": bool(container_url),
            "postgres_user_set": bool(postgres_user),
            "postgres_password_set": bool(postgres_password),
            "postgres_db_set": bool(postgres_db),
            "scheme": parsed.scheme if parsed else "",
            "container_scheme": container_parsed.scheme if container_parsed else "",
        },
    )


def _parse_migration_revisions() -> tuple[list[str], list[str]]:
    revisions: list[str] = []
    down_revisions: list[str] = []
    versions_dir = migrations_path() / "versions"
    for file_path in sorted(versions_dir.glob("*.py")):
        text = file_path.read_text(encoding="utf-8")
        rev_match = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        down_match = re.search(r"^down_revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        if rev_match:
            revisions.append(rev_match.group(1))
        if down_match:
            down_revisions.append(down_match.group(1))
    return revisions, down_revisions


def check_migrations() -> DoctorCheck:
    revisions, down_revisions = _parse_migration_revisions()
    heads = sorted(set(revisions) - set(down_revisions))
    if not revisions:
        return DoctorCheck("migrations", "fail", "no Alembic migration revisions found")

    rc, output = _run_command([sys.executable, "-m", "alembic", "heads"], timeout=30)
    status = "pass" if rc == 0 and all(head in output for head in heads) else "warn"
    return DoctorCheck(
        "migrations",
        status,
        "Alembic heads are discoverable"
        if status == "pass"
        else "Alembic head command could not be fully verified",
        {"expected_heads": heads, "revision_count": len(revisions), "alembic_heads_output": output},
    )


def check_agent_catalog() -> DoctorCheck:
    required_roles = {"coder", "researcher", "reviewer", "poyraz", "qa", "coverage"}
    try:
        from agent.registry import AgentCatalog

        registered = {spec.role_name for spec in AgentCatalog.list_all()}
    except Exception as exc:  # pragma: no cover - defensive runtime path
        return DoctorCheck("agent_catalog", "fail", f"AgentCatalog failed to load: {exc}")

    missing = sorted(required_roles - registered)
    return DoctorCheck(
        "agent_catalog",
        _status_from_bool(not missing),
        "all built-in roles are registered"
        if not missing
        else f"missing roles: {', '.join(missing)}",
        {"required_roles": sorted(required_roles), "registered_roles": sorted(registered)},
    )


def check_supervisor_routing() -> DoctorCheck:
    try:
        from agent.core.supervisor import SupervisorAgent

        samples = {
            "research": "web kaynak araştır",
            "review": "pull request review incele",
            "marketing": "seo kampanya metni üret",
            "coverage": "pytest coverage eksik test yaz",
            "code": "dosyaya fonksiyon ekle",
        }
        observed = {
            expected: SupervisorAgent._intent(prompt) for expected, prompt in samples.items()
        }
    except Exception as exc:  # pragma: no cover - defensive runtime path
        return DoctorCheck("supervisor_routing", "fail", f"Supervisor routing check failed: {exc}")

    mismatches = {expected: actual for expected, actual in observed.items() if expected != actual}
    return DoctorCheck(
        "supervisor_routing",
        _status_from_bool(not mismatches),
        "Supervisor intent routing smoke checks passed"
        if not mismatches
        else f"routing mismatches: {mismatches}",
        {"observed": observed},
    )


def check_websocket_routes() -> DoctorCheck:
    try:
        from web_server import app

        websocket_paths = sorted(
            getattr(route, "path", "")
            for route in app.routes
            if "WebSocket" in route.__class__.__name__
        )
    except Exception as exc:  # pragma: no cover - defensive runtime path
        source = (BASE_DIR / "web_server.py").read_text(encoding="utf-8")
        required = {"/ws/chat", "/ws/voice"}
        static_paths = sorted(path for path in required if f'@app.websocket("{path}")' in source)
        missing_static = sorted(required - set(static_paths))
        return DoctorCheck(
            "websocket_routes",
            "warn" if not missing_static else "fail",
            "web_server import failed, but websocket decorators were found statically"
            if not missing_static
            else f"web_server import failed and static routes are missing: {missing_static}",
            {
                "required": sorted(required),
                "websocket_paths": static_paths,
                "import_error": str(exc),
            },
        )

    required = {"/ws/chat", "/ws/voice"}
    missing = sorted(required - set(websocket_paths))
    return DoctorCheck(
        "websocket_routes",
        _status_from_bool(not missing),
        "required websocket routes are mounted"
        if not missing
        else f"missing websocket routes: {missing}",
        {"required": sorted(required), "websocket_paths": websocket_paths},
    )


def check_gpu() -> DoctorCheck:
    details: dict[str, Any] = {"detected": False, "run_gpu_stress": False}
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        rc, output = _run_command(
            [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"], timeout=10
        )
        if rc == 0 and output:
            details.update(
                {"detected": True, "source": "nvidia-smi", "devices": output.splitlines()}
            )
    if not details["detected"]:
        try:
            import torch

            if torch.cuda.is_available():
                details.update(
                    {
                        "detected": True,
                        "source": "torch",
                        "devices": [
                            torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
                        ],
                    }
                )
        except Exception as exc:
            details["torch_error"] = str(exc)

    details["run_gpu_stress"] = bool(details["detected"])
    return DoctorCheck(
        "gpu",
        "pass" if details["detected"] else "warn",
        "GPU detected; RUN_GPU_STRESS should be enabled"
        if details["detected"]
        else "GPU not detected; GPU stress tests remain opt-in",
        details,
    )


def _ollama_base_url() -> str:
    raw = os.getenv("OLLAMA_URL", "http://localhost:11434/api").rstrip("/")
    return raw if raw.endswith("/api") else f"{raw}/api"


def check_model(coding_model: str | None = None, *, smoke: bool = True) -> DoctorCheck:
    model = (coding_model or os.getenv("CODING_MODEL") or "qwen2.5-coder:7b").strip()
    model_prefix = model.split(":", 1)[0]
    base = _ollama_base_url()
    details: dict[str, Any] = {
        "model": model,
        "ollama_url": base,
        "present": False,
        "json_smoke": False,
    }
    try:
        import httpx

        with httpx.Client(timeout=10) as client:
            tags = client.get(f"{base}/tags")
            tags.raise_for_status()
            models = tags.json().get("models", [])
            names = {str(item.get("name", "")) for item in models if isinstance(item, dict)}
            details["present"] = model in names or any(
                name.startswith(model_prefix) for name in names
            )
            details["available_models"] = sorted(names)[:20]
            if smoke and details["present"]:
                prompt = 'Return exactly this JSON and nothing else: {"sidar_doctor": true}'
                response = client.post(
                    f"{base}/generate",
                    json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
                    timeout=60,
                )
                response.raise_for_status()
                text = str(response.json().get("response", "")).strip()
                details["smoke_response"] = text[:500]
                parsed = json.loads(text)
                details["json_smoke"] = parsed.get("sidar_doctor") is True
    except Exception as exc:
        details["error"] = str(exc)
        return DoctorCheck("model", "warn", "Ollama/model check could not be completed", details)

    if not details["present"]:
        return DoctorCheck("model", "warn", f"coding model is not present: {model}", details)
    if smoke and not details["json_smoke"]:
        return DoctorCheck(
            "model", "fail", "coding model did not return valid JSON smoke output", details
        )
    return DoctorCheck("model", "pass", "coding model is present and JSON smoke passed", details)


def run_doctor_report(
    *,
    output_path: str | Path = DEFAULT_OUTPUT,
    include_model_smoke: bool = True,
) -> dict[str, Any]:
    checks = [
        check_uv(),
        check_database_env(),
        check_migrations(),
        check_agent_catalog(),
        check_supervisor_routing(),
        check_websocket_routes(),
        check_gpu(),
        check_model(smoke=include_model_smoke),
    ]
    statuses = [check.status for check in checks]
    overall = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "overall_status": overall,
        "run_gpu_stress": any(
            check.name == "gpu" and bool(check.details.get("run_gpu_stress")) for check in checks
        ),
        "checks": [check.as_dict() for check in checks],
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    report = run_doctor_report(output_path=output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["overall_status"] in {"pass", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
