"""
Sidar Project - Görev Takip Yöneticisi
Claude Code'daki TodoWrite/TodoRead araçlarına eşdeğer görev listesi yönetimi.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

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

    def __init__(self) -> None:
        self._tasks: List[Task] = []
        self._next_id: int = 1
        self._lock = threading.RLock()
        logger.info("TodoManager başlatıldı.")

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

        with self._lock:
            task = Task(id=self._next_id, content=content, status=status)
            self._tasks.append(task)
            self._next_id += 1
            task_id = task.id

        logger.debug("Görev eklendi: #%d — %s", task_id, content[:50])
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
                    logger.debug("Görev #%d: %s → %s", task_id, old_status, new_status)
                    return (
                        f"{STATUS_ICONS[new_status]} Görev #{task_id} güncellendi: "
                        f"{old_status} → {new_status}\n"
                        f"   {task.content}"
                    )

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

    def list_tasks(self, filter_status: Optional[str] = None) -> str:
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

        # Duruma göre grupla
        pending = [t for t in tasks if t.status == STATUS_PENDING]
        in_progress = [t for t in tasks if t.status == STATUS_IN_PROGRESS]
        completed = [t for t in tasks if t.status == STATUS_COMPLETED]

        lines = ["📋 Görev Listesi"]
        lines.append(f"   Toplam: {len(tasks)} | 🔄 Aktif: {len(in_progress)} | ⬜ Bekleyen: {len(pending)} | ✅ Tamamlanan: {len(completed)}")
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
        return f"🗑 {removed} tamamlanmış görev silindi."

    def clear_all(self) -> str:
        """Tüm görevleri sil."""
        with self._lock:
            count = len(self._tasks)
            self._tasks.clear()
            self._next_id = 1
        return f"🗑 Tüm görevler temizlendi ({count} görev silindi)."

    # ─────────────────────────────────────────────
    #  YARDIMCILAR
    # ─────────────────────────────────────────────

    def get_active_count(self) -> int:
        """Aktif (in_progress + pending) görev sayısını döndürür."""
        with self._lock:
            return sum(1 for t in self._tasks if t.status != STATUS_COMPLETED)

    def __len__(self) -> int:
        with self._lock:
            return len(self._tasks)

    def __repr__(self) -> str:
        return f"<TodoManager tasks={len(self)}>"