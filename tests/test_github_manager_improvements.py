"""GitHubManager iyileştirmeleri için hedefli regresyon testleri."""

from pathlib import Path
import importlib.util
import sys
import types


def _load_github_manager():
    pkg = types.ModuleType("managers")
    pkg.__path__ = [str(Path("managers").resolve())]
    sys.modules.setdefault("managers", pkg)

    gm_spec = importlib.util.spec_from_file_location("managers.github_manager", "managers/github_manager.py")
    gm_mod = importlib.util.module_from_spec(gm_spec)
    sys.modules["managers.github_manager"] = gm_mod
    gm_spec.loader.exec_module(gm_mod)
    return gm_mod.GitHubManager


class DummyRepoObj:
    def __init__(self, full_name: str, default_branch: str = "main", private: bool = False):
        self.full_name = full_name
        self.default_branch = default_branch
        self.private = private


class DummyUser:
    def __init__(self, repos):
        self._repos = repos

    def get_repos(self, **kwargs):
        return self._repos


class DummyOrg:
    def __init__(self, repos):
        self._repos = repos

    def get_repos(self, **kwargs):
        return self._repos


class DummyGH:
    def __init__(self, user_repos=None, org_repos=None, fail_user=False, fail_org=False):
        self._user_repos = user_repos or []
        self._org_repos = org_repos or []
        self.fail_user = fail_user
        self.fail_org = fail_org

    def get_user(self, owner=None):
        if self.fail_user:
            raise RuntimeError("user fail")
        return DummyUser(self._user_repos)

    def get_organization(self, owner):
        if self.fail_org:
            raise RuntimeError("org fail")
        return DummyOrg(self._org_repos)


class DummyRepoAPI:
    def __init__(self):
        self.created = False
        self.updated = False

    def get_contents(self, file_path, **kwargs):
        err = RuntimeError("not found")
        err.status = 404
        raise err

    def create_file(self, **kwargs):
        self.created = True

    def update_file(self, **kwargs):
        self.updated = True


class DummyRepoUpdateAPI(DummyRepoAPI):
    class _Existing:
        sha = "abc123"

    def get_contents(self, file_path, **kwargs):
        return self._Existing()


def _manager_with_gh(gh=None, repo=None):
    GitHubManager = _load_github_manager()
    m = GitHubManager(token="")
    m._available = True
    m._gh = gh
    m._repo = repo
    return m


def test_list_repos_owner_fallback_user_to_org():
    """Owner user akışı başarısızsa organization kaynağına kontrollü fallback yapılır."""
    gh = DummyGH(
        user_repos=[],
        org_repos=[DummyRepoObj("acme/proj")],
        fail_user=True,
        fail_org=False,
    )
    mgr = _manager_with_gh(gh=gh)

    ok, repos = mgr.list_repos(owner="acme", limit=10)

    assert ok is True
    assert repos[0]["full_name"] == "acme/proj"


def test_create_or_update_file_creates_only_on_404():
    """Dosya oluşturma yolu yalnızca 404 benzeri 'bulunamadı' durumunda çalışır."""
    repo = DummyRepoAPI()
    mgr = _manager_with_gh(repo=repo)

    ok, msg = mgr.create_or_update_file("new.txt", "hello", "add file")

    assert ok is True
    assert "oluşturuldu" in msg
    assert repo.created is True
    assert repo.updated is False


def test_create_or_update_file_updates_when_exists():
    """Dosya mevcutsa update akışı çalışır."""
    repo = DummyRepoUpdateAPI()
    mgr = _manager_with_gh(repo=repo)

    ok, msg = mgr.create_or_update_file("exists.txt", "hello", "update file")

    assert ok is True
    assert "güncellendi" in msg
    assert repo.updated is True
