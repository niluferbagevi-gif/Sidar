"""Sidar araç kayıt/argüman şema yardımcıları."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class WriteFileSchema(BaseModel):
    path: str
    content: str


class PatchFileSchema(BaseModel):
    path: str
    old_text: str
    new_text: str


class GithubListFilesSchema(BaseModel):
    path: str = ""
    branch: Optional[str] = None


class GithubWriteSchema(BaseModel):
    path: str
    content: str
    commit_message: str
    branch: Optional[str] = None


class GithubCreateBranchSchema(BaseModel):
    branch_name: str
    from_branch: Optional[str] = None


class GithubCreatePRSchema(BaseModel):
    title: str
    body: str
    head: str
    base: Optional[str] = None


class GithubListPRsSchema(BaseModel):
    state: str = "open"
    limit: int = 10


class GithubListIssuesSchema(BaseModel):
    state: str = "open"
    limit: int = 10


class GithubCreateIssueSchema(BaseModel):
    title: str
    body: str


class GithubCommentIssueSchema(BaseModel):
    number: int
    body: str


class GithubCloseIssueSchema(BaseModel):
    number: int


class GithubPRDiffSchema(BaseModel):
    number: int = Field(description="Diff (fark) kodu alınacak PR numarası")


class ScanProjectTodosSchema(BaseModel):
    directory: Optional[str] = Field(default=None, description="Taranacak alt dizin (boş bırakılırsa tüm proje taranır)")
    extensions: Optional[List[str]] = Field(default=None, description="Taranacak dosya uzantıları listesi (Örn: ['.py', '.js'])")


TOOL_ARG_SCHEMAS: Dict[str, Type[BaseModel]] = {
    "write_file": WriteFileSchema,
    "patch_file": PatchFileSchema,
    "github_list_files": GithubListFilesSchema,
    "github_write": GithubWriteSchema,
    "github_create_branch": GithubCreateBranchSchema,
    "github_create_pr": GithubCreatePRSchema,
    "github_list_prs": GithubListPRsSchema,
    "github_list_issues": GithubListIssuesSchema,
    "github_create_issue": GithubCreateIssueSchema,
    "github_comment_issue": GithubCommentIssueSchema,
    "github_close_issue": GithubCloseIssueSchema,
    "github_pr_diff": GithubPRDiffSchema,
    "scan_project_todos": ScanProjectTodosSchema,
}

# Pydantic v2: Optional alanları olan modellerde forward reference çözümlemesi için model_rebuild() gerekir.
for _schema in TOOL_ARG_SCHEMAS.values():
    _schema.model_rebuild()


def parse_tool_argument(tool_name: str, raw_arg: str) -> Any:
    """Şema tanımlı araçlar için yalnızca JSON argümanını typed modele dönüştür."""
    schema = TOOL_ARG_SCHEMAS.get(tool_name)
    if schema is None:
        return raw_arg

    text = (raw_arg or "").strip()
    if not text:
        return schema.model_validate({})

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{tool_name} aracı JSON argümanı bekliyor.") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{tool_name} aracı JSON object argümanı bekliyor.")

    return schema.model_validate(payload)


def build_tool_dispatch(agent: Any) -> Dict[str, Callable[[Any], Any]]:
    """Araç tablosunu dış modülde üretir (tek source-of-truth)."""
    return {
        "list_dir":               agent._tool_list_dir,
        "read_file":              agent._tool_read_file,
        "write_file":             agent._tool_write_file,
        "patch_file":             agent._tool_patch_file,
        "execute_code":           agent._tool_execute_code,
        "audit":                  agent._tool_audit,
        "health":                 agent._tool_health,
        "gpu_optimize":           agent._tool_gpu_optimize,
        "github_commits":         agent._tool_github_commits,
        "github_info":            agent._tool_github_info,
        "github_read":            agent._tool_github_read,
        "github_list_files":      agent._tool_github_list_files,
        "github_write":           agent._tool_github_write,
        "github_create_branch":   agent._tool_github_create_branch,
        "github_create_pr":       agent._tool_github_create_pr,
        "github_search_code":     agent._tool_github_search_code,
        "github_list_prs":        agent._tool_github_list_prs,
        "github_get_pr":          agent._tool_github_get_pr,
        "github_comment_pr":      agent._tool_github_comment_pr,
        "github_close_pr":        agent._tool_github_close_pr,
        "github_pr_files":        agent._tool_github_pr_files,
        "github_smart_pr":        agent._tool_github_smart_pr,
        "github_list_issues":    agent._tool_github_list_issues,
        "github_create_issue":   agent._tool_github_create_issue,
        "github_comment_issue":  agent._tool_github_comment_issue,
        "github_close_issue":    agent._tool_github_close_issue,
        "github_pr_diff":       agent._tool_github_pr_diff,
        "web_search":             agent._tool_web_search,
        "fetch_url":              agent._tool_fetch_url,
        "search_docs":            agent._tool_search_docs,
        "search_stackoverflow":   agent._tool_search_stackoverflow,
        "pypi":                   agent._tool_pypi,
        "pypi_compare":           agent._tool_pypi_compare,
        "npm":                    agent._tool_npm,
        "gh_releases":            agent._tool_gh_releases,
        "gh_latest":              agent._tool_gh_latest,
        "docs_search":            agent._tool_docs_search,
        "docs_add":               agent._tool_docs_add,
        "docs_add_file":          agent._tool_docs_add_file,
        "docs_list":              agent._tool_docs_list,
        "docs_delete":            agent._tool_docs_delete,
        "run_shell":              agent._tool_run_shell,
        "bash":                   agent._tool_run_shell,
        "shell":                  agent._tool_run_shell,
        "glob_search":            agent._tool_glob_search,
        "grep_files":             agent._tool_grep_files,
        "grep":                   agent._tool_grep_files,
        "ls":                     agent._tool_list_dir,
        "todo_write":             agent._tool_todo_write,
        "todo_read":              agent._tool_todo_read,
        "todo_update":            agent._tool_todo_update,
        "scan_project_todos":    agent._tool_scan_project_todos,
        "get_config":             agent._tool_get_config,
        "print_config_summary":   agent._tool_get_config,
        "subtask":                agent._tool_subtask,
        "agent":                  agent._tool_subtask,
    }


class SidarToolRegistryMixin:
    async def _tool_list_dir(self, a: str) -> str:
        """Yerel bir dizinin içeriğini listeler."""
        # Dizin listeleme disk I/O içerir — event loop'u bloke etmemek için thread'e itilir
        _, result = await asyncio.to_thread(self.code.list_directory, a or ".")
        return result

    async def _tool_read_file(self, a: str) -> str:
        """Yerel bir dosyayı satır numaralarıyla okur."""
        if not a: return "Dosya yolu belirtilmedi."
        # Disk okuma event loop'u bloke eder — thread'e itilir
        ok, result = await asyncio.to_thread(self.code.read_file, a)
        if ok:
            await asyncio.to_thread(self.memory.set_last_file, a)
            # Büyük dosya tespiti: eşiği geçen dosyalar için RAG önerisi ekle
            threshold = getattr(self.cfg, "RAG_FILE_THRESHOLD", 20000)
            if len(result) > threshold:
                fname = Path(a).name
                result += (
                    f"\n\n---\n💡 **[Büyük Dosya — {len(result):,} karakter]** "
                    f"Bu dosyayı her seferinde okumak yerine RAG deposuna ekleyin:\n"
                    f"  • Eklemek için: `docs_add_file|{a}` aracını çağırın\n"
                    f"  • Ekledikten sonra sorgu için: `docs_search|{fname} <sorgunuz>`\n"
                    f"  • Bu sayede Sidar yalnızca ilgili bölümü bulup çıkarır."
                )
        return result

    async def _tool_write_file(self, a: str | WriteFileSchema) -> str:
        """Bir dosyayı verilen içerikle tamamen yazar (overwrite)."""
        if isinstance(a, WriteFileSchema):
            path = a.path.strip()
            content = a.content
        else:
            parts = a.split("|||", 1)
            if len(parts) < 2:
                return "⚠ Hatalı format. Kullanım: path|||content"
            path = parts[0].strip()
            content = parts[1]
        _, result = await asyncio.to_thread(self.code.write_file, path, content)
        return result

    async def _tool_patch_file(self, a: str | PatchFileSchema) -> str:
        """Dosyada eski metni yenisiyle değiştirerek yama uygular."""
        if isinstance(a, PatchFileSchema):
            path, old_text, new_text = a.path.strip(), a.old_text, a.new_text
        else:
            parts = a.split("|||")
            if len(parts) < 3:
                return "⚠ Hatalı patch formatı. Kullanım: path|||eski_kod|||yeni_kod"
            path, old_text, new_text = parts[0].strip(), parts[1], parts[2]
        _, result = await asyncio.to_thread(self.code.patch_file, path, old_text, new_text)
        return result

    async def _tool_execute_code(self, a: str) -> str:
        """Python kodunu izole ortamda çalıştırır."""
        if not a: return "⚠ Çalıştırılacak kod belirtilmedi."
        if hasattr(self.code, "execute_code_async"):
            _, result = await self.code.execute_code_async(a)
        else:
            _, result = await asyncio.to_thread(self.code.execute_code, a)
        return result

    async def _tool_audit(self, a: str) -> str:
        """Projeyi hızlı statik denetimden geçirir."""
        # Tüm .py dosyalarını tararken ağır disk I/O yapılır — thread'e itilir
        return await asyncio.to_thread(self.code.audit_project, a or ".")

    async def _tool_health(self, _: str) -> str:
        """Sistem sağlık raporunu döndürür."""
        return self.health.full_report()

    async def _tool_gpu_optimize(self, _: str) -> str:
        """GPU bellek temizleme/optimizasyon rutini çalıştırır."""
        return self.health.optimize_gpu_memory()

    async def _tool_github_commits(self, a: str) -> str:
        try: n = int(a)
        except: n = 10
        _, result = self.github.list_commits(n=n)
        return result

    async def _tool_github_info(self, _: str) -> str:
        _, result = self.github.get_repo_info()
        return result

    async def _tool_github_read(self, a: str) -> str:
        if not a: return "⚠ Okunacak GitHub dosya yolu belirtilmedi."
        _, result = self.github.read_remote_file(a)
        return result

    async def _tool_github_list_files(self, a: str | GithubListFilesSchema) -> str:
        """GitHub deposundaki dizin içeriğini listele. Argüman: 'path[|||branch]'"""
        if isinstance(a, GithubListFilesSchema):
            path, branch = a.path, a.branch
        else:
            parts = a.split("|||")
            path = parts[0].strip() if parts else ""
            branch = parts[1].strip() if len(parts) > 1 else None
        _, result = self.github.list_files(path, branch)
        return result

    async def _tool_github_write(self, a: str | GithubWriteSchema) -> str:
        """GitHub'a dosya yaz/güncelle. Argüman: 'path|||content|||commit_message[|||branch]'"""
        if isinstance(a, GithubWriteSchema):
            path, content, message, branch = a.path.strip(), a.content, a.commit_message.strip(), a.branch
        else:
            parts = a.split("|||")
            if len(parts) < 3:
                return "⚠ Hatalı format. Kullanım: path|||içerik|||commit_mesajı[|||branch]"
            path = parts[0].strip()
            content = parts[1]
            message = parts[2].strip()
            branch = parts[3].strip() if len(parts) > 3 else None
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, result = self.github.create_or_update_file(path, content, message, branch)
        return result

    async def _tool_github_create_branch(self, a: str | GithubCreateBranchSchema) -> str:
        """GitHub'da yeni dal oluştur. Argüman: 'branch_adı[|||kaynak_branch]'"""
        if isinstance(a, GithubCreateBranchSchema):
            branch_name, from_branch = a.branch_name, a.from_branch
        else:
            if not a:
                return "⚠ Dal adı belirtilmedi."
            parts = a.split("|||")
            branch_name = parts[0].strip()
            from_branch = parts[1].strip() if len(parts) > 1 else None
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, result = self.github.create_branch(branch_name, from_branch)
        return result

    async def _tool_github_create_pr(self, a: str | GithubCreatePRSchema) -> str:
        """GitHub Pull Request oluştur. Argüman: 'başlık|||açıklama|||head_branch[|||base_branch]'"""
        if isinstance(a, GithubCreatePRSchema):
            title, body, head, base = a.title.strip(), a.body, a.head.strip(), a.base
        else:
            parts = a.split("|||")
            if len(parts) < 3:
                return "⚠ Hatalı format. Kullanım: başlık|||açıklama|||head_branch[|||base_branch]"
            title = parts[0].strip()
            body = parts[1]
            head = parts[2].strip()
            base = parts[3].strip() if len(parts) > 3 else None
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, result = self.github.create_pull_request(title, body, head, base)
        return result

    async def _tool_github_search_code(self, a: str) -> str:
        """GitHub deposunda kod ara. Argüman: arama_sorgusu"""
        if not a:
            return "⚠ Arama sorgusu belirtilmedi."
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, result = self.github.search_code(a)
        return result

    async def _tool_github_list_prs(self, a: str | GithubListPRsSchema) -> str:
        """Pull Request listesi. Argüman: 'state[|||limit]' (state: open/closed/all)"""
        if isinstance(a, GithubListPRsSchema):
            state, limit = a.state, a.limit
        else:
            parts = a.split("|||")
            state = parts[0].strip() if parts[0].strip() else "open"
            try:
                limit = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else 10
            except ValueError:
                limit = 10
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, result = self.github.list_pull_requests(state=state, limit=limit)
        return result

    async def _tool_github_get_pr(self, a: str) -> str:
        """Belirli bir PR'ın detaylarını getir. Argüman: PR numarası"""
        if not a:
            return "⚠ PR numarası belirtilmedi."
        try:
            number = int(a.strip())
        except ValueError:
            return "⚠ Geçerli bir PR numarası girin."
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, result = self.github.get_pull_request(number)
        return result

    async def _tool_github_comment_pr(self, a: str) -> str:
        """PR'a yorum ekle. Argüman: 'pr_numarası|||yorum_metni'"""
        parts = a.split("|||", 1)
        if len(parts) < 2:
            return "⚠ Format: pr_numarası|||yorum_metni"
        try:
            number = int(parts[0].strip())
        except ValueError:
            return "⚠ Geçerli bir PR numarası girin."
        comment = parts[1].strip()
        if not comment:
            return "⚠ Yorum metni boş olamaz."
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, result = self.github.add_pr_comment(number, comment)
        return result

    async def _tool_github_close_pr(self, a: str) -> str:
        """PR'ı kapat. Argüman: PR numarası"""
        if not a:
            return "⚠ PR numarası belirtilmedi."
        try:
            number = int(a.strip())
        except ValueError:
            return "⚠ Geçerli bir PR numarası girin."
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, result = self.github.close_pull_request(number)
        return result

    async def _tool_github_pr_files(self, a: str) -> str:
        """PR'daki değişen dosyaları listele. Argüman: PR numarası"""
        if not a:
            return "⚠ PR numarası belirtilmedi."
        try:
            number = int(a.strip())
        except ValueError:
            return "⚠ Geçerli bir PR numarası girin."
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, result = self.github.get_pr_files(number)
        return result


    async def _tool_github_list_issues(self, a: str | GithubListIssuesSchema) -> str:
        """Issue listesi. Argüman: 'state[|||limit]' (state: open/closed/all)"""
        if isinstance(a, GithubListIssuesSchema):
            state, limit = a.state, a.limit
        else:
            arg = parse_tool_argument("github_list_issues", a)
            state = getattr(arg, "state", "open")
            limit = getattr(arg, "limit", 10)

        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."

        ok, issues = await asyncio.to_thread(self.github.list_issues, state, limit)
        if not ok:
            return issues[0] if issues else "Hata: Issue'lar alınamadı."
        if not issues:
            return f"Repo'da {state} durumunda issue bulunmuyor."

        lines = [f"--- {state.upper()} ISSUES ---"]
        for item in issues:
            lines.append(
                f"#{item['number']} [{item['user']}] {item['title']} ({item['created_at']})"
            )
        return "\n".join(lines)

    async def _tool_github_create_issue(self, a: str | GithubCreateIssueSchema) -> str:
        """Yeni issue oluştur. Argüman: 'title|||body'"""
        arg = a if isinstance(a, GithubCreateIssueSchema) else parse_tool_argument("github_create_issue", a)
        if not getattr(arg, "title", None):
            return "⚠ Kullanım hatası: title gerekli."
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, msg = await asyncio.to_thread(self.github.create_issue, arg.title, arg.body)
        return msg

    async def _tool_github_comment_issue(self, a: str | GithubCommentIssueSchema) -> str:
        """Issue'ya yorum ekle. Argüman: 'number|||body'"""
        arg = a if isinstance(a, GithubCommentIssueSchema) else parse_tool_argument("github_comment_issue", a)
        if not getattr(arg, "number", None):
            return "⚠ Kullanım hatası: number gerekli."
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, msg = await asyncio.to_thread(self.github.comment_issue, arg.number, arg.body)
        return msg

    async def _tool_github_close_issue(self, a: str | GithubCloseIssueSchema) -> str:
        """Issue kapat. Argüman: issue numarası"""
        arg = a if isinstance(a, GithubCloseIssueSchema) else parse_tool_argument("github_close_issue", a)
        if not getattr(arg, "number", None):
            return "⚠ Kullanım hatası: number gerekli."
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, msg = await asyncio.to_thread(self.github.close_issue, arg.number)
        return msg


    async def _tool_github_pr_diff(self, a: str | GithubPRDiffSchema) -> str:
        """PR diff içeriğini getir. Argüman: PR numarası"""
        arg = a if isinstance(a, GithubPRDiffSchema) else parse_tool_argument("github_pr_diff", a)
        if not getattr(arg, "number", None):
            return "⚠ Kullanım hatası: number gerekli."
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, result = await asyncio.to_thread(self.github.get_pull_request_diff, arg.number)
        return result

    async def _tool_github_smart_pr(self, a: str) -> str:
        """
        Akıllı PR oluşturma — Claude Code tarzı.

        Git diff/log analiz eder, LLM ile anlamlı başlık+açıklama üretir,
        ardından GitHub API üzerinden PR oluşturur.

        Argüman: 'head_branch[|||base_branch[|||ek_notlar]]'
        head_branch boş bırakılırsa mevcut git branch kullanılır.
        """
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış. .env dosyasına GITHUB_TOKEN ekleyin."

        parts = a.split("|||")
        head = parts[0].strip() if parts and parts[0].strip() else ""
        base = parts[1].strip() if len(parts) > 1 and parts[1].strip() else ""
        notes = parts[2].strip() if len(parts) > 2 else ""

        # 1. Mevcut branch'i belirle
        if not head:
            ok, branch_out = await asyncio.to_thread(
                self.code.run_shell, "git branch --show-current"
            )
            head = branch_out.strip() if ok and branch_out.strip() else ""
            if not head:
                return (
                    "⚠ Mevcut git branch'i belirlenemedi.\n"
                    "Lütfen branch adını açıkça belirtin: 'github_smart_pr' aracına "
                    "'feature/my-branch' veya 'branch_adı|||main' formatında argüman geçin."
                )

        # 2. Base branch'i belirle
        if not base:
            try:
                base = self.github.default_branch
            except Exception:
                base = "main"

        # 3. Git durumu ve diff analizi
        _, git_status = await asyncio.to_thread(
            self.code.run_shell, "git status --short"
        )
        _, diff_stat = await asyncio.to_thread(
            self.code.run_shell, "git diff --stat HEAD"
        )
        _, diff_full = await asyncio.to_thread(
            self.code.run_shell, "git diff --no-color HEAD"
        )
        _, commit_log = await asyncio.to_thread(
            self.code.run_shell, f"git log {base}..HEAD --oneline 2>/dev/null || git log --oneline -10"
        )

        max_diff_chars = 10000
        if len(diff_full) > max_diff_chars:
            diff_full = (
                diff_full[:max_diff_chars]
                + "\n\n[...Diff çok büyük olduğu için geri kalanı kırpıldı...]"
            )

        # Değişiklik yoksa uyar
        if not git_status.strip() and not diff_stat.strip() and not commit_log.strip():
            return (
                f"⚠ '{head}' branch'inde '{base}'e göre commit edilmiş değişiklik bulunamadı.\n"
                "Önce değişikliklerinizi commit edin, ardından PR oluşturun."
            )

        # 4. LLM ile PR başlığı + açıklaması üret
        context_block = (
            f"Branch: {head} → {base}\n\n"
            f"Git Durumu (git status --short):\n{git_status or '(temiz)'}\n\n"
            f"Değişiklik Özeti (git diff --stat):\n{diff_stat or '(yok)'}\n\n"
            f"Commit Geçmişi:\n{commit_log or '(yok)'}\n"
        )
        if notes:
            context_block += f"\nEk Notlar: {notes}\n"

        pr_prompt = (
            "Aşağıdaki git değişikliklerine bakarak bir GitHub Pull Request başlığı ve açıklaması oluştur.\n"
            "Başlık kısa (max 70 karakter) ve açıklayıcı olmalı.\n"
            "Açıklama Türkçe olabilir; '## Özet' ve '## Test Planı' bölümleri içermeli.\n"
            "SADECE şu JSON formatında yanıt ver (başka hiçbir şey ekleme):\n"
            '{"title": "...", "body": "## Özet\\n- madde\\n\\n## Test Planı\\n- [ ] adım"}\n\n'
            + context_block
        )

        title = f"feat: {head} branch değişiklikleri"
        body = (
            f"## Özet\n- `{head}` branch'inden yapılan değişiklikler\n\n"
            f"## Test Planı\n- [ ] Manuel test edildi\n- [ ] Birim testler geçiyor"
        )

        try:
            raw = await self.llm.chat(
                messages=[{"role": "user", "content": pr_prompt}],
                model=getattr(self.cfg, "TEXT_MODEL", self.cfg.CODING_MODEL),
                temperature=0.2,
                stream=False,
                json_mode=True,
            )
            if isinstance(raw, str):
                _dec = json.JSONDecoder()
                idx = raw.find("{")
                if idx != -1:
                    pr_data, _ = _dec.raw_decode(raw, idx)
                    title = str(pr_data.get("title", title)).strip()[:70] or title
                    body = str(pr_data.get("body", body)).strip() or body
        except Exception as llm_exc:
            logger.warning("Smart PR: LLM başlık üretimi başarısız, varsayılan kullanılıyor: %s", llm_exc)

        # 5. GitHub PR oluştur
        ok, result = self.github.create_pull_request(title, body, head, base)
        if ok:
            return (
                f"✓ Akıllı PR oluşturuldu!\n{result}\n\n"
                f"**Başlık :** {title}\n"
                f"**Branch :** `{head}` → `{base}`\n\n"
                f"**Açıklama Önizlemesi:**\n{body[:500]}{'...' if len(body) > 500 else ''}"
            )
        return result

    async def _tool_web_search(self, a: str) -> str:
        if not a: return "⚠ Arama sorgusu belirtilmedi."
        _, result = await self.web.search(a)
        return result

    async def _tool_fetch_url(self, a: str) -> str:
        if not a: return "⚠ URL belirtilmedi."
        _, result = await self.web.fetch_url(a)
        return result

    async def _tool_search_docs(self, a: str) -> str:
        parts = a.split(" ", 1)
        lib, topic = parts[0], (parts[1] if len(parts) > 1 else "")
        _, result = await self.web.search_docs(lib, topic)
        return result

    async def _tool_search_stackoverflow(self, a: str) -> str:
        _, result = await self.web.search_stackoverflow(a)
        return result

    async def _tool_pypi(self, a: str) -> str:
        _, result = await self.pkg.pypi_info(a)
        return result

    async def _tool_pypi_compare(self, a: str) -> str:
        parts = a.split("|", 1)
        if len(parts) < 2: return "⚠ Kullanım: paket|mevcut_sürüm"
        _, result = await self.pkg.pypi_compare(parts[0].strip(), parts[1].strip())
        return result

    async def _tool_npm(self, a: str) -> str:
        _, result = await self.pkg.npm_info(a)
        return result

    async def _tool_gh_releases(self, a: str) -> str:
        _, result = await self.pkg.github_releases(a)
        return result

    async def _tool_gh_latest(self, a: str) -> str:
        _, result = await self.pkg.github_latest_release(a)
        return result

    async def _tool_docs_search(self, a: str) -> str:
        # Opsiyonel mode: "sorgu|mode"  (mode: auto/vector/bm25/keyword)
        parts = a.split("|", 1)
        query = parts[0].strip()
        mode  = parts[1].strip() if len(parts) > 1 else "auto"
        # Aktif oturum ID'sini al
        session_id = self.memory.active_session_id or "global"
        _, result = await asyncio.to_thread(self.docs.search, query, None, mode, session_id)
        return result

    async def _tool_docs_add(self, a: str) -> str:
        parts = a.split("|", 1)
        if len(parts) < 2: return "⚠ Kullanım: başlık|url"
        session_id = self.memory.active_session_id or "global"
        _, result = await self.docs.add_document_from_url(parts[1].strip(), title=parts[0].strip(), session_id=session_id)
        return result

    async def _tool_docs_add_file(self, a: str) -> str:
        """
        Yerel dosyayı RAG deposuna ekle.
        Format: 'dosya_yolu'  veya  'başlık|dosya_yolu'
        """
        parts = a.split("|", 1)
        if len(parts) == 2:
            title, path = parts[0].strip(), parts[1].strip()
        else:
            path  = parts[0].strip()
            title = Path(path).name if path else ""
        if not path:
            return "⚠ Dosya yolu belirtilmedi. Kullanım: docs_add_file|dosya_yolu"
        session_id = self.memory.active_session_id or "global"
        # add_document_from_file parametreleri: path, title, tags, session_id
        ok, result = await asyncio.to_thread(self.docs.add_document_from_file, path, title, None, session_id)
        return result

    async def _tool_docs_list(self, _: str) -> str:
        session_id = self.memory.active_session_id or "global"
        return self.docs.list_documents(session_id=session_id)

    async def _tool_docs_delete(self, a: str) -> str:
        session_id = self.memory.active_session_id or "global"
        return self.docs.delete_document(a, session_id=session_id)

    # ── Alt Görev / Paralel Araçlar (Claude Code Agent tool eşdeğeri) ─────

    async def _tool_subtask(self, task: str) -> str:
        """
        Bir alt görevi bağımsız mini ReAct döngüsünde çalıştırır.
        Claude Code'daki Agent tool eşdeğeri.
        Format: 'görev açıklaması'
        """
        if not task.strip():
            return "⚠ Alt görev açıklaması belirtilmedi."

        max_steps = int(getattr(self.cfg, "SUBTASK_MAX_STEPS", 5) or 5)
        max_steps = max(1, max_steps)  # yalnızca alt sınır: en az 1 adım
        messages: list = [{"role": "user", "content": task}]
        mini_system = (
            "Sen bağımsız bir alt ajansın. Verilen görevi tamamla.\n"
            "Her adımda şu JSON formatında yanıt ver:\n"
            '{"thought": "analiz", "tool": "araç_adı", "argument": "argüman"}\n'
            "Görev tamamlandığında tool='final_answer' kullan.\n"
            f"Maksimum {max_steps} adımda tamamla. Sonucu Türkçe olarak özetle."
        )

        for _ in range(max_steps):
            try:
                raw = await self.llm.chat(
                    messages=messages,
                    model=getattr(self.cfg, "TEXT_MODEL", self.cfg.CODING_MODEL),
                    system_prompt=mini_system,
                    temperature=0.2,
                    stream=False,
                    json_mode=True,
                )
                if not isinstance(raw, str):
                    messages += [
                        {"role": "assistant", "content": str(raw)},
                        {"role": "user", "content": _FMT_SYS_WARN.format(msg="Alt görevde model string dışı çıktı döndürdü; JSON üret.")},
                    ]
                    continue

                _dec = json.JSONDecoder()
                idx = raw.find("{")
                if idx == -1:
                    messages += [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": _FMT_SYS_ERR.format(msg="JSON bloğu bulunamadı. Geçerli ToolCall JSON üret.")},
                    ]
                    continue
                action, _ = _dec.raw_decode(raw, idx)
                action_data = ToolCall.model_validate(action)

                tool_name = action_data.tool.strip()
                tool_arg = action_data.argument

                if tool_name == "final_answer":
                    final_text = str(tool_arg).strip() or "✓ Alt görev tamamlandı."
                    return f"[Alt Görev Tamamlandı]\n{final_text}"

                if not tool_name:
                    messages += [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": _FMT_SYS_ERR.format(msg="tool alanı boş. Geçerli bir araç seç.")},
                    ]
                    continue

                tool_result = await self._execute_tool(tool_name, tool_arg)
                if tool_result is None:
                    messages += [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": _FMT_TOOL_ERR.format(name=tool_name, error="Bu araç mevcut değil.")},
                    ]
                    continue

                messages += [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": _FMT_TOOL_STEP.format(name=tool_name, result=str(tool_result)[:1500])},
                ]
            except ValidationError as exc:
                logger.warning("Subtask ToolCall doğrulama hatası: %s", exc)
                messages += [
                    {"role": "assistant", "content": raw if 'raw' in locals() else ""},
                    {"role": "user", "content": _FMT_SYS_ERR.format(msg="ToolCall şeması hatalı. thought/tool/argument alanlarını eksiksiz üret.")},
                ]
                continue
            except Exception as exc:
                logger.warning("Subtask adım hatası: %s", exc)
                break

        return f"[Alt Görev] Maksimum adım sayısına ({max_steps}) ulaşıldı veya görev tamamlanamadı."

    # Yalnızca okuma/sorgulama araçları paralel çalışabilir.
    _AUTO_PARALLEL_SAFE = frozenset({
        "list_dir", "ls", "read_file", "glob_search", "grep_files", "grep",
        "github_info", "github_read", "github_list_files", "github_commits",
        "github_search_code", "health", "audit", "todo_read", "get_config",
        "web_search", "pypi", "npm", "docs_search", "docs_list",
        "search_stackoverflow", "fetch_url",
    })

    # ── Kabuk Komutları (Shell) ─────────────────────────────────────────

    async def _tool_run_shell(self, a: str) -> str:
        """Kabuk komutu çalıştır (git, npm, pip, ls, vb.). Yalnızca FULL modda."""
        if not a:
            return "⚠ Çalıştırılacak komut belirtilmedi."
        ok, result = await asyncio.to_thread(self.code.run_shell, a)
        return result

    # ── Dosya Arama ─────────────────────────────────────────────────────

    async def _tool_glob_search(self, a: str) -> str:
        """Glob deseni ile dosya ara. Örn: '**/*.py' veya 'src/**/*.ts'."""
        parts = a.split("|||", 1)
        pattern = parts[0].strip()
        base = parts[1].strip() if len(parts) > 1 else "."
        if not pattern:
            return "⚠ Glob deseni belirtilmedi."
        ok, result = await asyncio.to_thread(self.code.glob_search, pattern, base)
        return result

    async def _tool_grep_files(self, a: str) -> str:
        """
        Regex ile dosya içeriği ara.
        Format: 'regex[|||yol[|||dosya_filtresi[|||context_satır_sayısı]]]'
        """
        parts = a.split("|||")
        pattern = parts[0].strip() if parts else ""
        path = parts[1].strip() if len(parts) > 1 else "."
        file_glob = parts[2].strip() if len(parts) > 2 else "*"
        try:
            ctx_lines = int(parts[3].strip()) if len(parts) > 3 else 0
        except (ValueError, IndexError):
            ctx_lines = 0

        if not pattern:
            return "⚠ Arama kalıbı belirtilmedi."

        ok, result = await asyncio.to_thread(
            self.code.grep_files, pattern, path, file_glob,
            True, ctx_lines
        )
        return result

    # ── Görev Yönetimi (Todo) ───────────────────────────────────────────

    async def _tool_todo_write(self, a: str) -> str:
        """
        Görev listesini güncelle.
        Format: 'görev1:::durum1|||görev2:::durum2|||...'
        Durum: pending / in_progress / completed
        """
        if not a.strip():
            return "⚠ Görev verisi belirtilmedi."

        tasks_data = []
        for item in a.split("|||"):
            item = item.strip()
            if not item:
                continue
            if ":::" in item:
                parts = item.split(":::", 1)
                tasks_data.append({"content": parts[0].strip(), "status": parts[1].strip()})
            else:
                tasks_data.append({"content": item, "status": "pending"})

        return self.todo.set_tasks(tasks_data)

    async def _tool_todo_read(self, _: str) -> str:
        """Mevcut görev listesini göster."""
        return self.todo.list_tasks()

    async def _tool_todo_update(self, a: str) -> str:
        """
        Tek bir görevi güncelle.
        Format: 'görev_id|||yeni_durum'
        """
        parts = a.split("|||", 1)
        if len(parts) < 2:
            return "⚠ Format: görev_id|||yeni_durum"
        try:
            task_id = int(parts[0].strip())
        except ValueError:
            return "⚠ Görev ID sayısal olmalı."
        return self.todo.update_task(task_id, parts[1].strip())


    async def _tool_scan_project_todos(self, a: str | ScanProjectTodosSchema) -> str:
        """Projedeki TODO/FIXME etiketlerini tarar. Argüman: 'directory[|||ext1,ext2]'"""
        arg = a if isinstance(a, ScanProjectTodosSchema) else parse_tool_argument("scan_project_todos", a)
        directory = getattr(arg, "directory", None)
        extensions = getattr(arg, "extensions", None)

        # Tarama işlemi disk okuması yapacağı için event loop'u bloklamadan çalıştır
        return await asyncio.to_thread(self.todo.scan_project_todos, directory, extensions)

    async def _tool_get_config(self, _: str) -> str:
        """Çalışma anındaki gerçek Config değerlerini döndürür (.env dahil).
        Dizin ağacı ve satır numaraları dahil — LLM'in zengin final_answer
        üretebilmesi için tüm ham veri burada sağlanır.
        """
        import os as _os

        # ── Dizin ağacı (kök seviyesi) ─────────────────────────────
        base = str(self.cfg.BASE_DIR)
        try:
            entries = sorted(_os.listdir(base))
        except OSError:
            entries = []
        dirs  = [e for e in entries if _os.path.isdir(_os.path.join(base, e))]
        files = [e for e in entries if _os.path.isfile(_os.path.join(base, e))]
        tree_lines = [f"{base}/"]
        for d in dirs:
            tree_lines.append(f"  ├── {d}/")
        for i, f in enumerate(files):
            prefix = "└──" if i == len(files) - 1 else "├──"
            tree_lines.append(f"  {prefix} {f}")
        dir_tree = "\n".join(tree_lines)

        # ── GPU bilgisi ─────────────────────────────────────────────
        if self.cfg.USE_GPU:
            gpu_line = (
                f"{getattr(self.cfg, 'GPU_INFO', 'GPU')} "
                f"({getattr(self.cfg, 'GPU_COUNT', 1)} GPU, "
                f"CUDA {getattr(self.cfg, 'CUDA_VERSION', 'N/A')})"
            )
        else:
            gpu_line = f"Yok ({getattr(self.cfg, 'GPU_INFO', 'N/A')})"

        enc_status = "Etkin (Fernet)" if getattr(self.cfg, "MEMORY_ENCRYPTION_KEY", "") else "Devre Dışı"

        lines = [
            f"[Proje Kök Dizini]\n{dir_tree}",
            "",
            "[Gerçek Config Değerleri — config.py + .env]",
            "",
            "## Temel",
            f"  Proje        : {self.cfg.PROJECT_NAME} v{self.cfg.VERSION}",
            f"  Proje Dizini : {base}",
            f"  Erişim Seviye: {self.cfg.ACCESS_LEVEL.upper()}",
            f"  Debug Modu   : {self.cfg.DEBUG_MODE}",
            f"  Bellek Şifre : {enc_status}",
            "",
            "## 1. AI_PROVIDER",
            f"  Değer    : {self.cfg.AI_PROVIDER.upper()}",
            "  Seçenekler: 'ollama' (yerel) | 'gemini' (bulut)",
            "  Değiştirmek için: .env → AI_PROVIDER=gemini",
            "",
            "## 2. USE_GPU / GPU_MEMORY_FRACTION",
            f"  USE_GPU              : {self.cfg.USE_GPU}",
            f"  GPU                  : {gpu_line}",
            f"  GPU_MEMORY_FRACTION  : {getattr(self.cfg, 'GPU_MEMORY_FRACTION', 0.8)} "
            "(VRAM'in bu oranı ayrılır; geçerli aralık 0.1–1.0)",
            "",
            "## 3. OLLAMA_URL / CODING_MODEL / TEXT_MODEL",
            f"  OLLAMA_URL   : {self.cfg.OLLAMA_URL}",
            f"  CODING_MODEL : {self.cfg.CODING_MODEL}",
            f"  TEXT_MODEL   : {self.cfg.TEXT_MODEL}",
            f"  OLLAMA_TIMEOUT: {getattr(self.cfg, 'OLLAMA_TIMEOUT', 30)}s",
            "",
            "## 4. MAX_REACT_STEPS / REACT_TIMEOUT",
            f"  MAX_REACT_STEPS: {self.cfg.MAX_REACT_STEPS}",
            f"  REACT_TIMEOUT  : {getattr(self.cfg, 'REACT_TIMEOUT', 60)}s",
            "  Not: Karmaşık görevlerde bu değerlerin artırılması gerekebilir.",
            "",
            "## 5. RAG_TOP_K / RAG_CHUNK_SIZE / RAG_CHUNK_OVERLAP",
            f"  RAG_TOP_K        : {getattr(self.cfg, 'RAG_TOP_K', 3)}  (en iyi N sonuç getirilir)",
            f"  RAG_CHUNK_SIZE   : {getattr(self.cfg, 'RAG_CHUNK_SIZE', 1000)} karakter",
            f"  RAG_CHUNK_OVERLAP: {getattr(self.cfg, 'RAG_CHUNK_OVERLAP', 200)} karakter",
            "  Not: Bu değerler cevap kalitesini doğrudan etkiler.",
            "",
            "## Diğer",
            f"  CPU Çekirdek : {getattr(self.cfg, 'CPU_COUNT', 'N/A')}",
            f"  GitHub Repo  : {getattr(self.cfg, 'GITHUB_REPO', None) or '(ayarlanmamış)'}",
            f"  Bellek Turu  : max {self.cfg.MAX_MEMORY_TURNS}",
        ]
        return "\n".join(lines)

