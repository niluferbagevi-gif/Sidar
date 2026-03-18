import React, { useMemo } from "react";
import { useChatStore } from "../hooks/useChatStore.js";

export function P2PDialoguePanel() {
  const { telemetryEvents } = useChatStore();
  const dialogue = useMemo(
    () => telemetryEvents.filter((evt) => evt.kind === "status" || evt.kind === "thought").slice(-12),
    [telemetryEvents],
  );

  return (
    <section className="panel">
      <h2>Canlı P2P Ajan Diyaloğu</h2>
      <p className="panel__hint">Supervisor, reviewer ve coder gibi ajanlar arası konuşma akışını izleyin.</p>
      <div className="event-list">
        {dialogue.length === 0 && <div className="empty-state">Henüz P2P etkinliği yok. Sohbete mesaj gönderin.</div>}
        {dialogue.map((evt) => (
          <div key={evt.id} className={`event-list__item event-list__item--${evt.kind}`}>
            <div className="event-list__meta">{new Date(evt.ts).toLocaleTimeString("tr-TR")}</div>
            <div className="event-list__content">{evt.content}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
