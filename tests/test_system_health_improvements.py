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