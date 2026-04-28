"""
Sidar Project — Proaktif CI Remediation Yardımcıları
CI pipeline başarısızlıklarını webhook tetiklerinden çıkarır, ajanlar için
teşhis/remediation prompt'u üretir ve PR taslağı oluşturur.
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import re
import shlex
from typing import Any

_CI_FAILURE_CONCLUSIONS = {
    "failure",
    "timed_out",
    "cancelled",
    "startup_failure",
    "action_required",
}
_TARGET_PATTERN = re.compile(
    r"""(?P<path>(?:tests|core|agent|managers|web_server|main|config|docs|web_ui_react)[/\w.\-]+)"""
)
_ROOT_CAUSE_PATTERN = re.compile(
    r"""(?P<line>.*?(?:AssertionError|ModuleNotFoundError|ImportError|TypeError|ValueError|SyntaxError|NameError|timeout|timed out|failed|Incompatible types|Missing type parameters|no-untyped-def|mypy).*)""",
    re.IGNORECASE,
)
_MYPY_ERROR_LINE_PATTERN = re.compile(
    r"^(?P<path>[\w./\\-]+\.py):(?P<line>\d+)(?::(?P<column>\d+))?:\s*error:\s*(?P<message>.+?)\s*(?:\[(?P<code>[^\]]+)\])?$"
)
_MISSING_MODULE_PATTERN = re.compile(
    r"(?:ModuleNotFoundError:\s*No module named|No module named)\s+['\"](?P<module>[\w.:-]+)['\"]",
    re.IGNORECASE,
)
_MYPY_IMPORT_UNTYPED_MODULE_PATTERN = re.compile(
    r"(?:Library stubs not installed for|Cannot find implementation or library stub for module named)\s+['\"](?P<module>[\w.:-]+)['\"]",
    re.IGNORECASE,
)
_MYPY_STUB_INSTALL_HINT_PATTERN = re.compile(
    r"(?:uv\s+pip\s+install|python(?:3)?\s+-m\s+pip\s+install|pip\s+install)\s+(?P<pkg>types-[A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_AUTO_INSTALL_PACKAGES: dict[str, str] = {
    "psycopg2": "psycopg2-binary",
}
_AUTO_INSTALL_TYPE_STUBS: dict[str, str] = {
    "psutil": "types-psutil",
    "yaml": "types-PyYAML",
    "dateutil": "types-python-dateutil",
    "requests": "types-requests",
}


def _is_allowed_validation_command(command: str) -> bool:
    normalized = str(command or "").strip().strip("`")
    if not normalized:
        return False
    if any(token in normalized for token in ("&&", "||", ";", "|", ">", "<", "$", "\n", "\r")):
        return False
    try:
        parts = shlex.split(normalized)
    except ValueError:
        return False
    if not parts:
        return False

    def _is_allowed_pytest_arg(token: str) -> bool:
        return (
            token == "."
            or token.startswith("-")
            or token.startswith("tests/")
            or token.startswith("test/")
            or token.startswith("./")
            or token.endswith(".py")
            or "/" in token
        )

    if parts[0] == "pytest":
        return all(_is_allowed_pytest_arg(token) for token in parts[1:])
    if parts[:3] == ["python", "-m", "pytest"]:
        return all(_is_allowed_pytest_arg(token) for token in parts[3:])
    if parts[:2] == ["bash", "run_tests.sh"]:
        return all(re.fullmatch(r"[\w./-]+", token) for token in parts[2:])
    if parts[:3] == ["uv", "pip", "install"] and len(parts) >= 4:
        return all(re.fullmatch(r"[A-Za-z0-9_.-]+", token) for token in parts[3:])
    return False


def _trim_text(value: Any, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " …[truncated]"


def _extract_suspected_targets(*values: Any) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "")
        for match in _TARGET_PATTERN.finditer(text):
            path = match.group("path").strip().strip(".,:;)")
            if path and path not in seen:
                seen.add(path)
                found.append(path)
    return found[:8]


def _extract_root_cause_line(*values: Any) -> str:
    for value in values:
        text = str(value or "")
        for line in text.splitlines():
            normalized = line.strip()
            if not normalized:
                continue
            if _ROOT_CAUSE_PATTERN.match(normalized):
                return _trim_text(normalized, 220)
    return ""


def _extract_failed_job_names(data: dict[str, Any]) -> list[str]:
    jobs = list(data.get("failed_jobs") or data.get("jobs") or [])
    names: list[str] = []
    for item in jobs:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("job") or item.get("title") or "").strip()
        else:
            name = str(item or "").strip()
        if name and name not in names:
            names.append(name)
    return names[:6]


def _generic_ci_context(event_name: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    data = dict(payload or {})
    normalized = str(event_name or "").strip().lower()
    explicit_flag = bool(data.get("ci_failure") or data.get("pipeline_failed"))
    ci_like = normalized in {"ci_failure_remediation", "ci_pipeline_failed", "pipeline_failed"}
    if not explicit_flag and not ci_like:
        return None

    failure_summary = _trim_text(
        data.get("failure_summary") or data.get("summary") or data.get("message") or "ci failure",
        220,
    )
    log_excerpt = _trim_text(
        data.get("log_excerpt")
        or data.get("logs")
        or data.get("error")
        or data.get("details")
        or "",
        1200,
    )
    suspected_targets = _extract_suspected_targets(log_excerpt, failure_summary)
    failed_jobs = _extract_failed_job_names(data)
    return {
        "kind": "generic_ci_failure",
        "repo": str(data.get("repo") or data.get("repository") or "").strip(),
        "workflow_name": str(
            data.get("workflow_name")
            or data.get("pipeline")
            or data.get("job_name")
            or "ci_failure"
        ).strip(),
        "run_id": str(
            data.get("run_id") or data.get("pipeline_id") or data.get("build_id") or ""
        ).strip(),
        "run_number": str(data.get("run_number") or data.get("pipeline_number") or "").strip(),
        "branch": str(data.get("branch") or data.get("ref") or "").strip(),
        "base_branch": str(data.get("base_branch") or data.get("target_branch") or "main").strip(),
        "sha": str(data.get("sha") or data.get("commit") or "").strip(),
        "conclusion": str(data.get("conclusion") or "failure").strip(),
        "status": str(data.get("status") or "completed").strip(),
        "html_url": str(data.get("html_url") or data.get("pipeline_url") or "").strip(),
        "jobs_url": str(data.get("jobs_url") or "").strip(),
        "logs_url": str(data.get("logs_url") or data.get("log_url") or "").strip(),
        "log_excerpt": log_excerpt,
        "failure_summary": failure_summary,
        "suspected_targets": suspected_targets,
        "failed_jobs": failed_jobs,
        "root_cause_hint": _extract_root_cause_line(log_excerpt, failure_summary),
        "diagnostic_hints": _build_diagnostic_hints(
            failure_summary, log_excerpt, suspected_targets
        ),
    }


def _build_diagnostic_hints(
    failure_summary: str, log_excerpt: str, suspected_targets: list[str]
) -> list[str]:
    hints: list[str] = []
    if suspected_targets:
        hints.append(f"İlk inceleme hedefleri: {', '.join(suspected_targets)}")
    if "pytest" in failure_summary.lower() or "assert" in log_excerpt.lower():
        hints.append("Test assertion drift veya beklenen çıktı değişimi olabilir.")
    if "timeout" in failure_summary.lower():
        hints.append("Timeout / yarış durumu / dış bağımlılık gecikmesi araştırılmalı.")
    if "import" in log_excerpt.lower() or "module" in log_excerpt.lower():
        hints.append(
            "Import zinciri ve GraphRAG etki analizi ile bağımlı modüller kontrol edilmeli."
        )
    return hints[:5]


def is_ci_failure_event(event_name: str, payload: dict[str, Any]) -> bool:
    normalized = str(event_name or "").strip().lower()
    data = dict(payload or {})

    if normalized == "workflow_run":
        workflow = dict(data.get("workflow_run") or {})
        return (
            str(workflow.get("status", "")).lower() == "completed"
            and str(workflow.get("conclusion", "")).lower() in _CI_FAILURE_CONCLUSIONS
        )

    if normalized == "check_run":
        check = dict(data.get("check_run") or {})
        return str(check.get("conclusion", "")).lower() in _CI_FAILURE_CONCLUSIONS

    if normalized == "check_suite":
        suite = dict(data.get("check_suite") or {})
        return str(suite.get("conclusion", "")).lower() in _CI_FAILURE_CONCLUSIONS

    return False


def build_ci_failure_context(event_name: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    generic = _generic_ci_context(event_name, payload)
    if generic:
        return generic

    if not is_ci_failure_event(event_name, payload):
        return None

    normalized = str(event_name or "").strip().lower()
    data = dict(payload or {})
    repo = dict(data.get("repository") or {})
    repo_name = str(repo.get("full_name") or repo.get("name") or "").strip()

    if normalized == "workflow_run":
        workflow = dict(data.get("workflow_run") or {})
        pull_requests = list(workflow.get("pull_requests") or [])
        base_branch = ""
        if pull_requests:
            base_branch = str((pull_requests[0] or {}).get("base", {}).get("ref", "") or "").strip()
        failure_summary = _trim_text(workflow.get("conclusion") or "failure", 200)
        log_excerpt = _trim_text(workflow.get("display_title") or workflow.get("name") or "", 400)
        suspected_targets = _extract_suspected_targets(log_excerpt, failure_summary)
        return {
            "kind": "workflow_run",
            "repo": repo_name,
            "workflow_name": str(workflow.get("name", "") or "workflow_run"),
            "run_id": str(workflow.get("id", "") or ""),
            "run_number": str(workflow.get("run_number", "") or ""),
            "branch": str(workflow.get("head_branch", "") or ""),
            "base_branch": base_branch or str(repo.get("default_branch", "") or "main"),
            "sha": str(workflow.get("head_sha", "") or ""),
            "conclusion": str(workflow.get("conclusion", "") or ""),
            "status": str(workflow.get("status", "") or ""),
            "html_url": str(workflow.get("html_url", "") or ""),
            "jobs_url": str(workflow.get("jobs_url", "") or ""),
            "logs_url": str(workflow.get("logs_url", "") or ""),
            "log_excerpt": log_excerpt,
            "failure_summary": failure_summary,
            "suspected_targets": suspected_targets,
            "failed_jobs": _extract_failed_job_names(workflow),
            "root_cause_hint": _extract_root_cause_line(log_excerpt, failure_summary),
            "diagnostic_hints": _build_diagnostic_hints(
                failure_summary, log_excerpt, suspected_targets
            ),
        }

    if normalized == "check_run":
        check = dict(data.get("check_run") or {})
        output = dict(check.get("output") or {})
        log_excerpt = _trim_text(
            "\n\n".join(filter(None, [output.get("summary"), output.get("text")])), 1200
        )
        failure_summary = _trim_text(
            output.get("title") or check.get("name") or "check failed", 200
        )
        suspected_targets = _extract_suspected_targets(log_excerpt, failure_summary)
        return {
            "kind": "check_run",
            "repo": repo_name,
            "workflow_name": str(check.get("name", "") or "check_run"),
            "run_id": str(check.get("id", "") or ""),
            "run_number": "",
            "branch": str(
                data.get("check_run", {}).get("check_suite", {}).get("head_branch", "") or ""
            ),
            "base_branch": str(repo.get("default_branch", "") or "main"),
            "sha": str(check.get("head_sha", "") or ""),
            "conclusion": str(check.get("conclusion", "") or ""),
            "status": str(check.get("status", "") or ""),
            "html_url": str(check.get("html_url", "") or ""),
            "jobs_url": str(check.get("details_url", "") or ""),
            "logs_url": str(check.get("details_url", "") or ""),
            "log_excerpt": log_excerpt,
            "failure_summary": failure_summary,
            "suspected_targets": suspected_targets,
            "failed_jobs": _extract_failed_job_names(check),
            "root_cause_hint": _extract_root_cause_line(log_excerpt, failure_summary),
            "diagnostic_hints": _build_diagnostic_hints(
                failure_summary, log_excerpt, suspected_targets
            ),
        }

    suite = dict(data.get("check_suite") or {})
    failure_summary = _trim_text(suite.get("conclusion") or "check suite failure", 200)
    log_excerpt = _trim_text(suite.get("app", {}).get("name") or "check_suite_failure", 400)
    suspected_targets = _extract_suspected_targets(log_excerpt, failure_summary)
    return {
        "kind": "check_suite",
        "repo": repo_name,
        "workflow_name": str(suite.get("head_branch", "") or "check_suite"),
        "run_id": str(suite.get("id", "") or ""),
        "run_number": "",
        "branch": str(suite.get("head_branch", "") or ""),
        "base_branch": str(repo.get("default_branch", "") or "main"),
        "sha": str(suite.get("head_sha", "") or ""),
        "conclusion": str(suite.get("conclusion", "") or ""),
        "status": str(suite.get("status", "") or ""),
        "html_url": str(suite.get("url", "") or ""),
        "jobs_url": str(suite.get("url", "") or ""),
        "logs_url": str(suite.get("url", "") or ""),
        "log_excerpt": log_excerpt,
        "failure_summary": failure_summary,
        "suspected_targets": suspected_targets,
        "failed_jobs": _extract_failed_job_names(suite),
        "root_cause_hint": _extract_root_cause_line(log_excerpt, failure_summary),
        "diagnostic_hints": _build_diagnostic_hints(
            failure_summary, log_excerpt, suspected_targets
        ),
    }


def build_local_failure_context(
    log_text: str,
    *,
    source: str = "mypy",
    log_path: str = "",
) -> dict[str, Any]:
    """Yerel araç log'larından CI-remediation uyumlu context üretir."""
    text = str(log_text or "")
    normalized_source = str(source or "local").strip().lower() or "local"
    suspected_targets: list[str] = []
    root_cause_hint = ""
    failure_lines: list[str] = []
    seen_paths: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _MYPY_ERROR_LINE_PATTERN.match(line)
        if match:
            path = str(match.group("path") or "").strip().lstrip("./")
            if path and path not in seen_paths:
                seen_paths.add(path)
                suspected_targets.append(path)
            code = str(match.group("code") or "").strip()
            message = str(match.group("message") or "").strip()
            failure_lines.append(f"{path}:{match.group('line')} {message} [{code or 'mypy'}]")
            continue
        if _ROOT_CAUSE_PATTERN.match(line) and not root_cause_hint:
            root_cause_hint = _trim_text(line, 220)

    failure_summary = (
        f"{normalized_source} yerel kalite kapısında hata bulundu "
        f"({len(failure_lines)} kayıt, {len(suspected_targets)} dosya)."
    )
    local_scope_limit = max(
        1,
        int(os.getenv("SELF_HEAL_LOCAL_SCOPE_LIMIT", "200") or "200"),
    )
    effective_targets = suspected_targets[:local_scope_limit]
    log_excerpt = _trim_text(text, 1200)
    if not root_cause_hint and failure_lines:
        root_cause_hint = _trim_text(failure_lines[0], 220)
    return {
        "kind": "local_failure",
        "repo": "",
        "workflow_name": f"local_{normalized_source}",
        "run_id": "local",
        "run_number": "",
        "branch": "",
        "base_branch": "main",
        "sha": "",
        "conclusion": "failure",
        "status": "completed",
        "html_url": "",
        "jobs_url": "",
        "logs_url": str(log_path or "").strip(),
        "log_excerpt": log_excerpt,
        "failure_summary": _trim_text(failure_summary, 220),
        "suspected_targets": effective_targets,
        "failed_jobs": [f"local:{normalized_source}"],
        "root_cause_hint": root_cause_hint,
        "diagnostic_hints": _build_diagnostic_hints(
            failure_summary,
            "\n".join(failure_lines) or log_excerpt,
            effective_targets,
        ),
    }


