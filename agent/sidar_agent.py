"""
Sidar Project - Ana Ajan
ReAct (Reason + Act) döngüsü ile çalışan yazılım mühendisi AI asistanı (Asenkron + Pydantic Uyumlu).
"""

import logging
import json
import re
import asyncio
import time
from pathlib import Path
from typing import Optional, AsyncIterator, Dict

from pydantic import BaseModel, Field, ValidationError

from config import Config
from core.memory import ConversationMemory
from core.llm_client import LLMClient
from core.rag import DocumentStore
from managers.code_manager import CodeManager
from managers.system_health import SystemHealthManager
from managers.github_manager import GitHubManager
from managers.security import SecurityManager
from managers.web_search import WebSearchManager
from managers.package_info import PackageInfoManager
from managers.todo_manager import TodoManager
from agent.auto_handle import AutoHandle
from agent.definitions import SIDAR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  ARAÇ MESAJ FORMAT SABİTLERİ
# LLM'in önceki araç sonuçlarını tutarlı parse edebilmesi için
# tek bir şema kullanılır.
# ─────────────────────────────────────────────
_FMT_TOOL_OK = (
    "[ARAÇ:{name}:SONUÇ]\n"
    "===\n"
    "{result}\n"
    "===\n"
    "KURAL: Yukarıdaki değerleri AYNEN kullan. ASLA kendi bilginden değer uydurma.\n"
    "Eğer görev tamamlandıysa MUTLAKA şu formatta yanıt ver:\n"
    "{{\"thought\": \"analiz\", \"tool\": \"final_answer\", \"argument\": \"<Markdown özet>\"}}\n"
    "Devam gerekiyorsa sonraki aracı çağır."
)
_FMT_TOOL_ERR = "[ARAÇ:{name}:HATA]\n{error}"  # araç hatası (bilinmeyen araç vb.)
_FMT_SYS_ERR  = "[Sistem Hatası] {msg}"        # ayrıştırma / doğrulama hatası
_FMT_SYS_WARN = "[Sistem Uyarısı] {msg}"       # döngü / iyileştirme uyarıları
_FMT_TOOL_STEP = "[ARAÇ:{name}:SONUÇ]\n===\n{result}\n===\nDevam et veya final_answer ver."

# Kodex-benzeri kullanım için: basit/tek-adım istekleri ReAct döngüsüne girmeden
# doğrudan güvenli araçlara yönlendiren hafif intent router.
_DIRECT_ROUTE_ALLOWED_TOOLS = frozenset({
    "list_dir",
    "ls",
    "read_file",
    "github_list_files",
    "github_read",
    "github_info",
    "github_commits",
    "get_config",
    "health",
    "audit",
    "docs_list",
    "glob_search",
    "grep_files",
    "grep",
    "todo_read",
})

# ─────────────────────────────────────────────
#  PYDANTIC VERİ MODELİ (YAPISAL ÇIKTI)
# ─────────────────────────────────────────────
class ToolCall(BaseModel):
    """LLM'in ReAct döngüsünde üretmesi gereken JSON şeması."""
    thought: str = Field(description="Ajanın mevcut adımdaki analizi ve planı.")
    tool: str = Field(description="Çalıştırılacak aracın tam adı (örn: final_answer, web_search).")
    argument: str = Field(default="", description="Araca geçirilecek parametre (opsiyonel).")


