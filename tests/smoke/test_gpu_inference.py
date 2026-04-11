"""GPU-odaklı smoke testleri."""

from __future__ import annotations

import os
import shutil

import pytest

from core.llm_client import OllamaClient
from tests.helpers import make_test_config

def is_gpu_available() -> bool:
    if shutil.which("nvidia-smi") is not None:
        return True
    # WSL2 özel CUDA yolu kontrolü
    if os.path.exists("/usr/lib/wsl/lib/nvidia-smi"):
        return True
    return False


pytestmark = pytest.mark.skipif(
    not is_gpu_available(),
    reason="Sistemde veya WSL2 katmanında NVIDIA GPU bulunamadı, GPU smoke testi atlanıyor.",
)


@pytest.mark.gpu
@pytest.mark.asyncio
async def test_real_gpu_inference_smoke() -> None:
    """GPU mevcutsa, Ollama çağrısının GPU bayrağı ile temel yanıt döndürdüğünü doğrular."""
    if not shutil.which("ollama"):
        pytest.skip("Sistemde 'ollama' komutu bulunamadı.")

    cfg = make_test_config(
        USE_GPU=True,
        OLLAMA_URL="http://localhost:11434",
        OLLAMA_TIMEOUT=30,
        CODING_MODEL="qwen2.5-coder:1.5b",
    )
    client = OllamaClient(cfg)

    is_available = await client.is_available()
    if not is_available:
        pytest.skip("Ollama servisine ulaşılamıyor.")

    installed_models = await client.list_models()
    if "qwen2.5-coder:1.5b" not in installed_models:
        pytest.skip("qwen2.5-coder:1.5b modeli yüklü değil.")

    response = await client.chat(
        messages=[{"role": "user", "content": "Sadece 'GPU Çalışıyor' yaz."}],
        model="qwen2.5-coder:1.5b",
        json_mode=False,
    )

    assert isinstance(response, str)
    assert len(response.strip()) > 0
