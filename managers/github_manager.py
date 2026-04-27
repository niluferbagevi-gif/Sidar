"""
Sidar Project - GitHub Yöneticisi
Depo analizi, commit geçmişi ve uzak dosya okuma (Binary Korumalı).
Sürüm: 2.7.0
"""

import logging
import re

from tenacity import RetryError, retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# Güvenli dal adı kalıbı: yalnızca harf, rakam, /, _, -, . izinli
_BRANCH_RE = re.compile(r"^[a-zA-Z0-9/_.\-]+$")


def _is_not_found_error(exc: Exception) -> bool:
    """PyGithub 404/UnknownObject benzeri hataları güvenli şekilde tespit eder."""
    status = getattr(exc, "status", None)
    if status == 404:
        return True
    message = str(exc).lower()
    return "404" in message or "not found" in message


def _is_retryable_github_error(exc: Exception) -> bool:
    """Rate-limit ve geçici ağ/API hataları için retry kararı."""
    status = getattr(exc, "status", None)
    message = str(exc).lower()
    if status in {429, 502, 503, 504}:
        return True
    if status == 403 and "rate limit" in message:
        return True
    return any(
        token in message
        for token in ("rate limit", "temporarily unavailable", "timeout", "connection reset")
    )


class GitHubManager:
    """
    GitHub API üzerinden depo analizi yapar.
    PyGithub kütüphanesi kullanır.
    """

    # Okunmasına izin verilen, metin tabanlı (text-based) güvenli dosya uzantıları
    SAFE_TEXT_EXTENSIONS = {
        ".py",
        ".txt",
        ".md",
        ".json",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".toml",
        ".csv",
        ".xml",
        ".html",
        ".css",
        ".js",
        ".ts",
        ".sh",
        ".bash",
        ".bat",
        ".sql",
        ".gitignore",
        ".dockerignore",
    }

    # Uzantısız güvenli dosya isimleri (küçük harfle karşılaştırılır)
    SAFE_EXTENSIONLESS = {
        "makefile",
        "dockerfile",
        "procfile",
        "vagrantfile",
        "rakefile",
        "jenkinsfile",
        "gemfile",
        "brewfile",
        "cmakelists",
        "gradlew",
        "mvnw",
        "license",
        "changelog",
        "readme",
        "authors",
        "contributors",
        "notice",
    }

    @staticmethod
    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception(_is_retryable_github_error),
    )
    def _call_with_retry(func, *args, **kwargs):
        return func(*args, **kwargs)

    def __init__(self, token: str, repo_name: str = "", require_token: bool = False) -> None:
        # Token sonuna yanlışlıkla eklenen boşluk veya hatalı karakterleri temizle
        self.token = str(token).strip() if token else ""
        # Olası Türkçe karakter kazalarını önlemek için ascii formatına zorla
        self.token = self.token.encode("ascii", "ignore").decode("ascii")
        self.repo_name = repo_name
        self.require_token = require_token
        self._gh = None
        self._repo = None
        self._available = False
        self._init_client()

    # ─────────────────────────────────────────────
    #  BAŞLATMA
    # ─────────────────────────────────────────────

    def _init_client(self) -> None:
        if not self.token:
            if self.require_token or self.repo_name:
                raise ValueError(
                    "HATA: GitHub araçları aktif ancak GITHUB_TOKEN bulunamadı. "
                    "Lütfen .env dosyasını kontrol edin."
                )
            logger.warning("GitHub token ayarlanmamış. GitHub özellikleri devre dışı.")
            return
        try:
            from github import Auth, Github  # type: ignore

            # PyGithub: login_or_token parametresi deprecated.
            # Yeni önerilen kullanım auth=Auth.Token(...).
            self._gh = Github(auth=Auth.Token(self.token))
            # Token doğrulama
            _ = self._call_with_retry(self._gh.get_user).login
            self._available = True
            logger.info("GitHub bağlantısı kuruldu.")
            if self.repo_name:  # pragma: no cover
                self._load_repo(self.repo_name)
        except ImportError:
            logger.error("'PyGithub' paketi kurulu değil. pip install PyGithub")
        except Exception as exc:
            logger.error("GitHub bağlantı hatası: %s", exc)

    def _load_repo(self, repo_name: str) -> bool:
        """Depo nesnesini yükle."""
        if not self._gh:
            return False
        try:
            self._repo = self._call_with_retry(self._gh.get_repo, repo_name)
            self.repo_name = repo_name
            logger.info("Depo yüklendi: %s", repo_name)
            return True
        except RetryError as exc:
            logger.error("Depo yükleme tekrar limiti aşıldı (%s): %s", repo_name, exc)
            return False
        except Exception as exc:
            logger.error("Depo yükleme hatası (%s): %s", repo_name, exc)
            return False

    # ─────────────────────────────────────────────
    #  DEPO İŞLEMLERİ
    # ─────────────────────────────────────────────

    def set_repo(self, repo_name: str) -> tuple[bool, str]:
        """Aktif depoyu değiştir."""
        if not self._available:
            return False, "GitHub bağlantısı yok."
        ok = self._load_repo(repo_name)
        if ok:
            return True, f"Depo değiştirildi: {repo_name}"
        return False, f"Depo bulunamadı veya erişim reddedildi: {repo_name}"

    def list_repos(self, owner: str = "", limit: int = 100) -> tuple[bool, list[dict[str, str]]]:
        """
        Erişilebilen depoları listeler.
        owner verilirse ilgili kullanıcı/organizasyon hesabının depolarını döner.
        """
        if not self._gh:
            return False, []
        try:
            repos: list[dict[str, str]] = []
            if owner:
                account = self._call_with_retry(self._gh.get_user, owner)
                account_type = str(getattr(account, "type", "")).lower()
                repo_type = "all" if account_type == "organization" else "owner"
                source = account.get_repos(type=repo_type)
            else:
                source = self._call_with_retry(self._gh.get_user).get_repos(visibility="all")

            for i, repo in enumerate(source):
                if i >= limit:
                    break
                repos.append(
                    {
                        "full_name": repo.full_name,
                        "default_branch": repo.default_branch,
                        "private": str(bool(getattr(repo, "private", False))).lower(),
                    }
                )
            return True, repos
        except Exception as exc:
            logger.error("Repo listesi alınamadı (%s): %s", owner or "self", exc)
            return False, []

    def get_repo_info(self) -> tuple[bool, str]:
        """Depo bilgilerini döndür."""
        if not self._repo:
            return False, "Aktif depo yok. Önce bir depo belirtin."
        try:
            r = self._repo
            return True, (
                f"[Depo Bilgisi] {r.full_name}\n"
                f"  Açıklama  : {r.description or 'Yok'}\n"
                f"  Dil       : {r.language or 'Bilinmiyor'}\n"
                f"  Yıldız    : {r.stargazers_count}\n"
                f"  Fork      : {r.forks_count}\n"
                f"  Açık PR   : {self._call_with_retry(r.get_pulls, state='open').totalCount}\n"
                f"  Açık Issue: {self._call_with_retry(r.get_issues, state='open').totalCount}\n"
                f"  Varsayılan branch: {r.default_branch}"
            )
        except Exception as exc:
            return False, f"Depo bilgisi alınamadı: {exc}"

    def list_commits(self, limit: int = 30, branch: str | None = None) -> tuple[bool, str]:
        """Son commit'leri limitli şekilde listele."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            kwargs = {}
            if branch:
                kwargs["sha"] = branch
            requested_limit = int(limit)
            actual_limit = max(1, min(requested_limit, 100))
            commits = list(self._call_with_retry(self._repo.get_commits, **kwargs)[:actual_limit])

            warning = ""
            if requested_limit > 100:  # pragma: no cover
                warning = (
                    f"\n⚠ Uyarı: İstenen {requested_limit} commit sayısı, "
                    f"API sınırları gereği {actual_limit} olarak kısıtlandı.\n"
                )

            lines = [f"[Son {len(commits)} Commit — {self._repo.full_name}]{warning}"]
            for c in commits:
                sha = c.sha[:7]
                msg = c.commit.message.splitlines()[0][:72]
                author = c.commit.author.name
                date = c.commit.author.date.strftime("%Y-%m-%d %H:%M")
                lines.append(f"  {sha}  {date}  {author}  {msg}")
            return True, "\n".join(lines)
        except Exception as exc:
            return False, f"Commit listesi alınamadı: {exc}"

    def read_remote_file(self, file_path: str, ref: str | None = None) -> tuple[bool, str]:
        """Uzak depodaki bir dosyayı okur (Binary korumalı)."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            kwargs = {}
            if ref:
                kwargs["ref"] = ref

            content_file = self._call_with_retry(self._repo.get_contents, file_path, **kwargs)

            # Eğer dönen veri bir liste ise, bu bir dizindir
            if isinstance(content_file, list):
                lines = [f"[Dizin: {file_path}]"]
                for item in content_file:
                    icon = "📂" if item.type == "dir" else "📄"
                    lines.append(f"  {icon} {item.name}")
                return True, "\n".join(lines)

            # Eğer bu bir dosyaysa, içeriği UTF-8 mi yoksa Binary mi diye kontrol et
            file_name = content_file.name.lower()

            # Uzantısız dosyalar (Makefile, Dockerfile vb.) için uzantıyı boş varsayıyoruz
            extension = ""
            if "." in file_name:
                extension = "." + file_name.split(".")[-1]

            # Uzantısız dosyalar için whitelist kontrolü
            if not extension:
                if file_name.lower() not in self.SAFE_EXTENSIONLESS:
                    return False, (
                        f"⚠ Güvenlik: '{content_file.name}' uzantısız dosya güvenli listede değil. "
                        f"İzin verilen uzantısız dosyalar: Makefile, Dockerfile, Procfile vb."
                    )
            # Uzantılı dosyalar için güvenli uzantı kontrolü
            elif extension not in self.SAFE_TEXT_EXTENSIONS:
                return False, (
                    f"⚠ Güvenlik/Hata Koruması: '{file_name}' dosyasının binary (ikili) veya "
                    f"desteklenmeyen bir veri formatı (.png, .zip, vb.) olduğu varsayılarak "
                    f"okuma işlemi iptal edildi. Yalnızca metin tabanlı dosyalar okunabilir."
                )

            # Güvenli olduğuna ikna olduysak, decode et
            decoded = content_file.decoded_content.decode("utf-8", errors="replace")
            return True, decoded

        except UnicodeDecodeError:
            # Uzantısı .txt ama içi binary/bozuk olan dosyalar için fallback
            return False, (
                f"⚠ Hata: '{file_path}' dosyası UTF-8 formatında okunamadı. "
                "Dosya binary (ikili veri) içeriyor olabilir."
            )
        except Exception as exc:
            return False, f"Uzak dosya okunamadı ({file_path}): {exc}"

    def list_branches(self, limit: int = 30) -> tuple[bool, str]:
        """Depo dallarını limitli şekilde listele."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            limit = max(1, min(int(limit), 100))
            branches = list(self._call_with_retry(self._repo.get_branches)[:limit])
            lines = [f"[Branch Listesi — {self._repo.full_name}]"]
            for b in branches:
                prefix = "* " if b.name == self._repo.default_branch else "  "
                lines.append(f"{prefix}{b.name}")
            return True, "\n".join(lines)
        except Exception as exc:
            return False, f"Branch listesi alınamadı: {exc}"

    def list_files(self, path: str = "", branch: str | None = None) -> tuple[bool, str]:
        """Depodaki bir dizinin içeriğini listele."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            kwargs = {}
            if branch:
                kwargs["ref"] = branch
            contents = self._call_with_retry(self._repo.get_contents, path or "", **kwargs)
            if not isinstance(contents, list):
                contents = [contents]
            lines = [f"[GitHub Dosya Listesi: {path or '/'}]"]
            for item in sorted(contents, key=lambda x: (x.type != "dir", x.name)):
                icon = "📂" if item.type == "dir" else "📄"
                lines.append(f"  {icon} {item.name}")
            return True, "\n".join(lines)
        except Exception as exc:
            return False, f"Dosya listesi alınamadı: {exc}"

    def create_or_update_file(
        self,
        file_path: str,
        content: str,
        message: str,
        branch: str | None = None,
    ) -> tuple[bool, str]:
        """GitHub deposuna dosya oluştur veya güncelle."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            kwargs = {}
            if branch:
                kwargs["branch"] = branch

            try:
                existing = self._repo.get_contents(file_path, **kwargs)
            except Exception as exc:
                if _is_not_found_error(exc):
                    existing = None
                else:
                    return False, f"GitHub dosya okuma hatası: {exc}"

            if existing is not None:
                self._repo.update_file(
                    path=file_path,
                    message=message,
                    content=content,
                    sha=existing.sha,
                    **kwargs,
                )
                return True, f"✓ Dosya güncellendi: {file_path}"

            self._repo.create_file(
                path=file_path,
                message=message,
                content=content,
                **kwargs,
            )
            return True, f"✓ Dosya oluşturuldu: {file_path}"
        except Exception as exc:
            return False, f"GitHub dosya yazma hatası: {exc}"

    def create_branch(self, branch_name: str, from_branch: str | None = None) -> tuple[bool, str]:
        """
        Yeni git dalı oluştur.

        Args:
            branch_name: Oluşturulacak dal adı (yalnızca harf/rakam//_/./- izinli).
            from_branch: Kaynak dal (None ise varsayılan dal kullanılır).

        Returns:
            (başarı, mesaj)
        """
        if not self._repo:
            return False, "Aktif depo yok."
        # Güvenlik: dal adı injection koruması
        if not branch_name or not _BRANCH_RE.match(branch_name):
            return False, (
                f"Geçersiz dal adı: '{branch_name}'. "
                "Yalnızca harf, rakam, '/', '_', '-', '.' kullanılabilir."
            )
        try:
            source = from_branch or self._repo.default_branch
            source_ref = self._repo.get_branch(source)
            self._repo.create_git_ref(
                ref=f"refs/heads/{branch_name}",
                sha=source_ref.commit.sha,
            )
            return True, f"✓ Dal oluşturuldu: {branch_name} ({source} kaynağından)"
        except Exception as exc:
            return False, f"Dal oluşturma hatası: {exc}"

    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: str | None = None,
    ) -> tuple[bool, str]:
        """Pull request oluştur."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            base_branch = base or self._repo.default_branch
            pr = self._repo.create_pull(
                title=title,
                body=body,
                head=head,
                base=base_branch,
            )
            return True, (
                f"✓ Pull Request oluşturuldu:\n"
                f"  Başlık : {pr.title}\n"
                f"  URL    : {pr.html_url}\n"
                f"  Numara : #{pr.number}"
            )
        except Exception as exc:
            return False, f"Pull Request oluşturma hatası: {exc}"

    def list_pull_requests(
        self,
        state: str = "open",
        limit: int = 30,
    ) -> tuple[bool, str]:
        """Pull Request listesi döndür. state: open / closed / all"""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            valid_states = {"open", "closed", "all"}
            state = state.lower() if state.lower() in valid_states else "open"
            limit = max(1, min(int(limit), 100))
            pulls = list(self._repo.get_pulls(state=state, sort="updated")[:limit])
            if not pulls:
                return True, f"[PR Listesi — {self._repo.full_name}]\n  (Hiç {state} PR bulunamadı)"
            lines = [f"[PR Listesi ({state.upper()}) — {self._repo.full_name}]"]
            for pr in pulls:
                date = pr.updated_at.strftime("%Y-%m-%d")
                lines.append(f"  #{pr.number:4d}  {date}  {pr.user.login:<16}  {pr.title[:60]}")
            return True, "\n".join(lines)
        except Exception as exc:
            return False, f"PR listesi alınamadı: {exc}"

    def get_pull_request(self, number: int) -> tuple[bool, str]:
        """Belirli bir PR'ın detaylarını döndür."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            pr = self._repo.get_pull(number)
            files = list(pr.get_files())
            file_list = "\n".join(
                f"    {f.status:8}  +{f.additions:<4} -{f.deletions:<4}  {f.filename}"
                for f in files[:20]
            )
            suffix = f"\n    ... (+{len(files) - 20} dosya daha)" if len(files) > 20 else ""
            return True, (
                f"[PR #{pr.number} — {self._repo.full_name}]\n"
                f"  Başlık   : {pr.title}\n"
                f"  Durum    : {pr.state.upper()}\n"
                f"  Yazar    : {pr.user.login}\n"
                f"  Branch   : {pr.head.ref} → {pr.base.ref}\n"
                f"  Oluşturma: {pr.created_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"  Güncelleme:{pr.updated_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"  Değişiklik: +{pr.additions} / -{pr.deletions} ({pr.changed_files} dosya)\n"
                f"  Yorumlar : {pr.comments}\n"
                f"  URL      : {pr.html_url}\n\n"
                f"  Açıklama :\n{pr.body or '(boş)'}\n\n"
                f"  Değişen Dosyalar:\n{file_list}{suffix}"
            )
        except Exception as exc:
            return False, f"PR detayı alınamadı: {exc}"

    def add_pr_comment(self, number: int, comment: str) -> tuple[bool, str]:
        """Bir PR'a yorum ekle."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            issue = self._repo.get_issue(number)
            created = issue.create_comment(comment)
            return True, (f"✓ Yorum eklendi (PR #{number}):\n" f"  URL: {created.html_url}")
        except Exception as exc:
            return False, f"PR yorumu eklenemedi: {exc}"

    def close_pull_request(self, number: int) -> tuple[bool, str]:
        """Bir PR'ı kapat (merged olmadan)."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            pr = self._repo.get_pull(number)
            pr.edit(state="closed")
            return True, f"✓ PR #{number} kapatıldı: {pr.html_url}"
        except Exception as exc:
            return False, f"PR kapatma hatası: {exc}"

    def list_issues(self, state: str = "open", limit: int = 10) -> tuple[bool, list]:
        """Depodaki Issue'ları listeler (PR'ları filtreler)."""
        if not self._repo:
            return False, ["Aktif depo yok."]
        try:
            valid_states = {"open", "closed", "all"}
            safe_state = state.lower() if state.lower() in valid_states else "open"
            safe_limit = max(1, min(int(limit), 100))
            issues = self._repo.get_issues(state=safe_state)
            result = []
            for issue in issues[:safe_limit]:
                # GitHub API'sinde PR'lar da birer Issue'dur, onları filtrele
                if issue.pull_request is not None:
                    continue
                result.append(
                    {
                        "number": issue.number,
                        "title": issue.title,
                        "state": issue.state,
                        "user": issue.user.login,
                        "created_at": issue.created_at.isoformat(),
                    }
                )
            return True, result
        except Exception as exc:
            logger.error("Issue listeleme hatası: %s", exc)
            return False, [f"Hata: {exc}"]

    def create_issue(self, title: str, body: str) -> tuple[bool, str]:
        """Yeni bir Issue oluşturur."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            issue = self._repo.create_issue(title=title, body=body)
            return True, f"✓ Issue oluşturuldu: #{issue.number} - {issue.title}"
        except Exception as exc:
            return False, f"✗ Issue oluşturulamadı: {exc}"

    def comment_issue(self, number: int, body: str) -> tuple[bool, str]:
        """Var olan bir Issue'ya yorum ekler."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            issue = self._repo.get_issue(number=number)
            issue.create_comment(body)
            return True, f"✓ Issue #{number} için yorum eklendi."
        except Exception as exc:
            return False, f"✗ Yorum eklenemedi: {exc}"

    def close_issue(self, number: int) -> tuple[bool, str]:
        """Bir Issue'yu kapatır."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            issue = self._repo.get_issue(number=number)
            issue.edit(state="closed")
            return True, f"✓ Issue #{number} başarıyla kapatıldı."
        except Exception as exc:
            return False, f"✗ Issue kapatılamadı: {exc}"

    def get_pull_request_diff(self, number: int) -> tuple[bool, str]:
        """Bir PR'ın birleştirilmiş diff (patch) içeriğini döndürür."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            pr = self._repo.get_pull(number)
            diff_parts = [f"--- PR #{number} DIFF ({pr.title}) ---"]

            for file in pr.get_files():
                diff_parts.append(f"\nDosya: {file.filename} | Durum: {file.status}")
                diff_parts.append("---------------------------------------------------")
                if file.patch:
                    diff_parts.append(file.patch)
                else:
                    diff_parts.append(
                        "(Bu dosya için Diff/Patch metni yok - ikili/binary dosya olabilir)"
                    )

            if len(diff_parts) == 1:
                return True, "Bu PR'da değiştirilmiş kod dosyası bulunmuyor."

            return True, "\n".join(diff_parts)
        except Exception as exc:
            logger.error("PR Diff alınamadı: %s", exc)
            return False, f"Diff alınamadı: {exc}"

    def get_pr_files(self, number: int) -> tuple[bool, str]:
        """PR'da değişen dosyaların listesini döndür."""
        if not self._repo:
            return False, "Aktif depo yok."
        try:
            pr = self._repo.get_pull(number)
            files = list(pr.get_files())
            lines = [f"[PR #{number} Değişen Dosyalar — {self._repo.full_name}]"]
            for f in files:
                lines.append(f"  {f.status:8}  +{f.additions:<4} -{f.deletions:<4}  {f.filename}")
            return True, "\n".join(lines)
        except Exception as exc:
            return False, f"PR dosya listesi alınamadı: {exc}"

    def search_code(self, query: str) -> tuple[bool, str]:
        """Depoda kod araması yap."""
        if not self._gh or not self._repo:
            return False, "GitHub bağlantısı veya aktif depo yok."
        try:
            full_query = f"{query} repo:{self._repo.full_name}"
            results = list(self._gh.search_code(full_query)[:10])
            if not results:
                return True, f"'{query}' için sonuç bulunamadı."
            lines = [f"[Kod Arama: '{query}']"]
            for item in results:
                lines.append(f"  📄 {item.path}")
            return True, "\n".join(lines)
        except Exception as exc:
            return False, f"Kod arama hatası: {exc}"

    # ─────────────────────────────────────────────
    #  DURUM
    # ─────────────────────────────────────────────

    def is_available(self) -> bool:
        if not self._available and not self.token:
            logger.debug(
                "GitHub: Token eksik. .env dosyasına GITHUB_TOKEN=<token> ekleyin. "
                "Token oluşturmak için: https://github.com/settings/tokens"
            )
        return self._available

    def status(self) -> str:
        if not self._available:
            if not self.token:
                return (
                    "GitHub: Bağlı değil\n"
                    "  → Token eklemek için: .env dosyasına GITHUB_TOKEN=<token> satırı ekleyin\n"
                    "  → Token oluşturmak için: https://github.com/settings/tokens\n"
                    "  → Gerekli izinler: repo (okuma) veya public_repo (genel depolar)"
                )
            return "GitHub: Token geçersiz veya bağlantı hatası (log dosyasını kontrol edin)"
        repo_info = f" | Depo: {self.repo_name}" if self.repo_name else " | Depo: ayarlanmamış"
        return f"GitHub: Bağlı{repo_info}"

    @property
    def default_branch(self) -> str:
        """Aktif repo'nun varsayılan branch adını döndürür; repo yoksa 'main'."""
        return self._repo.default_branch if self._repo else "main"

    def get_pull_requests_detailed(
        self,
        state: str = "open",
        limit: int = 50,
    ) -> tuple[bool, list[dict], str]:
        """
        PR listesini yapısal dict listesi olarak döndürür.

        web_server.py gibi dış modüllerin _repo'ya doğrudan erişmesini önler.
        """
        if not self._repo:
            return False, [], "Repo ayarlanmamış."
        try:
            prs = []
            for pr in self._repo.get_pulls(state=state, sort="updated")[:limit]:
                prs.append(
                    {
                        "number": pr.number,
                        "title": pr.title,
                        "state": pr.state,
                        "author": pr.user.login,
                        "head": pr.head.ref,
                        "base": pr.base.ref,
                        "url": pr.html_url,
                        "created_at": pr.created_at.strftime("%Y-%m-%d %H:%M"),
                        "updated_at": pr.updated_at.strftime("%Y-%m-%d %H:%M"),
                        "additions": pr.additions,
                        "deletions": pr.deletions,
                        "changed_files": pr.changed_files,
                        "comments": pr.comments,
                    }
                )
            return True, prs, ""
        except Exception as exc:
            logger.error("get_pull_requests_detailed hatası: %s", exc)
            return False, [], str(exc)

    def __repr__(self) -> str:
        return f"<GitHubManager available={self._available} " f"repo={self.repo_name or 'None'}>"
