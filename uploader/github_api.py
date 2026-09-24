"""GitHub REST helpers for opening (or reusing) the upload pull request.

Extracted from ``github_upload.py``; collaborators are injected by its wrappers.
"""

from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping

from core.utils.trusted_urlopen import urlopen_trusted_request

GITHUB_PR_API_MAX_ATTEMPTS = 3

GITHUB_PR_API_RETRY_BASE_SECONDS = 1.0

GITHUB_PR_API_RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}


def github_repo_slug(remote_url: str, *, _is_valid_repo_url: Callable[..., bool]) -> str:
    """Extract an ``owner/repository`` slug from a validated GitHub remote URL."""
    normalized = str(remote_url or "").strip().removesuffix("/").removesuffix(".git")
    if not _is_valid_repo_url(remote_url):
        return ""
    if normalized.startswith("git@github.com:"):
        return normalized.removeprefix("git@github.com:")
    return normalized.removeprefix("https://github.com/")


def github_api_request(
    url: str,
    *,
    method: str,
    github_token: str,
    timeout: float,
    payload: Mapping[str, object] | None = None,
) -> object:
    """Send JSON to the allowlisted GitHub API origin through one audited sink."""
    normalized_method = method.upper()
    if normalized_method not in {"GET", "POST"}:
        raise ValueError("GitHub API isteği yalnızca GET veya POST kullanabilir.")
    if timeout <= 0:
        raise ValueError("GitHub API timeout değeri pozitif olmalıdır.")
    parsed = urllib.parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("GitHub API URL portu geçersiz.") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.github.com"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(
            "GitHub API isteği yalnızca https://api.github.com hedefine gönderilebilir."
        )

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=normalized_method)
    # URL origin'i yukarıdaki allowlist ile doğrulanır; tek denetlenmiş ağ sink'i budur.
    with urlopen_trusted_request(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def find_existing_upload_pull_request(
    repo_slug: str, branch: str, github_token: str, *, _github_api_request: Callable[..., object]
) -> str:
    """Return an existing open upload PR after an ambiguous create response."""
    owner = repo_slug.partition("/")[0]
    query = urllib.parse.urlencode({"state": "open", "head": f"{owner}:{branch}", "base": "main"})
    try:
        result = _github_api_request(
            f"https://api.github.com/repos/{repo_slug}/pulls?{query}",
            method="GET",
            github_token=github_token,
            timeout=30,
        )
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ):
        return ""
    if not isinstance(result, list):
        return ""
    for pull_request in result:
        if isinstance(pull_request, Mapping):
            pr_url = str(pull_request.get("html_url", "")).strip()
            if pr_url:
                return pr_url
    return ""


def open_upload_pull_request_via_api(
    branch: str,
    github_token: str,
    *,
    _find_existing_upload_pull_request: Callable[..., str],
    _github_api_request: Callable[..., object],
    _github_repo_slug: Callable[..., str],
    resolve_upload_version: Callable[..., str],
    run_command: Callable[..., tuple[bool, str]],
) -> tuple[bool, str]:
    """Create the upload PR through GitHub's API when the optional ``gh`` CLI is absent."""
    remote_ok, remote_url = run_command(["git", "remote", "get-url", "origin"], show_output=False)
    repo_slug = _github_repo_slug(remote_url) if remote_ok else ""
    if not repo_slug:
        return False, "GitHub origin adresinden owner/repository bilgisi çözülemedi."

    payload = {
        "title": f"Sidar {resolve_upload_version()} otomatik yükleme",
        "head": branch,
        "base": "main",
        "body": "Sidar github_upload.py tarafından PR-first yükleme akışıyla oluşturuldu.",
    }
    result: object = {}
    last_error = ""
    for attempt in range(1, GITHUB_PR_API_MAX_ATTEMPTS + 1):
        try:
            result = _github_api_request(
                f"https://api.github.com/repos/{repo_slug}/pulls",
                method="POST",
                github_token=github_token,
                timeout=30,
                payload=payload,
            )
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            if exc.code == 401:
                return (
                    False,
                    "GitHub token reddedildi (HTTP 401 / Bad credentials). "
                    "Tokenı GitHub'da yenileyip GITHUB_TOKEN (veya GH_TOKEN/GITHUB_PAT) "
                    "değerini SIDAR_KEYS_FILE ya da ~/.sidar_keys.env içinde güncelleyin. "
                    "Fine-grained token kullanıyorsanız ilgili repository için Pull requests: "
                    "Read and write izni verin.",
                )
            if exc.code == 422:
                existing_url = _find_existing_upload_pull_request(repo_slug, branch, github_token)
                if existing_url:
                    return True, existing_url
            last_error = f"GitHub API PR isteği HTTP {exc.code} ile reddedildi: {detail}"
            retryable = exc.code in GITHUB_PR_API_RETRYABLE_HTTP_CODES
        except (
            urllib.error.URLError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            existing_url = _find_existing_upload_pull_request(repo_slug, branch, github_token)
            if existing_url:
                return True, existing_url
            last_error = f"GitHub API üzerinden PR oluşturulamadı: {exc}"
            retryable = True

        if not retryable or attempt == GITHUB_PR_API_MAX_ATTEMPTS:
            return False, last_error
        time.sleep(GITHUB_PR_API_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))

    pr_url = str(result.get("html_url", "")).strip() if isinstance(result, Mapping) else ""
    if not pr_url:
        return False, "GitHub API PR yanıtında html_url bulunamadı."
    return True, pr_url


def open_upload_pull_request(
    branch: str,
    github_token: str,
    *,
    _open_upload_pull_request_via_api: Callable[..., tuple[bool, str]],
    run_command: Callable[..., tuple[bool, str]],
) -> tuple[bool, str]:
    """Open a GitHub PR, using ``gh`` when installed and the API otherwise."""
    if shutil.which("gh") is None:
        return _open_upload_pull_request_via_api(branch, github_token)
    return run_command(
        ["gh", "pr", "create", "--base", "main", "--head", branch, "--fill"],
        show_output=False,
        extra_env={"GH_TOKEN": github_token},
    )
