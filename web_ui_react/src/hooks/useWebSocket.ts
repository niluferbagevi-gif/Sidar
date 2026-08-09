import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { TOKEN_CHANGE_EVENT, TOKEN_KEY, getStoredToken } from "../lib/api.js";

const WS_URL = () =>
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/chat`;

const RECONNECT_BASE_DELAY_MS = 800;
const RECONNECT_MAX_DELAY_MS = 20_000;
const RECONNECT_JITTER_MS = 600;

export type WebSocketStatus =
  | "unauthenticated"
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "error";

export type RoomParticipant = Record<string, unknown>;
export type RoomMessage = Record<string, unknown> & {
  id: string;
  content?: string;
  role?: string;
  request_id?: string;
};
export type CollaborationEvent = Record<string, unknown> & {
  kind?: "status" | "tool_call" | "thought" | string;
  source?: string;
  content?: string;
};
export type RoomStateMessage = Record<string, unknown> & {
  type: "room_state";
  room_id: string;
  participants: RoomParticipant[];
  messages: RoomMessage[];
  telemetry: CollaborationEvent[];
};

export type SidarWebSocketMessage =
  | { auth_ok: true }
  | RoomStateMessage
  | { type: "presence"; room_id: string; participants: RoomParticipant[] }
  | { type: "room_message"; message: RoomMessage }
  | { type: "assistant_stream_start"; room_id: string; request_id: string; author_name: string }
  | { type: "assistant_chunk"; room_id: string; request_id: string; chunk: string; author_name: string }
  | { type: "assistant_done"; room_id: string; request_id: string; message: RoomMessage | null; cancelled?: boolean }
  | { type: "collaboration_event"; event: CollaborationEvent }
  | { type: "room_error"; room_id: string; error: string; request_id?: string };

type IncomingMessage = Record<string, unknown> & {
  type?: string;
  auth_ok?: boolean;
  room_id?: string;
  participants?: RoomParticipant[];
  message?: RoomMessage | null;
  request_id?: string;
  chunk?: string;
  content?: string;
  event?: CollaborationEvent;
  error?: string;
  done?: boolean;
  status?: string;
  tool_call?: string;
  thought?: string;
};

export interface UseWebSocketOptions {
  roomId?: string;
  displayName?: string;
  onChunk?: (chunk: string, requestId?: string) => void;
  onDone?: (message: string | RoomMessage | null, requestId?: string) => void;
  onError?: (message: string) => void;
  onStatus?: (status: string) => void;
  onToolCall?: (toolCall: string) => void;
  onThought?: (thought: string) => void;
  onRoomState?: (state: RoomStateMessage) => void;
  onRoomMessage?: (message: RoomMessage) => void;
  onPresence?: (participants: RoomParticipant[]) => void;
  onRoomEvent?: (event: CollaborationEvent) => void;
  onAssistantStart?: (requestId: string) => void;
}

export type OutgoingWebSocketMessage = string | Record<string, unknown>;

export interface UseWebSocketResult {
  send: (message: OutgoingWebSocketMessage) => void;
  status: WebSocketStatus;
  connect: () => void;
  disconnect: () => void;
  joinRoom: (roomId?: string, displayName?: string) => void;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const parseIncomingMessage = (raw: string): IncomingMessage => {
  const parsed: unknown = JSON.parse(raw);
  if (!isRecord(parsed)) throw new TypeError("WebSocket payload must be an object");
  return parsed as IncomingMessage;
};

export function useWebSocket(
  _sessionId: string | undefined,
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
  }: UseWebSocketOptions = {},
): UseWebSocketResult {
  const wsRef = useRef<WebSocket | null>(null);
  const joinedRoomRef = useRef<string>("");
  const [status, setStatus] = useState<WebSocketStatus>(() =>
    getStoredToken() ? "disconnected" : "unauthenticated"
  );
  const bufferRef = useRef<string>("");
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const manualCloseRef = useRef(false);
  const connectRef = useRef<(() => void) | null>(null);
  const callbacksRef = useRef<UseWebSocketOptions>({});
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

  const joinRoom = useCallback((targetRoomId?: string, targetDisplayName?: string) => {
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

    const token = getStoredToken();
    if (!token) {
      setStatus("unauthenticated");
      return;
    }

    setStatus("connecting");
    clearReconnectTimer();
    // Token is carried only via the WebSocket subprotocol handshake, never
    // in the URL — a query-string token would land in plaintext in proxy
    // access logs and browser history (see web/security.py's
    // extract_ws_header_token, which never reads a query parameter).
    const ws = new WebSocket(WS_URL(), [token]);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const raw = typeof event.data === "string" ? event.data : String(event.data);

      if (raw === "[DONE]") {
        callbacksRef.current.onDone?.(bufferRef.current);
        bufferRef.current = "";
        return;
      }

      try {
        const msg = parseIncomingMessage(raw);
        if (msg.auth_ok) {
          reconnectAttemptRef.current = 0;
          setStatus("connected");
          joinedRoomRef.current = "";
          joinRoom(roomId, displayName);
          return;
        }

        if (msg.type === "room_state") {
          joinedRoomRef.current = msg.room_id || joinedRoomRef.current;
          // Normalize older servers to the canonical typed room-state contract.
          callbacksRef.current.onRoomState?.({
            ...msg,
            type: "room_state",
            room_id: msg.room_id || "",
            participants: Array.isArray(msg.participants) ? msg.participants : [],
            messages: Array.isArray(msg.messages) ? msg.messages : [],
            telemetry: Array.isArray(msg.telemetry) ? msg.telemetry : [],
          });
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
          const chunk = typeof msg.content === "string" ? msg.content : msg.chunk || "";
          bufferRef.current += chunk;
          callbacksRef.current.onChunk?.(chunk);
        } else if (msg.type === "error" || typeof msg.error === "string") {
          const error = typeof msg.content === "string" ? msg.content : msg.error || "";
          callbacksRef.current.onError?.(error);
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

    ws.onclose = (event) => {
      wsRef.current = null;
      setStatus("disconnected");
      if (manualCloseRef.current) return;
      // Auth-related closes (invalid/expired/missing token — see
      // web/security.py's ws_close_policy_violation, always code 1008)
      // won't resolve by retrying: the server will keep rejecting the same
      // stale token every ~20s. Surface "unauthenticated" instead so the UI
      // can prompt a re-login rather than polling forever.
      if (event?.code === 1008) {
        setStatus("unauthenticated");
        return;
      }
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

  const send = useCallback((message: OutgoingWebSocketMessage) => {
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
    const handleStorage = (event: StorageEvent) => {
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