def build_ci_failure_prompt(context: dict[str, Any]) -> str:
    info = dict(context or {})
    suspected_targets = ", ".join(info.get("suspected_targets") or [])
    diagnostic_hints = " | ".join(info.get("diagnostic_hints") or [])
    failed_jobs = ", ".join(info.get("failed_jobs") or [])
    return (
        "[CI_REMEDIATION]\n"
        "Aşağıdaki CI başarısızlığını proaktif remediation akışı olarak ele al.\n"
        "1. Kök nedeni teşhis et.\n"
        "2. Minimal ve güvenli patch öner.\n"
        "3. Çalıştırılması gereken testleri belirt.\n"
        "4. PR başlığı ve PR gövdesi taslağı üret.\n"
        "5. Log/URL'lerden emin olamadığın noktaları açıkça varsayım olarak işaretle.\n\n"
        f"repo={info.get('repo', '')}\n"
        f"kind={info.get('kind', '')}\n"
        f"workflow_name={info.get('workflow_name', '')}\n"
        f"run_id={info.get('run_id', '')}\n"
        f"run_number={info.get('run_number', '')}\n"
        f"branch={info.get('branch', '')}\n"
        f"base_branch={info.get('base_branch', '')}\n"
        f"sha={info.get('sha', '')}\n"
        f"status={info.get('status', '')}\n"
        f"conclusion={info.get('conclusion', '')}\n"
        f"html_url={info.get('html_url', '')}\n"
        f"jobs_url={info.get('jobs_url', '')}\n"
        f"logs_url={info.get('logs_url', '')}\n"
        f"failure_summary={info.get('failure_summary', '')}\n"
        f"log_excerpt={info.get('log_excerpt', '')}\n"
        f"failed_jobs={failed_jobs}\n"
        f"root_cause_hint={info.get('root_cause_hint', '')}\n"
        f"suspected_targets={suspected_targets}\n"
        f"diagnostic_hints={diagnostic_hints}\n"
    )


