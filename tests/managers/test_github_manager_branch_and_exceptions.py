from __future__ import annotations

from types import SimpleNamespace

from managers.github_manager import GitHubManager


class _GHManagerNoInit(GitHubManager):
    def _init_client(self) -> None:
        self._gh = None
        self._repo = None
        self._available = False


def test_create_branch_rejects_invalid_branch_names() -> None:
    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)
    manager._repo = SimpleNamespace(default_branch="main")

    ok, message = manager.create_branch("bad branch name")

    assert ok is False
    assert "Geçersiz dal adı" in message


def test_create_branch_returns_error_when_repo_ref_fails() -> None:
    class _RepoStub:
        default_branch = "main"

        def get_branch(self, _name: str):
            raise RuntimeError("cannot resolve branch")

    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)
    manager._repo = _RepoStub()

    ok, message = manager.create_branch("feature/x")

    assert ok is False
    assert "Dal oluşturma hatası" in message


def test_search_code_handles_empty_results_and_api_error() -> None:
    class _RepoStub:
        full_name = "octo/repo"

    class _GHStub:
        def __init__(self, *, raises: bool) -> None:
            self.raises = raises

        def search_code(self, _query: str):
            if self.raises:
                raise RuntimeError("github api down")
            return []

    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)
    manager._repo = _RepoStub()

    manager._gh = _GHStub(raises=False)
    ok_empty, msg_empty = manager.search_code("TODO")
    assert ok_empty is True
    assert "sonuç bulunamadı" in msg_empty.lower()

    manager._gh = _GHStub(raises=True)
    ok_err, msg_err = manager.search_code("TODO")
    assert ok_err is False
    assert "Kod arama hatası" in msg_err


def test_get_pull_requests_detailed_returns_structured_payload_and_error() -> None:
    class _PRStub:
        number = 7
        title = "Fix bug"
        state = "open"
        user = SimpleNamespace(login="alice")
        head = SimpleNamespace(ref="feature/x")
        base = SimpleNamespace(ref="main")
        html_url = "https://example/pr/7"
        created_at = SimpleNamespace(strftime=lambda _fmt: "2026-01-01 10:00")
        updated_at = SimpleNamespace(strftime=lambda _fmt: "2026-01-02 10:00")
        additions = 10
        deletions = 2
        changed_files = 3
        comments = 1

    class _RepoOk:
        def get_pulls(self, **_kwargs):
            return [_PRStub()]

    class _RepoFail:
        def get_pulls(self, **_kwargs):
            raise RuntimeError("cannot list pulls")

    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)

    manager._repo = _RepoOk()
    ok, rows, err = manager.get_pull_requests_detailed(state="open", limit=10)
    assert ok is True
    assert err == ""
    assert rows[0]["number"] == 7
    assert rows[0]["author"] == "alice"

    manager._repo = _RepoFail()
    ok_err, rows_err, err_msg = manager.get_pull_requests_detailed(state="open", limit=10)
    assert ok_err is False
    assert rows_err == []
    assert "cannot list pulls" in err_msg
