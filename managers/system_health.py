"""
Sidar Project — Sistem Sağlığı Yöneticisi
Sürüm: 2.7.0 (GPU Genişletilmiş İzleme)

Özellikler:
- CPU kullanımı (psutil)
- RAM kullanımı (psutil)
- GPU: cihaz adı, VRAM, CUDA sürümü, driver sürümü (torch.cuda + pynvml)
- GPU sıcaklık & anlık kullanım yüzdesi (nvidia-ml-py / pynvml — opsiyonel)
- GPU VRAM temizleme (torch.cuda.empty_cache + gc)
"""

import atexit
import gc
import logging
import platform
import socket
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlparse

from config import Config

logger = logging.getLogger(__name__)


def render_llm_metrics_prometheus(snapshot: dict[str, object]) -> str:
    """LLM metrik snapshot'unu Prometheus text formatına çevirir."""
    lines: list[str] = [
        "# HELP sidar_llm_calls_total Toplam LLM çağrı sayısı",
        "# TYPE sidar_llm_calls_total counter",
        "# HELP sidar_llm_cost_total_usd Toplam LLM maliyeti (USD)",
        "# TYPE sidar_llm_cost_total_usd counter",
        "# HELP sidar_llm_tokens_total Toplam LLM token sayısı",
        "# TYPE sidar_llm_tokens_total counter",
        "# HELP sidar_llm_failures_total Toplam başarısız LLM çağrısı",
        "# TYPE sidar_llm_failures_total counter",
        "# HELP sidar_semantic_cache_hits_total Semantic cache isabet sayısı",
        "# TYPE sidar_semantic_cache_hits_total counter",
        "# HELP sidar_semantic_cache_misses_total Semantic cache ıskalama sayısı",
        "# TYPE sidar_semantic_cache_misses_total counter",
        "# HELP sidar_semantic_cache_skips_total Semantic cache skip sayısı",
        "# TYPE sidar_semantic_cache_skips_total counter",
        "# HELP sidar_semantic_cache_evictions_total Semantic cache LRU eviction sayısı",
        "# TYPE sidar_semantic_cache_evictions_total counter",
        "# HELP sidar_semantic_cache_redis_errors_total Semantic cache Redis hata sayısı",
        "# TYPE sidar_semantic_cache_redis_errors_total counter",
        "# HELP sidar_semantic_cache_circuit_open_total Semantic cache circuit-open bypass sayısı",
        "# TYPE sidar_semantic_cache_circuit_open_total counter",
        "# HELP sidar_semantic_cache_hit_rate Semantic cache isabet oranı (0.0–1.0)",
        "# TYPE sidar_semantic_cache_hit_rate gauge",
        "# HELP sidar_semantic_cache_items Semantic cache içindeki aktif kayıt sayısı",
        "# TYPE sidar_semantic_cache_items gauge",
        "# HELP sidar_semantic_cache_redis_latency_ms Semantic cache için son Redis erişim gecikmesi (ms)",
        "# TYPE sidar_semantic_cache_redis_latency_ms gauge",
        "# HELP sidar_cache_hits_total Legacy alias for semantic cache isabet sayısı",
        "# TYPE sidar_cache_hits_total counter",
        "# HELP sidar_cache_misses_total Legacy alias for semantic cache ıskalama sayısı",
        "# TYPE sidar_cache_misses_total counter",
        "# HELP sidar_cache_skips_total Legacy alias for semantic cache skip sayısı",
        "# TYPE sidar_cache_skips_total counter",
        "# HELP sidar_cache_evictions_total Legacy alias for semantic cache LRU eviction sayısı",
        "# TYPE sidar_cache_evictions_total counter",
        "# HELP sidar_cache_redis_errors_total Legacy alias for semantic cache Redis hata sayısı",
        "# TYPE sidar_cache_redis_errors_total counter",
        "# HELP sidar_cache_circuit_open_total Legacy alias for semantic cache circuit-open bypass sayısı",
        "# TYPE sidar_cache_circuit_open_total counter",
        "# HELP sidar_cache_hit_rate Legacy alias for semantic cache isabet oranı (0.0–1.0)",
        "# TYPE sidar_cache_hit_rate gauge",
        "# HELP sidar_cache_items Legacy alias for semantic cache içindeki aktif kayıt sayısı",
        "# TYPE sidar_cache_items gauge",
        "# HELP sidar_cache_redis_latency_ms Legacy alias for semantic cache son Redis erişim gecikmesi (ms)",
        "# TYPE sidar_cache_redis_latency_ms gauge",
    ]

    totals = (snapshot or {}).get("totals", {}) if isinstance(snapshot, dict) else {}
    lines.append(f"sidar_llm_calls_total {int(totals.get('calls', 0) or 0)}")
    lines.append(f"sidar_llm_cost_total_usd {float(totals.get('cost_usd', 0.0) or 0.0)}")
    lines.append(f"sidar_llm_tokens_total {int(totals.get('total_tokens', 0) or 0)}")
    lines.append(f"sidar_llm_failures_total {int(totals.get('failures', 0) or 0)}")

    # Semantic cache metrikleri
    cache = (snapshot or {}).get("cache", {}) if isinstance(snapshot, dict) else {}
    hits = int(cache.get("hits", 0) or 0)
    misses = int(cache.get("misses", 0) or 0)
    skips = int(cache.get("skips", 0) or 0)
    evictions = int(cache.get("evictions", 0) or 0)
    redis_errors = int(cache.get("redis_errors", 0) or 0)
    circuit_open_bypasses = int(cache.get("circuit_open_bypasses", 0) or 0)
    hit_rate = float(cache.get("hit_rate", 0.0) or 0.0)
    items = int(cache.get("items", 0) or 0)
    redis_latency_ms = float(cache.get("redis_latency_ms", 0.0) or 0.0)

    lines.append(f"sidar_semantic_cache_hits_total {hits}")
    lines.append(f"sidar_semantic_cache_misses_total {misses}")
    lines.append(f"sidar_semantic_cache_skips_total {skips}")
    lines.append(f"sidar_semantic_cache_evictions_total {evictions}")
    lines.append(f"sidar_semantic_cache_redis_errors_total {redis_errors}")
    lines.append(f"sidar_semantic_cache_circuit_open_total {circuit_open_bypasses}")
    lines.append(f"sidar_semantic_cache_hit_rate {hit_rate}")
    lines.append(f"sidar_semantic_cache_items {items}")
    lines.append(f"sidar_semantic_cache_redis_latency_ms {redis_latency_ms}")

    # Legacy alias'ları kısa vadeli dashboard/backward-compat için koru.
    lines.append(f"sidar_cache_hits_total {hits}")
    lines.append(f"sidar_cache_misses_total {misses}")
    lines.append(f"sidar_cache_skips_total {skips}")
    lines.append(f"sidar_cache_evictions_total {evictions}")
    lines.append(f"sidar_cache_redis_errors_total {redis_errors}")
    lines.append(f"sidar_cache_circuit_open_total {circuit_open_bypasses}")
    lines.append(f"sidar_cache_hit_rate {hit_rate}")
    lines.append(f"sidar_cache_items {items}")
    lines.append(f"sidar_cache_redis_latency_ms {redis_latency_ms}")

    by_provider = snapshot.get("by_provider", {}) if isinstance(snapshot, dict) else {}
    for provider, row in by_provider.items():
        p = str(provider or "unknown").replace('"', '\\"')
        lines.append(f'sidar_llm_calls_total{{provider="{p}"}} {int(row.get("calls", 0) or 0)}')
        lines.append(
            f'sidar_llm_cost_total_usd{{provider="{p}"}} {float(row.get("cost_usd", 0.0) or 0.0)}'
        )
        lines.append(
            f'sidar_llm_tokens_total{{provider="{p}"}} {int(row.get("total_tokens", 0) or 0)}'
        )
        lines.append(
            f'sidar_llm_failures_total{{provider="{p}"}} {int(row.get("failures", 0) or 0)}'
        )
        lines.append(
            f'sidar_llm_latency_ms_avg{{provider="{p}"}} {float(row.get("latency_ms_avg", 0.0) or 0.0)}'
        )

    by_user = snapshot.get("by_user", {}) if isinstance(snapshot, dict) else {}
    for user_id, row in by_user.items():
        uid = str(user_id or "anonymous").replace('"', '\\"')
        lines.append(
            f'sidar_llm_user_calls_total{{user_id="{uid}"}} {int(row.get("calls", 0) or 0)}'
        )
        lines.append(
            f'sidar_llm_user_cost_total_usd{{user_id="{uid}"}} {float(row.get("cost_usd", 0.0) or 0.0)}'
        )
        lines.append(
            f'sidar_llm_user_tokens_total{{user_id="{uid}"}} {int(row.get("total_tokens", 0) or 0)}'
        )

    return "\n".join(lines) + "\n"


