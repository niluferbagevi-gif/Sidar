"""
Sidar Project - Paket Bilgi Yöneticisi
PyPI, npm Registry ve GitHub Releases entegrasyonu (Asenkron).
Sürüm: 2.7.0

Gerçek zamanlı paket sürüm kontrolü, changelog ve bağımlılık sorguları.
"""

import logging
import re
from typing import Dict, Tuple

import httpx
from packaging.version import Version, InvalidVersion

logger = logging.getLogger(__name__)


class PackageInfoManager:
    """
    Python (PyPI), JavaScript (npm) ve GitHub projeleri için
    paket bilgisi sorgular. (Tamamen asenkron mimari).
    """

    # Varsayılan değer (Config verilmezse kullanılır)
    TIMEOUT = 12  # saniye

    def __init__(self, config=None) -> None:
        if config is not None:
            self.TIMEOUT = getattr(config, "PACKAGE_INFO_TIMEOUT", self.TIMEOUT)

    # ─────────────────────────────────────────────
    #  PyPI (ASYNC)
    # ─────────────────────────────────────────────

    async def _fetch_pypi_json(self, package: str) -> Tuple[bool, Dict, str]:
        """PyPI JSON verisini ham olarak döndürür."""
        url = f"https://pypi.org/pypi/{package}/json"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(url)
            if resp.status_code == 404:
                return False, {}, f"✗ PyPI'de '{package}' paketi bulunamadı."
            resp.raise_for_status()
            return True, resp.json(), ""
        except httpx.TimeoutException:
            return False, {}, f"[HATA] PyPI zaman aşımı: {package}"
        except httpx.RequestError as exc:
            return False, {}, f"[HATA] PyPI bağlantı hatası: {exc}"
        except Exception as exc:
            logger.error("PyPI sorgu hatası: %s", exc)
            return False, {}, f"[HATA] PyPI: {exc}"

    async def pypi_info(self, package: str) -> Tuple[bool, str]:
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
        all_versions = list(data.get("releases", {}).keys())
        recent_versions = sorted(
            [v for v in all_versions if not self._is_prerelease(v)],
            key=self._version_sort_key,
            reverse=True,
        )[:8]

        lines = [
            f"[PyPI: {package}]",
            f"  Güncel sürüm  : {info.get('version', '?')}",
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

    async def pypi_latest_version(self, package: str) -> Tuple[bool, str]:
        """Sadece güncel sürüm numarasını döndür (Asenkron)."""
        ok, data, err = await self._fetch_pypi_json(package)
        if not ok:
            return False, err
        version = data.get("info", {}).get("version", "?")
        return True, f"{package}=={version}"

    async def pypi_compare(self, package: str, current_version: str) -> Tuple[bool, str]:
        """
        Kurulu sürümü PyPI'deki güncel sürümle karşılaştır (Asenkron).
        """
        ok, data, err = await self._fetch_pypi_json(package)
        if not ok:
            return False, err

        latest = data.get("info", {}).get("version", "?")
        ok_info, info = await self.pypi_info(package)
        if not ok_info:
            return False, info

        if current_version == latest:
            status_line = f"  Durum         : ✓ Güncel ({current_version})"
        else:
            status_line = f"  Durum         : ⚠ Güncelleme mevcut — {current_version} → {latest}"

        return True, f"{info}\n  Kurulu sürüm  : {current_version}\n{status_line}"

    # ─────────────────────────────────────────────
    #  npm (ASYNC)
    # ─────────────────────────────────────────────

    async def npm_info(self, package: str) -> Tuple[bool, str]:
        """
        npm Registry'den paket bilgisi çek (Asenkron).
        """
        url = f"https://registry.npmjs.org/{package}/latest"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(url)
                
            if resp.status_code == 404:
                return False, f"✗ npm'de '{package}' paketi bulunamadı."
            resp.raise_for_status()
            data = resp.json()

            author = data.get("author", {})
            author_str = (
                author.get("name", str(author))
                if isinstance(author, dict)
                else str(author)
            )

            lines = [
                f"[npm: {package}]",
                f"  Güncel sürüm : {data.get('version', '?')}",
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

        except httpx.TimeoutException:
            return False, f"[HATA] npm zaman aşımı: {package}"
        except httpx.RequestError as exc:
            return False, f"[HATA] npm bağlantı hatası: {exc}"
        except Exception as exc:
            logger.error("npm sorgu hatası: %s", exc)
            return False, f"[HATA] npm: {exc}"

    # ─────────────────────────────────────────────
    #  GITHUB RELEASES (ASYNC)
    # ─────────────────────────────────────────────

    async def github_releases(self, repo: str, limit: int = 5) -> Tuple[bool, str]:
        """
        GitHub Releases API ile sürümleri listele (Asenkron).
        """
        url = f"https://api.github.com/repos/{repo}/releases"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(
                    url,
                    headers={"Accept": "application/vnd.github+json"}
                )
                
            if resp.status_code == 404:
                return False, f"✗ GitHub deposu bulunamadı: {repo}"
            resp.raise_for_status()
            releases = resp.json()[:limit]

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

        except httpx.TimeoutException:
            return False, f"[HATA] GitHub API zaman aşımı: {repo}"
        except Exception as exc:
            logger.error("GitHub releases hatası: %s", exc)
            return False, f"[HATA] GitHub Releases: {exc}"

    async def github_latest_release(self, repo: str) -> Tuple[bool, str]:
        """Sadece en güncel release tag'ini döndür (Asenkron)."""
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(
                    url,
                    headers={"Accept": "application/vnd.github+json"}
                )
                
            if resp.status_code == 404:
                return False, f"✗ '{repo}' için release bulunamadı."
            resp.raise_for_status()
            data = resp.json()
            tag = data.get("tag_name", "?")
            date = (data.get("published_at") or "?")[:10]
            return True, f"{repo} — En güncel: {tag} [{date}]"
        except Exception as exc:
            return False, f"[HATA] GitHub: {exc}"

    # ─────────────────────────────────────────────
    #  YARDIMCILAR
    # ─────────────────────────────────────────────

    @staticmethod
    def _is_prerelease(version: str) -> bool:
        """Sürümün pre-release olup olmadığını kontrol et."""
        try:
            return Version(version).is_prerelease
        except InvalidVersion:
            # PEP440 dışı semver pre-release etiketlerini yakala: 1.2.3-alpha.1, 2.0.0-rc
            if re.search(r"-([0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)$", version):
                return True
            # Bilinmeyen formatlar için agresif filtreleme yerine stable kabul et
            return False

    @staticmethod
    def _version_sort_key(version: str) -> Version:
        """
        Sürüm dizisini PEP 440 uyumlu şekilde sırala.
        packaging.version.Version kullanımı: 1.0.0 > 1.0.0rc1 > 1.0.0b2 > 1.0.0a1
        Geçersiz sürüm formatlarında 0.0.0 döndürülür (sona düşer).
        """
        try:
            return Version(version)
        except InvalidVersion:
            return Version("0.0.0")

    def status(self) -> str:
        return "PackageInfo: PyPI + npm + GitHub Releases — Aktif (Asenkron)"

    def __repr__(self) -> str:
        return f"<PackageInfoManager timeout={self.TIMEOUT}s>"  