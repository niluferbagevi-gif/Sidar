/**
 * App — Sidar React UI kök bileşeni.
 *
 * FastAPI web_server.py /ws/{session_id} WebSocket endpoint'ine bağlanır,
 * akış mesajlarını gerçek zamanlı gösterir.
 */

import React, { useCallback } from "react";
import { ChatWindow } from "./components/ChatWindow.jsx";
import { ChatInput } from "./components/ChatInput.jsx";
import { StatusBar } from "./components/StatusBar.jsx";
import { useWebSocket } from "./hooks/useWebSocket.js";
import { useChatStore } from "./hooks/useChatStore.js";

export default function App() {
  const {
    sessionId,
    addUserMessage,
    appendChunk,
    commitAssistantMessage,
    setError,
    newSession,
  } = useChatStore();

  const { send, status } = useWebSocket(sessionId, {
    onChunk: appendChunk,
    onDone:  commitAssistantMessage,
    onError: setError,
  });

  const handleSend = useCallback((text) => {
    addUserMessage(text);
    // FastAPI web_server.py WebSocket handler formatı: düz metin mesaj
    send(text);
  }, [addUserMessage, send]);

  const handleNewSession = useCallback(() => {
    newSession();
  }, [newSession]);

  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">SİDAR <span className="app__subtitle">Yazılım Mühendisi AI</span></h1>
        <StatusBar wsStatus={status} onNewSession={handleNewSession} />
      </header>

      <main className="app__main">
        <ChatWindow />
      </main>

      <footer className="app__footer">
        <ChatInput onSend={handleSend} disabled={status !== "connected"} />
      </footer>
    </div>
  );
}