def build_self_heal_patch_prompt(
    context: dict[str, Any],
    diagnosis: str,
    remediation_loop: dict[str, Any],
    file_snapshots: list[dict[str, str]],
) -> str:
    """Self-healing için düşük riskli JSON patch planı prompt'u üretir."""
    info = dict(context or {})
    loop = dict(remediation_loop or {})
    scope_paths = [
        str(item).strip() for item in list(loop.get("scope_paths") or []) if str(item).strip()
    ]
    validation_commands = [
        str(item).strip()
        for item in list(loop.get("validation_commands") or [])
        if str(item).strip()
    ]
    snapshot_lines: list[str] = []
    for item in file_snapshots[:6]:
        path = str(item.get("path") or "").strip()
        content = _trim_text(item.get("content") or "", 4000)
        if not path or not content:
            continue
        snapshot_lines.append(f"[FILE] {path}\n{content}")

    return (
        "[SELF_HEAL_PLAN]\n"
        "Sadece düşük riskli, minimal ve geri alınabilir patch planı üret.\n"
        "Yanıtın yalnızca geçerli JSON olsun. Markdown kullanma.\n"
        "Sadece şu şemayı kullan:\n"
        '{"summary":"...","confidence":"low|medium|high","operations":[{"action":"patch","path":"...","target":"...","replacement":"..."}],"validation_commands":["pytest -q ..."]}\n'
        "Kurallar:\n"
        f"- Yalnızca şu kapsam içindeki dosyaları değiştir: {', '.join(scope_paths) or '-'}\n"
        "- Sadece `patch` aksiyonu üret; dosyayı tamamen yeniden yazma.\n"
        "- `target` mevcut dosyada birebir bulunmalı; minimal diff üret.\n"
        "- Patch öncesi/sonrası deterministik olmalı.\n"
        "- Validation komutları güvenli sandbox içinde çalışacak; pytest/python -m pytest/bash run_tests.sh dışına çıkma.\n\n"
        f"repo={info.get('repo', '')}\n"
        f"workflow_name={info.get('workflow_name', '')}\n"
        f"failure_summary={info.get('failure_summary', '')}\n"
        f"root_cause_hint={info.get('root_cause_hint', '')}\n"
        f"diagnosis={_trim_text(diagnosis, 5000)}\n"
        f"validation_commands={', '.join(validation_commands) or '-'}\n\n"
        + "\n\n".join(snapshot_lines)
    )


