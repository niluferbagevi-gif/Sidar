import { useCallback, useEffect, useRef, useState } from "react";

const WS_URL = (sessionId) =>
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${sessionId}`;

export function useWebSocket(sessionId, { onChunk, onDone, onError, onStatus, onToolCall, onThought } = {}) {
  const wsRef = useRef(null);
  const [status, setStatus] = useState("disconnected");
  const bufferRef = useRef("");

  const connect = useCallback(() => {
    if (!sessionId) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setStatus("connecting");
    const ws = new WebSocket(WS_URL(sessionId));
    wsRef.current = ws;

    ws.onopen = () => setStatus("connected");

    ws.onmessage = (event) => {
      const raw = event.data;

      if (raw === "[DONE]") {
        onDone?.(bufferRef.current);
        bufferRef.current = "";
        return;
      }

      try {
        const msg = JSON.parse(raw);
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

    ws.onclose = () => setStatus("disconnected");
  }, [sessionId, onChunk, onDone, onError, onStatus, onToolCall, onThought]);

  const disconnect = useCallback(() => {
    wsRef.current?.close();
  }, []);

  const send = useCallback(
    (message) => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        onError?.("Bağlantı kapalı.");
        return;
      }
      bufferRef.current = "";
      wsRef.current.send(typeof message === "string" ? message : JSON.stringify(message));
    },
    [onError],
  );

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { send, status, connect, disconnect };
}
