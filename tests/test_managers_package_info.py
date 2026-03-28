"""
managers/package_info.py için birim testleri.
PackageInfoManager: constructor, _is_prerelease, _version_sort_key,
_cache_get/_cache_set, cache TTL.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta


def _get_pi():
    if "managers.package_info" in sys.modules:
        del sys.modules["managers.package_info"]
    import managers.package_info as pi
    return pi


# ══════════════════════════════════════════════════════════════
# Constructor
# ══════════════════════════════════════════════════════════════

class TestPackageInfoManagerInit:
    def test_default_timeout(self):
        pi = _get_pi()
        mgr = pi.PackageInfoManager()
        assert mgr.TIMEOUT == 12.0

    def test_default_cache_ttl(self):
        pi = _get_pi()
        mgr = pi.PackageInfoManager()
        assert mgr.CACHE_TTL_SECONDS == 1800

    def test_config_sets_timeout(self):
        pi = _get_pi()

        class _Cfg:
            PACKAGE_INFO_TIMEOUT = 5
            PACKAGE_INFO_CACHE_TTL = 900
            VERSION = "1.0"

        mgr = pi.PackageInfoManager(config=_Cfg())
        assert mgr.TIMEOUT == 5.0

    def test_config_sets_cache_ttl(self):
        pi = _get_pi()

        class _Cfg:
            PACKAGE_INFO_TIMEOUT = 12
            PACKAGE_INFO_CACHE_TTL = 600
            VERSION = "1.0"

        mgr = pi.PackageInfoManager(config=_Cfg())
        assert mgr.CACHE_TTL_SECONDS == 600

    def test_empty_cache_on_init(self):
        pi = _get_pi()
        mgr = pi.PackageInfoManager()
        assert mgr._cache == {}

    def test_headers_contain_user_agent(self):
        pi = _get_pi()
        mgr = pi.PackageInfoManager()
        assert "User-Agent" in mgr.headers
        assert "SidarAI" in mgr.headers["User-Agent"]


# ══════════════════════════════════════════════════════════════
# _is_prerelease
# ══════════════════════════════════════════════════════════════

class TestIsPrerelease:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_alpha_is_prerelease(self):
        mgr = self._mgr()
        assert mgr._is_prerelease("1.0.0a1") is True

    def test_beta_is_prerelease(self):
        mgr = self._mgr()
        assert mgr._is_prerelease("2.0.0b3") is True

    def test_rc_is_prerelease(self):
        mgr = self._mgr()
        assert mgr._is_prerelease("3.0.0rc1") is True

    def test_dev_is_prerelease(self):
        mgr = self._mgr()
        assert mgr._is_prerelease("1.0.0.dev0") is True

    def test_stable_not_prerelease(self):
        mgr = self._mgr()
        assert mgr._is_prerelease("1.2.3") is False

    def test_stable_post_not_prerelease(self):
        mgr = self._mgr()
        assert mgr._is_prerelease("1.2.3.post1") is False


# ══════════════════════════════════════════════════════════════
# _version_sort_key
# ══════════════════════════════════════════════════════════════

class TestVersionSortKey:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_valid_version_returns_comparable(self):
        mgr = self._mgr()
        key = mgr._version_sort_key("1.2.3")
        assert key is not None

    def test_invalid_version_returns_fallback(self):
        mgr = self._mgr()
        # Should not raise
        key = mgr._version_sort_key("not-a-version")
        assert key is not None

    def test_ordering(self):
        mgr = self._mgr()
        versions = ["1.0.0", "2.0.0", "1.5.0"]
        sorted_v = sorted(versions, key=mgr._version_sort_key, reverse=True)
        assert sorted_v[0] == "2.0.0"


# ══════════════════════════════════════════════════════════════
# _cache_get / _cache_set
# ══════════════════════════════════════════════════════════════

class TestCacheGetSet:
    def _mgr(self):
        pi = _get_pi()
        return pi.PackageInfoManager()

    def test_miss_on_empty_cache(self):
        mgr = self._mgr()
        hit, data = mgr._cache_get("missing_key")
        assert hit is False
        assert data == {}

    def test_set_then_get(self):
        mgr = self._mgr()
        mgr._cache_set("pypi:requests", {"info": {"version": "2.28.0"}})
        hit, data = mgr._cache_get("pypi:requests")
        assert hit is True
        assert data["info"]["version"] == "2.28.0"

    def test_expired_entry_returns_miss(self):
        mgr = self._mgr()
        # Manually insert an old entry
        mgr._cache["pypi:old"] = ({"info": {}}, datetime.now() - timedelta(seconds=9999))
        hit, data = mgr._cache_get("pypi:old")
        assert hit is False

    def test_expired_entry_removed(self):
        mgr = self._mgr()
        mgr._cache["pypi:old"] = ({"info": {}}, datetime.now() - timedelta(seconds=9999))
        mgr._cache_get("pypi:old")
        assert "pypi:old" not in mgr._cache
