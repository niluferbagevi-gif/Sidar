"""WebSocket chat route and streaming helpers."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import json
import re
import secrets
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from web.security import extract_ws_header_token as default_extract_ws_header_token


def websocket_is_connected(websocket: WebSocket) -> bool:
    """Return whether the accepted websocket is still connected for outbound sends."""
    return getattr(websocket, "client_state", WebSocketState.CONNECTED) == WebSocketState.CONNECTED


async def send_json_if_connected(websocket: WebSocket, payload: dict[str, Any]) -> bool:
    """Send a JSON payload only while the websocket remains connected."""
    if not websocket_is_connected(websocket):
        return False
    await websocket.send_json(payload)
    return True


def build_ws_chat_router(deps_factory: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/chat")
    async def _websocket_chat_route(websocket: WebSocket) -> Any:
        return await websocket_chat(websocket, deps_factory())

    return router


async def ws_stream_agent_text_response(websocket: WebSocket, agent: Any, prompt: str) -> None:
    """Agent text çıktısını voice/chat benzeri websocket istemcisine aktar."""
    tool_sentinel = re.compile(r"^\x00TOOL:([^\x00]+)\x00$")
    thought_sentinel = re.compile(r"^\x00THOUGHT:([^\x00]+)\x00$")
    voice_pipeline = getattr(websocket, "_sidar_voice_pipeline", None)
    duplex_state = getattr(websocket, "_sidar_voice_duplex_state", None)
    pending_voice_text = ""

    async def _emit_voice_segments(*, flush: bool = False) -> None:
        nonlocal pending_voice_text
        if not voice_pipeline or not getattr(voice_pipeline, "enabled", False):
            return
        if hasattr(voice_pipeline, "buffer_assistant_text"):
            _turn_id, packets = voice_pipeline.buffer_assistant_text(
                duplex_state,
                pending_voice_text,
                flush=flush,
            )
            pending_voice_text = ""
        else:
            ready_segments, remainder = voice_pipeline.extract_ready_segments(
                pending_voice_text, flush=flush
            )
            pending_voice_text = remainder
            packets = [
                {"assistant_turn_id": 0, "audio_sequence": idx, "text": segment}
                for idx, segment in enumerate(ready_segments, start=1)
            ]
        for packet in packets:
            segment = str(packet.get("text", "") or "").strip()
            if not segment:
                continue
            tts_result = await voice_pipeline.synthesize_text(segment)
            if not tts_result.get("success"):
                continue
            audio_bytes = bytes(tts_result.get("audio_bytes") or b"")
            if not audio_bytes:
                continue
            sent = await send_json_if_connected(
                websocket,
                {
                    "audio_chunk": base64.b64encode(audio_bytes).decode("ascii"),
                    "audio_text": segment,
                    "audio_mime_type": tts_result.get("mime_type", "audio/wav"),
                    "audio_provider": tts_result.get("provider", ""),
                    "audio_voice": tts_result.get("voice", ""),
                    "assistant_turn_id": int(packet.get("assistant_turn_id", 0) or 0),
                    "audio_sequence": int(packet.get("audio_sequence", 0) or 0),
                },
            )
            if not sent:
                return

    async for chunk in agent.respond(prompt):
        if not websocket_is_connected(websocket):
            break
        m_tool = tool_sentinel.match(chunk)
        m_thought = thought_sentinel.match(chunk)
        if m_tool:
            if not await send_json_if_connected(websocket, {"tool_call": m_tool.group(1)}):
                break
        elif m_thought:
            if not await send_json_if_connected(websocket, {"thought": m_thought.group(1)}):
                break
        else:
            if not await send_json_if_connected(websocket, {"chunk": chunk}):
                break
            if voice_pipeline and getattr(voice_pipeline, "enabled", False):
                pending_voice_text += chunk
                await _emit_voice_segments()

    await _emit_voice_segments(flush=True)


async def websocket_chat(websocket: WebSocket, deps: Any) -> Any:
    """
    Çift yönlü WebSocket chat arayüzü.
    Kullanıcı mesajlarını alır, asenkron LLM yanıtlarını stream eder
    ve anlık iptal (cancel) isteklerini yönetir.

    Kimlik Doğrulama (tercih sırası):
    1. Sec-WebSocket-Protocol başlığı (güvenli — token HTTP upgrade aşamasında taşınır)
    2. İlk JSON mesajı { action: 'auth', token: '...' } (geriye dönük uyumluluk)
    """
    # Sec-WebSocket-Protocol başlığından token'ı oku ancak raw token'ı subprotocol olarak echo etme.
    # Yeni istemciler sabit SIDAR_WS_CHAT_PROTOCOL değerini ayrıca sunarsa yalnız bu sabit değer
    # kabul edilir; geriye dönük raw-token header akışı subprotocol echo olmadan çalışır.
    proto_header = websocket.headers.get("sec-websocket-protocol", "").strip()
    extract_ws_header_token = getattr(
        deps, "extract_ws_header_token", default_extract_ws_header_token
    )
    header_token, accept_subprotocol = extract_ws_header_token(proto_header)

    if accept_subprotocol:
        await websocket.accept(subprotocol=accept_subprotocol)
    else:
        await websocket.accept()

    agent = await deps.resolve_agent_instance()
    active_task: asyncio.Task[Any] | None = None
    ws_user_id = ""
    ws_username = ""
    ws_user_role = "user"
    ws_authenticated = False
    joined_room_id = ""

    # Başlık token'ı varsa bağlantı açılır açılmaz doğrula
    if header_token:
        ws_user = await deps.await_if_needed(deps.resolve_user_from_token(agent, header_token))
        if not ws_user:
            await deps.ws_close_policy_violation(websocket, "Invalid or expired token")
            return
        ws_user_id = ws_user.id
        ws_username = ws_user.username
        ws_user_role = deps.normalize_collaboration_role(getattr(ws_user, "role", "user"))
        ws_authenticated = True
        await agent.memory.set_active_user(ws_user_id, ws_username)
        with contextlib.suppress(Exception):
            await websocket.send_json({"auth_ok": True})

    async def _cancel_task_and_wait(task: Any | None) -> None:
        if task is None or task.done():
            return
        task.cancel()
        if inspect.isawaitable(task):
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def generate_response(msg: str) -> None:
        sub_id = None
        status_task = None
        stop_status = asyncio.Event()
        ctx_token = deps.set_current_metrics_user_id(ws_user_id) if ws_user_id else None
        try:
            if len(agent.memory) == 0:
                title = msg[:30] + "..." if len(msg) > 30 else msg
                if hasattr(agent.memory, "aupdate_title"):
                    await deps.await_if_needed(agent.memory.aupdate_title(title))
                else:
                    await deps.await_if_needed(agent.memory.update_title(title))

            event_bus = deps.get_agent_event_bus()
            sub_id, status_queue = event_bus.subscribe()

            async def _status_pump() -> None:
                while not stop_status.is_set():
                    try:
                        evt = await asyncio.wait_for(status_queue.get(), timeout=0.5)
                    except TimeoutError:
                        continue
                    if not await send_json_if_connected(
                        websocket, {"status": f"{evt.source}: {evt.message}"}
                    ):
                        break

            status_task = asyncio.create_task(_status_pump())

            _TOOL_SENTINEL = re.compile(r"^\x00TOOL:([^\x00]+)\x00$")
            _THOUGHT_SENTINEL = re.compile(r"^\x00THOUGHT:([^\x00]+)\x00$")

            async for chunk in agent.respond(msg):
                if not websocket_is_connected(websocket):
                    break
                m_tool = _TOOL_SENTINEL.match(chunk)
                m_thought = _THOUGHT_SENTINEL.match(chunk)

                if m_tool:
                    if not await send_json_if_connected(websocket, {"tool_call": m_tool.group(1)}):
                        break
                elif m_thought:
                    if not await send_json_if_connected(websocket, {"thought": m_thought.group(1)}):
                        break
                else:
                    if not await send_json_if_connected(websocket, {"chunk": chunk}):
                        break

            await send_json_if_connected(websocket, {"done": True})
        except asyncio.CancelledError:
            pass
        except deps.llm_api_error_cls as exc:
            deps.logger.warning(
                "LLM sağlayıcı hatası: provider=%s status=%s retryable=%s",
                exc.provider,
                exc.status_code,
                exc.retryable,
            )
            try:
                await send_json_if_connected(
                    websocket,
                    {
                        "chunk": f"\n[LLM Hatası] {exc.provider} ({exc.status_code or 'n/a'}): {exc}",
                        "done": True,
                    },
                )
            except Exception as exc:
                deps.logger.debug("WebSocket LLM hata mesajı gönderilemedi: %s", exc)
        except Exception as exc:
            deps.logger.exception("Agent respond hatası: %s", exc)
            try:
                await send_json_if_connected(
                    websocket, {"chunk": f"\n[Sistem Hatası] {exc}", "done": True}
                )
            except Exception as exc:
                deps.logger.debug("WebSocket sistem hata mesajı gönderilemedi: %s", exc)
        finally:
            stop_status.set()
            if status_task is not None:
                status_task.cancel()
                with contextlib.suppress(Exception):
                    await status_task
            if sub_id is not None:
                deps.get_agent_event_bus().unsubscribe(sub_id)
            if ctx_token is not None:
                deps.reset_current_metrics_user_id(ctx_token)

    async def generate_room_response(room: Any, *, actor_name: str, msg: str) -> None:
        sub_id = None
        status_task = None
        stop_status = asyncio.Event()
        request_id = secrets.token_hex(6)
        collaboration_prompt = deps.build_collaboration_prompt(
            room, actor_name=actor_name, command=msg
        )
        ctx_token = deps.set_current_metrics_user_id(ws_user_id) if ws_user_id else None
        try:
            event_bus = deps.get_agent_event_bus()
            sub_id, status_queue = event_bus.subscribe()

            async def _status_pump() -> None:
                while not stop_status.is_set():
                    try:
                        evt = await asyncio.wait_for(status_queue.get(), timeout=0.5)
                    except TimeoutError:
                        continue
                    payload = {
                        "id": secrets.token_hex(8),
                        "room_id": room.room_id,
                        "kind": "status",
                        "source": evt.source,
                        "content": deps.mask_collaboration_text(evt.message),
                        "ts": deps.collaboration_now_iso(),
                    }
                    deps.append_room_telemetry(room, payload)
                    await deps.broadcast_room_payload(
                        room, {"type": "collaboration_event", "event": payload}
                    )

            status_task = asyncio.create_task(_status_pump())
            await deps.broadcast_room_payload(
                room,
                {
                    "type": "assistant_stream_start",
                    "room_id": room.room_id,
                    "request_id": request_id,
                    "author_name": "SİDAR",
                },
            )
            result = await agent._try_multi_agent(collaboration_prompt)
            for chunk in deps.iter_stream_chunks(result):
                await deps.broadcast_room_payload(
                    room,
                    {
                        "type": "assistant_chunk",
                        "room_id": room.room_id,
                        "request_id": request_id,
                        "chunk": deps.mask_collaboration_text(chunk),
                        "author_name": "SİDAR",
                    },
                )

            assistant_message = deps.build_room_message(
                room_id=room.room_id,
                role="assistant",
                content=result,
                author_name="SİDAR",
                author_id="sidar",
                kind="assistant_reply",
                request_id=request_id,
            )
            deps.append_room_message(room, assistant_message)
            await deps.broadcast_room_payload(
                room,
                {
                    "type": "assistant_done",
                    "room_id": room.room_id,
                    "request_id": request_id,
                    "message": assistant_message,
                },
            )
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await deps.broadcast_room_payload(
                    room,
                    {
                        "type": "assistant_done",
                        "room_id": room.room_id,
                        "request_id": request_id,
                        "cancelled": True,
                        "message": None,
                    },
                )
            raise
        except Exception as exc:
            deps.logger.exception("Collaborative agent response error: %s", exc)
            await deps.broadcast_room_payload(
                room,
                {
                    "type": "room_error",
                    "room_id": room.room_id,
                    "error": deps.mask_collaboration_text(str(exc)),
                    "request_id": request_id,
                },
            )
        finally:
            stop_status.set()
            if status_task is not None:
                status_task.cancel()
                with contextlib.suppress(Exception):
                    await status_task
            if sub_id is not None:
                deps.get_agent_event_bus().unsubscribe(sub_id)
            if room.active_task is not None and room.active_task.done():
                room.active_task = None
            if ctx_token is not None:
                deps.reset_current_metrics_user_id(ctx_token)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue

            action = payload.get("action")
            user_message = payload.get("message", "").strip()

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
                ws_user_role = deps.normalize_collaboration_role(getattr(ws_user, "role", "user"))
                ws_authenticated = True
                await agent.memory.set_active_user(ws_user_id, ws_username)
                with contextlib.suppress(Exception):
                    await websocket.send_json({"auth_ok": True})
                continue

            if action == "join_room":
                target_room_id = str(payload.get("room_id", "") or "").strip()
                display_name = str(
                    payload.get("display_name", "") or ws_username or ws_user_id
                ).strip()
                room = await deps.join_collaboration_room(
                    websocket,
                    room_id=target_room_id,
                    user_id=ws_user_id,
                    username=ws_username,
                    display_name=display_name,
                    user_role=ws_user_role,
                )
                joined_room_id = room.room_id
                continue

            if action == "cancel" and active_task and not active_task.done():
                active_task.cancel()
                await websocket.send_json(
                    {
                        "chunk": "\n\n*[Sistem: İşlem kullanıcı tarafından iptal edildi]*\n",
                        "done": True,
                    }
                )
                continue

            if action == "cancel" and joined_room_id:
                existing_room = deps.collaboration_rooms.get(joined_room_id)
                if (
                    existing_room
                    and existing_room.active_task
                    and not existing_room.active_task.done()
                ):
                    existing_room.active_task.cancel()
                continue

            if not user_message:
                continue

            client_ip = websocket.client.host if websocket.client else "unknown"
            if await deps.redis_is_rate_limited(
                "chat_ws", client_ip, deps.rate_limit, deps.rate_window
            ):
                await websocket.send_json(
                    {
                        "chunk": "[Hız Sınırı] Çok fazla istek. Lütfen bir dakika bekleyin.",
                        "done": True,
                    }
                )
                continue

            await _cancel_task_and_wait(active_task)

            if joined_room_id:
                room_entry = deps.collaboration_rooms.get(joined_room_id)
                if room_entry is None:
                    room_entry = await deps.join_collaboration_room(
                        websocket,
                        room_id=joined_room_id,
                        user_id=ws_user_id,
                        username=ws_username,
                        display_name=ws_username or ws_user_id,
                        user_role=ws_user_role,
                    )
                room = room_entry
                display_name = (
                    str(payload.get("display_name", "") or ws_username or ws_user_id).strip()
                    or ws_username
                    or ws_user_id
                    or "Anonim"
                )
                user_message_payload = deps.build_room_message(
                    room_id=room.room_id,
                    role="user",
                    content=user_message,
                    author_name=display_name,
                    author_id=ws_user_id or display_name,
                    kind="sidar_command"
                    if deps.is_sidar_mention(user_message)
                    else "collaboration_note",
                )
                deps.append_room_message(room, user_message_payload)
                await deps.broadcast_room_payload(
                    room, {"type": "room_message", "message": user_message_payload}
                )

                if deps.is_sidar_mention(user_message):
                    command = deps.strip_sidar_mention(user_message)
                    if not command:
                        await deps.broadcast_room_payload(
                            room,
                            {
                                "type": "room_error",
                                "room_id": room.room_id,
                                "error": "@Sidar etiketi sonrası komut bulunamadı.",
                            },
                        )
                        continue
                    participant = room.participants.get(deps.socket_key(websocket))
                    if deps.collaboration_command_requires_write(command) and not (
                        participant and participant.can_write
                    ):
                        deps.append_room_telemetry(
                            room,
                            {
                                "id": secrets.token_hex(8),
                                "room_id": room.room_id,
                                "kind": "rbac_denied",
                                "source": "collaboration_rbac",
                                "content": command,
                                "ts": deps.collaboration_now_iso(),
                            },
                        )
                        await deps.broadcast_room_payload(
                            room,
                            {
                                "type": "room_error",
                                "room_id": room.room_id,
                                "error": "Bu kullanıcı ortak çalışma alanında yazma yetkisine sahip değil.",
                            },
                        )
                        continue
                    await _cancel_task_and_wait(room.active_task)
                    room.active_task = asyncio.create_task(
                        generate_room_response(room, actor_name=display_name, msg=command)
                    )
                    await asyncio.sleep(0)
                continue

            active_task = asyncio.create_task(generate_response(user_message))
            await asyncio.sleep(0)

    except WebSocketDisconnect:
        deps.logger.info("İstemci WebSocket bağlantısını kesti.")
        await _cancel_task_and_wait(active_task)
        if joined_room_id:
            room = deps.collaboration_rooms.get(joined_room_id)
            await _cancel_task_and_wait(getattr(room, "active_task", None))
        await deps.leave_collaboration_room(websocket)
    except Exception as _ws_exc:
        # anyio.ClosedResourceError: uvicorn/anyio üst katmanının bağlantı
        # kapatma sinyali — WebSocketDisconnect ile eşdeğer, normal çıkış.
        if deps.anyio_closed is not None and isinstance(_ws_exc, deps.anyio_closed):
            deps.logger.info("İstemci WebSocket bağlantısını kesti (anyio ClosedResourceError).")
            await _cancel_task_and_wait(active_task)
            if joined_room_id:
                room = deps.collaboration_rooms.get(joined_room_id)
                await _cancel_task_and_wait(getattr(room, "active_task", None))
            await deps.leave_collaboration_room(websocket)
        else:
            deps.logger.warning("WebSocket beklenmedik hata: %s", _ws_exc)
            with contextlib.suppress(Exception):
                await websocket.send_json(
                    {"error": "WebSocket oturumu beklenmedik şekilde sonlandı.", "done": True}
                )
            with contextlib.suppress(Exception):
                await deps.leave_collaboration_room(websocket)
