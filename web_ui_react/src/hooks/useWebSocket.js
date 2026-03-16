/**
 * useWebSocket — Sidar WebSocket bağlantı hook'u.
 *
 * FastAPI web_server.py /ws/{session_id} endpoint'ine bağlanır.
 * Akış mesajları (streaming) otomatik olarak yakalanır ve
 * `onChunk` callback'i ile iletilir.
 *
 * Kullanım:
 *   const { send, status } = useWebSocket(sessionId, {
 *     onChunk: (text) => setPartial(prev => prev + text),
 *     onDone:  (full) => setMessages(m => [...m, { role:"assistant", content:full }]),
 *     onError: (msg)  => console.error(msg),
 *   });
 */

import { useCallback, useEffect, useRef, useState } from "react";

const WS_URL = (sessionId) =>
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${sessionId}`;

/**
 * @param {string} sessionId
 * @param {{ onChunk?: Function, onDone?: Function, onError?: Function }} callbacks
 */
export function useWebSocket(sessionId, { onChunk, onDone, onError } = {}) {
  const wsRef = useRef(null);
  const [status, setStatus] = useState("disconnected"); // disconnected | connecting | connected | error
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

      // Akış sonu işareti
      if (raw === "[DONE]") {
        onDone?.(bufferRef.current);
        bufferRef.current = "";
        return;
      }

      // JSON zarf: { type, content } veya ham metin chunk
      try {
        const msg = JSON.parse(raw);
        if (msg.type === "chunk") {
          bufferRef.current += msg.content;
          onChunk?.(msg.content);
        } else if (msg.type === "error") {
          onError?.(msg.content);
        } else if (msg.type === "done") {
          onDone?.(bufferRef.current || msg.content);
          bufferRef.current = "";
        }
      } catch {
        // Ham metin chunk (JSON değil)
        bufferRef.current += raw;
        onChunk?.(raw);
      }
    };

    ws.onerror = () => {
      setStatus("error");
      onError?.("WebSocket bağlantı hatası.");
    };

    ws.onclose = () => setStatus("disconnected");
  }, [sessionId, onChunk, onDone, onError]);

  const disconnect = useCallback(() => {
    wsRef.current?.close();
  }, []);

  const send = useCallback((message) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      onError?.("Bağlantı kapalı.");
      return;
    }
    bufferRef.current = "";
    wsRef.current.send(typeof message === "string" ? message : JSON.stringify(message));
  }, [onError]);

  // sessionId değişince yeniden bağlan
  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { send, status, connect, disconnect };
}