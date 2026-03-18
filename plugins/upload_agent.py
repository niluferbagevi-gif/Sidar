"""Upload plugin ajanı.

Bu modül, test ortamlarında `agent` paketinin ağır bağımlılıkları eksik olsa bile
minimum davranışıyla içe aktarılabilmelidir.
"""

try:
    from agent.base_agent import BaseAgent
except Exception:  # pragma: no cover - testlerde ve hafif ortamlarda güvenli fallback
    class BaseAgent:  # type: ignore[no-redef]
        """Tam ajan altyapısı yüklenemediğinde kullanılan minimal fallback tabanı."""

        pass



class UploadAgent(BaseAgent):
    """Yüklenen plugin akışları için minimum demo ajan."""

    async def run_task(self, task_prompt: str) -> str:
        prompt = (task_prompt or "").strip()
        if not prompt:
            return "Boş görev alındı."
        return f"UploadAgent: {prompt}"
