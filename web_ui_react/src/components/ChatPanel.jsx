import React, { useCallback } from "react";
import { ChatWindow } from "./ChatWindow.jsx";
import { ChatInput } from "./ChatInput.jsx";
import { StatusBar } from "./StatusBar.jsx";
import { VoiceAssistantPanel } from "./VoiceAssistantPanel.jsx";
import { useWebSocket } from "../hooks/useWebSocket.js";
import { useVoiceAssistant } from "../hooks/useVoiceAssistant.js";
import { useChatStore } from "../hooks/useChatStore.js";

export function ChatPanel() {
  const {
    sessionId,
    addUserMessage,
    appendChunk,
    commitAssistantMessage,
    setError,
    addTelemetryEvent,
    newSession,
  } = useChatStore();

  const { send, status } = useWebSocket(sessionId, {
    onChunk: appendChunk,
    onDone: commitAssistantMessage,
    onError: setError,
    onStatus: (msg) => addTelemetryEvent("status", msg),
    onToolCall: (msg) => addTelemetryEvent("tool_call", msg),
    onThought: (msg) => addTelemetryEvent("thought", msg),
  });

  const handleSend = useCallback(
    (text) => {
      addUserMessage(text);
      send(text);
    },
    [addUserMessage, send],
  );

  const voice = useVoiceAssistant({
    onUserTranscript: (transcript) => {
      addUserMessage(`🎤 ${transcript}`);
    },
    onAssistantChunk: appendChunk,
    onAssistantDone: commitAssistantMessage,
    onError: setError,
    onTelemetry: (kind, content) => addTelemetryEvent(kind, content),
  });

  const handleNewSession = useCallback(() => {
    voice.stop();
    newSession();
  }, [newSession, voice]);

  return (
    <>
      <header className="panel-toolbar panel-toolbar--chat">
        <div>
          <h2>Sohbet</h2>
          <p className="panel__hint">WebSocket üzerinden canlı agent streaming akışı.</p>
        </div>
        <StatusBar wsStatus={status} onNewSession={handleNewSession} voiceStatus={voice.statusLabel} />
      </header>
      <div className="app__chat-shell">
        <ChatWindow />
        <VoiceAssistantPanel voice={voice} />
        <footer className="app__footer">
          <ChatInput onSend={handleSend} disabled={status !== "connected"} />
        </footer>
      </div>
    </>
  );
}