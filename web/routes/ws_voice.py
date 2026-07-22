"""Voice WebSocket route and helpers."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from web.routes.ws_chat import send_json_if_connected, websocket_is_connected
from web.routes.ws_lifecycle import WebSocketLifecycle, reject_rate_limited_connection
from web.security import (
    SIDAR_WS_VOICE_PROTOCOL,
)
from web.security import (
    extract_ws_header_token as default_extract_ws_header_token,
)


def build_ws_voice_router(deps_factory: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/voice")
    async def _websocket_voice_route(websocket: WebSocket) -> Any:
        return await websocket_voice(websocket, deps_factory())

    return router


async def websocket_voice(websocket: WebSocket, deps: Any) -> Any:
    """Gerçek zamanlı ses oturumu için websocket.

    MVP davranışı:
    - İstemci binary ses chunk'larını gönderir.
    - `commit` / `end` aksiyonu ile biriken ses STT'den geçirilir.
    - Transkript çıkarıldıktan sonra ajan metin yanıtı stream edilir.
    """
    if await reject_rate_limited_connection(websocket, deps):
        return

    proto_header = websocket.headers.get("sec-websocket-protocol", "").strip()
    extract_ws_header_token = getattr(
        deps, "extract_ws_header_token", default_extract_ws_header_token
    )
    header_token, accept_subprotocol = extract_ws_header_token(
        proto_header, getattr(deps, "ws_voice_protocol", SIDAR_WS_VOICE_PROTOCOL)
    )

    if accept_subprotocol:
        await websocket.accept(subprotocol=accept_subprotocol)
    else:
        await websocket.accept()

    try:
        from core.multimodal import MultimodalPipeline
    except ImportError:
        await websocket.send_json({"error": "core.multimodal modülü yüklenemedi.", "done": True})
        await websocket.close(code=1011, reason="multimodal unavailable")
        return

    try:
        from core.voice import VoicePipeline
    except ImportError:
        VoicePipeline = None  # type: ignore[misc, assignment]

    agent = await deps.resolve_agent_instance()
    lifecycle = WebSocketLifecycle(websocket, logger=getattr(deps, "logger", None))
    pipeline = MultimodalPipeline(agent.llm, deps.cfg)
    voice_pipeline = None
    voice_init_error = ""
    if VoicePipeline is not None:
        try:
            voice_pipeline = VoicePipeline(deps.cfg)
        except Exception as exc:
            voice_init_error = f"Voice Disabled: {exc.__class__.__name__}"
            deps.logger.warning("Voice pipeline başlatılamadı, voice devre dışı: %s", exc)
    max_voice_bytes = int(
        getattr(deps.cfg, "VOICE_WS_MAX_BYTES", 10 * 1024 * 1024) or 10 * 1024 * 1024
    )

    audio_buffer = bytearray()
    ws_user_id = ""
    ws_username = ""
    ws_authenticated = False
    session_mime_type = "audio/webm"
    session_language: str | None = None
    session_prompt = ""
    voice_sequence = 0
    active_response_task: asyncio.Task[Any] | None = None
    websocket._sidar_voice_pipeline = voice_pipeline  # type: ignore[attr-defined, unused-ignore]
    duplex_state = (
        voice_pipeline.create_duplex_state()
        if voice_pipeline is not None and hasattr(voice_pipeline, "create_duplex_state")
        else None
    )
    websocket._sidar_voice_duplex_state = duplex_state  # type: ignore[attr-defined, unused-ignore]

    async def _emit_voice_state(event: str) -> None:
        nonlocal voice_sequence
        voice_sequence += 1
        if voice_pipeline is None or not hasattr(voice_pipeline, "build_voice_state_payload"):
            await send_json_if_connected(
                websocket,
                {
                    "voice_state": str(event or "").strip().lower() or "unknown",
                    "buffered_bytes": len(audio_buffer),
                    "sequence": voice_sequence,
                    "vad_enabled": bool(getattr(voice_pipeline, "vad_enabled", False))
                    if voice_pipeline is not None
                    else False,
                    "auto_commit_ready": False,
                    "duplex_enabled": bool(getattr(voice_pipeline, "duplex_enabled", False))
                    if voice_pipeline is not None
                    else False,
                    "interrupt_ready": False,
                    "tts_enabled": bool(getattr(voice_pipeline, "enabled", False))
                    if voice_pipeline is not None
                    else False,
                    "voice_disabled_reason": voice_init_error,
                    "assistant_turn_id": int(getattr(duplex_state, "assistant_turn_id", 0) or 0),
                    "output_buffer_chars": len(
                        getattr(duplex_state, "output_text_buffer", "") or ""
                    ),
                    "last_interrupt_reason": str(
                        getattr(duplex_state, "last_interrupt_reason", "") or ""
                    ),
                },
            )
            return
        await send_json_if_connected(
            websocket,
            voice_pipeline.build_voice_state_payload(
                event=event,
                buffered_bytes=len(audio_buffer),
                sequence=voice_sequence,
                duplex_state=duplex_state,
            ),
        )

    async def _cancel_active_response(reason: str) -> None:
        nonlocal active_response_task
        interrupt_payload = (
            voice_pipeline.interrupt_assistant_turn(duplex_state, reason=reason)
            if voice_pipeline is not None and hasattr(voice_pipeline, "interrupt_assistant_turn")
            else {
                "assistant_turn_id": int(getattr(duplex_state, "assistant_turn_id", 0) or 0),
                "dropped_text_chars": 0,
                "cancelled_audio_sequences": 0,
                "reason": reason,
            }
        )
        if active_response_task is None or active_response_task.done():
            return
        await lifecycle.cancel_task(active_response_task)
        await send_json_if_connected(  # pragma: no cover - concurrent cancellation race
            websocket, {"voice_interruption": reason, "cancelled": True, **interrupt_payload}
        )
        active_response_task = None  # pragma: no cover - concurrent cancellation race

    async def _run_voice_turn(
        *,
        audio_bytes: bytes,
        mime_type: str,
        language: str | None,
        prompt: str,
    ) -> None:
        if not websocket_is_connected(websocket):
            return  # pragma: no cover - disconnect race before background turn starts
        if not audio_bytes:  # pragma: no cover - defensive, empty buffers filtered upstream
            await send_json_if_connected(
                websocket, {"error": "İşlenecek ses verisi bulunamadı.", "done": True}
            )
            return

        result = await pipeline.transcribe_bytes(
            audio_bytes,
            mime_type=mime_type,
            language=language,
            prompt=prompt,
        )
        await _emit_voice_state("processed")

        if not isinstance(result, dict) or not result.get("success"):
            reason = "Ses transkripsiyonu başarısız oldu."
            if isinstance(result, dict):
                reason = str(result.get("reason", reason) or reason)
            await send_json_if_connected(websocket, {"error": reason, "done": True})
            return

        transcript_text = str(result.get("text", "") or "").strip()
        if not await send_json_if_connected(
            websocket,
            {
                "transcript": transcript_text,
                "language": result.get("language", ""),
                "provider": result.get("provider", ""),
            },
        ):
            return
        if not transcript_text:
            await send_json_if_connected(websocket, {"done": True})
            return

        assistant_turn_id = (
            voice_pipeline.begin_assistant_turn(duplex_state)
            if voice_pipeline is not None and hasattr(voice_pipeline, "begin_assistant_turn")
            else int(getattr(duplex_state, "assistant_turn_id", 0) or 0)
        )
        if not await send_json_if_connected(
            websocket, {"assistant_turn": "started", "assistant_turn_id": assistant_turn_id}
        ):
            return

        try:
            await deps.ws_stream_agent_text_response(websocket, agent, transcript_text)
        except deps.llm_api_error_cls as exc:
            await send_json_if_connected(
                websocket,
                {
                    "chunk": f"\n[LLM Hatası] {exc.provider} ({exc.status_code or 'n/a'}): {exc}",
                    "done": True,
                },
            )
            return
        except Exception as exc:
            deps.logger.exception("Voice websocket agent yanıtı hatası: %s", exc)
            await send_json_if_connected(
                websocket, {"chunk": f"\n[Sistem Hatası] {exc}", "done": True}
            )
            return

        if not await send_json_if_connected(
            websocket, {"assistant_turn": "completed", "assistant_turn_id": assistant_turn_id}
        ):
            return
        await send_json_if_connected(websocket, {"done": True})

    async def _process_audio_commit() -> None:
        nonlocal audio_buffer, active_response_task
        if not audio_buffer:
            await send_json_if_connected(
                websocket, {"error": "İşlenecek ses verisi bulunamadı.", "done": True}
            )
            return

        if active_response_task and not active_response_task.done():
            await _cancel_active_response("superseded_by_new_turn")

        commit_audio = bytes(audio_buffer)
        audio_buffer.clear()
        active_response_task = lifecycle.track_task(
            asyncio.create_task(
                _run_voice_turn(
                    audio_bytes=commit_audio,
                    mime_type=session_mime_type,
                    language=session_language,
                    prompt=session_prompt,
                )
            )
        )

    if header_token:
        ws_user = await deps.await_if_needed(deps.resolve_user_from_token(agent, header_token))
        if not ws_user:
            await deps.ws_close_policy_violation(websocket, "Invalid or expired token")
            return
        ws_user_id = ws_user.id
        ws_username = ws_user.username
        ws_authenticated = True
        await agent.memory.set_active_user(ws_user_id, ws_username)
        with contextlib.suppress(Exception):
            await websocket.send_json({"auth_ok": True})

    ws_auth_timeout_seconds = int(
        getattr(getattr(deps, "cfg", None), "WS_AUTH_TIMEOUT_SECONDS", 15) or 15
    )
    ws_auth_deadline = asyncio.get_event_loop().time() + ws_auth_timeout_seconds

    try:
        while True:
            if ws_authenticated:
                packet = await websocket.receive()
            else:
                # Kimlik doğrulanmamış bir istemci bağlantıyı süresiz açık tutamaz
                # (yavaş DoS / kaynak tükenmesi) — ne sessiz kalarak ne de ardı
                # ardına geçersiz/auth-olmayan mesaj göndererek. Zaman aşımı
                # bağlantının kabulünden itibaren sabit bir mutlak son tarihtir;
                # her mesajda sıfırlanmaz.
                remaining = ws_auth_deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    await deps.ws_close_policy_violation(websocket, "Authentication timeout")
                    return
                try:
                    packet = await asyncio.wait_for(websocket.receive(), timeout=remaining)
                except (
                    TimeoutError
                ):  # pragma: no cover - timing race covered by timeout integration tests
                    await deps.ws_close_policy_violation(websocket, "Authentication timeout")
                    return
            packet_type = packet.get("type")
            if packet_type == "websocket.disconnect":
                raise WebSocketDisconnect()

            bytes_payload = packet.get("bytes")
            if bytes_payload is not None:
                if not ws_authenticated:
                    await deps.ws_close_policy_violation(websocket, "Authentication required")
                    return
                if len(audio_buffer) + len(bytes_payload) > max_voice_bytes:
                    await deps.ws_close_policy_violation(websocket, "Voice payload too large")
                    return
                audio_buffer.extend(bytes_payload)
                await websocket.send_json({"buffered_bytes": len(audio_buffer)})
                await _emit_voice_state("chunk")
                continue

            text_payload = packet.get("text")
            if text_payload is None:
                continue

            try:
                payload = json.loads(text_payload)
            except json.JSONDecodeError:
                continue

            action = str(payload.get("action", "") or "").strip().lower()
            if not ws_authenticated:
                if action != "auth":
                    await deps.ws_close_policy_violation(websocket, "Authentication required")
                    return
                auth_token = (payload.get("token", "") or "").strip()
                if not auth_token:
                    await deps.ws_close_policy_violation(websocket, "Authentication token missing")
                    return
                ws_user = await deps.await_if_needed(
                    deps.resolve_user_from_token(agent, auth_token)
                )
                if not ws_user:
                    await deps.ws_close_policy_violation(websocket, "Invalid or expired token")
                    return
                ws_user_id = ws_user.id
                ws_username = ws_user.username
                ws_authenticated = True
                await agent.memory.set_active_user(ws_user_id, ws_username)
                with contextlib.suppress(Exception):
                    await websocket.send_json({"auth_ok": True})
                continue

            if action in {"start", "reset"}:
                audio_buffer.clear()
                session_mime_type = str(payload.get("mime_type", "audio/webm") or "audio/webm")
                session_language = payload.get("language")
                session_prompt = str(payload.get("prompt", "") or "")
                await websocket.send_json(
                    {
                        "voice_session": "ready",
                        "mime_type": session_mime_type,
                        "duplex": True,
                        "vad_enabled": bool(getattr(voice_pipeline, "vad_enabled", False)),
                        "tts_enabled": bool(getattr(voice_pipeline, "enabled", False))
                        if voice_pipeline is not None
                        else False,
                        "voice_disabled_reason": str(
                            getattr(voice_pipeline, "voice_disabled_reason", "") or voice_init_error
                        ),
                    }
                )
                await _emit_voice_state("ready")
                continue

            if action == "append_base64":
                encoded_chunk = str(payload.get("chunk", "") or "").strip()
                if not encoded_chunk:
                    continue
                try:
                    decoded_chunk = base64.b64decode(encoded_chunk, validate=True)
                except Exception:
                    await websocket.send_json(
                        {"error": "Geçersiz base64 ses parçası", "done": True}
                    )
                    continue
                if len(audio_buffer) + len(decoded_chunk) > max_voice_bytes:
                    await deps.ws_close_policy_violation(websocket, "Voice payload too large")
                    return
                audio_buffer.extend(decoded_chunk)
                await websocket.send_json({"buffered_bytes": len(audio_buffer)})
                await _emit_voice_state("chunk")
                continue

            if action == "cancel":
                audio_buffer.clear()
                await _cancel_active_response("user_cancelled")
                await _emit_voice_state("cancelled")
                await websocket.send_json({"cancelled": True, "done": True})
                continue

            if action == "vad_event":
                vad_state = str(payload.get("state", "") or "unknown")
                await _emit_voice_state(vad_state)
                if (
                    voice_pipeline
                    and hasattr(voice_pipeline, "should_interrupt_response")
                    and voice_pipeline.should_interrupt_response(len(audio_buffer), event=vad_state)
                ):
                    await _cancel_active_response("barge_in")
                if voice_pipeline and voice_pipeline.should_commit_audio(
                    len(audio_buffer), event=vad_state
                ):
                    await _process_audio_commit()
                continue

            if action not in {"commit", "process", "end", "vad_commit"}:
                continue

            session_mime_type = str(
                payload.get("mime_type", session_mime_type) or session_mime_type
            )
            session_language = payload.get("language", session_language)
            session_prompt = str(payload.get("prompt", session_prompt) or session_prompt)
            await _process_audio_commit()
    except WebSocketDisconnect:
        deps.logger.info("İstemci voice WebSocket bağlantısını kesti.")
        await lifecycle.close(reason="disconnect")
    except Exception as exc:
        if deps.anyio_closed is not None and isinstance(exc, deps.anyio_closed):
            deps.logger.info(
                "İstemci voice WebSocket bağlantısını kesti (anyio ClosedResourceError)."
            )
            await lifecycle.close(reason="closed_resource")
        else:
            deps.logger.warning("Voice WebSocket beklenmedik hata: %s", exc)
            await lifecycle.close(reason="unexpected_error")
