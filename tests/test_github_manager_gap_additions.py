import types

from tests.test_github_manager_runtime import GM, _manager


def test_list_repos_respects_limit_break_and_owner_source():
    class _Repo:
        def __init__(self, n):
            self.full_name = f"org/r{n}"
            self.default_branch = "main"
            self.private = False

    class _User:
        type = "User"

        def get_repos(self, type="owner"):
            assert type == "owner"
            return [_Repo(1), _Repo(2), _Repo(3)]

    gh = types.SimpleNamespace(get_user=lambda owner=None: _User())
    m = _manager(repo=None, gh=gh, available=True, token="t")

    ok, repos = m.list_repos(owner="alice", limit=1)
    assert ok is True
    assert repos == [{"full_name": "org/r1", "default_branch": "main", "private": "false"}]


def test_get_repo_info_exception_branch_returns_error_message():
    class _RepoBoom:
        full_name = "org/repo"

        @property
        def description(self):
            raise RuntimeError("rate limit")

    m = _manager(repo=_RepoBoom(), gh=None, available=True, token="t")
    ok, msg = m.get_repo_info()
    assert ok is False
    assert "Depo bilgisi alınamadı" in msg


def test_read_remote_file_ref_404_and_unsafe_extensionless_and_binary():
    class _Repo:
        def get_contents(self, file_path, **kwargs):
            if file_path == "missing.md":
                raise Exception("404 Not Found")
            if file_path == "UNKNOWNFILE":
                return types.SimpleNamespace(name="UNKNOWNFILE", decoded_content=b"x")
            if file_path == "image.pdf":
                return types.SimpleNamespace(name="image.pdf", decoded_content=b"%PDF")
            assert kwargs.get("ref") == "dev"
            return types.SimpleNamespace(name="README.md", decoded_content=b"ok")

    m = _manager(repo=_Repo(), gh=None, available=True, token="t")

    ok, content = m.read_remote_file("README.md", ref="dev")
    assert ok is True and content == "ok"

    ok, msg404 = m.read_remote_file("missing.md")
    assert ok is False and "404" in msg404

    ok, msg_extless = m.read_remote_file("UNKNOWNFILE")
    assert ok is False and "uzantısız dosya güvenli listede değil" in msg_extless

    ok, msg_bin = m.read_remote_file("image.pdf")
    assert ok is False and "binary" in msg_bin.lower()


def test_list_files_single_file_wrapped_and_create_update_outer_exception():
    class _RepoSingle:
        full_name = "org/repo"

        def get_contents(self, _path, **kwargs):
            return types.SimpleNamespace(type="file", name="README.md")

    m = _manager(repo=_RepoSingle(), gh=None, available=True, token="t")
    ok, out = m.list_files(path="README.md", branch="main")
    assert ok is True and "README.md" in out

    class _RepoWriteErr:
        def get_contents(self, *_a, **_k):
            raise Exception("404 not found")

        def create_file(self, **kwargs):
            raise RuntimeError("rate limit exceeded")

    m2 = _manager(repo=_RepoWriteErr(), gh=None, available=True, token="t")
    ok, msg = m2.create_or_update_file("new.txt", "x", "add")
    assert ok is False and "dosya yazma hatası" in msg.lower()


def test_get_pull_request_diff_no_files_branch_message():
    class _PR:
        title = "No changes"

        def get_files(self):
            return []

    class _Repo:
        def get_pull(self, number):
            return _PR()

    m = _manager(repo=_Repo(), gh=None, available=True, token="t")
    ok, msg = m.get_pull_request_diff(10)
    assert ok is True
    assert "değiştirilmiş kod dosyası bulunmuyor" in msg