def normalize_self_heal_plan(
    raw_plan: Any,
    *,
    scope_paths: list[str],
    fallback_validation_commands: list[str],
    max_operations: int = 3,
) -> dict[str, Any]:
    """LLM çıktısını güvenli, kapsam kısıtlı self-heal planına dönüştürür."""
    def _coerce_payload(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, list):
            return {"operations": value}
        return {}

    if isinstance(raw_plan, str):
        text = raw_plan.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
        try:
            payload = _coerce_payload(json.loads(text))
        except Exception:
            payload = {}
    else:
        payload = _coerce_payload(raw_plan)

    if not payload and isinstance(raw_plan, str):
        # Bazı küçük/yerel modeller JSON yerine python-benzeri liste döndürebilir.
        alt_start = raw_plan.find("[")
        alt_end = raw_plan.rfind("]")
        if alt_start != -1 and alt_end != -1 and alt_end > alt_start:
            candidate = raw_plan[alt_start : alt_end + 1]
            with contextlib.suppress(Exception):
                parsed = ast.literal_eval(candidate)
                payload = _coerce_payload(parsed)

    allowed_paths = {str(path).strip().lstrip("./") for path in scope_paths if str(path).strip()}
    raw_operations = (
        payload.get("operations")
        or payload.get("patches")
        or payload.get("edits")
        or payload.get("changes")
        or []
    )
    if isinstance(raw_operations, dict):
        raw_operations = [raw_operations]
    if not raw_operations and isinstance(payload.get("operation"), dict):
        raw_operations = [payload.get("operation")]
    if not raw_operations and any(
        key in payload for key in ("target", "replacement", "before", "after")
    ):
        raw_operations = [payload]

    operations = []
    for item in list(raw_operations or [])[:max_operations]:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or item.get("op") or item.get("type") or "").strip().lower()
        path = str(
            item.get("path")
            or item.get("file")
            or item.get("target_path")
            or item.get("file_path")
            or ""
        ).strip().lstrip("./")
        target = str(
            item.get("target")
            or item.get("find")
            or item.get("search")
            or item.get("before")
            or item.get("old")
            or ""
        )
        replacement = str(
            item.get("replacement")
            or item.get("replace")
            or item.get("after")
            or item.get("new")
            or ""
        )
        if not action and target:
            action = "patch"
        if action != "patch" or not path or not target or path.startswith("/") or ".." in path:
            continue
        if allowed_paths and path not in allowed_paths:
            continue
        operations.append(
            {
                "action": "patch",
                "path": path,
                "target": target,
                "replacement": replacement,
            }
        )

    validation_commands: list[str] = []
    for command in list(payload.get("validation_commands") or []) + list(
        fallback_validation_commands or []
    ):
        normalized = str(command or "").strip().strip("`")
        if not _is_allowed_validation_command(normalized):
            continue
        if normalized not in validation_commands:
            validation_commands.append(normalized)

    return {
        "summary": str(payload.get("summary") or "").strip()
        or "LLM self-heal planı normalize edildi.",
        "confidence": str(payload.get("confidence") or "unknown").strip().lower(),
        "operations": operations,
        "validation_commands": validation_commands[:5],
    }


