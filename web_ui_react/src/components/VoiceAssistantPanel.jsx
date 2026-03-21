import React from "react";

export function VoiceAssistantPanel({ voice }) {
  const { state, statusLabel, toggle, interrupt, supported } = voice;

  return (
    <section className="voice-panel" aria-live="polite">
      <div className="voice-panel__header">
        <div>
          <h3>Duplex Ses Deneyimi</h3>
          <p className="panel__hint">Mikrofon canlı VAD ile izlenir; SİDAR konuşurken araya girerseniz istemci sesi anında keser.</p>
        </div>
        <div className={`voice-panel__badge voice-panel__badge--${state.status}`}>
          {statusLabel}
        </div>
      </div>

      <div className="voice-panel__controls">
        <button type="button" onClick={toggle} disabled={!supported}>
          {state.isMicActive ? "■ Mikrofona Ara Ver" : "🎙 Mikrofonu Başlat"}
        </button>
        <button
          type="button"
          className="button-secondary"
          onClick={interrupt}
          disabled={!state.isAssistantAudioPlaying && !state.queueDepth}
        >
          ⏹ SİDAR Sesini Kes
        </button>
      </div>

      <div className="voice-panel__summary">{supported ? state.summary : "Bu tarayıcı MediaRecorder / getUserMedia desteği sunmuyor."}</div>

      <div className="voice-panel__grid">
        <div className="voice-panel__card">
          <div className="voice-panel__label">Son transcript</div>
          <div className="voice-panel__value">{state.transcript || "Henüz transcript alınmadı."}</div>
        </div>
        <div className="voice-panel__card">
          <div className="voice-panel__label">VAD</div>
          <div className="voice-panel__value">
            seviye {state.vad.level.toFixed(3)} · {state.vad.speaking ? "konuşma" : "sessizlik"}
          </div>
        </div>
        <div className="voice-panel__card">
          <div className="voice-panel__label">Kesme / turn</div>
          <div className="voice-panel__value">
            {state.lastInterruptReason || "—"} · turn #{state.assistantTurnId || 0}
          </div>
        </div>
        <div className="voice-panel__card">
          <div className="voice-panel__label">Buffer / çıktı</div>
          <div className="voice-panel__value">
            {state.bufferedBytes} bayt · kuyruk {state.queueDepth} · {state.audioMimeType || "audio/wav"}
          </div>
        </div>
      </div>

      <div className="voice-panel__diagnostics">
        {state.diagnostics.length === 0 ? (
          <span className="voice-panel__diagnostic-empty">Tanılama olayları burada görünecek.</span>
        ) : (
          state.diagnostics.map((item) => (
            <span className="voice-panel__diagnostic" key={item.id}>
              <strong>{item.label}</strong>
              <span>{item.value}</span>
              <em>{item.at}</em>
            </span>
          ))
        )}
      </div>
    </section>
  );
}