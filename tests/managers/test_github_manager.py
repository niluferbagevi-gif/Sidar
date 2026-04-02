from types import SimpleNamespace

from managers.github_manager import GitHubManager, _is_not_found_error


class _RepoStub:
    def __init__(self) -> None:
        self.default_branch = "main"
        self.full_name = "octo/repo"

    def get_branches(self):
        return [SimpleNamespace(name="main"), SimpleNamespace(name="feature/x")]


class _GHManagerNoInit(GitHubManager):
    def _init_client(self) -> None:  # noqa: D401
        # Network bağımlılığını tamamen kapatıyoruz.
        self._gh = None
        self._repo = None
        self._available = False


def test_is_not_found_error_detects_status_or_message() -> None:
    assert _is_not_found_error(Exception("404 not found")) is True
    assert _is_not_found_error(type("E", (), {"status": 404})()) is True
    assert _is_not_found_error(Exception("boom")) is False


def test_set_repo_returns_error_when_not_available() -> None:
    manager = _GHManagerNoInit(token="", repo_name="", require_token=False)

    ok, message = manager.set_repo("octo/repo")

    assert ok is False
    assert "bağlantı" in message.lower()


def test_list_branches_formats_default_marker() -> None:
    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)
    manager._repo = _RepoStub()

    ok, output = manager.list_branches(limit=5)

    assert ok is True
    assert "* main" in output
    assert "feature/x" in output
