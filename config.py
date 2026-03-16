
"""
Sidar Project — Merkezi Yapılandırma Modülü
Sürüm: 3.0.0 (Kurumsal/SaaS sürüm: multi-agent, auth, DB migration, observability, sandbox)
Açıklama: Sistem ayarları, donanım tespiti, dizin yönetimi ve loglama altyapısı.
"""

import os
import sys
import logging
import warnings
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dotenv import load_dotenv
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

# ═══════════════════════════════════════════════════════════════
# UYARI FİLTRELERİ
# ═══════════════════════════════════════════════════════════════
warnings.filterwarnings("ignore", category=FutureWarning, module="torch")
warnings.filterwarnings("ignore", category=UserWarning, module="torch")
warnings.filterwarnings("ignore", category=UserWarning, message=".*pkg_resources is deprecated.*")

# ═══════════════════════════════════════════════════════════════
# TEMEL DİZİN VE .ENV YÜKLEMESİ  (diğer her şeyden ÖNCE)
# ═══════════════════════════════════════════════════════════════
BASE_DIR = Path(__file__).resolve().parent

# 1. Ortam değişkenini kontrol et (örn: SIDAR_ENV=production)
sidar_env = os.getenv("SIDAR_ENV", "").strip().lower()

# 2. Önce her zaman temel .env dosyasını yükle (varsa)
base_env_path = BASE_DIR / ".env"
if base_env_path.exists():
    load_dotenv(dotenv_path=base_env_path)

# 3. Ortama özgü dosyayı (örn: .env.production) temel ayarların üstüne yaz
if sidar_env:
    specific_env_path = BASE_DIR / f".env.{sidar_env}"
    if specific_env_path.exists():
        load_dotenv(dotenv_path=specific_env_path, override=True)
        print(f"ℹ️  Ortama özgü yapılandırma yüklendi: .env.{sidar_env}")
    else:
        optional_env_aliases = {"development", "dev", "local"}
        if sidar_env in optional_env_aliases and base_env_path.exists():
            print(
                f"ℹ️  .env.{sidar_env} bulunamadı; temel .env ayarları kullanılacak."
            )
        else:
            print(f"⚠️  Belirtilen ortam dosyası bulunamadı: .env.{sidar_env}. Temel ayarlar kullanılacak.")
elif not base_env_path.exists():
    print("⚠️  '.env' dosyası bulunamadı! Varsayılan ayarlar kullanılacak.")

ENV_PATH = base_env_path

# ═══════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════

def get_bool_env(key: str, default: bool = False) -> bool:
    raw_val = os.getenv(key)
    if raw_val is None or not raw_val.strip():
        return default
    val = raw_val.strip().lower()
    return val in ("true", "1", "yes", "on")


