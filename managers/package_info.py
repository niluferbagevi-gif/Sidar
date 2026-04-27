"""
Sidar Project - Paket Bilgi Yöneticisi
PyPI, npm Registry ve GitHub Releases entegrasyonu (Asenkron).

Gerçek zamanlı paket sürüm kontrolü, changelog ve bağımlılık sorguları.
"""

import logging
import re
from datetime import datetime, timedelta

import httpx
from packaging.version import InvalidVersion, Version

logger = logging.getLogger(__name__)


class PackageInfoManager:
    """
    Python (PyPI), JavaScript (npm) ve GitHub projeleri için
    paket bilgisi sorgular. (Tamamen asenkron mimari).
    """

    # Varsayılan değerler (Config verilmezse kullanılır)
    TIMEOUT = 12  # saniye
    CACHE_TTL_SECONDS = 1800  # 30 dakika

    def __init__(self, config=None) -> None:
        self.cfg = config

        # Instance defaultlarını init başında kesinleştir.
        self.TIMEOUT = 12
        self.CACHE_TTL_SECONDS = 1800

        if config is not None:
            self.TIMEOUT = getattr(config, "PACKAGE_INFO_TIMEOUT", self.TIMEOUT)
            self.CACHE_TTL_SECONDS = getattr(
                config, "PACKAGE_INFO_CACHE_TTL", self.CACHE_TTL_SECONDS
            )

        cache_ttl_seconds = self.CACHE_TTL_SECONDS
        self.cache_ttl = timedelta(seconds=max(60, int(cache_ttl_seconds)))
        self._cache: dict[str, tuple[dict, datetime]] = {}

        self.TIMEOUT = float(self.TIMEOUT)
        timeout_seconds = self.TIMEOUT
        try:
            self.timeout = httpx.Timeout(timeout=timeout_seconds, connect=5.0)
        except TypeError:
            # Bazı test stub'larında/versiyonlarda imza farklı olabilir.
            try:
                self.timeout = httpx.Timeout(timeout_seconds)
            except TypeError:
                # En kısıtlı stub'larda (örn. Timeout=object) yalnızca argümansız çağrı çalışır.
                self.timeout = httpx.Timeout()

        version = getattr(config, "VERSION", "5.1.0") if config is not None else "5.1.0"
        self.headers = {
            "User-Agent": f"SidarAI/{version} (Software Engineer Assistant)",
            "Accept": "application/json",
        }

    # ─────────────────────────────────────────────
    #  YARDIMCILAR (CACHE + HTTP)
    # ─────────────────────────────────────────────

    def _cache_get(self, key: str) -> tuple[bool, dict]:
        cached = self._cache.get(key)
        if not cached:
            return False, {}
        value, ts = cached
        if datetime.now() - ts < self.cache_ttl:
            return True, value
        self._cache.pop(key, None)
        return False, {}

    def _cache_set(self, key: str, value: dict) -> None:
        self._cache[key] = (value, datetime.now())

    async def _get_json(self, url: str, cache_key: str = "") -> tuple[bool, dict, str]:
        if cache_key:
            hit, data = self._cache_get(cache_key)
            if hit:
                return True, data, ""

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers=self.headers,
            ) as client:
                resp = await client.get(url)
            if resp.status_code == 404:
                return False, {}, "not_found"
            resp.raise_for_status()
            data = resp.json()
            if cache_key:
                self._cache_set(cache_key, data)
            return True, data, ""
        except httpx.TimeoutException:
            return False, {}, "timeout"
        except httpx.RequestError as exc:
            return False, {}, f"request:{exc}"
        except Exception as exc:
            logger.error("Paket bilgi API hatası: %s", exc)
            return False, {}, f"unexpected:{exc}"

    # ─────────────────────────────────────────────
    #  PyPI (ASYNC)
    # ─────────────────────────────────────────────

    async def _fetch_pypi_json(self, package: str) -> tuple[bool, dict, str]:
        """PyPI JSON verisini ham olarak döndürür."""
        url = f"https://pypi.org/pypi/{package}/json"
        ok, data, err = await self._get_json(url, cache_key=f"pypi:{package.lower()}")
        if ok:
            return True, data, ""
        if err == "not_found":
            return False, {}, f"✗ PyPI'de '{package}' paketi bulunamadı."
        if err == "timeout":
            return False, {}, f"[HATA] PyPI zaman aşımı: {package}"
        if err.startswith("request:"):
            return False, {}, f"[HATA] PyPI bağlantı hatası: {err.split(':', 1)[1]}"
        return False, {}, f"[HATA] PyPI: {err}"

    async def pypi_info(self, package: str) -> tuple[bool, str]:
        """
        PyPI JSON API'den paket bilgisi çek (Asenkron).

        Args:
            package: Paket adı (örn: "fastapi", "httpx")

        Returns:
            (başarı, biçimlendirilmiş_bilgi)
        """
        ok, data, err = await self._fetch_pypi_json(package)
        if not ok:
            return False, err

        info = data.get("info", {})
        all_versions = []
        for version_key in data.get("releases", {}).keys():
            if version_key is None:
                continue
            normalized_key = str(version_key).strip()
            if not normalized_key:
                continue
            all_versions.append(normalized_key)
        recent_versions = sorted(
            [v for v in all_versions if not self._is_prerelease(v)],
            key=self._version_sort_key,
            reverse=True,
        )[:8]

        lines = [
            f"[PyPI: {package}]",
            f"  Güncel sürüm  : {info.get('version') or '?'}",
            f"  Yazar         : {(info.get('author') or info.get('author_email') or '?')[:80]}",
            f"  Lisans        : {info.get('license', '?') or '?'}",
            f"  Python gerekli: {info.get('requires_python', '?') or '?'}",
            f"  Özet          : {(info.get('summary') or '')[:150]}",
            f"  Proje URL     : {info.get('project_url') or 'https://pypi.org/project/' + package}",
            f"  Son sürümler  : {', '.join(recent_versions)}",
        ]

        requires = info.get("requires_dist") or []
        if requires:
            cleaned = [r.split(";")[0].strip() for r in requires[:10]]
            lines.append(f"  Bağımlılıklar : {', '.join(cleaned)}")

        home_page = info.get("home_page") or info.get("project_url")
        if home_page:
            lines.append(f"  Ana sayfa     : {home_page}")

        return True, "\n".join(lines)

    async def pypi_latest_version(self, package: str) -> tuple[bool, str]:
        """Sadece güncel sürüm numarasını döndür (Asenkron)."""
        ok, data, err = await self._fetch_pypi_json(package)
        if not ok:
            return False, err
        version = data.get("info", {}).get("version", "?")
        version = version or "?"
        return True, f"{package}=={version}"

    async def pypi_compare(self, package: str, current_version: str) -> tuple[bool, str]:
        """
        Kurulu sürümü PyPI'deki güncel sürümle karşılaştır (Asenkron).
        """
        ok, data, err = await self._fetch_pypi_json(package)
        if not ok:
            return False, err

        latest = data.get("info", {}).get("version", "?")
        latest = latest or "?"
        current_version = current_version or "?"
        ok_info, info = await self.pypi_info(package)
        if not ok_info:
            return False, info

        try:
            needs_update = Version(str(current_version)) < Version(str(latest))
        except (InvalidVersion, TypeError):
            needs_update = str(current_version) != str(latest)
        if not needs_update:
            status_line = f"  Durum         : ✓ Güncel ({current_version})"
        else:
            status_line = f"  Durum         : ⚠ Güncelleme mevcut — {current_version} → {latest}"

        return True, f"{info}\n  Kurulu sürüm  : {current_version}\n{status_line}"

    # ─────────────────────────────────────────────
    #  npm (ASYNC)
    # ─────────────────────────────────────────────

    async def npm_info(self, package: str) -> tuple[bool, str]:
        """
        npm Registry'den paket bilgisi çek (Asenkron).
        """
        url = f"https://registry.npmjs.org/{package}/latest"
        ok, data, err = await self._get_json(url, cache_key=f"npm:{package.lower()}")
        if not ok:
            if err == "not_found":
                return False, f"✗ npm'de '{package}' paketi bulunamadı."
            if err == "timeout":
                return False, f"[HATA] npm zaman aşımı: {package}"
            if err.startswith("request:"):
                return False, f"[HATA] npm bağlantı hatası: {err.split(':', 1)[1]}"
            return False, f"[HATA] npm: {err}"

        author = data.get("author", {})
        author_str = author.get("name", str(author)) if isinstance(author, dict) else str(author)

        lines = [
            f"[npm: {package}]",
            f"  Güncel sürüm : {data.get('version') or '?'}",
            f"  Yazar        : {author_str[:80]}",
            f"  Lisans       : {data.get('license', '?')}",
            f"  Özet         : {(data.get('description') or '')[:150]}",
            f"  Ana dosya    : {data.get('main', '?')}",
        ]

        deps = data.get("dependencies", {})
        if deps:
            dep_list = [f"{k}@{v}" for k, v in list(deps.items())[:8]]
            lines.append(f"  Bağımlılıklar: {', '.join(dep_list)}")

        peer_deps = data.get("peerDependencies", {})
        if peer_deps:
            peer_list = [f"{k}@{v}" for k, v in list(peer_deps.items())[:5]]
            lines.append(f"  Peer deps    : {', '.join(peer_list)}")

        engines = data.get("engines", {})
        if engines:
            lines.append(f"  Engine gerek : {engines}")

        return True, "\n".join(lines)

    # ─────────────────────────────────────────────
    #  GITHUB RELEASES (ASYNC)
    # ─────────────────────────────────────────────

    async def github_releases(self, repo: str, limit: int = 5) -> tuple[bool, str]:
        """
        GitHub Releases API ile sürümleri listele (Asenkron).
        """
        url = f"https://api.github.com/repos/{repo}/releases"
        ok, data, err = await self._get_json(url, cache_key=f"ghrel:{repo.lower()}:{limit}")
        if not ok:
            if err == "not_found":
                return False, f"✗ GitHub deposu bulunamadı: {repo}"
            if err == "timeout":
                return False, f"[HATA] GitHub API zaman aşımı: {repo}"
            return False, f"[HATA] GitHub Releases: {err}"

        releases = data[:limit] if isinstance(data, list) else []

        if not releases:
            return True, f"[GitHub Releases: {repo}]\n  Henüz release yok."

        lines = [f"[GitHub Releases: {repo}]", ""]
        for r in releases:
            tag = r.get("tag_name", "?")
            name = r.get("name") or tag
            date = (r.get("published_at") or "?")[:10]
            prerelease = " (pre-release)" if r.get("prerelease") else ""
            body = (r.get("body") or "").strip()[:300].replace("\n", " ")
            lines.append(f"  {tag} — {name} [{date}]{prerelease}")
            if body:
                lines.append(f"    {body}")
            lines.append("")

        return True, "\n".join(lines)

    async def github_latest_release(self, repo: str) -> tuple[bool, str]:
        """Sadece en güncel release tag'ini döndür (Asenkron)."""
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        ok, data, err = await self._get_json(url, cache_key=f"ghlatest:{repo.lower()}")
        if not ok:
            if err == "not_found":
                return False, f"✗ '{repo}' için release bulunamadı."
            if err == "timeout":
                return False, f"[HATA] GitHub API zaman aşımı: {repo}"
            return False, f"[HATA] GitHub: {err}"
        tag = data.get("tag_name", "?")
        date = (data.get("published_at") or "?")[:10]
        return True, f"{repo} — En güncel: {tag} [{date}]"

    # ─────────────────────────────────────────────
    #  YARDIMCILAR
    # ─────────────────────────────────────────────

    @staticmethod
    def _is_prerelease(version: object) -> bool:
        """Sürümün pre-release olup olmadığını kontrol et.

        Hem PEP 440 (alpha/beta/rc) hem de npm semver sayısal pre-release
        formatlarını destekler (örn: 1.0.0-0, 2.0.0-42).
        """
        version = "" if version is None else str(version).strip()
        if not version:
            return False

        # npm semver sayısal pre-release: 1.0.0-0, 1.0.0-1, 2.0.0-42
        # packaging kütüphanesi bunları post-release olarak yorumlar; önce biz kontrol ederiz.
        if re.match(r"^\d+\.\d+\.\d+-\d+$", version):
            return True
        try:
            return Version(version).is_prerelease
        except InvalidVersion:
            # PEP440 dışı semver pre-release etiketlerini yakala: 1.2.3-alpha.1, 2.0.0-rc
            if re.search(r"-([0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)$", version):
                return True
            # Bilinmeyen formatlar için agresif filtreleme yerine stable kabul et
            return False

    @staticmethod
    def _version_sort_key(version: object) -> Version:
        """
        Sürüm dizisini PEP 440 uyumlu şekilde sırala.
        packaging.version.Version kullanımı: 1.0.0 > 1.0.0rc1 > 1.0.0b2 > 1.0.0a1
        Geçersiz sürüm formatlarında 0.0.0 döndürülür (sona düşer).
        """
        version_text = "" if version is None else str(version).strip()
        if not version_text:
            return Version("0.0.0")
        try:
            return Version(version_text)
        except (InvalidVersion, TypeError):
            return Version("0.0.0")

    def status(self) -> str:
        return "PackageInfo: PyPI + npm + GitHub Releases — Aktif (Asenkron)"

    def __repr__(self) -> str:
        ttl_seconds = int(getattr(self, "cache_ttl", timedelta(seconds=60)).total_seconds())
        timeout_seconds = getattr(self, "TIMEOUT", "?")
        return f"<PackageInfoManager timeout={timeout_seconds}s cache_ttl={ttl_seconds}s>"
