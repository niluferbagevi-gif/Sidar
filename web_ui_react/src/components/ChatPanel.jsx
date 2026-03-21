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
    roomId,
    displayName,
    setRoomId,
    setDisplayName,
    hydrateRoom,
    updateParticipants,
    pushRoomMessage,
    startAssistantStream,
    appendChunk,
    commitAssistantMessage,
    setError,
    addTelemetryEvent,
    newSession,
    participants,
  } = useChatStore();

  const { send, status } = useWebSocket(sessionId, {
    roomId,
    displayName,
    onChunk: appendChunk,
    onDone: commitAssistantMessage,
    onError: setError,
    onStatus: (msg) => addTelemetryEvent("status", msg),
    onToolCall: (msg) => addTelemetryEvent("tool_call", msg),
    onThought: (msg) => addTelemetryEvent("thought", msg),
    onRoomState: hydrateRoom,
    onRoomMessage: pushRoomMessage,
    onPresence: updateParticipants,
    onRoomEvent: (event) => addTelemetryEvent(event.kind || "status", event.content || "", event),
    onAssistantStart: startAssistantStream,
  });

  const handleSend = useCallback(
    (text) => {
      send(text);
    },
    [send],
  );

  const voice = useVoiceAssistant({
    onUserTranscript: (transcript) => {
      send(`@Sidar ${transcript}`);
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
          <p className="panel__hint">Room tabanlı ortak çalışma alanı. Ekip arkadaşlarınızın @Sidar komutlarını ve swarm akışını canlı izleyin.</p>
        </div>
        <StatusBar
          wsStatus={status}
          onNewSession={handleNewSession}
          voiceStatus={voice.statusLabel}
          roomId={roomId}
          collaborators={participants.length}
        />
      </header>
      <div className="app__chat-shell">
        <section className="collab-bar">
          <label>
            Workspace / Room
            <input value={roomId} onChange={(e) => setRoomId(e.target.value)} placeholder="workspace:sidar" />
          </label>
          <label>
            Görünen ad
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="Operatör" />
          </label>
          <div className="collab-bar__summary">
            <strong>{participants.length}</strong>
            <span>katılımcı bağlı</span>
          </div>
        </section>
        <ChatWindow />
        <VoiceAssistantPanel voice={voice} />
        <footer className="app__footer">
          <ChatInput onSend={handleSend} disabled={status !== "connected"} />
        </footer>
      </div>
    </>
  );
}