class SystemHealthManager:
    """
    Donanım sağlığını izler, raporlar ve GPU belleğini optimize eder.
    nvidia-ml-py (pynvml) kuruluysa GPU sıcaklık/kullanım verisi de sağlar.
    """

    def __init__(
        self,
        use_gpu: bool = True,
        cpu_sample_interval: float = 0.0,
        cfg: Config | None = None,
    ) -> None:
        self.cfg = cfg or Config()
        self.use_gpu = use_gpu
        self._lock = threading.RLock()
        # Varsayılan 0.0 ile bloklamayan örnekleme (psutil.cpu_percent(interval=0.0))
        # Aralığı 0.0–2.0 sn arasında sınırla.
        self.cpu_sample_interval = max(0.0, min(float(cpu_sample_interval), 2.0))

        # Bağımlılık kontrolleri
        self._torch_available = self._check_import("torch")
        self._psutil_available = self._check_import("psutil")
        self._pynvml_available = self._check_import("pynvml")

        self._gpu_available = self._check_gpu()

        # pynvml başlat (sıcaklık / kullanım için)
        self._nvml_initialized = False
        if self._pynvml_available and self._gpu_available:
            self._init_nvml()

        # __del__ her zaman deterministik çalışmayabileceği için, çıkışta da temizlik dene.
        atexit.register(self.close)

        # Prometheus gauge cache (opsiyonel; prometheus_client yoksa None kalır).
        self._prometheus_gauges: dict[str, object] | None = None

    # ─────────────────────────────────────────────
    #  BAŞLANGIÇ KONTROLLERI
    # ─────────────────────────────────────────────

    @staticmethod
    def _check_import(module_name: str) -> bool:
        import importlib

        try:
            importlib.import_module(module_name)
            return True
        except Exception:
            return False

    def _check_gpu(self) -> bool:
        if not self.use_gpu or not self._torch_available:
            return False
        try:
            import torch

            return torch.cuda.is_available()
        except Exception:
            return False

    def _init_nvml(self) -> None:
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml_initialized = True
            logger.debug("pynvml başlatıldı — GPU sıcaklık/kullanım izleme aktif.")
        except Exception as exc:
            # WSL2'de NVML erişimi Windows sürücüsü proxy'si üzerinden kısıtlıdır
            try:
                with open("/proc/sys/kernel/osrelease") as _f:
                    _wsl2 = "microsoft" in _f.read().lower()
            except Exception:
                _wsl2 = False
            if _wsl2:
                logger.info(
                    "ℹ️  WSL2: pynvml başlatılamadı (beklenen davranış — "
                    "GPU access blocked by the operating system). "
                    "GPU sıcaklık/kullanım izleme kapalı; "
                    "temel bilgiler için nvidia-smi kullanılacak. Hata: %s",
                    exc,
                )
            else:
                logger.debug("pynvml başlatılamadı (opsiyonel): %s", exc)

    # ─────────────────────────────────────────────
    #  CPU & RAM
    # ─────────────────────────────────────────────

    def get_cpu_usage(self, interval: float | None = None) -> float | None:
        """
        CPU kullanım yüzdesini döndür.

        interval None ise `self.cpu_sample_interval` kullanılır (varsayılan 0.0, bloklamaz).
        """
        if not self._psutil_available:
            return None
        try:
            import psutil

            sample_interval = self.cpu_sample_interval if interval is None else max(0.0, interval)
            return psutil.cpu_percent(interval=sample_interval)
        except Exception:
            return None

    def get_memory_info(self) -> dict[str, float]:
        """RAM bilgisini GB cinsinden döndür."""
        if not self._psutil_available:
            return {}
        try:
            import psutil

            vm = psutil.virtual_memory()
            return {
                "total_gb": round(vm.total / 1e9, 2),
                "used_gb": round(vm.used / 1e9, 2),
                "available_gb": round(vm.available / 1e9, 2),
                "percent": vm.percent,
            }
        except Exception:
            return {}

    # ─────────────────────────────────────────────
    #  GPU
    # ─────────────────────────────────────────────

    def get_gpu_info(self) -> dict:
        """
        Detaylı GPU bilgisini döndür.

        Alanlar:
          available, device_count, cuda_version, driver_version,
          devices[]: id, name, compute_capability, total_vram_gb,
                     allocated_gb, reserved_gb, free_gb,
                     temperature_c (pynvml varsa), utilization_pct (pynvml varsa)
        """
        if not self._gpu_available:
            return {"available": False, "reason": "CUDA bulunamadı veya devre dışı"}

        try:
            import torch

            device_count = torch.cuda.device_count()
            devices: list[dict] = []

            for i in range(device_count):
                props = torch.cuda.get_device_properties(i)
                total_mem = props.total_memory / 1e9
                alloc_mem = torch.cuda.memory_allocated(i) / 1e9
                res_mem = torch.cuda.memory_reserved(i) / 1e9

                dev: dict = {
                    "id": i,
                    "name": props.name,
                    "compute_capability": f"{props.major}.{props.minor}",
                    "total_vram_gb": round(total_mem, 2),
                    "allocated_gb": round(alloc_mem, 2),
                    "reserved_gb": round(res_mem, 2),
                    "free_gb": round(total_mem - res_mem, 2),
                }

                # pynvml ek verisi
                if self._nvml_initialized:  # pragma: no cover
                    try:
                        import pynvml

                        handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                        dev["temperature_c"] = temp
                        dev["utilization_pct"] = util.gpu
                        dev["mem_utilization_pct"] = util.memory
                    except Exception as exc:
                        # pynvml hatası kritik değil; WSL2/sürücü sınırlaması olabilir
                        logger.debug("pynvml GPU sorgu hatası (beklenen — WSL2/sürücü): %s", exc)

                devices.append(dev)

            return {
                "available": True,
                "device_count": device_count,
                "cuda_version": torch.version.cuda or "N/A",
                "driver_version": self._get_driver_version(),
                "devices": devices,
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def _get_driver_version(self) -> str:
        """NVIDIA sürücü sürümünü döndür (pynvml; WSL2 fallback: nvidia-smi)."""
        if self._nvml_initialized:
            try:
                import pynvml

                return pynvml.nvmlSystemGetDriverVersion()
            except Exception as exc:
                logger.debug("pynvml sürücü sürümü alınamadı: %s", exc)
        # WSL2 fallback: nvidia-smi subprocess ile sürücü sürümünü al
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = result.stdout.strip().split("\n")[0]
            if version:
                return version
            # Çıktı boş → GPU yok veya sürücü raporlamıyor (WSL2'de beklenen)
            logger.debug(
                "nvidia-smi çıktısı boş (return code: %d) — sürücü sürümü N/A.",
                result.returncode,
            )
        except FileNotFoundError:
            logger.debug("nvidia-smi bulunamadı — NVIDIA sürücüsü kurulu değil.")
        except Exception as exc:
            logger.debug("nvidia-smi çalıştırılamadı: %s", exc)
        return "N/A"

    def optimize_gpu_memory(self) -> str:
        """
        GPU VRAM'ını boşalt ve Python GC'yi çalıştır.

        try-finally garantisi: torch.cuda.empty_cache() hata verse bile
        gc.collect() her koşulda çalıştırılır (bellek sızıntısı önlenir).

        Returns:
            İnsan okunabilir boşaltma raporu.
        """
        freed_mb = 0.0
        gpu_error: str | None = None

        try:
            if self._gpu_available:
                try:
                    import torch

                    before = torch.cuda.memory_reserved() / 1e6
                    torch.cuda.empty_cache()
                    after = torch.cuda.memory_reserved() / 1e6
                    freed_mb = max(before - after, 0.0)
                    logger.info("GPU bellek temizlendi: %.1f MB boşaltıldı.", freed_mb)
                except Exception as exc:
                    gpu_error = str(exc)
                    logger.warning("GPU bellek temizleme hatası (GC yine de çalışacak): %s", exc)
        finally:
            # Hata olsa da olmasa da Python GC garantili çalışır
            gc.collect()

        lines = [f"GPU VRAM temizlendi: {freed_mb:.1f} MB boşaltıldı"]
        if gpu_error:
            lines.append(f"  ⚠ GPU cache hatası: {gpu_error}")
        lines.append("Python GC çalıştırıldı. ✓")
        return "\n".join(lines)

    def check_ollama(self) -> bool:
        """Ollama servisinin erişilebilirliğini timeout ile doğrula."""
        try:
            import requests

            base_url = getattr(self.cfg, "OLLAMA_URL", "http://localhost:11434/api")
            timeout = max(1, int(getattr(self.cfg, "OLLAMA_TIMEOUT", 5)))
            resp = requests.get(f"{base_url.rstrip('/')}/tags", timeout=timeout)
            return resp.status_code == 200
        except Exception:
            return False

    def update_prometheus_metrics(self, metrics_dict: dict[str, float]) -> None:
        """SystemHealth verilerini mevcut Prometheus Gauge nesnelerine aktar."""
        if not metrics_dict:
            return
        if self._prometheus_gauges is None:
            if not self._check_import("prometheus_client"):
                self._prometheus_gauges = {}
                return
            try:
                from prometheus_client import Gauge

                self._prometheus_gauges = {
                    "cpu_percent": Gauge(
                        "sidar_system_cpu_percent",
                        "SystemHealth CPU kullanım yüzdesi",
                    ),
                    "ram_percent": Gauge(
                        "sidar_system_ram_percent",
                        "SystemHealth RAM kullanım yüzdesi",
                    ),
                    "gpu_util_percent": Gauge(
                        "sidar_system_gpu_util_percent",
                        "SystemHealth GPU kullanım yüzdesi",
                    ),
                    "gpu_temp_c": Gauge(
                        "sidar_system_gpu_temp_celsius",
                        "SystemHealth GPU sıcaklığı (C)",
                    ),
                }
            except Exception:
                self._prometheus_gauges = {}

        if not self._prometheus_gauges:
            return

        map_keys = {
            "cpu_percent": "cpu_percent",
            "ram_percent": "ram_percent",
            "gpu_utilization_pct": "gpu_util_percent",
            "gpu_temperature_c": "gpu_temp_c",
        }
        for src_key, gauge_key in map_keys.items():
            val = metrics_dict.get(src_key)
            if val is None:
                continue
            try:
                self._prometheus_gauges[gauge_key].set(float(val))
            except Exception:
                continue

    # ─────────────────────────────────────────────
    #  TAM RAPOR
    # ─────────────────────────────────────────────

    def get_health_summary(self) -> dict:
        """Kubernetes / Docker monitör sistemleri için yapısal (JSON) sağlık özeti."""
        cpu = self.get_cpu_usage()
        mem = self.get_memory_info()
        gpu = self.get_gpu_info()
        summary = {
            "status": "healthy",
            "cpu_percent": cpu if cpu is not None else 0.0,
            "ram_percent": mem.get("percent", 0.0) if mem else 0.0,
            "gpu_available": gpu.get("available", False),
            "ollama_online": self.check_ollama(),
            "python_version": platform.python_version(),
            "os": platform.system(),
        }
        if getattr(self.cfg, "ENABLE_DEPENDENCY_HEALTHCHECKS", False):
            dependencies = self.get_dependency_health()
            summary["dependencies"] = dependencies
            if any(
                item.get("healthy") is False for item in dependencies.values()
            ):  # pragma: no cover
                summary["status"] = "degraded"
        return summary

    def get_dependency_health(self) -> dict:
        """Redis/PostgreSQL gibi dış bağımlılıklar için hafif readiness kontrolü."""
        return {
            "redis": self.check_redis(),
            "database": self.check_database(),
        }

    def _tcp_dependency_health(self, host: str, port: int, *, label: str) -> dict:
        timeout_ms = max(50, int(getattr(self.cfg, "HEALTHCHECK_CONNECT_TIMEOUT_MS", 250) or 250))
        try:
            with socket.create_connection((host, port), timeout=timeout_ms / 1000.0):
                return {"healthy": True, "target": f"{host}:{port}", "kind": label}
        except Exception as exc:
            return {"healthy": False, "target": f"{host}:{port}", "kind": label, "error": str(exc)}

    def check_redis(self) -> dict:
        raw = str(getattr(self.cfg, "REDIS_URL", "") or "").strip()
        if not raw:
            return {"healthy": True, "kind": "redis", "mode": "disabled"}
        parsed = urlparse(raw)
        host = parsed.hostname or "localhost"
        port = int(parsed.port or 6379)
        status = self._tcp_dependency_health(host, port, label="redis")
        status["mode"] = "tcp"
        return status

    def check_database(self) -> dict:
        raw = str(getattr(self.cfg, "DATABASE_URL", "") or "").strip()
        if not raw:
            return {"healthy": True, "kind": "database", "mode": "disabled"}
        lowered = raw.lower()
        if lowered.startswith("sqlite"):
            path = raw.split(":///", 1)[-1] if ":///" in raw else raw
            db_path = Path(path)
            exists = db_path.exists()
            return {
                "healthy": exists or not db_path.name,
                "kind": "database",
                "mode": "sqlite",
                "target": str(db_path),
                **(
                    {}
                    if exists or not db_path.name
                    else {"error": "sqlite database file not found"}
                ),
            }
        parsed = urlparse(raw)
        host = parsed.hostname or "localhost"
        port = int(parsed.port or 5432)
        status = self._tcp_dependency_health(host, port, label="database")
        status["mode"] = parsed.scheme or "tcp"
        return status

    def full_report(self) -> str:
        """Kapsamlı sistem sağlık raporu (metin)."""
        lines = ["[Sistem Sağlık Raporu]"]

        # Platform
        lines.append(f"  OS        : {platform.system()} {platform.release()}")
        lines.append(f"  Python    : {platform.python_version()}")

        # CPU
        cpu = self.get_cpu_usage()
        if cpu is not None:
            lines.append(f"  CPU       : %{cpu:.1f} kullanımda")
        else:
            lines.append("  CPU       : psutil kurulu değil")

        # RAM
        mem = self.get_memory_info()
        if mem:
            lines.append(
                f"  RAM       : {mem['used_gb']:.1f}/{mem['total_gb']:.1f} GB "
                f"(%{mem['percent']:.0f} kullanımda)"
            )

        # Ollama
        ollama_up = self.check_ollama()
        lines.append(f"  Ollama    : {'Çevrimiçi' if ollama_up else 'Çevrimdışı'}")

        # GPU
        gpu = self.get_gpu_info()
        if gpu.get("available"):
            lines.append(
                f"  CUDA      : {gpu.get('cuda_version', 'N/A')}  |  "
                f"Sürücü: {gpu.get('driver_version', 'N/A')}"
            )
            for d in gpu["devices"]:
                line = (
                    f"  GPU {d['id']}     : {d['name']}  |  "
                    f"Compute {d.get('compute_capability', '?')}  |  "
                    f"VRAM {d['allocated_gb']:.1f}/{d['total_vram_gb']:.1f} GB  "
                    f"(Serbest {d['free_gb']:.1f} GB)"
                )
                if "temperature_c" in d:
                    line += f"  |  {d['temperature_c']}°C"
                if "utilization_pct" in d:
                    line += f"  |  %{d['utilization_pct']} GPU"
                lines.append(line)
        else:
            lines.append(f"  GPU       : {gpu.get('reason', gpu.get('error', 'Yok'))}")

        ram_percent = mem.get("percent") if mem else None
        gpu_devices = gpu.get("devices", []) if isinstance(gpu, dict) else []
        gpu_temp = gpu_devices[0].get("temperature_c") if gpu_devices else None
        gpu_util = gpu_devices[0].get("utilization_pct") if gpu_devices else None
        self.update_prometheus_metrics(
            {
                "cpu_percent": cpu if cpu is not None else 0.0,
                "ram_percent": ram_percent if ram_percent is not None else 0.0,
                "gpu_utilization_pct": gpu_util if gpu_util is not None else 0.0,
                "gpu_temperature_c": gpu_temp if gpu_temp is not None else 0.0,
            }
        )

        return "\n".join(lines)

    # ─────────────────────────────────────────────
    #  TEMİZLİK
    # ─────────────────────────────────────────────

    def close(self) -> None:
        """NVML oturumunu deterministik olarak kapatır (idempotent)."""
        with self._lock:
            if not getattr(self, "_nvml_initialized", False):
                return
            try:
                import pynvml

                pynvml.nvmlShutdown()
            except Exception:
                pass
            finally:
                self._nvml_initialized = False

    def __del__(self) -> None:
        # Geriye dönük uyumluluk: GC sırasında da kapanışı dene.
        self.close()

    def __repr__(self) -> str:
        return (
            f"<SystemHealthManager gpu={self._gpu_available} "
            f"torch={self._torch_available} "
            f"pynvml={self._nvml_initialized}>"
        )