def get_int_env(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_float_env(key: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_list_env(key: str, default: Optional[List[str]] = None,
                 separator: str = ",") -> List[str]:
    if default is None:
        default = []
    value = os.getenv(key, "")
    if not value:
        return default
    return [item.strip() for item in value.split(separator) if item.strip()]


# ═══════════════════════════════════════════════════════════════
# LOGLAMA SİSTEMİ  (dinamik, RotatingFileHandler)
# ═══════════════════════════════════════════════════════════════
_LOG_DIR = BASE_DIR / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_LOG_LEVEL_STR  = os.getenv("LOG_LEVEL", "INFO").upper()
_LOG_FILE_PATH  = BASE_DIR / os.getenv("LOG_FILE", "logs/sidar_system.log")
_LOG_MAX_BYTES  = get_int_env("LOG_MAX_BYTES", 10_485_760)   # 10 MB
_LOG_BACKUP_CNT = get_int_env("LOG_BACKUP_COUNT", 5)

_LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL_STR, logging.INFO),
    format="%(asctime)s - [%(levelname)s] - %(name)s - (%(filename)s:%(lineno)d) - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            _LOG_FILE_PATH,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_CNT,
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("Sidar.Config")

if ENV_PATH.exists():
    logger.info("✅ Ortam değişkenleri yüklendi: %s", ENV_PATH)

# ═══════════════════════════════════════════════════════════════
# SANDBOX KAYNAK KOTALARI (Docker/cgroups)
# ═══════════════════════════════════════════════════════════════
SANDBOX_LIMITS = {
    "memory": os.getenv("SANDBOX_MEMORY", "256m"),
    "cpus": os.getenv("SANDBOX_CPUS", "0.5"),
    "pids_limit": get_int_env("SANDBOX_PIDS_LIMIT", 64),
    "network": os.getenv("SANDBOX_NETWORK", "none"),
    "timeout": get_int_env("SANDBOX_TIMEOUT", 10),
}

# ═══════════════════════════════════════════════════════════════
# DONANIM TESPİTİ
# ═══════════════════════════════════════════════════════════════

@dataclass
class HardwareInfo:
    """Başlangıçta tespit edilen donanım bilgilerini tutar."""
    has_cuda: bool
    gpu_name: str
    gpu_count: int = 0
    cpu_count: int = 0
    cuda_version: str = "N/A"
    driver_version: str = "N/A"


def _is_wsl2() -> bool:
    """WSL2 ortamını tespit eder (/proc/sys/kernel/osrelease içinde 'microsoft' arar)."""
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except Exception:
        return False


def check_hardware() -> HardwareInfo:
    """GPU/CPU donanımını tespit eder; PyTorch yoksa sessizce devam eder."""
    info = HardwareInfo(has_cuda=False, gpu_name="N/A")

    wsl2 = _is_wsl2()
    if wsl2:
        logger.info("ℹ️  WSL2 ortamı tespit edildi — CUDA, Windows sürücüsü üzerinden erişilecek.")

    if not get_bool_env("USE_GPU", True):
        logger.info("ℹ️  GPU kullanımı .env ile devre dışı bırakıldı.")
        info.gpu_name = "Devre Dışı (Kullanıcı)"
        return info

    try:
        import torch
        if torch.cuda.is_available():
            info.has_cuda     = True
            info.gpu_count    = torch.cuda.device_count()
            info.gpu_name     = torch.cuda.get_device_name(0)
            info.cuda_version = torch.version.cuda or "N/A"
            logger.info(
                "🚀 GPU Hızlandırma Aktif: %s  (%d GPU tespit edildi, CUDA %s)",
                info.gpu_name, info.gpu_count, info.cuda_version,
            )
            # VRAM fraksiyonunu hemen uygula (GPU_MEMORY_FRACTION env'den okunur)
            frac = get_float_env("GPU_MEMORY_FRACTION", 0.8)
            if not (0.1 <= frac < 1.0):
                logger.warning(
                    "GPU_MEMORY_FRACTION=%.2f geçersiz aralık (0.1–1.0 bekleniyor) "
                    "— varsayılan 0.8 kullanılıyor.",
                    frac,
                )
                frac = 0.8
            try:
                torch.cuda.set_per_process_memory_fraction(frac, device=0)
                logger.info("🔧 VRAM fraksiyonu ayarlandı: %.0f%%", frac * 100)
            except Exception as exc:
                logger.debug("VRAM fraksiyon ayarı atlandı: %s", exc)
        else:
            if wsl2:
                logger.warning(
                    "⚠️  WSL2 — CUDA bulunamadı. Kontrol: "
                    "Windows NVIDIA sürücüsü güncel mi? "
                    "PyTorch CUDA 12.x wheel ile kuruldu mu? "
                    "(pip install torch --index-url https://download.pytorch.org/whl/cu124)"
                )
            else:
                logger.info("ℹ️  CUDA bulunamadı — CPU modunda çalışılacak.")
            info.gpu_name = "CUDA Bulunamadı"
    except ImportError:
        logger.warning("⚠️  PyTorch kurulu değil; GPU kontrolü atlanıyor.")
        info.gpu_name = "PyTorch Yok"
    except Exception as exc:
        logger.warning("⚠️  Donanım kontrolü hatası: %s", exc)
        info.gpu_name = "Tespit Edilemedi"

    # sürücü sürümü — nvidia-ml-py varsa al
    try:
        import pynvml
        pynvml.nvmlInit()
        info.driver_version = pynvml.nvmlSystemGetDriverVersion()
        pynvml.nvmlShutdown()
    except Exception:
        pass  # opsiyonel bağımlılık; WSL2'de NVML erişimi kısıtlı olabilir

    try:
        import multiprocessing
        info.cpu_count = multiprocessing.cpu_count()
    except Exception:
        info.cpu_count = 1

    return info



# ═══════════════════════════════════════════════════════════════
# ANA YAPILANDIRMA SINIFI
# ═══════════════════════════════════════════════════════════════

class Config:
    """
    Sidar Merkezi Yapılandırma Sınıfı
    Sürüm: 3.0.0
    """

    # ─── Genel ───────────────────────────────────────────────
    PROJECT_NAME: str = "Sidar"
    VERSION: str      = "3.0.0"
    DEBUG_MODE: bool  = get_bool_env("DEBUG_MODE", False)
    ENABLE_MULTI_AGENT: bool = True  # Legacy bayrak kaldırıldı; sistem daima Supervisor akışında çalışır.

    # ─── Dizinler ────────────────────────────────────────────
    BASE_DIR:    Path = BASE_DIR
    TEMP_DIR:    Path = BASE_DIR / "temp"
    LOGS_DIR:    Path = BASE_DIR / "logs"
    DATA_DIR:    Path = BASE_DIR / "data"
    MEMORY_FILE: Path = DATA_DIR / "memory.json"

    REQUIRED_DIRS: List[Path] = [BASE_DIR / "temp", BASE_DIR / "logs", BASE_DIR / "data"]

    # ─── AI Sağlayıcı ────────────────────────────────────────
    AI_PROVIDER:    str = os.getenv("AI_PROVIDER", "ollama")   # "ollama" | "gemini" | "openai" | "anthropic" | "litellm"
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL:   str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL:   str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_TIMEOUT: int = get_int_env("OPENAI_TIMEOUT", 60)
    LLM_MAX_RETRIES: int = get_int_env("LLM_MAX_RETRIES", 2)
    LLM_RETRY_BASE_DELAY: float = get_float_env("LLM_RETRY_BASE_DELAY", 0.4)
    LLM_RETRY_MAX_DELAY: float = get_float_env("LLM_RETRY_MAX_DELAY", 4.0)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL:   str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    ANTHROPIC_TIMEOUT: int = get_int_env("ANTHROPIC_TIMEOUT", 60)

    # ─── LiteLLM Gateway ─────────────────────────────────────
    LITELLM_GATEWAY_URL: str = os.getenv("LITELLM_GATEWAY_URL", "")
    LITELLM_API_KEY: str = os.getenv("LITELLM_API_KEY", "")
    LITELLM_MODEL: str = os.getenv("LITELLM_MODEL", "")
    LITELLM_FALLBACK_MODELS: List[str] = get_list_env("LITELLM_FALLBACK_MODELS", [])
    LITELLM_TIMEOUT: int = get_int_env("LITELLM_TIMEOUT", 60)

    # ─── Ollama ──────────────────────────────────────────────
    OLLAMA_URL:     str = os.getenv("OLLAMA_URL", "http://localhost:11434/api")
    OLLAMA_TIMEOUT: int = get_int_env("OLLAMA_TIMEOUT", 30)
    CODING_MODEL:   str = os.getenv("CODING_MODEL", "qwen2.5-coder:7b")
    TEXT_MODEL:     str = os.getenv("TEXT_MODEL", "gemma2:9b")

    # ─── Erişim Seviyesi (OpenClaw) ──────────────────────────
    ACCESS_LEVEL: str = os.getenv("ACCESS_LEVEL", "full")
    API_KEY: str = os.getenv("API_KEY", "")

    # ─── JWT Auth (stateless) ─────────────────────────────────
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", os.getenv("API_KEY", ""))
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_TTL_DAYS: int = get_int_env("JWT_TTL_DAYS", 7)

    # ─── GitHub ──────────────────────────────────────────────
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_REPO:  str = os.getenv("GITHUB_REPO", "")
    GITHUB_WEBHOOK_SECRET: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")

    # ─── HuggingFace ─────────────────────────────────────────
    HF_TOKEN:       str = os.getenv("HF_TOKEN", "")
    HF_HUB_OFFLINE: bool = get_bool_env("HF_HUB_OFFLINE", False)

    # ─── Donanım & GPU ───────────────────────────────────────
    USE_GPU:       bool  = get_bool_env("USE_GPU", True)
    GPU_INFO:      str   = "Devre Dışı / CPU Modu"
    GPU_COUNT:     int   = 0
    CPU_COUNT:     int   = os.cpu_count() or 1
    CUDA_VERSION:  str   = "N/A"
    DRIVER_VERSION: str  = "N/A"

    _hardware_loaded: bool = False

    # Birden fazla GPU varsa hangi device kullanılsın (0-indexed)
    GPU_DEVICE: int = get_int_env("GPU_DEVICE", 0)

    # Çoklu GPU dağıtık mod
    MULTI_GPU: bool = get_bool_env("MULTI_GPU", False)

    # Embedding ve model yüklemeleri için VRAM fraksiyonu (0.1–1.0)
    GPU_MEMORY_FRACTION: float = get_float_env("GPU_MEMORY_FRACTION", 0.8)

    # FP16 / mixed precision  →  embedding modellerinde bellek tasarrufu
    GPU_MIXED_PRECISION: bool = get_bool_env("GPU_MIXED_PRECISION", False)

    # ─── Uygulama ────────────────────────────────────────────
    MAX_MEMORY_TURNS:  int = get_int_env("MAX_MEMORY_TURNS", 20)
    MEMORY_SUMMARY_KEEP_LAST: int = get_int_env("MEMORY_SUMMARY_KEEP_LAST", 4)
    LOG_LEVEL:         str = os.getenv("LOG_LEVEL", "INFO")
    RESPONSE_LANGUAGE: str = os.getenv("RESPONSE_LANGUAGE", "tr")

    # ─── Loglama ─────────────────────────────────────────────
    LOG_FILE:         Path = _LOG_FILE_PATH
    LOG_MAX_BYTES:     int = _LOG_MAX_BYTES
    LOG_BACKUP_COUNT:  int = _LOG_BACKUP_CNT

    # ─── ReAct Döngüsü ───────────────────────────────────────
    MAX_REACT_STEPS:   int = get_int_env("MAX_REACT_STEPS", 10)
    REACT_TIMEOUT:     int = get_int_env("REACT_TIMEOUT", 60)
    SUBTASK_MAX_STEPS: int = get_int_env("SUBTASK_MAX_STEPS", 5)
    AUTO_HANDLE_TIMEOUT: int = get_int_env("AUTO_HANDLE_TIMEOUT", 12)

    # ─── API Rate Limiting ───────────────────────────────────
    RATE_LIMIT_WINDOW:    int = get_int_env("RATE_LIMIT_WINDOW", 60)
    RATE_LIMIT_CHAT:      int = get_int_env("RATE_LIMIT_CHAT", 20)
    RATE_LIMIT_MUTATIONS: int = get_int_env("RATE_LIMIT_MUTATIONS", 60)
    RATE_LIMIT_GET_IO:    int = get_int_env("RATE_LIMIT_GET_IO", 30)
    REDIS_URL:            str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # ─── Veritabanı (v3.0 çoklu kullanıcı hazırlığı) ────────
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/sidar.db")
    DB_POOL_SIZE: int = get_int_env("DB_POOL_SIZE", 5)
    DB_SCHEMA_VERSION_TABLE: str = os.getenv("DB_SCHEMA_VERSION_TABLE", "schema_versions")
    DB_SCHEMA_TARGET_VERSION: int = get_int_env("DB_SCHEMA_TARGET_VERSION", 1)

    # ─── Gözlemlenebilirlik (OpenTelemetry) ───────────────────
    ENABLE_TRACING:       bool = get_bool_env("ENABLE_TRACING", False)
    OTEL_EXPORTER_ENDPOINT: str = os.getenv("OTEL_EXPORTER_ENDPOINT", "http://localhost:4317")

    # ─── Web Arama ───────────────────────────────────────────
    SEARCH_ENGINE:        str = os.getenv("SEARCH_ENGINE", "auto")
    TAVILY_API_KEY:       str = os.getenv("TAVILY_API_KEY", "")
    GOOGLE_SEARCH_API_KEY: str = os.getenv("GOOGLE_SEARCH_API_KEY", "")
    GOOGLE_SEARCH_CX:     str = os.getenv("GOOGLE_SEARCH_CX", "")
    WEB_SEARCH_MAX_RESULTS: int = get_int_env("WEB_SEARCH_MAX_RESULTS", 5)
    WEB_FETCH_TIMEOUT:     int = get_int_env("WEB_FETCH_TIMEOUT", 15)
    WEB_FETCH_MAX_CHARS:   int = get_int_env("WEB_FETCH_MAX_CHARS", 12000)
    # Yeni ad (tercih edilen): scrape/okuma karakter limiti
    WEB_SCRAPE_MAX_CHARS:  int = get_int_env("WEB_SCRAPE_MAX_CHARS", WEB_FETCH_MAX_CHARS)

    # ─── Paket Bilgi ─────────────────────────────────────────
    PACKAGE_INFO_TIMEOUT: int = get_int_env("PACKAGE_INFO_TIMEOUT", 12)
    PACKAGE_INFO_CACHE_TTL: int = get_int_env("PACKAGE_INFO_CACHE_TTL", 1800)

    # ─── RAG — Belge Deposu ──────────────────────────────────
    RAG_DIR:            Path = BASE_DIR / os.getenv("RAG_DIR", "data/rag")
    RAG_TOP_K:           int = get_int_env("RAG_TOP_K", 3)
    RAG_CHUNK_SIZE:      int = get_int_env("RAG_CHUNK_SIZE", 1000)
    RAG_CHUNK_OVERLAP:   int = get_int_env("RAG_CHUNK_OVERLAP", 200)
    # Büyük dosya eşiği: bu karakter sayısını geçen dosyalar okunduğunda
    # RAG deposuna ekleme önerilir (varsayılan ≈ 400 satır / ~20 KB).
    RAG_FILE_THRESHOLD: int = get_int_env("RAG_FILE_THRESHOLD", 20000)
    RAG_VECTOR_BACKEND: str = os.getenv("RAG_VECTOR_BACKEND", "chroma")  # chroma | pgvector
    PGVECTOR_TABLE: str = os.getenv("PGVECTOR_TABLE", "rag_embeddings")
    PGVECTOR_EMBEDDING_DIM: int = get_int_env("PGVECTOR_EMBEDDING_DIM", 384)
    PGVECTOR_EMBEDDING_MODEL: str = os.getenv("PGVECTOR_EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    # ─── Docker REPL Sandbox ─────────────────────────────────
    SANDBOX_LIMITS: Dict[str, Any] = dict(SANDBOX_LIMITS)
    DOCKER_PYTHON_IMAGE: str = os.getenv("DOCKER_PYTHON_IMAGE", "python:3.11-alpine")
    DOCKER_RUNTIME: str = os.getenv("DOCKER_RUNTIME", "")
    DOCKER_ALLOWED_RUNTIMES: List[str] = get_list_env("DOCKER_ALLOWED_RUNTIMES", ["", "runc", "runsc", "kata-runtime"])
    DOCKER_MICROVM_MODE: str = os.getenv("DOCKER_MICROVM_MODE", "off")
    DOCKER_MEM_LIMIT: str = os.getenv("DOCKER_MEM_LIMIT", "256m")
    DOCKER_NETWORK_DISABLED: bool = get_bool_env("DOCKER_NETWORK_DISABLED", True)
    DOCKER_NANO_CPUS: int = get_int_env("DOCKER_NANO_CPUS", 1_000_000_000)
    # Maksimum Docker sandbox çalışma süresi (saniye) — sonsuz döngü koruması
    DOCKER_EXEC_TIMEOUT: int = get_int_env("DOCKER_EXEC_TIMEOUT", 10)

    # ─── Bellek Şifrelemesi ───────────────────────────────────────
    # Boş bırakılırsa şifreleme devre dışı (varsayılan).
    # Fernet anahtarı üretmek için:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    MEMORY_ENCRYPTION_KEY: str = os.getenv("MEMORY_ENCRYPTION_KEY", "")

    # ─── Web Arayüzü ─────────────────────────────────────────
    WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
    WEB_PORT: int = get_int_env("WEB_PORT", 7860)
    WEB_GPU_PORT: int = get_int_env("WEB_GPU_PORT", 7861)

    # ─── Multi-Agent geçiş ayarları ─────────────────────────
    REVIEWER_TEST_COMMAND: str = os.getenv("REVIEWER_TEST_COMMAND", "python -m pytest")

    # ─────────────────────────────────────────────────────────
    #  METOTLAR
    # ─────────────────────────────────────────────────────────

    def __init__(self) -> None:
        # Donanım bilgisini import anında değil, ilk Config kullanımında yükle.
        self.__class__._ensure_hardware_info_loaded()


    @classmethod
    def _ensure_hardware_info_loaded(cls) -> None:
        """Donanım bilgisini lazy-load ederek import yan etkisini azalt."""
        if cls._hardware_loaded:
            return

        if not cls.USE_GPU:
            cls.GPU_INFO = "Devre Dışı / CPU Modu"
            cls.GPU_COUNT = 0
            cls.CUDA_VERSION = "N/A"
            cls.DRIVER_VERSION = "N/A"
            cls.CPU_COUNT = os.cpu_count() or 1
            cls._hardware_loaded = True
            return

        hw = check_hardware()
        cls.USE_GPU = bool(hw.has_cuda)
        cls.GPU_INFO = hw.gpu_name
        cls.GPU_COUNT = hw.gpu_count
        cls.CPU_COUNT = hw.cpu_count or (os.cpu_count() or 1)
        cls.CUDA_VERSION = hw.cuda_version
        cls.DRIVER_VERSION = hw.driver_version
        cls._hardware_loaded = True

    @classmethod
    def initialize_directories(cls) -> bool:
        """Gerekli tüm dizinleri oluşturur."""
        success = True
        for folder in cls.REQUIRED_DIRS:
            try:
                folder.mkdir(parents=True, exist_ok=True)
                logger.debug("✅ Dizin hazır: %s", folder.name)
            except Exception as exc:
                logger.error("❌ Dizin oluşturulamadı (%s): %s", folder.name, exc)
                success = False
        return success

    @classmethod
    def set_provider_mode(cls, mode: str) -> None:
        """AI sağlayıcı modunu çalışma zamanında değiştirir."""
        mode_map = {
            "online": "gemini", "gemini": "gemini",
            "local":  "ollama", "ollama": "ollama",
            "anthropic": "anthropic",
            "litellm": "litellm",
        }
        m_lower = mode.lower()
        if m_lower in mode_map:
            cls.AI_PROVIDER = mode_map[m_lower]
            logger.info("✅ AI Sağlayıcı güncellendi: %s", cls.AI_PROVIDER.upper())
        else:
            logger.error(
                "❌ Geçersiz sağlayıcı modu: %s  Geçerliler: %s",
                mode, list(mode_map.keys()),
            )

    @classmethod
    def validate_critical_settings(cls) -> bool:
        """Kritik yapılandırmaları doğrular; uyarıları loglar."""
        is_valid = True
        cls._ensure_hardware_info_loaded()
        cls.initialize_directories()

        if cls.AI_PROVIDER == "gemini" and not cls.GEMINI_API_KEY:
            logger.error(
                "❌ Gemini modu seçili ama GEMINI_API_KEY ayarlanmamış!\n"
                "   .env dosyasını kontrol edin."
            )
            is_valid = False

        if cls.MEMORY_ENCRYPTION_KEY:
            try:
                from cryptography.fernet import Fernet  # noqa: F401
                # Anahtarı ön doğrulama — geçersiz formatta erken hata ver
                try:
                    Fernet(cls.MEMORY_ENCRYPTION_KEY.encode())
                except Exception as key_exc:
                    logger.error(
                        "❌ MEMORY_ENCRYPTION_KEY geçersiz Fernet anahtarı: %s\n"
                        "   Geçerli anahtar üretmek için:\n"
                        "   python -c \"from cryptography.fernet import Fernet; "
                        "print(Fernet.generate_key().decode())\"",
                        key_exc,
                    )
                    is_valid = False
            except ImportError:
                logger.error(
                    "❌ MEMORY_ENCRYPTION_KEY ayarlanmış ama 'cryptography' paketi kurulu değil.\n"
                    "   Bu kritik bir güvenlik ayarıdır. Şifreleme olmadan devam etmek\n"
                    "   güvenlik riskine yol açabilir. Kurmak için: pip install cryptography"
                )
                is_valid = False

        if cls.AI_PROVIDER == "openai" and not cls.OPENAI_API_KEY:
            logger.error(
                "❌ OpenAI modu seçili ama OPENAI_API_KEY ayarlanmamış!\n"
                "   .env dosyasını kontrol edin."
            )
            is_valid = False

        if cls.AI_PROVIDER == "anthropic" and not cls.ANTHROPIC_API_KEY:
            logger.error(
                "❌ Anthropic modu seçili ama ANTHROPIC_API_KEY ayarlanmamış!\n"
                "   .env dosyasını kontrol edin."
            )
            is_valid = False

        if cls.AI_PROVIDER == "litellm" and not cls.LITELLM_GATEWAY_URL:
            logger.error(
                "❌ LiteLLM modu seçili ama LITELLM_GATEWAY_URL ayarlanmamış!\n"
                "   .env dosyasını kontrol edin."
            )
            is_valid = False

        if cls.AI_PROVIDER == "ollama":
            try:
                import httpx
                base = cls.OLLAMA_URL.rstrip("/")
                if base.endswith("/api"):
                    tags_url = base + "/tags"
                else:
                    tags_url = base + "/api/tags"
                with httpx.Client(timeout=2) as client:
                    r = client.get(tags_url)
                if r.status_code == 200:
                    logger.info("✅ Ollama bağlantısı başarılı.")
                else:
                    logger.warning("⚠️  Ollama yanıt kodu: %d", r.status_code)
            except Exception:
                logger.warning(
                    "⚠️  Ollama'ya ulaşılamadı (%s)\n"
                    "    'ollama serve' çalıştırıldığından emin olun.",
                    cls.OLLAMA_URL,
                )

        return is_valid

    @classmethod
    def get_system_info(cls) -> Dict[str, Any]:
        """Özet sistem bilgisini sözlük olarak döndürür."""
        cls._ensure_hardware_info_loaded()
        return {
            "project":            cls.PROJECT_NAME,
            "version":            cls.VERSION,
            "provider":           cls.AI_PROVIDER,
            "access_level":       cls.ACCESS_LEVEL,
            "gpu_enabled":        cls.USE_GPU,
            "gpu_info":           cls.GPU_INFO,
            "gpu_count":          cls.GPU_COUNT,
            "gpu_device":         cls.GPU_DEVICE,
            "cuda_version":       cls.CUDA_VERSION,
            "driver_version":     cls.DRIVER_VERSION,
            "multi_gpu":          cls.MULTI_GPU,
            "gpu_mixed_precision": cls.GPU_MIXED_PRECISION,
            "cpu_count":          cls.CPU_COUNT,
            "debug_mode":         cls.DEBUG_MODE,
            "web_port":           cls.WEB_PORT,
            "web_gpu_port":       cls.WEB_GPU_PORT,
            "hf_hub_offline":     cls.HF_HUB_OFFLINE,
            "rate_limit_window":  cls.RATE_LIMIT_WINDOW,
            "rate_limit_chat":    cls.RATE_LIMIT_CHAT,
            "rate_limit_mutations": cls.RATE_LIMIT_MUTATIONS,
            "rate_limit_get_io":  cls.RATE_LIMIT_GET_IO,
            "redis_url":          cls.REDIS_URL,
            "enable_tracing":     cls.ENABLE_TRACING,
            "otel_exporter_endpoint": cls.OTEL_EXPORTER_ENDPOINT,
        }

    @classmethod
    def print_config_summary(cls) -> None:
        """Konsola yapılandırma özetini yazdırır."""
        print("\n" + "═" * 62)
        print(f"  {cls.PROJECT_NAME} v{cls.VERSION} — Yapılandırma Özeti")
        print("═" * 62)
        print(f"  AI Sağlayıcı     : {cls.AI_PROVIDER.upper()}")
        if cls.USE_GPU:
            print(f"  GPU              : ✓ {cls.GPU_INFO}  (CUDA {cls.CUDA_VERSION})")
            print(f"  GPU Sayısı       : {cls.GPU_COUNT}")
            print(f"  Hedef Cihaz      : cuda:{cls.GPU_DEVICE}")
            print(f"  Mixed Precision  : {'Açık' if cls.GPU_MIXED_PRECISION else 'Kapalı'}")
            if cls.DRIVER_VERSION != "N/A":
                print(f"  Sürücü Sürümü    : {cls.DRIVER_VERSION}")
        else:
            print(f"  GPU              : ✗ CPU Modu  ({cls.GPU_INFO})")
        print(f"  CPU Çekirdek     : {cls.CPU_COUNT}")
        print(f"  Erişim Seviyesi  : {cls.ACCESS_LEVEL.upper()}")
        print(f"  Debug Modu       : {'Açık' if cls.DEBUG_MODE else 'Kapalı'}")
        if cls.AI_PROVIDER == "ollama":
            print(f"  CODING Modeli    : {cls.CODING_MODEL}")
            print(f"  TEXT Modeli      : {cls.TEXT_MODEL}")
        elif cls.AI_PROVIDER == "gemini":
            print(f"  Gemini Modeli    : {cls.GEMINI_MODEL}")
        elif cls.AI_PROVIDER == "openai":
            print(f"  OpenAI Modeli    : {cls.OPENAI_MODEL}")
        elif cls.AI_PROVIDER == "litellm":
            print(f"  LiteLLM Gateway  : {cls.LITELLM_GATEWAY_URL or '-'}")
            print(f"  LiteLLM Modeli   : {cls.LITELLM_MODEL or cls.OPENAI_MODEL}")
        else:
            print(f"  Anthropic Modeli : {cls.ANTHROPIC_MODEL}")
        print(f"  RAG Dizini       : {cls.RAG_DIR.relative_to(BASE_DIR)}")
        enc_status = "Etkin (Fernet)" if cls.MEMORY_ENCRYPTION_KEY else "Devre Dışı"
        print(f"  Bellek Şifreleme : {enc_status}")
        print("═" * 62 + "\n")


# ═══════════════════════════════════════════════════════════════
# BAŞLANGIÇ
# ═══════════════════════════════════════════════════════════════
logger.info("✅ %s v%s yapılandırması yüklendi.", Config.PROJECT_NAME, Config.VERSION)

if __name__ == "__main__":
    Config.initialize_directories()
    if Config.DEBUG_MODE:
        Config.print_config_summary() 
