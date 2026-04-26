
"""
Sidar Project — Merkezi Yapılandırma Modülü
Sürüm: v5.2.0 (Ultimate Launcher, multimodal/voice, browser automation, proaktif swarm)
Açıklama: Sistem ayarları, donanım tespiti, dizin yönetimi ve loglama altyapısı.
"""

import os
import sys
import logging
import warnings
import contextlib
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


def get_db_pool_size_default() -> int:
    """
    DB havuz boyutu için çekirdek sayısı + PostgreSQL max_connections temelli varsayılan üretir.

    Formül:
    - taban hedef = CPU * DB_POOL_SIZE_PER_CORE (varsayılan 2)
    - üst sınır = POSTGRES_MAX_CONNECTIONS - DB_POOL_CONNECTION_RESERVE (varsayılan 10)
    - global tavan = DB_POOL_SIZE_HARD_CAP (varsayılan 50)
    """
    cpu_count = max(1, int(os.cpu_count() or 1))
    per_core = max(1, get_int_env("DB_POOL_SIZE_PER_CORE", 2))
    postgres_max_connections = max(1, get_int_env("POSTGRES_MAX_CONNECTIONS", 100))
    reserve = max(0, get_int_env("DB_POOL_CONNECTION_RESERVE", 10))
    hard_cap = max(1, get_int_env("DB_POOL_SIZE_HARD_CAP", 50))

    max_by_postgres = max(1, postgres_max_connections - reserve)
    return max(2, min(cpu_count * per_core, max_by_postgres, hard_cap))


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

def _repair_log_file_permissions(log_file: Path) -> None:
    """Yazılamayan log dosyasını mümkünse mevcut kullanıcıya göre onarır."""
    if not log_file.exists():
        return

    if os.access(log_file, os.W_OK):
        return

    uid = os.getuid() if hasattr(os, "getuid") else None
    gid = os.getgid() if hasattr(os, "getgid") else None

    if uid is not None and gid is not None and hasattr(os, "chown"):
        with contextlib.suppress(PermissionError, OSError):
            os.chown(log_file, uid, gid)

    current_mode = log_file.stat().st_mode & 0o777
    with contextlib.suppress(PermissionError, OSError):
        log_file.chmod(current_mode | 0o200)

_repair_log_file_permissions(_LOG_FILE_PATH)

_root_logger = logging.getLogger()
for _handler in list(_root_logger.handlers):
    with contextlib.suppress(Exception):
        _handler.flush()
        _handler.close()
    _root_logger.removeHandler(_handler)

logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL_STR, logging.INFO),
    format="%(asctime)s - [%(levelname)s] - %(name)s - (%(filename)s:%(lineno)d) - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

with contextlib.suppress(Exception):
    _root_logger.handlers[0].setLevel(getattr(logging, _LOG_LEVEL_STR, logging.INFO))

try:
    _file_handler = RotatingFileHandler(
        _LOG_FILE_PATH,
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_CNT,
        encoding="utf-8",
    )
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - [%(levelname)s] - %(name)s - (%(filename)s:%(lineno)d) - %(message)s"
    ))
    _root_logger.addHandler(_file_handler)
except (PermissionError, OSError) as exc:
    _root_logger.warning(
        "⚠️ Log dosyasına yazılamıyor (%s). Sadece konsol loglama ile devam edilecek.",
        exc,
    )

logger = logging.getLogger("Sidar.Config")

