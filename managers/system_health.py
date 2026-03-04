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

import gc
import logging
import platform
import subprocess
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SystemHealthManager:
    """
    Donanım sağlığını izler, raporlar ve GPU belleğini optimize eder.
    nvidia-ml-py (pynvml) kuruluysa GPU sıcaklık/kullanım verisi de sağlar.
    """

    def __init__(self, use_gpu: bool = True) -> None:
        self.use_gpu = use_gpu
        self._lock = threading.RLock()

        # Bağımlılık kontrolleri
        self._torch_available  = self._check_import("torch")
        self._psutil_available = self._check_import("psutil")
        self._pynvml_available = self._check_import("pynvml")

        self._gpu_available = self._check_gpu()

        # pynvml başlat (sıcaklık / kullanım için)
        self._nvml_initialized = False
        if self._pynvml_available and self._gpu_available:
            self._init_nvml()

    # ─────────────────────────────────────────────
    #  BAŞLANGIÇ KONTROLLERI
    # ─────────────────────────────────────────────

    @staticmethod
    def _check_import(module_name: str) -> bool:
        import importlib
        try:
            importlib.import_module(module_name)
            return True
        except ImportError:
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
                    "temel bilgiler için nvidia-smi kullanılacak. Hata: %s", exc
                )
            else:
                logger.debug("pynvml başlatılamadı (opsiyonel): %s", exc)

    # ─────────────────────────────────────────────
    #  CPU & RAM
    # ─────────────────────────────────────────────

    def get_cpu_usage(self) -> Optional[float]:
        """CPU kullanım yüzdesini döndür."""
        if not self._psutil_available:
            return None
        try:
            import psutil
            return psutil.cpu_percent(interval=0.5)
        except Exception:
            return None

    def get_memory_info(self) -> Dict[str, float]:
        """RAM bilgisini GB cinsinden döndür."""
        if not self._psutil_available:
            return {}
        try:
            import psutil
            vm = psutil.virtual_memory()
            return {
                "total_gb":     round(vm.total    / 1e9, 2),
                "used_gb":      round(vm.used      / 1e9, 2),
                "available_gb": round(vm.available / 1e9, 2),
                "percent":      vm.percent,
            }
        except Exception:
            return {}

    # ─────────────────────────────────────────────
    #  GPU
    # ─────────────────────────────────────────────

    def get_gpu_info(self) -> Dict:
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
            devices: List[Dict] = []

            for i in range(device_count):
                props     = torch.cuda.get_device_properties(i)
                total_mem = props.total_memory / 1e9
                alloc_mem = torch.cuda.memory_allocated(i) / 1e9
                res_mem   = torch.cuda.memory_reserved(i)  / 1e9

                dev: Dict = {
                    "id":                 i,
                    "name":               props.name,
                    "compute_capability": f"{props.major}.{props.minor}",
                    "total_vram_gb":      round(total_mem, 2),
                    "allocated_gb":       round(alloc_mem, 2),
                    "reserved_gb":        round(res_mem,   2),
                    "free_gb":            round(total_mem - res_mem, 2),
                }

                # pynvml ek verisi
                if self._nvml_initialized:
                    try:
                        import pynvml
                        handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                        temp   = pynvml.nvmlDeviceGetTemperature(
                            handle, pynvml.NVML_TEMPERATURE_GPU
                        )
                        util   = pynvml.nvmlDeviceGetUtilizationRates(handle)
                        dev["temperature_c"]    = temp
                        dev["utilization_pct"]  = util.gpu
                        dev["mem_utilization_pct"] = util.memory
                    except Exception as exc:
                        # pynvml hatası kritik değil; WSL2/sürücü sınırlaması olabilir
                        logger.debug("pynvml GPU sorgu hatası (beklenen — WSL2/sürücü): %s", exc)

                devices.append(dev)

            return {
                "available":      True,
                "device_count":   device_count,
                "cuda_version":   torch.version.cuda or "N/A",
                "driver_version": self._get_driver_version(),
                "devices":        devices,
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
                capture_output=True, text=True, timeout=5,
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
        gpu_error: Optional[str] = None

        try:
            if self._gpu_available:
                try:
                    import torch
                    before   = torch.cuda.memory_reserved() / 1e6
                    torch.cuda.empty_cache()
                    after    = torch.cuda.memory_reserved() / 1e6
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

    # ─────────────────────────────────────────────
    #  TAM RAPOR
    # ─────────────────────────────────────────────

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

        return "\n".join(lines)

    # ─────────────────────────────────────────────
    #  TEMİZLİK
    # ─────────────────────────────────────────────

    def __del__(self) -> None:
        if self._nvml_initialized:
            try:
                import pynvml
                pynvml.nvmlShutdown()
            except Exception:
                pass

    def __repr__(self) -> str:
        return (
            f"<SystemHealthManager gpu={self._gpu_available} "
            f"torch={self._torch_available} "
            f"pynvml={self._nvml_initialized}>"
        )  