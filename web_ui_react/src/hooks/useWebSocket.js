import { useCallback, useEffect, useRef, useState } from "react";

const WS_URL = () =>
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/chat`;

const TOKEN_KEY = "sidar_access_token";
const RECONNECT_BASE_DELAY_MS = 800;
const RECONNECT_MAX_DELAY_MS = 20_000;
const RECONNECT_JITTER_MS = 600;

export function useWebSocket(
  _sessionId,
  {
    roomId,
    displayName,
    onChunk,
    onDone,
    onError,
    onStatus,
    onToolCall,
    onThought,
    onRoomState,
    onRoomMessage,
    onPresence,
    onRoomEvent,
    onAssistantStart,
  } = {},
) {
  const wsRef = useRef(null);
  const joinedRoomRef = useRef("");
  const [status, setStatus] = useState("disconnected");
  const bufferRef = useRef("");
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef(null);
  const manualCloseRef = useRef(false);
  const connectRef = useRef(null);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const scheduleReconnect = useCallback(() => {
    clearReconnectTimer();
    reconnectAttemptRef.current += 1;
    const exponentialDelay = Math.min(
      RECONNECT_MAX_DELAY_MS,
      RECONNECT_BASE_DELAY_MS * (2 ** (reconnectAttemptRef.current - 1)),
    );
    const jitter = Math.floor(Math.random() * RECONNECT_JITTER_MS);
    const nextDelay = exponentialDelay + jitter;
    setStatus("reconnecting");
    reconnectTimerRef.current = setTimeout(() => {
      connectRef.current?.();
    }, nextDelay);
  }, [clearReconnectTimer]);

  const joinRoom = useCallback((targetRoomId, targetDisplayName) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    const nextRoom = String(targetRoomId || "").trim();
    if (!nextRoom || joinedRoomRef.current === nextRoom) return;
    wsRef.current.send(JSON.stringify({
      action: "join_room",
      room_id: nextRoom,
      display_name: String(targetDisplayName || "").trim() || "Operatör",
    }));
    joinedRoomRef.current = nextRoom;
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const token = (localStorage.getItem(TOKEN_KEY) || "").trim();
    if (!token) {
      setStatus("unauthenticated");
      onError?.("Lütfen giriş yapın. Erişim belirteci bulunamadı.");
      return;
    }

    setStatus("connecting");
    clearReconnectTimer();
    const ws = new WebSocket(WS_URL(), [token]);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const raw = event.data;

      if (raw === "[DONE]") {
        onDone?.(bufferRef.current);
        bufferRef.current = "";
        return;
      }

      try {
        const msg = JSON.parse(raw);
        if (msg.auth_ok) {
          reconnectAttemptRef.current = 0;
          setStatus("connected");
          joinedRoomRef.current = "";
          joinRoom(roomId, displayName);
          return;
        }

        if (msg.type === "room_state") {
          joinedRoomRef.current = msg.room_id || joinedRoomRef.current;
          onRoomState?.(msg);
          return;
        }
        if (msg.type === "presence") {
          onPresence?.(msg.participants || []);
          return;
        }
        if (msg.type === "room_message" && msg.message) {
          onRoomMessage?.(msg.message);
          return;
        }
        if (msg.type === "assistant_stream_start") {
          bufferRef.current = "";
          onAssistantStart?.(msg.request_id || "");
          return;
        }
        if (msg.type === "assistant_chunk") {
          const chunk = msg.chunk || "";
          bufferRef.current += chunk;
          onChunk?.(chunk, msg.request_id || "");
          return;
        }
        if (msg.type === "assistant_done") {
          onDone?.(msg.message || null, msg.request_id || "");
          bufferRef.current = "";
          return;
        }
        if (msg.type === "collaboration_event" && msg.event) {
          const eventKind = msg.event.kind || "status";
          onRoomEvent?.(msg.event);
          if (eventKind === "status") onStatus?.(`${msg.event.source || "room"}: ${msg.event.content || ""}`);
          if (eventKind === "tool_call") onToolCall?.(msg.event.content || "");
          if (eventKind === "thought") onThought?.(msg.event.content || "");
          return;
        }
        if (msg.type === "room_error") {
          onError?.(msg.error || "Ortak çalışma alanı hatası.");
          return;
        }

        if (msg.type === "chunk" || typeof msg.chunk === "string") {
          const chunk = msg.content ?? msg.chunk;
          bufferRef.current += chunk;
          onChunk?.(chunk);
        } else if (msg.type === "error" || typeof msg.error === "string") {
          onError?.(msg.content ?? msg.error);
        } else if (msg.type === "done" || msg.done === true) {
          onDone?.(bufferRef.current || msg.content || "");
          bufferRef.current = "";
        } else if (typeof msg.status === "string") {
          onStatus?.(msg.status);
        } else if (typeof msg.tool_call === "string") {
          onToolCall?.(msg.tool_call);
        } else if (typeof msg.thought === "string") {
          onThought?.(msg.thought);
        }
      } catch {
        bufferRef.current += raw;
        onChunk?.(raw);
      }
    };

    ws.onerror = () => {
      setStatus("error");
      onError?.("WebSocket bağlantı hatası.");
    };

    ws.onclose = () => {
      wsRef.current = null;
      setStatus("disconnected");
      if (manualCloseRef.current) return;
      scheduleReconnect();
    };
  }, [
    clearReconnectTimer,
    displayName,
    joinRoom,
    onChunk,
    onDone,
    onError,
    onPresence,
    onRoomEvent,
    onRoomMessage,
    onRoomState,
    onStatus,
    onThought,
    onToolCall,
    onAssistantStart,
    roomId,
    scheduleReconnect,
  ]);

  const disconnect = useCallback(() => {
    manualCloseRef.current = true;
    clearReconnectTimer();
    wsRef.current?.close();
  }, [clearReconnectTimer]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const send = useCallback((message) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      onError?.("Bağlantı kapalı.");
      return;
    }
    bufferRef.current = "";
    const payload = typeof message === "string"
      ? { action: "message", message, room_id: roomId, display_name: displayName }
      : { room_id: roomId, display_name: displayName, ...message };
    wsRef.current.send(JSON.stringify(payload));
  }, [displayName, onError, roomId]);

  useEffect(() => {
    manualCloseRef.current = false;
    connect();
    return () => {
      manualCloseRef.current = true;
      clearReconnectTimer();
      disconnect();
    };
  }, [clearReconnectTimer, connect, disconnect]);

  useEffect(() => {
    joinRoom(roomId, displayName);
  }, [displayName, joinRoom, roomId]);

  return { send, status, connect, disconnect, joinRoom };
}
