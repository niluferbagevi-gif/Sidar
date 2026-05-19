from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from config import Config

_config_get_config: Callable[[], Config] | None
try:
    from config import get_config as _config_get_config
except ImportError:  # pragma: no cover - test doubles may only expose Config
    _config_get_config = None

logger = logging.getLogger(__name__)


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def sentence_transformer_device_from_config(cfg: Any) -> str:
    """Resolve the explicit SentenceTransformer device from Sidar GPU config."""
    if not _as_bool(getattr(cfg, "USE_GPU", False)):
        return "cpu"
    return f"cuda:{getattr(cfg, 'GPU_DEVICE', 0)}"


def _hf_hub_cache_roots() -> list[Path]:
    roots: list[Path] = []
    for env_name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE"):
        raw = os.getenv(env_name, "").strip()
        if raw:
            roots.append(Path(raw).expanduser())

    hf_home = Path(os.getenv("HF_HOME", "~/.cache/huggingface")).expanduser()
    roots.append(hf_home / "hub")
    roots.append(Path("~/.cache/huggingface/hub").expanduser())

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _hf_model_cache_dir_names(model_name: str) -> list[str]:
    normalized = model_name.strip()
    candidates = [normalized]
    if "/" not in normalized:
        candidates.append(f"sentence-transformers/{normalized}")
    return ["models--" + candidate.replace("/", "--") for candidate in candidates]


def hf_model_cache_exists(model_name: str) -> bool:
    """Return True when a HuggingFace Hub cache directory exists for a model."""
    normalized = str(model_name or "").strip()
    if not normalized:
        return False
    if Path(normalized).expanduser().exists():
        return True
    cache_dir_names = _hf_model_cache_dir_names(normalized)
    return any((root / cache_dir).exists() for root in _hf_hub_cache_roots() for cache_dir in cache_dir_names)


def sentence_transformer_local_files_only(cfg: Any, model_name: str) -> bool:
    """Decide whether SentenceTransformer should avoid HF Hub network checks."""
    if _as_bool(getattr(cfg, "HF_USE_LOCAL_CACHE_ONLY", False)):
        return True
    if _as_bool(getattr(cfg, "HF_HUB_OFFLINE", False)):
        return True
    return hf_model_cache_exists(model_name)


@contextmanager
def _scoped_hf_runtime_env() -> Any:
    keys = ("HF_HUB_DISABLE_PROGRESS_BARS", "TRANSFORMERS_VERBOSITY")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        os.environ["TRANSFORMERS_VERBOSITY"] = "error"
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def embed_texts_for_semantic_cache(
    texts: list[str], cfg: Config | None = None
) -> list[list[float]]:
    """Semantic cache için metinleri normalize edilmiş embedding vektörlerine dönüştürür."""
    if not texts:
        return []

    cfg = cfg or (_config_get_config() if callable(_config_get_config) else Config())
    model_name = str(
        getattr(cfg, "PGVECTOR_EMBEDDING_MODEL", "all-MiniLM-L6-v2") or "all-MiniLM-L6-v2"
    )
    try:
        from sentence_transformers import SentenceTransformer

        with _scoped_hf_runtime_env():
            model = SentenceTransformer(
                model_name,
                device=sentence_transformer_device_from_config(cfg),
                local_files_only=sentence_transformer_local_files_only(cfg, model_name),
            )
        vectors = model.encode(texts, normalize_embeddings=True)
        raw = vectors.tolist() if hasattr(vectors, "tolist") else [list(v) for v in vectors]
        return cast("list[list[float]]", raw)
    except Exception as exc:
        logger.debug("Semantic cache embedding üretilemedi: %s", exc)
        return []
