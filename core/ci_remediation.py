"""
Sidar Project — Proaktif CI Remediation Yardımcıları
CI pipeline başarısızlıklarını webhook tetiklerinden çıkarır, ajanlar için
teşhis/remediation prompt'u üretir ve PR taslağı oluşturur.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


_CI_FAILURE_CONCLUSIONS = {"failure", "timed_out", "cancelled", "startup_failure", "action_required"}
_TARGET_PATTERN = re.compile(r"""(?P<path>(?:tests|core|agent|managers|web_server|main|config|docs|web_ui_react)[/\w.\-]+)""")


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


def _build_diagnostic_hints(failure_summary: str, log_excerpt: str, suspected_targets: list[str]) -> list[str]:
    hints: list[str] = []
    if suspected_targets:
        hints.append(f"İlk inceleme hedefleri: {', '.join(suspected_targets)}")
    if "pytest" in failure_summary.lower() or "assert" in log_excerpt.lower():
        hints.append("Test assertion drift veya beklenen çıktı değişimi olabilir.")
    if "timeout" in failure_summary.lower():
        hints.append("Timeout / yarış durumu / dış bağımlılık gecikmesi araştırılmalı.")
    if "import" in log_excerpt.lower() or "module" in log_excerpt.lower():
        hints.append("Import zinciri ve GraphRAG etki analizi ile bağımlı modüller kontrol edilmeli.")
    return hints[:5]


def is_ci_failure_event(event_name: str, payload: Dict[str, Any]) -> bool:
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


def build_ci_failure_context(event_name: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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
            "diagnostic_hints": _build_diagnostic_hints(failure_summary, log_excerpt, suspected_targets),
        }

    if normalized == "check_run":
        check = dict(data.get("check_run") or {})
        output = dict(check.get("output") or {})
        log_excerpt = _trim_text("\n\n".join(filter(None, [output.get("summary"), output.get("text")])), 1200)
        failure_summary = _trim_text(output.get("title") or check.get("name") or "check failed", 200)
        suspected_targets = _extract_suspected_targets(log_excerpt, failure_summary)
        return {
            "kind": "check_run",
            "repo": repo_name,
            "workflow_name": str(check.get("name", "") or "check_run"),
            "run_id": str(check.get("id", "") or ""),
            "run_number": "",
            "branch": str(data.get("check_run", {}).get("check_suite", {}).get("head_branch", "") or ""),
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
            "diagnostic_hints": _build_diagnostic_hints(failure_summary, log_excerpt, suspected_targets),
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
        "diagnostic_hints": _build_diagnostic_hints(failure_summary, log_excerpt, suspected_targets),
    }


def build_ci_failure_prompt(context: Dict[str, Any]) -> str:
    info = dict(context or {})
    suspected_targets = ", ".join(info.get("suspected_targets") or [])
    diagnostic_hints = " | ".join(info.get("diagnostic_hints") or [])
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
        f"suspected_targets={suspected_targets}\n"
        f"diagnostic_hints={diagnostic_hints}\n"
    )


def build_pr_proposal(context: Dict[str, Any], diagnosis: str) -> Dict[str, Any]:
    info = dict(context or {})
    workflow_name = str(info.get("workflow_name", "") or "CI")
    run_id = str(info.get("run_id", "") or "manual")
    base_branch = str(info.get("base_branch", "") or "main")
    branch = str(info.get("branch", "") or "")
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
        "## Suspected Targets\n"
        f"{', '.join(info.get('suspected_targets') or []) or '-'}\n\n"
        "## Diagnosis and Proposed Patch\n"
        f"{_trim_text(diagnosis, 8000)}\n"
    )
    return {
        "title": title,
        "body": body,
        "base_branch": base_branch,
        "head_branch_suggestion": head_branch_suggestion,
        "auto_create_ready": False,
    }