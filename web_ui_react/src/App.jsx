import React, { useMemo, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { ChatPanel } from "./components/ChatPanel.jsx";
import { P2PDialoguePanel } from "./components/P2PDialoguePanel.jsx";
import { SwarmFlowPanel } from "./components/SwarmFlowPanel.jsx";
import { TenantAdminPanel } from "./components/TenantAdminPanel.jsx";
import { PromptAdminPanel } from "./components/PromptAdminPanel.jsx";
import { AgentManagerPanel } from "./components/AgentManagerPanel.jsx";
import { PluginMarketplacePanel } from "./components/PluginMarketplacePanel.jsx";
import { withPanelErrorBoundary } from "./components/PanelErrorBoundary.jsx";
import { getStoredToken, setStoredToken } from "./lib/api.js";

const NAV_ITEMS = [
  { to: "/chat", label: "Sohbet" },
  { to: "/p2p", label: "P2P Diyalog" },
  { to: "/swarm", label: "Swarm Akışı" },
  { to: "/admin/prompts", label: "Prompt Admin" },
  { to: "/admin/plugins", label: "Plugin Marketplace" },
  { to: "/admin/agents", label: "Agent Manager" },
  { to: "/admin/tenants", label: "Tenant Admin" },
];

export default function App() {
  const [tokenValue, setTokenValue] = useState(() => getStoredToken() || "");
  const [savedAt, setSavedAt] = useState(0);

  const tokenHint = useMemo(() => {
    if (!tokenValue) return "Admin ve sohbet API’leri için Bearer token saklayın.";
    return `Token hazır${savedAt ? ` · ${new Date(savedAt).toLocaleTimeString("tr-TR")}` : ""}`;
  }, [savedAt, tokenValue]);

  const handleTokenSave = () => {
    setStoredToken(tokenValue);
    setSavedAt(Date.now());
  };

  return (
    <div className="app app--wide">
      <header className="app__header app__header--stacked">
        <div>
          <h1 className="app__title">
            SİDAR <span className="app__subtitle">Kurumsal Agent Control Center</span>
          </h1>
          <p className="panel__hint">Route tabanlı SPA deneyimi, admin panelleri ve dinamik swarm araçları.</p>
        </div>
        <div className="token-toolbar">
          <input
            type="password"
            value={tokenValue}
            onChange={(e) => setTokenValue(e.target.value)}
            placeholder="Bearer token"
            aria-label="Bearer token"
          />
          <button onClick={handleTokenSave}>Token Kaydet</button>
          <span className="token-toolbar__hint">{tokenHint}</span>
        </div>
      </header>

      <nav className="app__tabs" aria-label="Ana bölümler">
        {NAV_ITEMS.map((item) => (
          <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "is-active" : "")}>
            {item.label}
          </NavLink>
        ))}
      </nav>

      <main className="app__main">
        <Routes>
          <Route path="/" element={<Navigate to="/chat" replace />} />
          <Route path="/chat" element={<ChatPanel key={`chat-${savedAt}`} />} />
          <Route path="/p2p" element={withPanelErrorBoundary(<P2PDialoguePanel />)} />
          <Route path="/swarm" element={withPanelErrorBoundary(<SwarmFlowPanel />)} />
          <Route path="/admin/prompts" element={<PromptAdminPanel />} />
          <Route path="/admin/plugins" element={<PluginMarketplacePanel />} />
          <Route path="/admin/agents" element={withPanelErrorBoundary(<AgentManagerPanel />)} />
          <Route path="/admin/tenants" element={<TenantAdminPanel />} />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Routes>
      </main>
    </div>
  );
}