def build_root_cause_summary(context: dict[str, Any], diagnosis: str) -> str:
    info = dict(context or {})
    diagnosis_text = str(diagnosis or "").strip()
    if diagnosis_text:
        first_sentence = diagnosis_text.splitlines()[0].strip()
        if first_sentence:
            compact_sentence = _trim_text(first_sentence, 220)
            if compact_sentence.lower().startswith(("kök neden", "root cause")):
                return compact_sentence
    inferred = _extract_root_cause_line(
        diagnosis, info.get("log_excerpt"), info.get("failure_summary")
    )
    if inferred:
        return inferred
    if info.get("root_cause_hint"):
        return str(info.get("root_cause_hint"))
    return _trim_text(
        str(info.get("failure_summary") or "CI başarısızlığı için ek teşhis gerekiyor."), 220
    )


def build_pr_proposal(context: dict[str, Any], diagnosis: str) -> dict[str, Any]:
    info = dict(context or {})
    workflow_name = str(info.get("workflow_name", "") or "CI")
    run_id = str(info.get("run_id", "") or "manual")
    base_branch = str(info.get("base_branch", "") or "main")
    branch = str(info.get("branch", "") or "")
    root_cause = build_root_cause_summary(info, diagnosis)
    title = f"CI remediation: stabilize {workflow_name}"
    head_branch_suggestion = f"ci-remediation/{run_id}"
    body = (
        "## Context\n"
        f"- Repository: {info.get('repo', '')}\n"
        f"- Workflow: {workflow_name}\n"
        f"- Run ID: {run_id}\n"
        f"- Base branch: {base_branch}\n"
        f"- Source branch: {branch}\n"
        f"- SHA: {info.get('sha', '')}\n"
        f"- HTML URL: {info.get('html_url', '')}\n"
        f"- Logs URL: {info.get('logs_url', '')}\n\n"
        "## Failure Summary\n"
        f"{info.get('failure_summary', '')}\n\n"
        "## Root Cause Hypothesis\n"
        f"{root_cause}\n\n"
        "## Suspected Targets\n"
        f"{', '.join(info.get('suspected_targets') or []) or '-'}\n\n"
        "## Failed Jobs\n"
        f"{', '.join(info.get('failed_jobs') or []) or '-'}\n\n"
        "## Diagnosis and Proposed Patch\n"
        f"{_trim_text(diagnosis, 8000)}\n"
    )
    return {
        "title": title,
        "body": body,
        "base_branch": base_branch,
        "head_branch_suggestion": head_branch_suggestion,
        "root_cause_summary": root_cause,
        "auto_create_ready": bool(root_cause),
    }