_DEPENDENCY_AUTO = object()

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

    try:
        import multiprocessing
        info.cpu_count = multiprocessing.cpu_count()
    except Exception:
        info.cpu_count = 1

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
            # VRAM fraksiyonu: geriye dönük GPU_MEMORY_FRACTION + opsiyonel LLM/RAG ayrımı
            legacy_frac = get_float_env("GPU_MEMORY_FRACTION", 0.8)
            llm_frac = get_float_env("LLM_GPU_MEMORY_FRACTION", legacy_frac)
            rag_frac = get_float_env("RAG_GPU_MEMORY_FRACTION", max(0.1, min(0.5, legacy_frac * 0.35)))
            if os.getenv("LLM_GPU_MEMORY_FRACTION") is not None or os.getenv("RAG_GPU_MEMORY_FRACTION") is not None:
                frac = llm_frac + rag_frac
            else:
                frac = legacy_frac
            if not (0.1 <= frac < 1.0):
                logger.warning(
                    "GPU bellek fraksiyonu=%.2f geçersiz aralık (0.1–0.99 bekleniyor, 1.0 dahil değil) "
                    "— varsayılan 0.8 kullanılıyor.",
                    frac,
                )
                frac = 0.8
            multi_gpu = get_bool_env("MULTI_GPU", False)
            target_device = max(0, get_int_env("GPU_DEVICE", 0))
            try:
                if multi_gpu and info.gpu_count > 1:
                    for device_idx in range(info.gpu_count):
                        torch.cuda.set_per_process_memory_fraction(frac, device=device_idx)
                    logger.info(
                        "🔧 VRAM fraksiyonu tüm GPU'lara uygulandı: %.0f%% (%d cihaz)",
                        frac * 100,
                        info.gpu_count,
                    )
                else:
                    if info.gpu_count > 0:
                        target_device = min(target_device, info.gpu_count - 1)
                    torch.cuda.set_per_process_memory_fraction(frac, device=target_device)
                    logger.info(
                        "🔧 VRAM fraksiyonu ayarlandı: %.0f%% (cuda:%d)",
                        frac * 100,
                        target_device,
                    )
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

    return info



# ═══════════════════════════════════════════════════════════════
# ANA YAPILANDIRMA SINIFI
# ═══════════════════════════════════════════════════════════════

