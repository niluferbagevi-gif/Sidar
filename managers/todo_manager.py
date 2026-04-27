"""
Sidar Project - Görev Takip Yöneticisi
Claude Code'daki TodoWrite/TodoRead araçlarına eşdeğer görev listesi yönetimi.
"""

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from config import Config

logger = logging.getLogger(__name__)

# Görev durumu sabitleri
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"

VALID_STATUSES = {STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_COMPLETED}

STATUS_ICONS = {
    STATUS_PENDING: "⬜",
    STATUS_IN_PROGRESS: "🔄",
    STATUS_COMPLETED: "✅",
}


@dataclass
class Task:
    """Tek bir görev kaydı."""

    id: int
    content: str
    status: str = STATUS_PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def update_status(self, new_status: str) -> None:
        self.status = new_status
        self.updated_at = time.time()


class TodoManager:
    """
    Görev listesi yöneticisi.
    Claude Code'daki TodoWrite/TodoRead araçlarına eşdeğer.

    Thread-safe: threading.RLock ile korunur.

    Özellikler:
    - Görev ekleme, güncelleme, silme
    - Durum takibi: pending / in_progress / completed
    - Okunabilir liste çıktısı
    - Aynı anda yalnızca bir "in_progress" göreve uyarı
    """

    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or Config()
        base_dir = Path(getattr(self.cfg, "BASE_DIR", ".")).resolve()
        self.base_dir = base_dir
        self.todo_path = base_dir / "todos.json"
        self._tasks: list[Task] = []
        self._next_id: int = 1
        self._lock = threading.RLock()
        self._load()
        logger.info("TodoManager başlatıldı. Yol=%s", self.todo_path)

    def _load(self) -> None:
        """todo_path üzerinden görevleri UTF-8 ile yükle."""
        with self._lock:
            try:
                if not self.todo_path.exists():
                    self.todo_path.parent.mkdir(parents=True, exist_ok=True)
                    return
                with open(self.todo_path, encoding="utf-8") as f:
                    raw = json.load(f)
                if not isinstance(raw, list):
                    return
                tasks: list[Task] = []
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    status = item.get("status", STATUS_PENDING)
                    if status not in VALID_STATUSES:
                        status = STATUS_PENDING
                    tasks.append(
                        Task(
                            id=int(item.get("id", len(tasks) + 1)),
                            content=str(item.get("content", "")).strip(),
                            status=status,
                            created_at=float(item.get("created_at", time.time())),
                            updated_at=float(item.get("updated_at", time.time())),
                        )
                    )
                self._tasks = [t for t in tasks if t.content]
                self._next_id = max((t.id for t in self._tasks), default=0) + 1
            except Exception as exc:
                logger.warning("TodoManager yükleme hatası: %s", exc)

    def _save(self) -> None:
        """Görevleri UTF-8/JSON olarak kalıcı kaydet."""
        with self._lock:
            self.todo_path.parent.mkdir(parents=True, exist_ok=True)
            payload = [asdict(t) for t in self._tasks]
            with open(self.todo_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    def _ensure_single_in_progress(self, preferred_task_id: int) -> int:
        """Tek bir in_progress görev kalacak şekilde diğerlerini pending'e çeker."""
        demoted = 0
        for task in self._tasks:
            if task.id == preferred_task_id:
                continue
            if task.status == STATUS_IN_PROGRESS:
                task.update_status(STATUS_PENDING)
                demoted += 1
        return demoted

    def _normalize_limit(self, limit: int, default: int = 50) -> int:
        """Limit değerini güvenli şekilde 1..200 aralığına normalize et."""
        try:
            normalized = int(limit)
        except (TypeError, ValueError):
            normalized = default
        return max(1, min(normalized, 200))

    # ─────────────────────────────────────────────
    #  GÖREV EKLEME
    # ─────────────────────────────────────────────

    def add_task(self, content: str, status: str = STATUS_PENDING) -> str:
        """
        Yeni görev ekle.

        Args:
            content: Görev açıklaması
            status: Başlangıç durumu (pending/in_progress/completed)

        Returns:
            Sonuç mesajı
        """
        content = content.strip()
        if not content:
            return "⚠ Görev açıklaması boş olamaz."

        if status not in VALID_STATUSES:
            return f"⚠ Geçersiz durum: '{status}'. Geçerli değerler: {', '.join(VALID_STATUSES)}"

        demoted = 0
        with self._lock:
            task = Task(id=self._next_id, content=content, status=status)
            self._tasks.append(task)
            self._next_id += 1
            task_id = task.id
            if status == STATUS_IN_PROGRESS:
                demoted = self._ensure_single_in_progress(task_id)
            self._save()

        logger.debug("Görev eklendi: #%d — %s", task_id, content[:50])
        if demoted:
            return (
                f"✅ Görev eklendi (#{task_id}): {content}" + "\n"
                f"ℹ Aynı anda tek aktif görev kuralı nedeniyle {demoted} görev pending'e çekildi."
            )
        return f"✅ Görev eklendi (#{task_id}): {content}"

    def set_tasks(self, tasks_data: list) -> str:
        """
        Görev listesini toplu olarak ayarla (Claude Code TodoWrite gibi).

        Args:
            tasks_data: [{"content": "...", "status": "..."}, ...] listesi

        Returns:
            Sonuç mesajı
        """
        if not isinstance(tasks_data, list):
            return "⚠ Görev verisi liste formatında olmalı."

        with self._lock:
            self._tasks.clear()
            self._next_id = 1
            added = 0
            latest_in_progress_id: int | None = None
            for item in tasks_data:
                if not isinstance(item, dict):
                    continue
                content = str(item.get("content", "")).strip()
                status = item.get("status", STATUS_PENDING)
                if content and status in VALID_STATUSES:
                    task = Task(id=self._next_id, content=content, status=status)
                    self._tasks.append(task)
                    self._next_id += 1
                    added += 1
                    if status == STATUS_IN_PROGRESS:
                        latest_in_progress_id = task.id

            demoted = 0
            if latest_in_progress_id is not None:
                demoted = self._ensure_single_in_progress(latest_in_progress_id)
            self._save()

        if demoted:
            return (
                f"✅ Görev listesi güncellendi: {added} görev ayarlandı." + "\n"
                f"ℹ Aynı anda tek aktif görev kuralı nedeniyle {demoted} görev pending'e çekildi."
            )
        return f"✅ Görev listesi güncellendi: {added} görev ayarlandı."

    # ─────────────────────────────────────────────
    #  DURUM GÜNCELLEME
    # ─────────────────────────────────────────────

    def update_task(self, task_id: int, new_status: str) -> str:
        """
        Görev durumunu güncelle.

        Args:
            task_id: Görev numarası
            new_status: Yeni durum (pending/in_progress/completed)

        Returns:
            Sonuç mesajı
        """
        if new_status not in VALID_STATUSES:
            return f"⚠ Geçersiz durum: '{new_status}'. Geçerli: {', '.join(VALID_STATUSES)}"

        with self._lock:
            for task in self._tasks:
                if task.id == task_id:
                    old_status = task.status
                    task.update_status(new_status)
                    demoted = 0
                    if new_status == STATUS_IN_PROGRESS:
                        demoted = self._ensure_single_in_progress(task_id)
                    self._save()
                    logger.debug("Görev #%d: %s → %s", task_id, old_status, new_status)
                    msg = (
                        f"{STATUS_ICONS[new_status]} Görev #{task_id} güncellendi: "
                        f"{old_status} → {new_status}" + "\n"
                        f"   {task.content}"
                    )
                    if demoted:
                        msg += (
                            "\n"
                            "ℹ Aynı anda tek aktif görev kuralı nedeniyle "
                            f"{demoted} görev pending'e çekildi."
                        )
                    return msg

        return f"⚠ Görev bulunamadı: #{task_id}"

    def mark_in_progress(self, task_id: int) -> str:
        """Görevi 'in_progress' olarak işaretle."""
        return self.update_task(task_id, STATUS_IN_PROGRESS)

    def mark_completed(self, task_id: int) -> str:
        """Görevi 'completed' olarak işaretle."""
        return self.update_task(task_id, STATUS_COMPLETED)

    # ─────────────────────────────────────────────
    #  GÖREV LİSTESİ
    # ─────────────────────────────────────────────

    def list_tasks(self, filter_status: str | None = None, limit: int = 50) -> str:
        """
        Görev listesini okunabilir formatta döndür.

        Args:
            filter_status: Belirli duruma filtrele (None = hepsi)

        Returns:
            Biçimlendirilmiş görev listesi
        """
        with self._lock:
            tasks = list(self._tasks)

        if not tasks:
            return "📋 Görev listesi boş."

        if filter_status and filter_status in VALID_STATUSES:
            tasks = [t for t in tasks if t.status == filter_status]
            if not tasks:
                return f"📋 '{filter_status}' durumunda görev yok."

        limit = self._normalize_limit(limit)
        tasks = tasks[:limit]

        # Duruma göre grupla
        pending = [t for t in tasks if t.status == STATUS_PENDING]
        in_progress = [t for t in tasks if t.status == STATUS_IN_PROGRESS]
        completed = [t for t in tasks if t.status == STATUS_COMPLETED]

        lines = ["📋 Görev Listesi"]
        lines.append(
            f"   Toplam: {len(tasks)} | 🔄 Aktif: {len(in_progress)} | ⬜ Bekleyen: {len(pending)} | ✅ Tamamlanan: {len(completed)}"
        )
        lines.append("")

        if in_progress:
            lines.append("🔄 Devam Eden:")
            for t in in_progress:
                lines.append(f"   #{t.id}  {t.content}")
            lines.append("")

        if pending:
            lines.append("⬜ Bekleyen:")
            for t in pending:
                lines.append(f"   #{t.id}  {t.content}")
            lines.append("")

        if completed:
            lines.append("✅ Tamamlanan:")
            for t in completed:
                lines.append(f"   #{t.id}  {t.content}")

        return "\n".join(lines)

    # ─────────────────────────────────────────────
    #  TEMİZLİK
    # ─────────────────────────────────────────────

    def clear_completed(self) -> str:
        """Tamamlanan görevleri sil."""
        with self._lock:
            before = len(self._tasks)
            self._tasks = [t for t in self._tasks if t.status != STATUS_COMPLETED]
            removed = before - len(self._tasks)
            if removed:
                self._save()
        return f"🗑 {removed} tamamlanmış görev silindi."

    def clear_all(self) -> str:
        """Tüm görevleri sil."""
        with self._lock:
            count = len(self._tasks)
            self._tasks.clear()
            self._next_id = 1
            self._save()
        return f"🗑 Tüm görevler temizlendi ({count} görev silindi)."

    # ─────────────────────────────────────────────
    #  YARDIMCILAR
    # ─────────────────────────────────────────────

    def get_tasks(self, status: str | None = None, limit: int = 50) -> list:
        """
        Görev listesini dict listesi olarak döndürür.
        REST endpoint ve UI entegrasyonu için kullanılır.
        """
        with self._lock:
            tasks = list(self._tasks)

        if status and status in VALID_STATUSES:
            tasks = [t for t in tasks if t.status == status]

        limit = self._normalize_limit(limit)
        tasks = tasks[:limit]

        return [
            {
                "id": t.id,
                "content": t.content,
                "status": t.status,
                "created_at": int(t.created_at),
                "updated_at": int(t.updated_at),
            }
            for t in tasks
        ]

    def get_active_count(self) -> int:
        """Aktif (in_progress + pending) görev sayısını döndürür."""
        with self._lock:
            return sum(1 for t in self._tasks if t.status != STATUS_COMPLETED)

    def __len__(self) -> int:
        with self._lock:
            return len(self._tasks)

    def __repr__(self) -> str:
        return f"<TodoManager tasks={len(self)}>"

    def scan_project_todos(
        self, directory: str | None = None, extensions: list[str] | None = None
    ) -> str:
        """Belirtilen dizindeki (veya projenin kökündeki) kod dosyalarını tarayarak TODO ve FIXME etiketlerini bulur."""
        import os

        try:
            base_scan_dir = Path(directory).resolve() if directory else self.base_dir
        except Exception:
            return "⚠ Geçersiz dizin parametresi."

        if not str(base_scan_dir).startswith(str(self.base_dir)):
            return "⚠ Güvenlik ihlali: Sadece proje dizini taranabilir."

        if not extensions:
            extensions = [
                ".py",
                ".js",
                ".ts",
                ".html",
                ".css",
                ".md",
                ".sh",
                ".yaml",
                ".yml",
                ".json",
                ".c",
                ".cpp",
                ".java",
                ".go",
            ]

        # Kullanıcı girdisini normalize et
        norm_exts = set()
        for ext in extensions:
            e = str(ext).strip().lower()
            if not e:
                continue
            if not e.startswith("."):
                e = f".{e}"
            norm_exts.add(e)

        if not norm_exts:
            return "⚠ Taranacak geçerli dosya uzantısı bulunamadı."

        found_items = []
        # Tarama esnasında zaman kaybetmemek ve çöp veri almamak için gereksiz klasörleri atla
        ignore_dirs = {
            ".git",
            "node_modules",
            "venv",
            "__pycache__",
            "build",
            "dist",
            ".idea",
            ".vscode",
            "logs",
            "sessions",
            "sidar_knowledge_base",
        }

        try:
            for root, dirs, files in os.walk(base_scan_dir):
                # Görmezden gelinecek klasörleri os.walk listesinden çıkar
                dirs[:] = [d for d in dirs if d not in ignore_dirs]

                for file in files:
                    file_path = Path(root) / file
                    if file_path.suffix.lower() not in norm_exts:
                        continue

                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        lines = content.splitlines()
                        for i, line in enumerate(lines, 1):
                            # TODO veya FIXME kelimesini içeren satırları yakala
                            if (
                                "TODO:" in line
                                or "FIXME:" in line
                                or "TODO " in line
                                or "FIXME " in line
                            ):
                                rel_path = file_path.relative_to(self.base_dir)
                                found_items.append(f"[{rel_path} : Satır {i}] {line.strip()}")
                    except Exception:
                        pass

            if not found_items:
                return (
                    "Harika! Projedeki dosyalarda herhangi bir TODO veya FIXME etiketi bulunamadı."
                )

            result = [f"--- PROJEDEKİ TODO VE FIXME LİSTESİ ({len(found_items)} adet) ---"]
            result.extend(found_items)
            return "\n".join(result)

        except Exception as exc:
            logger.error("Proje TODO tarama hatası: %s", exc)
            return f"⚠ Tarama sırasında hata oluştu: {exc}"
