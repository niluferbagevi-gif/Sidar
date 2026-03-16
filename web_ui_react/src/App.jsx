import React, { useCallback, useMemo, useState } from "react";
import { ChatWindow } from "./components/ChatWindow.jsx";
import { ChatInput } from "./components/ChatInput.jsx";
import { StatusBar } from "./components/StatusBar.jsx";
import { useWebSocket } from "./hooks/useWebSocket.js";
import { useChatStore } from "./hooks/useChatStore.js";

const INITIAL_TENANTS = [
  { id: "t-acme", name: "Acme Finans", plan: "Enterprise", agentQuota: 42, status: "active" },
  { id: "t-orion", name: "Orion Savunma", plan: "Business", agentQuota: 18, status: "active" },
  { id: "t-nova", name: "Nova Lojistik", plan: "Starter", agentQuota: 8, status: "paused" },
];

function P2PDialoguePanel() {
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

function SwarmFlowPanel() {
  const { telemetryEvents } = useChatStore();
  const steps = useMemo(
    () => telemetryEvents.filter((evt) => evt.kind === "tool_call" || evt.kind === "status").slice(-8),
    [telemetryEvents],
  );

  return (
    <section className="panel">
      <h2>Swarm Görev Akışı</h2>
      <p className="panel__hint">Araç çağrıları ve ajan durumları ile paralel/sıralı yürütmeyi takip edin.</p>
      <ol className="timeline">
        {steps.length === 0 && <li className="empty-state">Akış verisi bulunamadı.</li>}
        {steps.map((step, idx) => (
          <li key={step.id} className="timeline__item">
            <span className="timeline__badge">{idx + 1}</span>
            <div>
              <strong>{step.kind === "tool_call" ? "Tool Call" : "Durum"}</strong>
              <p>{step.content}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function TenantAdminPanel() {
  const [tenants, setTenants] = useState(INITIAL_TENANTS);
  const [name, setName] = useState("");

  const addTenant = useCallback(() => {
    const normalized = name.trim();
    if (!normalized) return;
    setTenants((prev) => [
      {
        id: `t-${normalized.toLowerCase().replace(/\s+/g, "-")}`,
        name: normalized,
        plan: "Starter",
        agentQuota: 5,
        status: "active",
      },
      ...prev,
    ]);
    setName("");
  }, [name]);

  const toggleStatus = useCallback((tenantId) => {
    setTenants((prev) =>
      prev.map((item) =>
        item.id === tenantId
          ? { ...item, status: item.status === "active" ? "paused" : "active" }
          : item,
      ),
    );
  }, []);

  return (
    <section className="panel">
      <h2>Tenant Yönetim Paneli</h2>
      <div className="tenant-form">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Yeni tenant adı"
          aria-label="Yeni tenant adı"
        />
        <button onClick={addTenant}>Tenant Ekle</button>
      </div>
      <div className="tenant-grid">
        {tenants.map((tenant) => (
          <article key={tenant.id} className="tenant-card">
            <h3>{tenant.name}</h3>
            <p>Plan: {tenant.plan}</p>
            <p>Ajan kotası: {tenant.agentQuota}</p>
            <p>Durum: <strong>{tenant.status === "active" ? "Aktif" : "Duraklatıldı"}</strong></p>
            <button onClick={() => toggleStatus(tenant.id)}>
              {tenant.status === "active" ? "Duraklat" : "Aktifleştir"}
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}

export default function App() {
  const {
    sessionId,
    addUserMessage,
    appendChunk,
    commitAssistantMessage,
    setError,
    addTelemetryEvent,
    newSession,
  } = useChatStore();

  const [activeTab, setActiveTab] = useState("chat");

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

  const handleNewSession = useCallback(() => {
    newSession();
  }, [newSession]);

  return (
    <div className="app app--wide">
      <header className="app__header">
        <h1 className="app__title">
          SİDAR <span className="app__subtitle">Kurumsal Agent Control Center</span>
        </h1>
        <StatusBar wsStatus={status} onNewSession={handleNewSession} />
      </header>

      <nav className="app__tabs" aria-label="Ana bölümler">
        <button onClick={() => setActiveTab("chat")} className={activeTab === "chat" ? "is-active" : ""}>Sohbet</button>
        <button onClick={() => setActiveTab("p2p")} className={activeTab === "p2p" ? "is-active" : ""}>P2P Diyalog</button>
        <button onClick={() => setActiveTab("swarm")} className={activeTab === "swarm" ? "is-active" : ""}>Swarm Akışı</button>
        <button onClick={() => setActiveTab("tenant")} className={activeTab === "tenant" ? "is-active" : ""}>Tenant Admin</button>
      </nav>

      <main className="app__main">
        {activeTab === "chat" && (
          <>
            <ChatWindow />
            <footer className="app__footer">
              <ChatInput onSend={handleSend} disabled={status !== "connected"} />
            </footer>
          </>
        )}
        {activeTab === "p2p" && <P2PDialoguePanel />}
        {activeTab === "swarm" && <SwarmFlowPanel />}
        {activeTab === "tenant" && <TenantAdminPanel />}
      </main>
    </div>
  );
}