class Config:
    """
    Sidar Merkezi Yapılandırma Sınıfı
    Sürüm: v5.2.0
    """

    # ─── Genel ───────────────────────────────────────────────
    PROJECT_NAME: str = "Sidar"
    VERSION: str      = "5.2.0"
    DEBUG_MODE: bool  = get_bool_env("DEBUG_MODE", False)
    ENABLE_MULTI_AGENT: bool = True  # Legacy bayrak kaldırıldı; sistem daima Supervisor akışında çalışır.
    ENABLE_AUTONOMOUS_SELF_HEAL: bool = get_bool_env("ENABLE_AUTONOMOUS_SELF_HEAL", False)
    SELF_HEAL_MAX_PATCHES: int = get_int_env("SELF_HEAL_MAX_PATCHES", 3)

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
    OLLAMA_FORCE_KILL_ON_SHUTDOWN: bool = get_bool_env("OLLAMA_FORCE_KILL_ON_SHUTDOWN", False)
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
    REQUIRE_GPU:   bool  = get_bool_env("REQUIRE_GPU", True)
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

    # Embedding ve model yüklemeleri için VRAM fraksiyonu (0.1–0.99 bekleniyor, 1.0 dahil değil)
    GPU_MEMORY_FRACTION: float = get_float_env("GPU_MEMORY_FRACTION", 0.8)
    # Yerel LLM ve RAG için ayrı bellek bütçeleri (opsiyonel)
    LLM_GPU_MEMORY_FRACTION: float = get_float_env("LLM_GPU_MEMORY_FRACTION", GPU_MEMORY_FRACTION)
    RAG_GPU_MEMORY_FRACTION: float = get_float_env("RAG_GPU_MEMORY_FRACTION", max(0.1, min(0.5, GPU_MEMORY_FRACTION * 0.35)))

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
    REDIS_MAX_CONNECTIONS: int = get_int_env("REDIS_MAX_CONNECTIONS", 50)
    ENABLE_DEPENDENCY_HEALTHCHECKS: bool = get_bool_env("ENABLE_DEPENDENCY_HEALTHCHECKS", False)
    HEALTHCHECK_CONNECT_TIMEOUT_MS: int = get_int_env("HEALTHCHECK_CONNECT_TIMEOUT_MS", 250)
    # Güvenilir ters proxy IP listesi (virgülle ayrılmış); boşsa proxy başlıkları kabul edilmez
    TRUSTED_PROXIES: frozenset = frozenset(get_list_env("TRUSTED_PROXIES", ["127.0.0.1"]))
    TRUSTED_PROXIES_LIST: List[str] = sorted(TRUSTED_PROXIES)
    # RAG yükleme boyut limiti (varsayılan 50 MB)
    MAX_RAG_UPLOAD_BYTES: int = get_int_env("MAX_RAG_UPLOAD_BYTES", 50 * 1024 * 1024)
    # Metrics endpoint'leri için statik Bearer token (boşsa yalnızca admin kullanıcılar erişebilir)
    METRICS_TOKEN: str = os.getenv("METRICS_TOKEN", "")

    # ─── Veritabanı (v3.0 çoklu kullanıcı hazırlığı) ────────
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://sidar:sidar@localhost:5432/sidar")
    DB_POOL_SIZE: int = get_int_env("DB_POOL_SIZE", get_db_pool_size_default())
    DB_SCHEMA_VERSION_TABLE: str = os.getenv("DB_SCHEMA_VERSION_TABLE", "schema_versions")
    DB_SCHEMA_TARGET_VERSION: int = get_int_env("DB_SCHEMA_TARGET_VERSION", 1)

    # ─── Gözlemlenebilirlik (OpenTelemetry) ───────────────────
    ENABLE_TRACING:       bool = get_bool_env("ENABLE_TRACING", False)
    OTEL_EXPORTER_ENDPOINT: str = os.getenv("OTEL_EXPORTER_ENDPOINT", "http://jaeger:4317")
    OTEL_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "sidar")
    OTEL_INSTRUMENT_FASTAPI: bool = get_bool_env("OTEL_INSTRUMENT_FASTAPI", True)
    OTEL_INSTRUMENT_HTTPX: bool = get_bool_env("OTEL_INSTRUMENT_HTTPX", True)

    # ─── Semantic Cache (v4.0) ───────────────────────────────
    ENABLE_SEMANTIC_CACHE: bool = get_bool_env("ENABLE_SEMANTIC_CACHE", False)
    SEMANTIC_CACHE_THRESHOLD: float = get_float_env("SEMANTIC_CACHE_THRESHOLD", 0.95)
    SEMANTIC_CACHE_TTL: int = get_int_env("SEMANTIC_CACHE_TTL", 3600)
    SEMANTIC_CACHE_MAX_ITEMS: int = get_int_env("SEMANTIC_CACHE_MAX_ITEMS", 500)
    SIDAR_EVENT_BUS_DLQ_CHANNEL: str = os.getenv("SIDAR_EVENT_BUS_DLQ_CHANNEL", "sidar:agent_events:dlq")
    SIDAR_EVENT_BUS_DLQ_MAXLEN: int = get_int_env("SIDAR_EVENT_BUS_DLQ_MAXLEN", 1000)

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
    # Docker zorunlu mod: True ise Docker erişilemezse yerel subprocess fallback engellenir
    DOCKER_REQUIRED: bool = get_bool_env("DOCKER_REQUIRED", False)

    # ─── Bellek Şifrelemesi ───────────────────────────────────────
    # Boş bırakılırsa şifreleme devre dışı (varsayılan).
    # Fernet anahtarı üretmek için:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    MEMORY_ENCRYPTION_KEY: str = os.getenv("MEMORY_ENCRYPTION_KEY", "")

    # ─── Web Arayüzü ─────────────────────────────────────────
    WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
    WEB_PORT: int = get_int_env("WEB_PORT", 7860)
    WEB_GPU_PORT: int = get_int_env("WEB_GPU_PORT", 7861)

    # ─── JWT Kimlik Doğrulama ────────────────────────────────
    # JWT_SECRET_KEY boş bırakılırsa sunucu başlangıcında CRITICAL uyarısı verilir.
    JWT_SECRET_KEY:  str = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM:   str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_TTL_DAYS:    int = get_int_env("JWT_TTL_DAYS", 7)

    # ─── Observability Bağlantı Noktaları ───────────────────
    # GRAFANA_URL ayarlanmazsa varsayılan olarak yerel kurulum portu kullanılır.
    GRAFANA_URL: str = os.getenv("GRAFANA_URL", "http://localhost:3000")

    # ─── Multi-Agent geçiş ayarları ─────────────────────────
    REVIEWER_TEST_COMMAND: str = os.getenv("REVIEWER_TEST_COMMAND", "python -m pytest")

    # ─── DLP — Veri Kaybı Önleme ─────────────────────────────
    DLP_ENABLED: bool = get_bool_env("DLP_ENABLED", True)
    DLP_LOG_DETECTIONS: bool = get_bool_env("DLP_LOG_DETECTIONS", False)

    # ─── HITL — Human-in-the-Loop Onay Geçidi ────────────────
    HITL_ENABLED: bool = get_bool_env("HITL_ENABLED", False)
    HITL_TIMEOUT_SECONDS: int = get_int_env("HITL_TIMEOUT_SECONDS", 120)

    # ─── LLM-as-a-Judge Kalite Değerlendirmesi ────────────────
    JUDGE_ENABLED: bool = get_bool_env("JUDGE_ENABLED", False)
    JUDGE_MODEL: str = os.getenv("JUDGE_MODEL", "")
    JUDGE_PROVIDER: str = os.getenv("JUDGE_PROVIDER", "ollama")
    JUDGE_SAMPLE_RATE: float = float(os.getenv("JUDGE_SAMPLE_RATE", "0.2") or "0.2")

    # ─── Cost-Aware Model Routing (v5.0) ──────────────────────
    ENABLE_COST_ROUTING: bool = get_bool_env("ENABLE_COST_ROUTING", False)
    # 0.0–1.0: Bu eşiğin altındaki sorgular lokal modele yönlendirilir
    COST_ROUTING_COMPLEXITY_THRESHOLD: float = get_float_env("COST_ROUTING_COMPLEXITY_THRESHOLD", 0.55)
    # Lokal sağlayıcı (basit sorgular için)
    COST_ROUTING_LOCAL_PROVIDER: str = os.getenv("COST_ROUTING_LOCAL_PROVIDER", "ollama")
    COST_ROUTING_LOCAL_MODEL: str = os.getenv("COST_ROUTING_LOCAL_MODEL", "")
    # Bulut sağlayıcı (karmaşık sorgular için; boşsa varsayılan sağlayıcı kullanılır)
    COST_ROUTING_CLOUD_PROVIDER: str = os.getenv("COST_ROUTING_CLOUD_PROVIDER", "")
    COST_ROUTING_CLOUD_MODEL: str = os.getenv("COST_ROUTING_CLOUD_MODEL", "")
    # Bu günlük bütçe (USD) aşılırsa tüm sorgular lokal modele yönlendirilir
    COST_ROUTING_DAILY_BUDGET_USD: float = get_float_env("COST_ROUTING_DAILY_BUDGET_USD", 1.0)
    # Tek bir isteğin yaklaşık token eşiği; aşılırsa lokal modele fallback uygulanır.
    COST_ROUTING_TOKEN_THRESHOLD: int = get_int_env("COST_ROUTING_TOKEN_THRESHOLD", 0)

    # ─── Entity/Persona Memory (v5.0) ─────────────────────────
    ENABLE_ENTITY_MEMORY: bool = get_bool_env("ENABLE_ENTITY_MEMORY", True)
    # Güncellenmemiş kayıtların saklanma süresi (gün); 0 = sonsuz
    ENTITY_MEMORY_TTL_DAYS: int = get_int_env("ENTITY_MEMORY_TTL_DAYS", 90)
    # Kullanıcı başına maksimum persona anahtarı sayısı (LRU eviction)
    ENTITY_MEMORY_MAX_PER_USER: int = get_int_env("ENTITY_MEMORY_MAX_PER_USER", 100)

    # ─── Active Learning + LoRA/QLoRA (v6.0) ────────────────────
    ENABLE_ACTIVE_LEARNING: bool = get_bool_env("ENABLE_ACTIVE_LEARNING", True)
    # Minimum geri bildirim puanı (bu değer ve üzeri export edilir)
    AL_MIN_RATING_FOR_TRAIN: int = get_int_env("AL_MIN_RATING_FOR_TRAIN", 1)
    # LoRA eğitimini etkinleştir (peft/transformers gerektirir)
    ENABLE_LORA_TRAINING: bool = get_bool_env("ENABLE_LORA_TRAINING", False)
    # Fine-tuning için temel model (HuggingFace hub ID)
    LORA_BASE_MODEL: str = os.getenv("LORA_BASE_MODEL", "")
    LORA_RANK: int = get_int_env("LORA_RANK", 8)
    LORA_ALPHA: int = get_int_env("LORA_ALPHA", 16)
    LORA_DROPOUT: float = get_float_env("LORA_DROPOUT", 0.05)
    LORA_EPOCHS: int = get_int_env("LORA_EPOCHS", 3)
    LORA_BATCH_SIZE: int = get_int_env("LORA_BATCH_SIZE", 4)
    LORA_USE_4BIT: bool = get_bool_env("LORA_USE_4BIT", True)
    LORA_OUTPUT_DIR: str = os.getenv("LORA_OUTPUT_DIR", "data/lora_adapters")
    # Ar-Ge: Judge/feedback sinyallerinden sürekli öğrenme bundle'ı üret
    ENABLE_CONTINUOUS_LEARNING: bool = get_bool_env("ENABLE_CONTINUOUS_LEARNING", False)
    CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES: int = get_int_env("CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES", 20)
    CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES: int = get_int_env("CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES", 10)
    CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS: int = get_int_env("CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS", 5000)
    CONTINUOUS_LEARNING_COOLDOWN_SECONDS: int = get_int_env("CONTINUOUS_LEARNING_COOLDOWN_SECONDS", 3600)
    CONTINUOUS_LEARNING_OUTPUT_DIR: str = os.getenv("CONTINUOUS_LEARNING_OUTPUT_DIR", "data/continuous_learning")
    CONTINUOUS_LEARNING_SFT_FORMAT: str = os.getenv("CONTINUOUS_LEARNING_SFT_FORMAT", "alpaca")

    # ─── Multimodal Vision (v6.0) ───────────────────────────────
    ENABLE_VISION: bool = get_bool_env("ENABLE_VISION", True)
    # Maksimum görsel boyutu (byte) — varsayılan 10 MB
    VISION_MAX_IMAGE_BYTES: int = get_int_env("VISION_MAX_IMAGE_BYTES", 10485760)
    ENABLE_MULTIMODAL: bool = get_bool_env("ENABLE_MULTIMODAL", True)
    MULTIMODAL_MAX_FILE_BYTES: int = get_int_env("MULTIMODAL_MAX_FILE_BYTES", 52428800)
    VOICE_STT_PROVIDER: str = os.getenv("VOICE_STT_PROVIDER", "whisper")
    VOICE_TTS_PROVIDER: str = os.getenv("VOICE_TTS_PROVIDER", "auto")
    VOICE_TTS_VOICE: str = os.getenv("VOICE_TTS_VOICE", "")
    VOICE_TTS_SEGMENT_CHARS: int = get_int_env("VOICE_TTS_SEGMENT_CHARS", 48)
    VOICE_TTS_BUFFER_CHARS: int = get_int_env("VOICE_TTS_BUFFER_CHARS", 96)
    VOICE_VAD_ENABLED: bool = get_bool_env("VOICE_VAD_ENABLED", True)
    VOICE_VAD_MIN_SPEECH_BYTES: int = get_int_env("VOICE_VAD_MIN_SPEECH_BYTES", 1024)
    VOICE_DUPLEX_ENABLED: bool = get_bool_env("VOICE_DUPLEX_ENABLED", True)
    VOICE_VAD_INTERRUPT_MIN_BYTES: int = get_int_env("VOICE_VAD_INTERRUPT_MIN_BYTES", 384)
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")
    VOICE_WS_MAX_BYTES: int = get_int_env("VOICE_WS_MAX_BYTES", 10485760)
    BROWSER_PROVIDER: str = os.getenv("BROWSER_PROVIDER", "auto")
    BROWSER_HEADLESS: bool = get_bool_env("BROWSER_HEADLESS", True)
    BROWSER_TIMEOUT_MS: int = get_int_env("BROWSER_TIMEOUT_MS", 15000)
    BROWSER_ALLOWED_DOMAINS: list[str] = get_list_env("BROWSER_ALLOWED_DOMAINS", [])
    ENABLE_LSP: bool = get_bool_env("ENABLE_LSP", True)
    LSP_TIMEOUT_SECONDS: int = get_int_env("LSP_TIMEOUT_SECONDS", 15)
    LSP_MAX_REFERENCES: int = get_int_env("LSP_MAX_REFERENCES", 200)
    PYTHON_LSP_SERVER: str = os.getenv("PYTHON_LSP_SERVER", "pyright-langserver")
    TYPESCRIPT_LSP_SERVER: str = os.getenv("TYPESCRIPT_LSP_SERVER", "typescript-language-server")
    ENABLE_AUTONOMOUS_CRON: bool = get_bool_env("ENABLE_AUTONOMOUS_CRON", False)
    AUTONOMOUS_CRON_INTERVAL_SECONDS: int = get_int_env("AUTONOMOUS_CRON_INTERVAL_SECONDS", 900)
    AUTONOMOUS_CRON_PROMPT: str = os.getenv(
        "AUTONOMOUS_CRON_PROMPT",
        "Sistemdeki bekleyen otonom iş fırsatlarını değerlendir ve gerekli aksiyon planını çıkar.",
    )
    ENABLE_NIGHTLY_MEMORY_PRUNING: bool = get_bool_env("ENABLE_NIGHTLY_MEMORY_PRUNING", False)
    NIGHTLY_MEMORY_INTERVAL_SECONDS: int = get_int_env("NIGHTLY_MEMORY_INTERVAL_SECONDS", 86400)
    NIGHTLY_MEMORY_IDLE_SECONDS: int = get_int_env("NIGHTLY_MEMORY_IDLE_SECONDS", 1800)
    NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS: int = get_int_env("NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS", 2)
    NIGHTLY_MEMORY_SESSION_MIN_MESSAGES: int = get_int_env("NIGHTLY_MEMORY_SESSION_MIN_MESSAGES", 12)
    NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS: int = get_int_env("NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS", 2)
    ENABLE_EVENT_WEBHOOKS: bool = get_bool_env("ENABLE_EVENT_WEBHOOKS", True)
    AUTONOMY_WEBHOOK_SECRET: str = os.getenv("AUTONOMY_WEBHOOK_SECRET", "")
    ENABLE_SWARM_FEDERATION: bool = get_bool_env("ENABLE_SWARM_FEDERATION", True)
    SWARM_FEDERATION_SHARED_SECRET: str = os.getenv("SWARM_FEDERATION_SHARED_SECRET", "")
    ENABLE_GRAPH_RAG: bool = get_bool_env("ENABLE_GRAPH_RAG", True)
    GRAPH_RAG_MAX_FILES: int = get_int_env("GRAPH_RAG_MAX_FILES", 5000)

    # ─── Slack Entegrasyonu (v6.0) ──────────────────────────────
    SLACK_TOKEN: str = os.getenv("SLACK_TOKEN", "")
    SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")
    SLACK_DEFAULT_CHANNEL: str = os.getenv("SLACK_DEFAULT_CHANNEL", "")

    # ─── Jira Entegrasyonu (v6.0) ───────────────────────────────
    JIRA_URL: str = os.getenv("JIRA_URL", "")
    JIRA_TOKEN: str = os.getenv("JIRA_TOKEN", "")
    JIRA_EMAIL: str = os.getenv("JIRA_EMAIL", "")
    JIRA_DEFAULT_PROJECT: str = os.getenv("JIRA_DEFAULT_PROJECT", "")
    # Geriye dönük/alternatif adlandırma uyumluluğu
    JIRA_BASE_URL: str = os.getenv("JIRA_BASE_URL", JIRA_URL)
    JIRA_API_TOKEN: str = os.getenv("JIRA_API_TOKEN", JIRA_TOKEN)

    # ─── Microsoft Teams Entegrasyonu (v6.0) ────────────────────
    TEAMS_WEBHOOK_URL: str = os.getenv("TEAMS_WEBHOOK_URL", "")

    # ─────────────────────────────────────────────────────────
    #  METOTLAR
    # ─────────────────────────────────────────────────────────

    def __init__(self) -> None:
        # Donanım bilgisini import anında değil, ilk Config kullanımında yükle.
        self.__class__._ensure_hardware_info_loaded()
        self.__class__._apply_gpu_memory_safety_check()
        if not str(self.JWT_SECRET_KEY or "").strip() and not self._is_test_env():
            raise ValueError("JWT_SECRET_KEY boş bırakılamaz. .env dosyasını kontrol edin.")


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
    def trusted_proxies_as_list(cls) -> List[str]:
        """Middleware entegrasyonları için güvenilir proxy değerlerini list[str] verir."""
        return list(cls.TRUSTED_PROXIES_LIST)

    @classmethod
    def _is_test_env(cls) -> bool:
        sidar_env = os.getenv("SIDAR_ENV", "").strip().lower()
        if sidar_env in {"test", "testing"}:
            return True
        return bool(os.getenv("PYTEST_CURRENT_TEST"))

    @classmethod
    def _apply_gpu_memory_safety_check(cls) -> None:
        """LLM+RAG VRAM fraksiyonu 1.0'ı aşarsa toplamı güvenli 0.8'e normalize eder."""
        llm = float(cls.LLM_GPU_MEMORY_FRACTION or 0.0)
        rag = float(cls.RAG_GPU_MEMORY_FRACTION or 0.0)
        total = llm + rag

        target_total = 0.8
        if total <= 0:
            cls.LLM_GPU_MEMORY_FRACTION = 0.4
            cls.RAG_GPU_MEMORY_FRACTION = 0.4
            cls.GPU_MEMORY_FRACTION = target_total
            return

        if total <= 1.0:
            return

        scale = target_total / total
        normalized_llm = max(0.05, llm * scale)
        normalized_rag = max(0.05, rag * scale)
        normalized_total = normalized_llm + normalized_rag

        # Min floor nedeniyle hedef toplamın üstüne çıkarsa oranı koruyarak tekrar ölçekle.
        if normalized_total > target_total:
            second_scale = target_total / normalized_total
            normalized_llm *= second_scale
            normalized_rag *= second_scale

        cls.LLM_GPU_MEMORY_FRACTION = round(normalized_llm, 4)
        cls.RAG_GPU_MEMORY_FRACTION = round(normalized_rag, 4)
        cls.GPU_MEMORY_FRACTION = round(target_total, 4)
        logger.warning(
            "LLM/RAG GPU bellek fraksiyonları toplamı %.2f bulundu; OOM riskini azaltmak için %.2f toplamına normalize edildi "
            "(LLM=%.2f, RAG=%.2f).",
            total,
            target_total,
            cls.LLM_GPU_MEMORY_FRACTION,
            cls.RAG_GPU_MEMORY_FRACTION,
        )

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
        cls._apply_gpu_memory_safety_check()
        cls.initialize_directories()

        if cls.REQUIRE_GPU and not cls.USE_GPU:
            logger.error(
                "❌ GPU zorunlu mod aktif (REQUIRE_GPU=true) ancak CUDA/PyTorch uygun değil veya USE_GPU=false.\n"
                "   Çözüm: CUDA destekli PyTorch kurun ve .env içinde USE_GPU=true yapın."
            )
            is_valid = False

        if cls.AI_PROVIDER == "gemini" and not cls.GEMINI_API_KEY:
            logger.error(
                "❌ Gemini modu seçili ama GEMINI_API_KEY ayarlanmamış!\n"
                "   .env dosyasını kontrol edin."
            )
            is_valid = False

        memory_encryption_key = (cls.MEMORY_ENCRYPTION_KEY or "").strip()

        if memory_encryption_key:
            try:
                from cryptography.fernet import Fernet  # noqa: F401
                # Anahtarı ön doğrulama — geçersiz formatta erken hata ver
                try:
                    Fernet(memory_encryption_key.encode())
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
        else:
            logger.critical(
                "MEMORY_ENCRYPTION_KEY is not set. Please generate a valid Fernet key for memory encryption. "
                "Konuşma geçmişi şifrelenmeden saklanıyor. Üretim ortamında .env dosyasına güçlü bir Fernet "
                "anahtarı eklemelisiniz.\n"
                "   Yeni anahtar üretmek için: python -c \"from cryptography.fernet import "
                "Fernet; print(Fernet.generate_key().decode())\""
            )
            if os.getenv("SIDAR_ENV", "").strip().lower() == "production":
                logger.critical(
                    "SIDAR_ENV=production iken MEMORY_ENCRYPTION_KEY zorunludur. Güvenlik nedeniyle uygulama durduruluyor."
                )
                raise SystemExit(1)

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
            "gpu_memory_fraction": cls.GPU_MEMORY_FRACTION,
            "llm_gpu_memory_fraction": cls.LLM_GPU_MEMORY_FRACTION,
            "rag_gpu_memory_fraction": cls.RAG_GPU_MEMORY_FRACTION,
            "cpu_count":          cls.CPU_COUNT,
            "debug_mode":         cls.DEBUG_MODE,
            "web_port":           cls.WEB_PORT,
            "web_gpu_port":       cls.WEB_GPU_PORT,
            "hf_hub_offline":     cls.HF_HUB_OFFLINE,
            "rate_limit_window":  cls.RATE_LIMIT_WINDOW,
            "rate_limit_chat":    cls.RATE_LIMIT_CHAT,
            "rate_limit_mutations": cls.RATE_LIMIT_MUTATIONS,
            "rate_limit_get_io":  cls.RATE_LIMIT_GET_IO,
            # REDIS_URL burada yer almaz — host/port/kimlik bilgisi ifşasını önlemek için
            "enable_tracing":     cls.ENABLE_TRACING,
            "otel_exporter_endpoint": cls.OTEL_EXPORTER_ENDPOINT,
            "enable_semantic_cache": cls.ENABLE_SEMANTIC_CACHE,
            "semantic_cache_threshold": cls.SEMANTIC_CACHE_THRESHOLD,
            "semantic_cache_ttl": cls.SEMANTIC_CACHE_TTL,
            "semantic_cache_max_items": cls.SEMANTIC_CACHE_MAX_ITEMS,
        }

    @classmethod
    def init_telemetry(
        cls,
        *,
        service_name: Optional[str] = None,
        fastapi_app=None,
        logger_obj: Optional[logging.Logger] = None,
        trace_module=_DEPENDENCY_AUTO,
        otlp_exporter_cls=_DEPENDENCY_AUTO,
        tracer_provider_cls=_DEPENDENCY_AUTO,
        resource_cls=_DEPENDENCY_AUTO,
        batch_span_processor_cls=_DEPENDENCY_AUTO,
        fastapi_instrumentor_cls=_DEPENDENCY_AUTO,
        httpx_instrumentor_cls=_DEPENDENCY_AUTO,
    ) -> bool:
        """OpenTelemetry tracing + opsiyonel FastAPI/HTTPX enstrümantasyonunu başlat."""
        log = logger_obj or logger
        if not cls.ENABLE_TRACING:
            return False

        if (
            trace_module is None
            or otlp_exporter_cls is None
            or tracer_provider_cls is None
            or resource_cls is None
            or batch_span_processor_cls is None
        ):
            log.warning("ENABLE_TRACING açık fakat OpenTelemetry bağımlılıkları yüklenemedi.")
            return False

        try:
            if trace_module is _DEPENDENCY_AUTO:
                from opentelemetry import trace as trace_module
            if otlp_exporter_cls is _DEPENDENCY_AUTO:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as otlp_exporter_cls
            if tracer_provider_cls is _DEPENDENCY_AUTO:
                from opentelemetry.sdk.trace import TracerProvider as tracer_provider_cls
            if resource_cls is _DEPENDENCY_AUTO:
                from opentelemetry.sdk.resources import Resource as resource_cls
            if batch_span_processor_cls is _DEPENDENCY_AUTO:
                from opentelemetry.sdk.trace.export import BatchSpanProcessor as batch_span_processor_cls
        except Exception:
            log.warning("ENABLE_TRACING açık fakat OpenTelemetry bağımlılıkları yüklenemedi.")
            return False

        try:
            svc_name = service_name or cls.OTEL_SERVICE_NAME or "sidar"
            resource = resource_cls.create({"service.name": svc_name})
            provider = tracer_provider_cls(resource=resource)
            exporter = otlp_exporter_cls(endpoint=cls.OTEL_EXPORTER_ENDPOINT, insecure=True)
            provider.add_span_processor(batch_span_processor_cls(exporter))
            trace_module.set_tracer_provider(provider)

            if fastapi_app is not None and cls.OTEL_INSTRUMENT_FASTAPI:
                if fastapi_instrumentor_cls is _DEPENDENCY_AUTO:
                    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor as fastapi_instrumentor_cls
                fastapi_instrumentor_cls.instrument_app(fastapi_app)

            if cls.OTEL_INSTRUMENT_HTTPX:
                if httpx_instrumentor_cls is _DEPENDENCY_AUTO:
                    try:
                        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor as httpx_instrumentor_cls
                    except Exception:
                        httpx_instrumentor_cls = None
                if httpx_instrumentor_cls is not None:
                    with contextlib.suppress(Exception):
                        httpx_instrumentor_cls().instrument()

            log.info("✅ OpenTelemetry aktif: %s", cls.OTEL_EXPORTER_ENDPOINT)
            return True
        except Exception as exc:
            log.warning("OpenTelemetry başlatılamadı: %s", exc)
            return False

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
            print(f"  LLM VRAM Payı    : {cls.LLM_GPU_MEMORY_FRACTION:.2f}")
            print(f"  RAG VRAM Payı    : {cls.RAG_GPU_MEMORY_FRACTION:.2f}")
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
# SINGLETON — Bulgu D: Config() tekrar çağrısı kaynak israfı
# ═══════════════════════════════════════════════════════════════
_config_instance: "Config | None" = None


def get_config() -> "Config":
    """Proses genelinde tek Config örneği döndürür (thread-safe, lazy)."""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


# ═══════════════════════════════════════════════════════════════
# BAŞLANGIÇ
# ═══════════════════════════════════════════════════════════════
logger.info("✅ %s v%s yapılandırması yüklendi.", Config.PROJECT_NAME, Config.VERSION)

if __name__ == "__main__":
    Config.initialize_directories()
    if Config.DEBUG_MODE:
        Config.print_config_summary()