class SidarAgent:
    """
    Sidar — Yazılım Mimarı ve Baş Mühendis AI Asistanı.
    Tamamen asenkron ağ istekleri, stream, yapısal veri ve sonsuz vektör hafıza uyumlu yapı.
    """

    VERSION = "2.7.0"  # Claude Code Uyumu: mtime cache, genişletilmiş direct-route, yeni alias'lar

    def __init__(self, cfg: Config = None) -> None:
        self.cfg = cfg or Config()
        self._lock = None  # Asenkron Lock, respond çağrıldığında yaratılacak

        # Alt sistemler — temel (Senkron/Yerel)
        self.security = SecurityManager(self.cfg.ACCESS_LEVEL, self.cfg.BASE_DIR)
        self.code = CodeManager(
            self.security,
            self.cfg.BASE_DIR,
            docker_image=getattr(self.cfg, "DOCKER_PYTHON_IMAGE", "python:3.11-alpine"),
            docker_exec_timeout=getattr(self.cfg, "DOCKER_EXEC_TIMEOUT", 10),
        )
        self.health = SystemHealthManager(self.cfg.USE_GPU)
        self.github = GitHubManager(self.cfg.GITHUB_TOKEN, self.cfg.GITHUB_REPO)
        
        self.memory = ConversationMemory(
            file_path=self.cfg.MEMORY_FILE,
            max_turns=self.cfg.MAX_MEMORY_TURNS,
            encryption_key=getattr(self.cfg, "MEMORY_ENCRYPTION_KEY", ""),
        )
        
        self.llm = LLMClient(self.cfg.AI_PROVIDER, self.cfg)

        # Alt sistemler — yeni (Asenkron)
        self.web = WebSearchManager(self.cfg)
        self.pkg = PackageInfoManager(self.cfg)
        self.docs = DocumentStore(
            self.cfg.RAG_DIR,
            top_k=self.cfg.RAG_TOP_K,
            chunk_size=self.cfg.RAG_CHUNK_SIZE,
            chunk_overlap=self.cfg.RAG_CHUNK_OVERLAP,
            use_gpu=getattr(self.cfg, "USE_GPU", False),
            gpu_device=getattr(self.cfg, "GPU_DEVICE", 0),
            mixed_precision=getattr(self.cfg, "GPU_MIXED_PRECISION", False),
        )

        self.todo = TodoManager()
        self._instructions_cache: Optional[str] = None
        self._instructions_mtimes: Dict[str, float] = {}

        self.auto = AutoHandle(
            self.code, self.health, self.github, self.memory,
            self.web, self.pkg, self.docs,
        )

        logger.info(
            "SidarAgent v%s başlatıldı — sağlayıcı=%s model=%s erişim=%s (VECTOR MEMORY + ASYNC)",
            self.VERSION,
            self.cfg.AI_PROVIDER,
            self.cfg.CODING_MODEL,
            self.cfg.ACCESS_LEVEL,
        )

    # ─────────────────────────────────────────────
    #  ANA YANIT METODU (ASYNC STREAMING)
    # ─────────────────────────────────────────────

    async def respond(self, user_input: str) -> AsyncIterator[str]:
        """
        Kullanıcı girdisini asenkron işle ve yanıtı STREAM olarak döndür.
        """
        user_input = user_input.strip()
        if not user_input:
            yield "⚠ Boş girdi."
            return

        # Event loop içinde güvenli Lock oluşturma
        if self._lock is None:
            self._lock = asyncio.Lock()

        # Bellek yazma ve hızlı eşleme kilitli bölgede yapılır
        # memory.add() → asyncio.to_thread: dosya I/O event loop'u bloke etmez
        async with self._lock:
            await asyncio.to_thread(self.memory.add, "user", user_input)
            handled, quick_response = await self.auto.handle(user_input)

            # AutoHandle yakalayamadıysa hafif LLM router ile tek-adım araç dene
            if not handled:
                routed = await self._try_direct_tool_route(user_input)
                if routed is not None:
                    handled = True
                    quick_response = routed

            if handled:
                await asyncio.to_thread(self.memory.add, "assistant", quick_response)

        # Lock serbest bırakıldı
        if handled:
            yield quick_response
            return

        # Bellek eşiği dolmak üzereyse özetleme ve arşivleme tetikle
        if self.memory.needs_summarization():
            yield "\n[Sistem] Konuşma belleği arşivleniyor ve sıkıştırılıyor...\n"
            await self._summarize_memory()

        # ReAct döngüsünü akıştır
        async for chunk in self._react_loop(user_input):
            yield chunk

    async def _try_direct_tool_route(self, user_input: str) -> Optional[str]:
        """
        Basit/tek-adım komutları LLM tabanlı hafif bir router ile doğrudan araca yönlendir.
        Böylece her yeni ifade için AutoHandle regex ekleme ihtiyacı azalır.
        """
        router_system = (
            "Kullanıcı isteğini TEK adımda çözülebilecekse uygun aracı seç. "
            "Yalnızca şu şemada JSON döndür: "
            '{"thought":"...","tool":"...","argument":"..."}. '
            "Araç gerekmiyorsa tool='none' döndür. "
            "Sadece izinli araçlar: "
            + ", ".join(sorted(_DIRECT_ROUTE_ALLOWED_TOOLS))
        )
        try:
            raw = await self.llm.chat(
                messages=[{"role": "user", "content": user_input}],
                model=getattr(self.cfg, "TEXT_MODEL", self.cfg.CODING_MODEL),
                system_prompt=router_system,
                temperature=0.0,
                stream=False,
                json_mode=True,
            )
            if not isinstance(raw, str):
                return None
            parsed = ToolCall.model_validate_json(raw)
            tool_name = parsed.tool.strip().lower()
            if tool_name in ("", "none", "final_answer"):
                return None
            if tool_name not in _DIRECT_ROUTE_ALLOWED_TOOLS:
                return None
            result = await self._execute_tool(tool_name, parsed.argument)
            return result
        except Exception:
            return None

    # ─────────────────────────────────────────────
    #  ReAct DÖNGÜSÜ (PYDANTIC PARSING)
    # ─────────────────────────────────────────────

    async def _react_loop(self, user_input: str) -> AsyncIterator[str]:
        """
        LLM ile araç çağrısı döngüsü (Asenkron).
        Kullanıcıya yalnızca nihai yanıt metni döndürülür; ara JSON/araç
        çıktıları arka planda işlenir.
        """
        messages = self.memory.get_messages_for_llm()
        context = self._build_context()
        full_system = SIDAR_SYSTEM_PROMPT + "\n\n" + context

        _last_tool: str = ""          # Son çağrılan araç adı
        _last_tool_result: str = ""   # Son araç sonucu (tekrar tespitinde kullanılır)

        for step in range(self.cfg.MAX_REACT_STEPS):
            # 1. LLM Çağrısı (Async Stream)
            # ReAct döngüsü: düşünme/planlama/özetleme → TEXT_MODEL
            # Kod odaklı araçlara (execute_code, write_file, patch_file) CODING_MODEL
            # atanabilir; ancak döngü genelinde tutarlılık için TEXT_MODEL tercih edilir.
            response_generator = await self.llm.chat(
                messages=messages,
                model=getattr(self.cfg, "TEXT_MODEL", self.cfg.CODING_MODEL),
                system_prompt=full_system,
                temperature=0.3,
                stream=True
            )

            # LLM yanıtını biriktir
            llm_response_accumulated = ""
            async for chunk in response_generator:
                llm_response_accumulated += chunk

            # 2. JSON Ayrıştırma ve Yapısal Doğrulama (Pydantic)
            try:
                raw_text = llm_response_accumulated.strip()

                # JSONDecoder ile ilk geçerli JSON nesnesini bul (greedy regex yerine)
                # Bu yaklaşım: birden fazla JSON bloğu veya gömülü kod olsa bile doğru olanı seçer
                _decoder = json.JSONDecoder()
                json_match = None
                _idx = raw_text.find('{')
                while _idx != -1:
                    try:
                        json_match, _ = _decoder.raw_decode(raw_text, _idx)
                        break
                    except json.JSONDecodeError:
                        _idx = raw_text.find('{', _idx + 1)

                if json_match is None:
                    raise ValueError("Yanıtın içerisinde süslü parantezlerle ( { ... } ) çevrili bir JSON objesi bulunamadı.")

                # LLM bazen {"response": "..."} veya {"answer": "..."} formatı kullanıyor.
                # Ayrıca {"project": "...", "version": "..."} gibi veri objeleri de döndürebilir.
                # Bunları gracefully final_answer ToolCall'a normalize et.
                if "tool" not in json_match:
                    thought = json_match.pop("thought", "LLM doğrudan yanıt verdi.")
                    # Bilinen alias varsa değerini al
                    for alias in ("response", "answer", "result", "output", "content"):
                        if alias in json_match:
                            json_match = {
                                "thought": thought,
                                "tool": "final_answer",
                                "argument": str(json_match[alias]),
                            }
                            break
                    else:
                        # Alias yok → LLM veri objesi döndürdü (config değerleri vb.)
                        # Tüm key-value çiftlerini okunabilir özet olarak sun.
                        summary = "\n".join(f"- **{k}:** {v}" for k, v in json_match.items())
                        json_match = {
                            "thought": thought,
                            "tool": "final_answer",
                            "argument": summary,
                        }

                # Pydantic ile doğrulama (Eksik veya hatalı tip varsa ValidationError fırlatır)
                action_data = ToolCall.model_validate(json_match)
                
                tool_name = action_data.tool
                tool_arg = action_data.argument

                if tool_name == "final_answer":
                    # Boş argument güvenlik ağı: JS'de falsy olduğu için UI "yanıt alınamadı" gösterir.
                    if not str(tool_arg).strip():
                        tool_arg = "✓ İşlem tamamlandı."
                    await asyncio.to_thread(self.memory.add, "assistant", tool_arg)
                    yield str(tool_arg)
                    return

                # ── Tekrar tespiti: aynı araç art arda 2+ kez çağrılıyorsa
                # modeli zorla final_answer ver.
                if tool_name == _last_tool and _last_tool_result:
                    loop_correction = _FMT_SYS_WARN.format(
                        msg=(
                            f"'{tool_name}' aracı art arda çağrıldı — döngü tespit edildi.\n"
                            f"Bu araç zaten aşağıdaki sonucu döndürdü:\n===\n{_last_tool_result}\n===\n"
                            f"Artık MUTLAKA final_answer aracını kullanarak bu sonucu kullanıcıya ilet.\n"
                            f"Örnek: {{\"thought\": \"Sonuç mevcut.\", \"tool\": \"final_answer\", \"argument\": \"<özet>\"}}"
                        )
                    )
                    messages = messages + [
                        {"role": "assistant", "content": llm_response_accumulated},
                        {"role": "user", "content": loop_correction},
                    ]
                    continue

                # Düşünce sürecini UI'ya bildir (sentinel format: \x00THOUGHT:<thought>\x00)
                _thought_safe = str(action_data.thought)[:300].replace('\x00', ' ')
                yield f"\x00THOUGHT:{_thought_safe}\x00"
                # Araç çağrısını UI'ya bildir (sentinel format: \x00TOOL:<name>\x00)
                yield f"\x00TOOL:{tool_name}\x00"

                # Aracı asenkron çalıştır
                tool_result = await self._execute_tool(tool_name, tool_arg)

                if tool_result is None:
                    messages = messages + [
                         {"role": "assistant", "content": llm_response_accumulated},
                         {"role": "user", "content": _FMT_TOOL_ERR.format(
                             name=tool_name,
                             error="Bu araç yok veya geçersiz bir işlem seçildi."
                         )},
                    ]
                    continue

                # Son araç bilgisini güncelle (tekrar tespiti için)
                _last_tool = tool_name
                _last_tool_result = str(tool_result)[:2000]  # bellek tasarrufu

                messages = messages + [
                    {"role": "assistant", "content": llm_response_accumulated},
                    {"role": "user", "content": _FMT_TOOL_OK.format(name=tool_name, result=tool_result)},
                ]

            except ValidationError as ve:
                logger.warning("Pydantic doğrulama hatası:\n%s", ve)
                error_feedback = _FMT_SYS_ERR.format(
                    msg=(
                        f"Ürettiğin JSON yapısı beklentilere uymuyor.\n"
                        f"Eksik veya hatalı alanlar:\n{ve}\n\n"
                        f"Lütfen sadece şu formata uyan BİR TANE JSON döndür:\n"
                        f'{{"thought": "düşüncen", "tool": "araç_adı", "argument": "argüman"}}'
                    )
                )
                messages = messages + [
                    {"role": "assistant", "content": llm_response_accumulated},
                    {"role": "user", "content": error_feedback},
                ]
            except (ValueError, json.JSONDecodeError) as e:
                logger.warning("JSON ayrıştırma hatası: %s", e)
                error_feedback = _FMT_SYS_ERR.format(
                    msg=(
                        f"Yanıtın geçerli bir JSON formatında değil veya bozuk: {e}\n\n"
                        f"Lütfen yanıtını herhangi bir markdown (```json) bloğuna almadan, "
                        f"sadece düz geçerli bir JSON objesi olarak ver."
                    )
                )
                messages = messages + [
                    {"role": "assistant", "content": llm_response_accumulated},
                    {"role": "user", "content": error_feedback},
                ]
            except Exception as exc:
                 logger.exception("ReAct döngüsünde beklenmeyen hata: %s", exc)
                 yield "Üzgünüm, yanıt üretirken beklenmeyen bir hata oluştu."
                 return
            
        yield "Üzgünüm, bu istek için güvenilir bir sonuca ulaşamadım (Maksimum adım sayısına ulaşıldı)."

    # ─────────────────────────────────────────────
    #  ARAÇ HANDLER METODLARI
    # ─────────────────────────────────────────────

    async def _tool_list_dir(self, a: str) -> str:
        # Dizin listeleme disk I/O içerir — event loop'u bloke etmemek için thread'e itilir
        _, result = await asyncio.to_thread(self.code.list_directory, a or ".")
        return result

    async def _tool_read_file(self, a: str) -> str:
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

    async def _tool_write_file(self, a: str) -> str:
        parts = a.split("|||", 1)
        if len(parts) < 2: return "⚠ Hatalı format. Kullanım: path|||content"
        # Disk yazma event loop'u bloke eder — thread'e itilir
        _, result = await asyncio.to_thread(self.code.write_file, parts[0].strip(), parts[1])
        return result

    async def _tool_patch_file(self, a: str) -> str:
        parts = a.split("|||")
        if len(parts) < 3: return "⚠ Hatalı patch formatı. Kullanım: path|||eski_kod|||yeni_kod"
        # Disk okuma+yazma event loop'u bloke eder — thread'e itilir
        _, result = await asyncio.to_thread(self.code.patch_file, parts[0].strip(), parts[1], parts[2])
        return result

    async def _tool_execute_code(self, a: str) -> str:
        if not a: return "⚠ Çalıştırılacak kod belirtilmedi."
        # execute_code içinde time.sleep(0.5) döngüsü var — event loop'u dondurur.
        # asyncio.to_thread ile ayrı bir thread'de çalıştırılır; web sunucusu kilitlenmez.
        _, result = await asyncio.to_thread(self.code.execute_code, a)
        return result

    async def _tool_audit(self, a: str) -> str:
        # Tüm .py dosyalarını tararken ağır disk I/O yapılır — thread'e itilir
        return await asyncio.to_thread(self.code.audit_project, a or ".")

    async def _tool_health(self, _: str) -> str:
        return self.health.full_report()

    async def _tool_gpu_optimize(self, _: str) -> str:
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

    async def _tool_github_list_files(self, a: str) -> str:
        """GitHub deposundaki dizin içeriğini listele. Argüman: 'path[|||branch]'"""
        parts = a.split("|||")
        path = parts[0].strip() if parts else ""
        branch = parts[1].strip() if len(parts) > 1 else None
        _, result = self.github.list_files(path, branch)
        return result

    async def _tool_github_write(self, a: str) -> str:
        """GitHub'a dosya yaz/güncelle. Argüman: 'path|||content|||commit_message[|||branch]'"""
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

    async def _tool_github_create_branch(self, a: str) -> str:
        """GitHub'da yeni dal oluştur. Argüman: 'branch_adı[|||kaynak_branch]'"""
        if not a:
            return "⚠ Dal adı belirtilmedi."
        parts = a.split("|||")
        branch_name = parts[0].strip()
        from_branch = parts[1].strip() if len(parts) > 1 else None
        if not self.github.is_available():
            return "⚠ GitHub token ayarlanmamış."
        _, result = self.github.create_branch(branch_name, from_branch)
        return result

    async def _tool_github_create_pr(self, a: str) -> str:
        """GitHub Pull Request oluştur. Argüman: 'başlık|||açıklama|||head_branch[|||base_branch]'"""
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

    async def _tool_github_list_prs(self, a: str) -> str:
        """Pull Request listesi. Argüman: 'state[|||limit]' (state: open/closed/all)"""
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
        _, commit_log = await asyncio.to_thread(
            self.code.run_shell, f"git log {base}..HEAD --oneline 2>/dev/null || git log --oneline -10"
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
        _, result = self.docs.search(query, mode=mode)
        return result

    async def _tool_docs_add(self, a: str) -> str:
        parts = a.split("|", 1)
        if len(parts) < 2: return "⚠ Kullanım: başlık|url"
        _, result = await self.docs.add_document_from_url(parts[1].strip(), title=parts[0].strip())
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
        ok, result = await asyncio.to_thread(self.docs.add_document_from_file, path, title)
        return result

    async def _tool_docs_list(self, _: str) -> str:
        return self.docs.list_documents()

    async def _tool_docs_delete(self, a: str) -> str:
        return self.docs.delete_document(a)

    # ── Alt Görev / Paralel Araçlar (Claude Code Agent tool eşdeğeri) ─────

    async def _tool_subtask(self, task: str) -> str:
        """
        Bir alt görevi bağımsız mini ReAct döngüsünde çalıştırır.
        Claude Code'daki Agent tool eşdeğeri — max 5 adım.
        Format: 'görev açıklaması'
        """
        if not task.strip():
            return "⚠ Alt görev açıklaması belirtilmedi."

        MAX_STEPS = 5
        messages: list = [{"role": "user", "content": task}]
        mini_system = (
            "Sen bağımsız bir alt ajansın. Verilen görevi tamamla.\n"
            "Her adımda şu JSON formatında yanıt ver:\n"
            '{"thought": "analiz", "tool": "araç_adı", "argument": "argüman"}\n'
            "Görev tamamlandığında tool='final_answer' kullan.\n"
            "Maksimum 5 adımda tamamla. Sonucu Türkçe olarak özetle."
        )

        for _ in range(MAX_STEPS):
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
                    break

                _dec = json.JSONDecoder()
                idx = raw.find("{")
                if idx == -1:
                    break
                action, _ = _dec.raw_decode(raw, idx)

                tool_name = str(action.get("tool", "")).strip()
                tool_arg  = str(action.get("argument", "")).strip()

                if tool_name == "final_answer":
                    return f"[Alt Görev Tamamlandı]\n{tool_arg}"

                if not tool_name:
                    break

                tool_result = await self._execute_tool(tool_name, tool_arg)
                if tool_result is None:
                    messages += [
                        {"role": "assistant", "content": raw},
                        {"role": "user",      "content": _FMT_TOOL_ERR.format(name=tool_name, error="Bu araç mevcut değil.")},
                    ]
                    continue

                messages += [
                    {"role": "assistant", "content": raw},
                    {"role": "user",      "content": _FMT_TOOL_STEP.format(name=tool_name, result=str(tool_result)[:1500])},
                ]
            except Exception as exc:
                logger.warning("Subtask adım hatası: %s", exc)
                break

        return "[Alt Görev] Maksimum adım sayısına ulaşıldı veya görev tamamlanamadı."

    # Yalnızca okuma/sorgulama araçları paralel çalışabilir.
    _PARALLEL_SAFE = frozenset({
        "list_dir", "ls", "read_file", "glob_search", "grep_files", "grep",
        "github_info", "github_read", "github_list_files", "github_commits",
        "github_search_code", "health", "audit", "todo_read", "get_config",
        "web_search", "pypi", "npm", "docs_search", "docs_list",
        "search_stackoverflow", "fetch_url",
    })

    async def _tool_parallel(self, a: str) -> str:
        """
        Birden fazla okuma/sorgulama aracını eşzamanlı çalıştırır.
        Claude Code'daki paralel araç çağrısı eşdeğeri.
        Format: 'araç1:argüman1|||araç2:argüman2|||...'
        Yalnızca güvenli (okuma) araçlar desteklenir.
        """
        if not a.strip():
            return "⚠ Araç listesi belirtilmedi."

        parts = [p.strip() for p in a.split("|||") if p.strip()]
        if not parts:
            return "⚠ Geçerli araç formatı bulunamadı."

        tasks: list[tuple[str, str]] = []
        for part in parts:
            tool_name, _, tool_arg = part.partition(":")
            tool_name = tool_name.strip()
            if not tool_name:
                continue
            if tool_name not in self._PARALLEL_SAFE:
                return (
                    f"⚠ '{tool_name}' paralel çalıştırma için güvensiz. "
                    f"İzinli araçlar: {', '.join(sorted(self._PARALLEL_SAFE))}"
                )
            tasks.append((tool_name, tool_arg.strip()))

        if not tasks:
            return "⚠ Çalıştırılacak geçerli araç bulunamadı."

        results = await asyncio.gather(
            *[self._execute_tool(name, arg) for name, arg in tasks],
            return_exceptions=True,
        )

        lines = [f"[Paralel Çalıştırma — {len(tasks)} araç]", ""]
        for (name, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                lines.append(f"❌ **{name}**: {result}")
            else:
                snippet = str(result)[:600]
                suffix  = "..." if result and len(str(result)) > 600 else ""
                lines.append(f"✓ **{name}**:\n{snippet}{suffix}")
            lines.append("")

        return "\n".join(lines)

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
            "## 1. AI_PROVIDER  [config.py satır 225]",
            f"  Değer    : {self.cfg.AI_PROVIDER.upper()}",
            "  Seçenekler: 'ollama' (yerel) | 'gemini' (bulut)",
            "  Değiştirmek için: .env → AI_PROVIDER=gemini",
            "",
            "## 2. USE_GPU / GPU_MEMORY_FRACTION  [config.py satır 243, 257]",
            f"  USE_GPU              : {self.cfg.USE_GPU}",
            f"  GPU                  : {gpu_line}",
            f"  GPU_MEMORY_FRACTION  : {getattr(self.cfg, 'GPU_MEMORY_FRACTION', 0.8)} "
            "(VRAM'in bu oranı ayrılır; geçerli aralık 0.1–1.0)",
            "",
            "## 3. OLLAMA_URL / CODING_MODEL / TEXT_MODEL  [config.py satır 230–233]",
            f"  OLLAMA_URL   : {self.cfg.OLLAMA_URL}",
            f"  CODING_MODEL : {self.cfg.CODING_MODEL}",
            f"  TEXT_MODEL   : {self.cfg.TEXT_MODEL}",
            f"  OLLAMA_TIMEOUT: {getattr(self.cfg, 'OLLAMA_TIMEOUT', 30)}s",
            "",
            "## 4. MAX_REACT_STEPS / REACT_TIMEOUT  [config.py satır 273–274]",
            f"  MAX_REACT_STEPS: {self.cfg.MAX_REACT_STEPS}",
            f"  REACT_TIMEOUT  : {getattr(self.cfg, 'REACT_TIMEOUT', 60)}s",
            "  Not: Karmaşık görevlerde bu değerlerin artırılması gerekebilir.",
            "",
            "## 5. RAG_TOP_K / RAG_CHUNK_SIZE / RAG_CHUNK_OVERLAP  [config.py satır 290–292]",
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

    async def _execute_tool(self, tool_name: str, tool_arg: str) -> Optional[str]:
        """Dispatch tablosu aracılığıyla araç handler'ını çağırır."""
        tool_arg = str(tool_arg).strip()
        dispatch = {
            "list_dir":               self._tool_list_dir,
            "read_file":              self._tool_read_file,
            "write_file":             self._tool_write_file,
            "patch_file":             self._tool_patch_file,
            "execute_code":           self._tool_execute_code,
            "audit":                  self._tool_audit,
            "health":                 self._tool_health,
            "gpu_optimize":           self._tool_gpu_optimize,
            "github_commits":         self._tool_github_commits,
            "github_info":            self._tool_github_info,
            "github_read":            self._tool_github_read,
            "github_list_files":      self._tool_github_list_files,
            "github_write":           self._tool_github_write,
            "github_create_branch":   self._tool_github_create_branch,
            "github_create_pr":       self._tool_github_create_pr,
            "github_search_code":     self._tool_github_search_code,
            # PR Yönetimi
            "github_list_prs":        self._tool_github_list_prs,
            "github_get_pr":          self._tool_github_get_pr,
            "github_comment_pr":      self._tool_github_comment_pr,
            "github_close_pr":        self._tool_github_close_pr,
            "github_pr_files":        self._tool_github_pr_files,
            "github_smart_pr":        self._tool_github_smart_pr,
            "web_search":             self._tool_web_search,
            "fetch_url":              self._tool_fetch_url,
            "search_docs":            self._tool_search_docs,
            "search_stackoverflow":   self._tool_search_stackoverflow,
            "pypi":                   self._tool_pypi,
            "pypi_compare":           self._tool_pypi_compare,
            "npm":                    self._tool_npm,
            "gh_releases":            self._tool_gh_releases,
            "gh_latest":              self._tool_gh_latest,
            "docs_search":            self._tool_docs_search,
            "docs_add":               self._tool_docs_add,
            "docs_add_file":          self._tool_docs_add_file,
            "docs_list":              self._tool_docs_list,
            "docs_delete":            self._tool_docs_delete,
            # Kabuk & Arama (Claude Code uyumlu)
            "run_shell":              self._tool_run_shell,
            "bash":                   self._tool_run_shell,     # alias
            "shell":                  self._tool_run_shell,     # alias
            "glob_search":            self._tool_glob_search,
            "grep_files":             self._tool_grep_files,
            "grep":                   self._tool_grep_files,    # alias
            "ls":                     self._tool_list_dir,      # alias
            # Görev Takibi
            "todo_write":             self._tool_todo_write,
            "todo_read":              self._tool_todo_read,
            "todo_update":            self._tool_todo_update,
            "get_config":             self._tool_get_config,
            "print_config_summary":   self._tool_get_config,   # alias — gereksiz LLM turu önleme
            # Alt Görev & Paralel (Claude Code Agent tool eşdeğeri)
            "subtask":                self._tool_subtask,
            "agent":                  self._tool_subtask,      # alias — Claude Code uyumu
            "parallel":               self._tool_parallel,
        }
        handler = dispatch.get(tool_name)
        return await handler(tool_arg) if handler else None

    # ─────────────────────────────────────────────
    #  BAĞLAM OLUŞTURMA
    # ─────────────────────────────────────────────

    def _build_context(self) -> str:
        """
        Tüm alt sistem durumlarını özetleyen bağlam dizesi.
        Her LLM turunda system_prompt'a eklenir; model bu değerleri
        ASLA tahmin etmemelidir — gerçek runtime değerler burada verilir.

        Ayrıca SIDAR.md / CLAUDE.md dosyaları varsa proje özel talimatları
        hiyerarşik öncelik ile bağlama eklenir.
        """
        lines = []

        # ── Proje Ayarları (gerçek değerler — hallucination önleme) ──
        lines.append("[Proje Ayarları — GERÇEK RUNTIME DEĞERLERİ]")
        lines.append(f"  Proje        : {self.cfg.PROJECT_NAME} v{self.cfg.VERSION}")
        lines.append(f"  Dizin        : {self.cfg.BASE_DIR}")
        lines.append(f"  AI Sağlayıcı : {self.cfg.AI_PROVIDER.upper()}")
        if self.cfg.AI_PROVIDER == "ollama":
            lines.append(f"  Coding Modeli: {self.cfg.CODING_MODEL}")
            lines.append(f"  Text Modeli  : {self.cfg.TEXT_MODEL}")
            lines.append(f"  Ollama URL   : {self.cfg.OLLAMA_URL}")
        else:
            lines.append(f"  Gemini Modeli: {self.cfg.GEMINI_MODEL}")
        lines.append(f"  Erişim Seviye: {self.cfg.ACCESS_LEVEL.upper()}")
        gpu_str = f"{self.cfg.GPU_INFO} (CUDA {self.cfg.CUDA_VERSION})" if self.cfg.USE_GPU else f"Yok ({self.cfg.GPU_INFO})"
        lines.append(f"  GPU          : {gpu_str}")

        # ── Araç Durumu ───────────────────────────────────────────────
        lines.append("")
        lines.append("[Araç Durumu]")
        lines.append(f"  Güvenlik   : {self.security.level_name.upper()}")
        gh_status = f"Bağlı — {self.cfg.GITHUB_REPO}" if self.github.is_available() else "Bağlı değil"
        lines.append(f"  GitHub     : {gh_status}")
        lines.append(f"  WebSearch  : {'Aktif' if self.web.is_available() else 'Kurulu değil'}")
        lines.append(f"  RAG        : {self.docs.status()}")

        m = self.code.get_metrics()
        lines.append(f"  Okunan     : {m['files_read']} dosya | Yazılan: {m['files_written']}")

        last_file = self.memory.get_last_file()
        if last_file:
            lines.append(f"  Son dosya  : {last_file}")

        # ── Görev Listesi (aktif görev varsa ekle) ──────────────────────
        if len(self.todo) > 0:
            lines.append("")
            lines.append("[Aktif Görev Listesi]")
            lines.append(self.todo.list_tasks())

        # ── SIDAR.md / CLAUDE.md (Claude Code uyumlu) ──────────────────
        instruction_block = self._load_instruction_files()
        if instruction_block:
            lines.append("")
            lines.append(instruction_block)

        return "\n".join(lines)

    def _load_instruction_files(self) -> str:
        """
        Proje genelindeki SIDAR.md ve CLAUDE.md dosyalarını hiyerarşik şekilde yükle.
        - Daha üst dizin dosyaları önce gelir.
        - Alt dizin dosyaları daha sonra gelerek öncelik alır.
        - Dosya değişikliği (mtime) algılandığında otomatik olarak yeniden yükler.
          Bu davranış Claude Code'un CLAUDE.md'yi her konuşmada taze okumasına eşdeğerdir.
        """
        root = Path(self.cfg.BASE_DIR)
        instruction_names = ("SIDAR.md", "CLAUDE.md")
        found_files = []

        for name in instruction_names:
            found_files.extend(root.rglob(name))

        # Aynı dosya iki kez gelmesin, deterministik sırada olsun
        unique_files = sorted({p.resolve() for p in found_files if p.is_file()})

        # Mevcut mtime'ları topla
        current_mtimes: Dict[str, float] = {}
        for path in unique_files:
            try:
                current_mtimes[str(path)] = path.stat().st_mtime
            except Exception:
                pass

        # Cache geçerli mi? Hem içerik hem mtime eşleşmeli
        if self._instructions_cache is not None and current_mtimes == self._instructions_mtimes:
            return self._instructions_cache

        # Değişiklik var veya ilk yükleme → yeniden oku
        self._instructions_mtimes = current_mtimes

        if not unique_files:
            self._instructions_cache = ""
            return ""

        blocks = ["[Proje Talimat Dosyaları — SIDAR.md / CLAUDE.md]"]
        for path in unique_files:
            try:
                rel = path.relative_to(root)
                content = path.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                continue
            if not content:
                continue
            blocks.append(f"\n## {rel}")
            blocks.append(content)

        self._instructions_cache = "\n".join(blocks) if len(blocks) > 1 else ""
        return self._instructions_cache

    # ─────────────────────────────────────────────
    #  BELLEK ÖZETLEME VE VEKTÖR ARŞİVLEME (ASYNC)
    # ─────────────────────────────────────────────

    async def _summarize_memory(self) -> None:
        """
        Konuşma geçmişini LLM ile özetler ve belleği sıkıştırır.
        AYRICA: Eski konuşmaları 'Sonsuz Hafıza' için Vektör DB'ye (ChromaDB) gömer.
        """
        history = self.memory.get_history()
        if len(history) < 4:
            return

        # 1. VEKTÖR BELLEK (SONSUZ HAFIZA) KAYDI
        # Kısa özetlemeye geçmeden önce, tüm detayları RAG sistemine kaydediyoruz
        full_turns_text = "\n\n".join(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t.get('timestamp', time.time())))}] {t['role'].upper()}:\n{t['content']}"
            for t in history
        )
        
        try:
            await asyncio.to_thread(
                self.docs.add_document,
                title=f"Sohbet Geçmişi Arşivi ({time.strftime('%Y-%m-%d %H:%M')})",
                content=full_turns_text,
                source="memory_archive",
                tags=["memory", "archive", "conversation"],
            )
            logger.info("Eski konuşmalar RAG (Vektör) belleğine arşivlendi.")
        except Exception as exc:
            logger.warning("Vektör belleğe kayıt başarısız: %s", exc)

        # 2. KISA SÜRELİ BELLEK ÖZETLEMESİ
        # LLM token tasarrufu için sadece ilk 400 karakterlik kısımları gönderiyoruz
        turns_text_short = "\n".join(
            f"{t['role'].upper()}: {t['content'][:400]}"
            for t in history
        )
        summarize_prompt = (
            "Aşağıdaki konuşmayı kısa ve bilgilendirici şekilde özetle. "
            "Teknik detayları, dosya adlarını ve kod kararlarını koru:\n\n"
            + turns_text_short
        )
        try:
            summary = await self.llm.chat(
                messages=[{"role": "user", "content": summarize_prompt}],
                model=getattr(self.cfg, "TEXT_MODEL", self.cfg.CODING_MODEL),
                temperature=0.1,
                stream=False,
                json_mode=False,
            )
            self.memory.apply_summary(str(summary))
            logger.info("Bellek özetlendi (%d → 2 mesaj).", len(history))
        except Exception as exc:
            logger.warning("Bellek özetleme başarısız: %s", exc)

    # ─────────────────────────────────────────────
    #  YARDIMCI METODLAR
    # ─────────────────────────────────────────────

    def clear_memory(self) -> str:
        self.memory.clear()
        return "Konuşma belleği temizlendi (dosya silindi). ✓"

    def status(self) -> str:
        lines = [
            f"[SidarAgent v{self.VERSION}]",
            f"  Sağlayıcı    : {self.cfg.AI_PROVIDER}",
            f"  Model        : {self.cfg.CODING_MODEL}",
            f"  Erişim       : {self.cfg.ACCESS_LEVEL}",
            f"  Bellek       : {len(self.memory)} mesaj (Kalıcı)",
            f"  {self.github.status()}",
            f"  {self.web.status()}",
            f"  {self.pkg.status()}",
            f"  {self.docs.status()}",
            self.health.full_report(),
        ]
        return "\n".join(lines)  