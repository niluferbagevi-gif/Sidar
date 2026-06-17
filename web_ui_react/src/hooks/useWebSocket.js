import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { getStoredToken, TOKEN_CHANGE_EVENT, TOKEN_KEY } from "../lib/api.js";

const WS_URL = () =>
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/chat`;

const RECONNECT_BASE_DELAY_MS = 800;
const RECONNECT_MAX_DELAY_MS = 20_000;
const RECONNECT_JITTER_MS = 600;

function readWebSocketToken() {
  const storedToken = getStoredToken().trim();
  if (storedToken) return storedToken;
  return (typeof localStorage !== "undefined" && localStorage.getItem(TOKEN_KEY)?.trim()) || "";
}

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
  const [status, setStatus] = useState(() =>
    readWebSocketToken()
      ? "disconnected"
      : "unauthenticated"
  );
  const bufferRef = useRef("");
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef(null);
  const manualCloseRef = useRef(false);
  const connectRef = useRef(null);
  const callbacksRef = useRef({});
  callbacksRef.current = {
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
  };

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

    const token = readWebSocketToken();
    if (!token) {
      setStatus("unauthenticated");
      return;
    }

    setStatus("connecting");
    clearReconnectTimer();
    const ws = new WebSocket(WS_URL(), [token]);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const raw = event.data;

      if (raw === "[DONE]") {
        callbacksRef.current.onDone?.(bufferRef.current);
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
          callbacksRef.current.onRoomState?.(msg);
          return;
        }
        if (msg.type === "presence") {
          callbacksRef.current.onPresence?.(msg.participants || []);
          return;
        }
        if (msg.type === "room_message" && msg.message) {
          callbacksRef.current.onRoomMessage?.(msg.message);
          return;
        }
        if (msg.type === "assistant_stream_start") {
          bufferRef.current = "";
          callbacksRef.current.onAssistantStart?.(msg.request_id || "");
          return;
        }
        if (msg.type === "assistant_chunk") {
          const chunk = msg.chunk || "";
          bufferRef.current += chunk;
          callbacksRef.current.onChunk?.(chunk, msg.request_id || "");
          return;
        }
        if (msg.type === "assistant_done") {
          callbacksRef.current.onDone?.(msg.message || null, msg.request_id || "");
          bufferRef.current = "";
          return;
        }
        if (msg.type === "collaboration_event" && msg.event) {
          const eventKind = msg.event.kind || "status";
          callbacksRef.current.onRoomEvent?.(msg.event);
          if (eventKind === "status") callbacksRef.current.onStatus?.(`${msg.event.source || "room"}: ${msg.event.content || ""}`);
          if (eventKind === "tool_call") callbacksRef.current.onToolCall?.(msg.event.content || "");
          if (eventKind === "thought") callbacksRef.current.onThought?.(msg.event.content || "");
          return;
        }
        if (msg.type === "room_error") {
          callbacksRef.current.onError?.(msg.error || "Ortak çalışma alanı hatası.");
          return;
        }

        if (msg.type === "chunk" || typeof msg.chunk === "string") {
          const chunk = msg.content ?? msg.chunk;
          bufferRef.current += chunk;
          callbacksRef.current.onChunk?.(chunk);
        } else if (msg.type === "error" || typeof msg.error === "string") {
          callbacksRef.current.onError?.(msg.content ?? msg.error);
        } else if (msg.type === "done" || msg.done === true) {
          callbacksRef.current.onDone?.(bufferRef.current || msg.content || "");
          bufferRef.current = "";
        } else if (typeof msg.status === "string") {
          callbacksRef.current.onStatus?.(msg.status);
        } else if (typeof msg.tool_call === "string") {
          callbacksRef.current.onToolCall?.(msg.tool_call);
        } else if (typeof msg.thought === "string") {
          callbacksRef.current.onThought?.(msg.thought);
        }
      } catch {
        bufferRef.current += raw;
        callbacksRef.current.onChunk?.(raw);
      }
    };

    ws.onerror = () => {
      setStatus("error");
      callbacksRef.current.onError?.("WebSocket bağlantı hatası.");
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
    roomId,
    scheduleReconnect,
  ]);

  const disconnect = useCallback(() => {
    manualCloseRef.current = true;
    clearReconnectTimer();
    wsRef.current?.close();
  }, [clearReconnectTimer]);

  const restartConnection = useCallback(() => {
    clearReconnectTimer();
    joinedRoomRef.current = "";
    const previousSocket = wsRef.current;
    wsRef.current = null;
    if (previousSocket) {
      previousSocket.onclose = null;
      previousSocket.onerror = null;
      previousSocket.onmessage = null;
      previousSocket.close();
    }
    manualCloseRef.current = false;
    connect();
  }, [clearReconnectTimer, connect]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const send = useCallback((message) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      callbacksRef.current.onError?.("Bağlantı kapalı.");
      return;
    }
    bufferRef.current = "";
    const payload = typeof message === "string"
      ? { action: "message", message, room_id: roomId, display_name: displayName }
      : { room_id: roomId, display_name: displayName, ...message };
    wsRef.current.send(JSON.stringify(payload));
  }, [displayName, roomId]);

  // İlk bağlantı durumunu paint öncesinde hesapla; token eksikse StatusBar ilk
  // görünür render'da doğrudan "Token gerekli" etiketini gösterebilsin.
  useLayoutEffect(() => {
    manualCloseRef.current = false;
    connect();
    return () => {
      manualCloseRef.current = true;
      clearReconnectTimer();
      disconnect();
    };
  }, [clearReconnectTimer, connect, disconnect]);

  useEffect(() => {
    /* c8 ignore next -- React SSR sırasında effect çalışmadığı için bu savunma dalı runtime guard olarak tutulur. */
    if (typeof window === "undefined") return undefined;
    const handleTokenChange = () => restartConnection();
    const handleStorage = (event) => {
      if (event.key === TOKEN_KEY) restartConnection();
    };
    window.addEventListener(TOKEN_CHANGE_EVENT, handleTokenChange);
    window.addEventListener("storage", handleStorage);
    return () => {
      window.removeEventListener(TOKEN_CHANGE_EVENT, handleTokenChange);
      window.removeEventListener("storage", handleStorage);
    };
  }, [restartConnection]);

  useEffect(() => {
    joinRoom(roomId, displayName);
  }, [displayName, joinRoom, roomId]);

  return { send, status, connect, disconnect, joinRoom };
}
