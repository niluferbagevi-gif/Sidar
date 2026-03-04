"""
Sidar Project - Konuşma Belleği (Kalıcı)
Çoklu tur konuşma geçmişini ve farklı sohbet oturumlarını yönetir, diske kaydeder.
"""

import json
import time
import uuid
import atexit
import threading
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class ConversationMemory:
    """
    Thread-safe ve kalıcı (persistent) çoklu konuşma (session) belleği yöneticisi.
    Verileri sessions dizininde ayrı JSON dosyalarında saklar.
    MEMORY_ENCRYPTION_KEY ayarlandığında oturum dosyaları Fernet (AES-128-CBC) ile şifrelenir.
    """

    def __init__(
        self,
        file_path: Path,
        max_turns: int = 20,
        encryption_key: str = "",
        autosave_interval_sec: float = 0.35,
        broken_retention_days: int = 14,
        broken_max_files: int = 50,
    ) -> None:
        # Eski memory.json yolunu alıp yerine 'sessions' klasörü oluşturuyoruz
        self.sessions_dir = file_path.parent / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.max_turns = max_turns
        self._lock = threading.RLock()

        # Opsiyonel Fernet şifreleme
        self._fernet = self._init_fernet(encryption_key)

        # Aktif oturum (seçili sohbet) bilgileri
        self.active_session_id: Optional[str] = None
        self.active_title: str = "Yeni Sohbet"
        self._turns: List[Dict] = []
        self._last_file: Optional[str] = None
        self._autosave_interval_sec = max(0.0, autosave_interval_sec)
        self._broken_retention_days = max(1, broken_retention_days)
        self._broken_max_files = max(1, broken_max_files)
        self._pending_save = False
        self._last_save_monotonic = 0.0

        # Kapanışta bekleyen yazımı kaçırmamak için güvenli flush.
        atexit.register(self.flush)

        # Başlangıçta oturumları yükle veya yeni oluştur
        self._init_sessions()

    @staticmethod
    def _init_fernet(key: str):
        """Fernet şifreleme nesnesini oluşturur; key boşsa None döner."""
        if not key:
            return None
        try:
            from cryptography.fernet import Fernet
            token = key.encode() if isinstance(key, str) else key
            fernet = Fernet(token)
            logger.info("✅ Bellek şifrelemesi etkin (Fernet/AES-128-CBC).")
            return fernet
        except Exception as exc:
            logger.warning(
                "⚠️ Bellek şifreleme başlatılamadı: %s — Düz metin kullanılacak.", exc
            )
            return None

    def _read_session_file(self, file_path: Path) -> dict:
        """Oturum dosyasını okur; şifreli ise çözer, düz metin ise doğrudan parse eder."""
        raw = file_path.read_bytes()
        if self._fernet:
            try:
                content = self._fernet.decrypt(raw).decode("utf-8")
            except Exception:
                # Eski şifrelenmemiş (geçiş dönemi) dosya — düz metin dene
                logger.warning(
                    "⚠️ Oturum dosyası şifre çözümlenemedi, düz metin deneniyor: %s",
                    file_path.name,
                )
                content = raw.decode("utf-8")
        else:
            content = raw.decode("utf-8")
        return json.loads(content)

    def _write_session_file(self, file_path: Path, data: dict) -> None:
        """Oturum dosyasını yazar; şifreleme etkinse Fernet ile şifreler."""
        json_bytes = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if self._fernet:
            file_path.write_bytes(self._fernet.encrypt(json_bytes))
        else:
            file_path.write_bytes(json_bytes)

    def _cleanup_quarantine_files(self) -> None:
        """Karantinadaki .json.broken dosyalarını yaş ve adet limitine göre temizler."""
        with self._lock:
            broken_files = sorted(
                self.sessions_dir.glob("*.json.broken"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not broken_files:
                return

            now = time.time()
            retention_seconds = self._broken_retention_days * 24 * 60 * 60

            removed = 0
            for index, file_path in enumerate(broken_files):
                file_age = now - file_path.stat().st_mtime
                should_delete_by_age = file_age > retention_seconds
                should_delete_by_count = index >= self._broken_max_files
                if not (should_delete_by_age or should_delete_by_count):
                    continue
                try:
                    file_path.unlink()
                    removed += 1
                except OSError as exc:
                    logger.warning("Karantina dosyası silinemedi (%s): %s", file_path.name, exc)

            if removed:
                logger.info("Karantina temizliği: %d dosya kaldırıldı.", removed)

    def _init_sessions(self) -> None:
        """Mevcut oturumları bul, yoksa yeni bir tane oluştur ve aktif yap."""
        self._cleanup_quarantine_files()
        sessions = self.get_all_sessions()
        if sessions:
            # En son güncellenen (en yeni) oturumu yükle
            last_session = sessions[0]
            self.load_session(last_session["id"])
        else:
            self.create_session("İlk Sohbet")

    # ─────────────────────────────────────────────
    #  OTURUM (SESSION) YÖNETİMİ
    # ─────────────────────────────────────────────

    def get_all_sessions(self) -> List[Dict]:
        """Tüm oturumları tarihe göre (en yeni en üstte) sıralı döndürür."""
        sessions = []
        with self._lock:
            for file_path in self.sessions_dir.glob("*.json"):
                try:
                    data = self._read_session_file(file_path)
                    turns = data.get("turns", [])
                    user_count = sum(1 for t in turns if t.get("role") == "user")
                    asst_count = sum(1 for t in turns if t.get("role") == "assistant")
                    sessions.append({
                        "id": data.get("id", file_path.stem),
                        "title": data.get("title", "İsimsiz Sohbet"),
                        "updated_at": data.get("updated_at", 0),
                        "msg_count": len(turns),
                        "user_count": user_count,
                        "asst_count": asst_count,
                    })
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    logger.error("Bozuk oturum dosyası: %s — %s", file_path.name, exc)
                    # Bozuk / şifre çözülemeyen dosyayı karantinaya al
                    broken_path = file_path.with_suffix(".json.broken")
                    try:
                        file_path.rename(broken_path)
                        logger.warning(
                            "Bozuk dosya karantinaya alındı: %s → %s",
                            file_path.name, broken_path.name,
                        )
                    except OSError as rename_exc:
                        logger.warning("Karantina yeniden adlandırması başarısız: %s", rename_exc)
                    else:
                        self._cleanup_quarantine_files()
                except Exception as exc:
                    logger.error("Oturum okuma hatası (%s): %s", file_path.name, exc)

        # Güncellenme zamanına göre azalan (descending) sırala
        sessions.sort(key=lambda x: x["updated_at"], reverse=True)
        return sessions

    def create_session(self, title: str = "Yeni Sohbet") -> str:
        """Yeni bir sohbet oturumu oluşturur ve aktif hale getirir."""
        session_id = str(uuid.uuid4())
        with self._lock:
            self.active_session_id = session_id
            self.active_title = title
            self._turns = []
            self._last_file = None
            self._save(force=True)
            logger.info(f"Yeni oturum oluşturuldu: {session_id} - {title}")
        return session_id

    def load_session(self, session_id: str) -> bool:
        """Belirtilen oturumu (sohbeti) belleğe yükler."""
        file_path = self.sessions_dir / f"{session_id}.json"
        if not file_path.exists():
            logger.warning(f"Oturum bulunamadı: {session_id}")
            return False

        try:
            with self._lock:
                data = self._read_session_file(file_path)
                self.active_session_id = session_id
                self.active_title = data.get("title", "İsimsiz Sohbet")
                self._turns = data.get("turns", [])
                self._last_file = data.get("last_file")
                logger.info(f"Oturum yüklendi: {session_id} ({len(self._turns)} mesaj)")
            return True
        except Exception as exc:
            logger.error(f"Oturum yükleme hatası ({session_id}): {exc}")
            return False

    def delete_session(self, session_id: str) -> bool:
        """Belirtilen oturumu siler."""
        file_path = self.sessions_dir / f"{session_id}.json"
        with self._lock:
            if file_path.exists():
                try:
                    file_path.unlink()
                    logger.info(f"Oturum silindi: {session_id}")
                    # Eğer silinen oturum aktif oturumsa, başka birine geç veya yeni oluştur
                    if self.active_session_id == session_id:
                        self._init_sessions()
                    return True
                except OSError as exc:
                    logger.error(f"Oturum silinirken hata: {exc}")
        return False
        
    def update_title(self, new_title: str) -> None:
        """Aktif oturumun başlığını günceller."""
        with self._lock:
            self.active_title = new_title
            self._save()

    # ─────────────────────────────────────────────
    #  PERSISTENCE (Kalıcılık)
    # ─────────────────────────────────────────────

    def _save(self, force: bool = False) -> None:
        """Aktif belleği (oturumu) diske kaydet."""
        if not self.active_session_id or not self.sessions_dir.exists():
            return
        
        try:
            with self._lock:
                now_mono = time.monotonic()
                if (
                    not force
                    and self._autosave_interval_sec > 0
                    and now_mono - self._last_save_monotonic < self._autosave_interval_sec
                ):
                    self._pending_save = True
                    return

                data = {
                    "id": self.active_session_id,
                    "title": self.active_title,
                    "updated_at": time.time(),
                    "last_file": self._last_file,
                    "turns": self._turns,
                }
                file_path = self.sessions_dir / f"{self.active_session_id}.json"
                self._write_session_file(file_path, data)
                self._pending_save = False
                self._last_save_monotonic = now_mono
        except Exception as exc:
            logger.error(f"Bellek kaydetme hatası: {exc}")

    def flush(self) -> None:
        """Bekleyen yazımı zorla diske geçir."""
        self._save(force=True)

    # ─────────────────────────────────────────────
    #  EKLEME & OKUMA
    # ─────────────────────────────────────────────

    def add(self, role: str, content: str) -> None:
        """Yeni bir mesaj turu ekle ve kaydet."""
        with self._lock:
            self._turns.append({
                "role": role,
                "content": content,
                "timestamp": time.time(),
            })
            # Pencere boyutunu koru
            if len(self._turns) > self.max_turns * 2:
                self._turns = self._turns[-(self.max_turns * 2):]

            self._save()

    def get_history(self, n_last: Optional[int] = None) -> List[Dict]:
        """Aktif sohbetin son n_last turunu döndür."""
        with self._lock:
            turns = list(self._turns)
        return turns if n_last is None else turns[-n_last:]

    def get_messages_for_llm(self) -> List[Dict[str, str]]:
        """LLM API çağrısı için mesaj listesi döndür."""
        with self._lock:
            return [{"role": t["role"], "content": t["content"]} for t in self._turns]

    # ─────────────────────────────────────────────
    #  DOSYA TAKİBİ
    # ─────────────────────────────────────────────

    def set_last_file(self, path: str) -> None:
        with self._lock:
            self._last_file = path
            self._save(force=True)

    def get_last_file(self) -> Optional[str]:
        with self._lock:
            return self._last_file

    # ─────────────────────────────────────────────
    #  ÖZETLEME DESTEĞİ
    # ─────────────────────────────────────────────

    def _estimate_tokens(self) -> int:
        """Kabaca token tahmini: UTF-8 Türkçe için ~3.5 karakter/token."""
        total_chars = sum(len(t.get("content", "")) for t in self._turns)
        return int(total_chars / 3.5)

    def needs_summarization(self) -> bool:
        """
        Bellek penceresinin %80'i dolduğunda veya tahmini token sayısı
        6000'i aştığında özetleme sinyali ver.
        """
        with self._lock:
            threshold = int(self.max_turns * 2 * 0.8)
            token_est = self._estimate_tokens()
            return len(self._turns) >= threshold or token_est > 6000

    def apply_summary(self, summary_text: str) -> None:
        """
        Tüm konuşma geçmişini özetle değiştir; belleği sıkıştırır.
        """
        with self._lock:
            self._turns = [
                {
                    "role": "user",
                    "content": "[Önceki konuşmaların özeti istendi]",
                    "timestamp": time.time(),
                },
                {
                    "role": "assistant",
                    "content": f"[KONUŞMA ÖZETİ]\n{summary_text}",
                    "timestamp": time.time(),
                },
            ]
            self._save(force=True)
        logger.info("Konuşma belleği özetleme ile sıkıştırıldı.")

    # ─────────────────────────────────────────────
    #  YARDIMCILAR
    # ─────────────────────────────────────────────

    def clear(self) -> None:
        """Aktif belleği temizle (dosyayı boşaltır ancak silmez)."""
        with self._lock:
            self._turns.clear()
            self._last_file = None
            self._save(force=True)

    def __len__(self) -> int:
        with self._lock:
            return len(self._turns)

    def __repr__(self) -> str:
        return f"<ConversationMemory session={self.active_session_id} turns={len(self._turns)}>"  
