import { useCallback, useEffect, useRef, useState } from "react";

const WS_URL = () =>
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/chat`;

const TOKEN_KEY = "sidar_access_token";

export function useWebSocket(_sessionId, { onChunk, onDone, onError, onStatus, onToolCall, onThought } = {}) {
  const wsRef = useRef(null);
  const [status, setStatus] = useState("disconnected");
  const bufferRef = useRef("");

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const token = (localStorage.getItem(TOKEN_KEY) || "").trim();
    if (!token) {
      setStatus("unauthenticated");
      onError?.("Lütfen giriş yapın. Erişim belirteci bulunamadı.");
      return;
    }

    setStatus("connecting");
    // Token'ı Sec-WebSocket-Protocol başlığı üzerinden gönder (JSON payload'dan daha güvenli)
    const ws = new WebSocket(WS_URL(), token ? [token] : undefined);
    wsRef.current = ws;

    ws.onopen = () => {
      // Başlık tabanlı auth kullanılıyor; onopen'da ek JSON auth mesajı gönderilmez.
      // Sunucu token'ı HTTP upgrade başlığından okuyarak auth_ok döner.
    };

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
          setStatus("connected");
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

    ws.onclose = () => setStatus("disconnected");
  }, [onChunk, onDone, onError, onStatus, onToolCall, onThought]);

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
      const payload = typeof message === "string"
        ? { action: "message", message }
        : message;
      wsRef.current.send(JSON.stringify(payload));
    },
    [onError],
  );

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { send, status, connect, disconnect };
}