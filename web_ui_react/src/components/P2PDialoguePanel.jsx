import React, { useMemo } from "react";
import { useChatStore } from "../hooks/useChatStore.js";

export function P2PDialoguePanel() {
  const { telemetryEvents } = useChatStore();
  const dialogue = useMemo(
    () => telemetryEvents.filter((evt) => evt.kind === "status" || evt.kind === "thought" || evt.kind === "tool_call").slice(-16),
    [telemetryEvents],
  );

  return (
    <section className="panel" role="region" aria-label="Canlı P2P ajan diyaloğu paneli">
      <h2>Canlı P2P Ajan Diyaloğu</h2>
      <p className="panel__hint">Supervisor, reviewer ve coder gibi ajanlar arası konuşma akışını izleyin.</p>
      <div className="event-list" role="log" aria-live="polite" aria-label="P2P diyalog olayları">
        {dialogue.length === 0 && <div className="empty-state">Henüz P2P etkinliği yok. Sohbete mesaj gönderin.</div>}
        {dialogue.map((evt) => (
          <div key={evt.id} className={`event-list__item event-list__item--${evt.kind}`}>
            <div className="event-list__meta">{new Date(evt.ts).toLocaleTimeString("tr-TR")}</div>
            <div className="event-list__content">
              {evt.source ? <strong>{evt.source}: </strong> : null}
              {evt.content}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
