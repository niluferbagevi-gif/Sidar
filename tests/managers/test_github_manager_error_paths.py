from __future__ import annotations

from types import SimpleNamespace

from managers.github_manager import GitHubManager


class _GHManagerNoInit(GitHubManager):
    def _init_client(self) -> None:
        self._gh = None
        self._repo = None
        self._available = False


class _RepoStub:
    def __init__(self):
        self.default_branch = "main"
        self.full_name = "org/repo"

    def get_contents(self, file_path: str, **_kwargs):
        if file_path == "binary.png":
            return SimpleNamespace(name="binary.png", decoded_content=b"\x89PNG")
        if file_path == "Makefile":
            return SimpleNamespace(name="Makefile", decoded_content=b"all:\n\techo ok\n")
        if file_path == "broken.txt":
            class _Broken:
                name = "broken.txt"

                @property
                def decoded_content(self):
                    raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")

            return _Broken()
        raise RuntimeError("not found")


def test_init_requires_token_when_repo_or_enforced() -> None:
    try:
        GitHubManager(token="", repo_name="org/repo", require_token=False)
        assert False, "ValueError bekleniyordu"
    except ValueError as exc:
        assert "GITHUB_TOKEN" in str(exc)


def test_read_remote_file_binary_decode_and_not_found_paths() -> None:
    manager = _GHManagerNoInit(token="t")
    manager._repo = _RepoStub()

    ok_binary, msg_binary = manager.read_remote_file("binary.png")
    assert ok_binary is False
    assert "Güvenlik" in msg_binary

    ok_make, msg_make = manager.read_remote_file("Makefile")
    assert ok_make is True
    assert "echo ok" in msg_make

    ok_broken, msg_broken = manager.read_remote_file("broken.txt")
    assert ok_broken is False
    assert "UTF-8" in msg_broken

    ok_missing, msg_missing = manager.read_remote_file("missing.py")
    assert ok_missing is False
    assert "Uzak dosya okunamadı" in msg_missing


def test_create_or_update_file_handles_not_found_and_unexpected_read_error() -> None:
    manager = _GHManagerNoInit(token="t")

    calls = {"created": 0, "updated": 0}

    class _Repo:
        def get_contents(self, file_path: str, **_kwargs):
            if file_path == "existing.py":
                return SimpleNamespace(sha="abc123")
            if file_path == "new.py":
                err = RuntimeError("404 not found")
                err.status = 404
                raise err
            raise RuntimeError("403 forbidden")

        def update_file(self, **_kwargs):
            calls["updated"] += 1

        def create_file(self, **_kwargs):
            calls["created"] += 1

    manager._repo = _Repo()

    ok_upd, msg_upd = manager.create_or_update_file("existing.py", "x=1", "update")
    assert ok_upd is True
    assert "güncellendi" in msg_upd

    ok_create, msg_create = manager.create_or_update_file("new.py", "x=2", "create")
    assert ok_create is True
    assert "oluşturuldu" in msg_create

    ok_err, msg_err = manager.create_or_update_file("forbidden.py", "x=3", "create")
    assert ok_err is False
    assert "dosya okuma hatası" in msg_err

    assert calls == {"created": 1, "updated": 1}


def test_create_branch_validates_name_and_handles_repo_errors() -> None:
    manager = _GHManagerNoInit(token="t")

    class _Repo:
        default_branch = "main"

        def get_branch(self, _source):
            return SimpleNamespace(commit=SimpleNamespace(sha="deadbeef"))

        def create_git_ref(self, **_kwargs):
            raise RuntimeError("permission denied")

    manager._repo = _Repo()

    ok_invalid, msg_invalid = manager.create_branch("bad branch name!")
    assert ok_invalid is False
    assert "Geçersiz dal adı" in msg_invalid

    ok_err, msg_err = manager.create_branch("feature/test")
    assert ok_err is False
    assert "Dal oluşturma hatası" in msg_err
