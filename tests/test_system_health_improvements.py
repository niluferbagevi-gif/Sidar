# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

from pathlib import Path


def test_cpu_usage_supports_non_blocking_interval_override():
    src = Path("managers/system_health.py").read_text(encoding="utf-8")
    assert "cpu_sample_interval: float = 0.0" in src
    assert "def get_cpu_usage(self, interval: Optional[float] = None)" in src
    assert "sample_interval = self.cpu_sample_interval if interval is None else max(0.0, interval)" in src


def test_nvml_cleanup_has_explicit_close_and_atexit_registration():
    src = Path("managers/system_health.py").read_text(encoding="utf-8")
    assert "atexit.register(self.close)" in src
    assert "def close(self) -> None:" in src
    assert "self._nvml_initialized = False" in src

def test_system_health_ollama_timeout_and_prometheus_hooks_present():
    src = Path("managers/system_health.py").read_text(encoding="utf-8")
    assert "def check_ollama(self) -> bool:" in src
    assert "getattr(self.cfg, \"OLLAMA_URL\", \"http://localhost:11434/api\")" in src
    assert "getattr(self.cfg, \"OLLAMA_TIMEOUT\", 5)" in src
    assert "requests.get(f\"{base_url.rstrip('/')}/tags\", timeout=timeout)" in src
    assert "def update_prometheus_metrics(self, metrics_dict: Dict[str, float]) -> None:" in src
    assert "sidar_system_cpu_percent" in src
    assert "self.update_prometheus_metrics({" in src

def test_system_health_exposes_structured_health_summary():
    src = Path("managers/system_health.py").read_text(encoding="utf-8")
    assert "def get_health_summary(self) -> dict:" in src
    assert '"status": "healthy"' in src
    assert '"ollama_online": self.check_ollama()' in src
    assert '"python_version": platform.python_version()' in src

def test_system_health_has_llm_prometheus_renderer():
    src = Path("managers/system_health.py").read_text(encoding="utf-8")
    assert "def render_llm_metrics_prometheus(snapshot" in src
    assert "sidar_llm_cost_total_usd" in src
    assert "sidar_llm_user_calls_total" in src