def _extract_validation_commands(context: dict[str, Any], diagnosis: str) -> list[str]:
    commands: list[str] = []
    for source in (context.get("failure_summary"), context.get("log_excerpt"), diagnosis):
        for line in str(source or "").splitlines():
            normalized = line.strip().strip("`")
            if not normalized:
                continue
            if _is_allowed_validation_command(normalized) and normalized not in commands:
                commands.append(normalized)
    suspected_targets = list(context.get("suspected_targets") or [])
    targeted_tests = [path for path in suspected_targets if str(path).startswith("tests/")]
    if targeted_tests:
        commands.append("pytest -q " + " ".join(targeted_tests[:6]))
    commands.append("python -m pytest")
    return list(dict.fromkeys(cmd for cmd in commands if cmd))[:5]


def build_remediation_loop(context: dict[str, Any], diagnosis: str) -> dict[str, Any]:
    info = dict(context or {})
    diagnosis_text = str(diagnosis or "").strip()
    suspected_targets = [
        str(item).strip() for item in list(info.get("suspected_targets") or []) if str(item).strip()
    ]
    failed_jobs = [
        str(item).strip() for item in list(info.get("failed_jobs") or []) if str(item).strip()
    ]
    root_cause = build_root_cause_summary(info, diagnosis_text)
    validation_commands = _extract_validation_commands(info, diagnosis_text)
    high_risk_keywords = (
        "syntaxerror",
        "modulenotfounderror",
        "importerror",
        "timeout",
        "typeerror",
        "valueerror",
    )
    combined_text = "\n".join(
        filter(
            None,
            [
                diagnosis_text,
                root_cause,
                info.get("failure_summary", ""),
                info.get("log_excerpt", ""),
            ],
        )
    ).lower()
    scope_hitl_threshold = max(
        1,
        int(os.getenv("SELF_HEAL_HITL_SCOPE_THRESHOLD", "3") or "3"),
    )
    auto_batch_size = max(
        1,
        int(os.getenv("SELF_HEAL_AUTONOMOUS_BATCH_SIZE", "5") or "5"),
    )
    needs_human_approval = (
        any(keyword in combined_text for keyword in high_risk_keywords)
        or len(suspected_targets) > scope_hitl_threshold
    )
    missing_modules = sorted(
        {
            match.group("module").strip()
            for match in _MISSING_MODULE_PATTERN.finditer(combined_text)
            if match.group("module").strip()
        }
    )
    import_untyped_modules = sorted(
        {
            match.group("module").strip().split(".", 1)[0]
            for match in _MYPY_IMPORT_UNTYPED_MODULE_PATTERN.finditer(combined_text)
            if match.group("module").strip()
        }
    )
    hinted_stub_packages = sorted(
        {
            match.group("pkg").strip()
            for match in _MYPY_STUB_INSTALL_HINT_PATTERN.finditer(combined_text)
            if match.group("pkg").strip()
        }
    )
    bootstrap_commands: list[str] = []
    for module_name in missing_modules:
        package_name = _AUTO_INSTALL_PACKAGES.get(module_name)
        if package_name:
            bootstrap_commands.append(f"uv pip install {package_name}")
    for module_name in import_untyped_modules:
        package_name = _AUTO_INSTALL_TYPE_STUBS.get(module_name)
        if package_name:
            bootstrap_commands.append(f"uv pip install {package_name}")
    for package_name in hinted_stub_packages:
        bootstrap_commands.append(f"uv pip install {package_name}")
    batched_scope = len(suspected_targets) > scope_hitl_threshold
    autonomous_batches: list[dict[str, Any]] = []
    if batched_scope:
        for index in range(0, len(suspected_targets), auto_batch_size):
            chunk = suspected_targets[index : index + auto_batch_size]
            module_hint = str(chunk[0]).split("/", 1)[0] if chunk else "module"
            autonomous_batches.append(
                {
                    "batch_id": f"batch-{(index // auto_batch_size) + 1}",
                    "module_hint": module_hint,
                    "scope_paths": chunk,
                    "suggested_prompt": (
                        f"Sadece {module_hint}/ kapsamındaki no-untyped-def ve argüman tipi hatalarını düzelt. "
                        f"Hedef dosyalar: {', '.join(chunk[:5])}"
                    ),
                }
            )
    mode = (
        "self_heal_with_hitl_batched"
        if needs_human_approval and batched_scope
        else "self_heal_with_hitl"
        if needs_human_approval
        else "self_heal"
    )
    status = "planned" if (diagnosis_text or suspected_targets) else "needs_diagnosis"
    effective_validation_commands = list(dict.fromkeys(bootstrap_commands + validation_commands))
    return {
        "status": status,
        "mode": mode,
        "needs_human_approval": needs_human_approval,
        "max_auto_attempts": 1 if needs_human_approval else 2,
        "scope_paths": suspected_targets[:12],
        "failed_jobs": failed_jobs[:6],
        "validation_commands": effective_validation_commands,
        "bootstrap_commands": bootstrap_commands,
        "autonomous_batches": autonomous_batches[:12],
        "steps": [
            {
                "name": "diagnose",
                "status": "completed" if diagnosis_text else "pending",
                "detail": root_cause,
            },
            {
                "name": "patch",
                "status": "pending" if suspected_targets else "blocked",
                "detail": "Şüpheli dosyalar için minimal ve kontrollü patch hazırlanacak.",
            },
            {
                "name": "validate",
                "status": "pending" if effective_validation_commands else "blocked",
                "detail": "Hedefli testler ve tam regresyon komutları çalıştırılacak.",
            },
            {
                "name": "handoff",
                "status": "pending",
                "detail": (
                    "Riskli remediation önce HITL onayına gidecek."
                    if needs_human_approval
                    else "Doğrulama sonrası PR/proposal güncellenecek."
                ),
            },
        ],
        "summary": (
            f"Remediation loop hazır: mod={mode}, hedef={len(suspected_targets[:12])} dosya, "
            f"doğrulama={len(effective_validation_commands)} komut, failed_jobs={len(failed_jobs[:6])}."
        ),
        "operator_guidance": (
            "Bekleyen HITL kaydını reject/cancel ederek remediation'ı modül bazlı batch'lerle yeniden başlatın."
            if needs_human_approval and batched_scope
            else ""
        ),
    }


def build_ci_remediation_payload(context: dict[str, Any], diagnosis: str) -> dict[str, Any]:
    info = dict(context or {})
    pr_proposal = build_pr_proposal(info, diagnosis)
    root_cause = pr_proposal.get("root_cause_summary") or build_root_cause_summary(info, diagnosis)
    remediation_loop = build_remediation_loop(info, diagnosis)
    return {
        "context": info,
        "prompt": build_ci_failure_prompt(info),
        "suspected_targets": list(info.get("suspected_targets") or []),
        "diagnostic_hints": list(info.get("diagnostic_hints") or []),
        "failed_jobs": list(info.get("failed_jobs") or []),
        "root_cause_summary": str(root_cause or ""),
        "remediation_loop": remediation_loop,
        "pr_proposal": pr_proposal,
    }
