"""YouTube transcript ve frame analizi için manager katmanı."""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from core.multimodal import build_multimodal_context, extract_video_frames
from core.vision import VisionPipeline


class YouTubeManager:
    """YouTube video URL'lerinden transcript ve frame analizi üreten yardımcı sınıf."""

    TRANSCRIPT_TIMEOUT = 15.0
    DEFAULT_LANGUAGES = ("tr", "en")

    def __init__(
        self,
        llm_client: Any | None = None,
        config: Any | None = None,
        *,
        http_client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.config = config
        self.http_client_factory = http_client_factory or httpx.AsyncClient
        self.transcript_timeout = float(
            getattr(config, "YOUTUBE_TRANSCRIPT_TIMEOUT", self.TRANSCRIPT_TIMEOUT)
            or self.TRANSCRIPT_TIMEOUT
        )

    @staticmethod
    def extract_video_id(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
            return text

        parsed = urlparse(text)
        host = (parsed.netloc or "").lower()
        if host.endswith("youtu.be"):
            candidate = parsed.path.strip("/").split("/")[0]
            return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else ""
        if "youtube.com" in host:
            if parsed.path == "/watch":
                candidate = parse_qs(parsed.query).get("v", [""])[0]
                return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else ""
            match = re.match(r"^/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})", parsed.path or "")
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _timedtext_url(video_id: str, language: str) -> str:
        return f"https://www.youtube.com/api/timedtext?v={video_id}&lang={language}&fmt=json3"

    @staticmethod
    def _normalize_transcript_events(events: list[dict[str, Any]]) -> dict[str, Any]:
        lines: list[str] = []
        segments: list[dict[str, Any]] = []
        for item in events or []:
            if not isinstance(item, dict):
                continue
            pieces = item.get("segs") or []
            if not isinstance(pieces, list):
                continue
            text = "".join(
                html.unescape(str(piece.get("utf8") or ""))
                for piece in pieces
                if isinstance(piece, dict)
            ).strip()
            if not text:
                continue
            start_ms = int(item.get("tStartMs") or 0)
            duration_ms = int(item.get("dDurationMs") or 0)
            lines.append(text)
            segments.append(
                {
                    "start_seconds": round(start_ms / 1000, 3),
                    "duration_seconds": round(duration_ms / 1000, 3),
                    "text": text,
                }
            )
        return {"text": " ".join(lines).strip(), "segments": segments}

    async def fetch_transcript(
        self, video_url_or_id: str, *, languages: tuple[str, ...] | None = None
    ) -> dict[str, Any]:
        video_id = self.extract_video_id(video_url_or_id)
        if not video_id:
            return {
                "success": False,
                "reason": "Geçerli YouTube video id bulunamadı.",
                "video_id": "",
            }

        langs = tuple(languages or self.DEFAULT_LANGUAGES)
        async with self.http_client_factory(
            timeout=self.transcript_timeout, follow_redirects=True
        ) as client:
            for language in langs:
                response = await client.get(self._timedtext_url(video_id, language))
                if response.status_code >= 400:
                    continue
                payload = response.json() if hasattr(response, "json") else {}
                events = payload.get("events") if isinstance(payload, dict) else []
                normalized = self._normalize_transcript_events(
                    events if isinstance(events, list) else []
                )
                if normalized["text"]:
                    return {
                        "success": True,
                        "video_id": video_id,
                        "language": language,
                        "text": normalized["text"],
                        "segments": normalized["segments"],
                    }

        return {
            "success": False,
            "video_id": video_id,
            "language": "",
            "text": "",
            "segments": [],
            "reason": "YouTube transcript bulunamadı veya boş döndü.",
        }

    async def analyze_video_file(
        self,
        video_path: str | Path,
        *,
        transcript: dict[str, Any] | None = None,
        analysis_type: str = "general",
        frame_interval_seconds: float = 5.0,
        max_frames: int = 6,
        extra_notes: str = "",
    ) -> dict[str, Any]:
        source = Path(video_path)
        if not source.exists():
            return {"success": False, "reason": f"Video dosyası bulunamadı: {source}"}
        if self.llm_client is None:
            return {"success": False, "reason": "Vision analizi için llm_client gerekli."}

        vision = VisionPipeline(self.llm_client, self.config)
        frames = await extract_video_frames(
            source,
            interval_seconds=frame_interval_seconds,
            max_frames=max_frames,
            output_dir=source.parent / f"{source.stem}_yt_frames",
        )
        frame_analyses: list[dict[str, Any]] = []
        for frame in frames:
            result = await vision.analyze(image_path=frame.path, analysis_type=analysis_type)
            frame_analyses.append(
                {
                    "timestamp_seconds": frame.timestamp_seconds,
                    "frame_path": frame.path,
                    "analysis": str(result.get("analysis", "") or "")
                    if isinstance(result, dict)
                    else "",
                    "success": bool(result.get("success", False))
                    if isinstance(result, dict)
                    else False,
                }
            )

        context = build_multimodal_context(
            media_kind="video",
            transcript=transcript or {},
            frame_analyses=frame_analyses,
            extra_notes=extra_notes,
        )
        return {
            "success": True,
            "video_path": str(source),
            "transcript": transcript or {},
            "frame_analyses": frame_analyses,
            "context": context,
        }

    async def build_video_analysis(
        self,
        *,
        video_url: str,
        video_path: str | Path,
        analysis_type: str = "general",
        languages: tuple[str, ...] | None = None,
        frame_interval_seconds: float = 5.0,
        max_frames: int = 6,
        extra_notes: str = "",
    ) -> dict[str, Any]:
        transcript = await self.fetch_transcript(video_url, languages=languages)
        analysis = await self.analyze_video_file(
            video_path,
            transcript=transcript,
            analysis_type=analysis_type,
            frame_interval_seconds=frame_interval_seconds,
            max_frames=max_frames,
            extra_notes=extra_notes,
        )
        if not analysis.get("success"):
            return analysis
        return {
            **analysis,
            "video_url": video_url,
            "video_id": self.extract_video_id(video_url),
        }
