import React, { lazy, Suspense, useMemo, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { ChatPanel } from "./components/ChatPanel.jsx";
import { withPanelErrorBoundary } from "./components/PanelErrorBoundary.jsx";
import { getStoredToken, getTokenPrincipal, isAdminPrincipal, setStoredToken } from "./lib/api.js";

function MissingLazyPanel({ exportName }) {
  return <div className="panel__hint">Panel bileşeni yüklenemedi: {exportName}</div>;
}

function lazyNamed(loader, exportName) {
  return lazy(() =>
    loader().then((module) => {
      const Component = module?.[exportName];
      return { default: Component || (() => <MissingLazyPanel exportName={exportName} />) };
    }),
  );
}

const P2PDialoguePanel = lazyNamed(() => import("./components/P2PDialoguePanel.jsx"), "P2PDialoguePanel");
const SwarmFlowPanel = lazyNamed(() => import("./components/SwarmFlowPanel.jsx"), "SwarmFlowPanel");
const OperationsQaPanel = lazyNamed(() => import("./components/OperationsQaPanel.jsx"), "OperationsQaPanel");
const PromptAdminPanel = lazyNamed(() => import("./components/PromptAdminPanel.jsx"), "PromptAdminPanel");
const PluginMarketplacePanel = lazyNamed(() => import("./components/PluginMarketplacePanel.jsx"), "PluginMarketplacePanel");
const AgentManagerPanel = lazyNamed(() => import("./components/AgentManagerPanel.jsx"), "AgentManagerPanel");
const TenantAdminPanel = lazyNamed(() => import("./components/TenantAdminPanel.jsx"), "TenantAdminPanel");

const ADMIN_ROUTES = [
  { path: "/admin/prompts", Panel: PromptAdminPanel },
  { path: "/admin/plugins", Panel: PluginMarketplacePanel },
  { path: "/admin/agents", Panel: AgentManagerPanel },
  { path: "/admin/tenants", Panel: TenantAdminPanel },
];

function withLazyPanel(node) {
  return withPanelErrorBoundary(<Suspense fallback={<div className="panel__hint">Panel yükleniyor...</div>}>{node}</Suspense>);
}

const NAV_ITEMS = [
  { to: "/chat", label: "Sohbet" },
  { to: "/p2p", label: "P2P Diyalog" },
  { to: "/swarm", label: "Swarm Akışı" },
  { to: "/ops-qa", label: "Poyraz & Coverage" },
  { to: "/admin/prompts", label: "Prompt Admin", requiresAdmin: true },
  { to: "/admin/plugins", label: "Plugin Marketplace", requiresAdmin: true },
  { to: "/admin/agents", label: "Agent Manager", requiresAdmin: true },
  { to: "/admin/tenants", label: "Tenant Admin", requiresAdmin: true },
];

function AdminRoute({ isAdmin, children }) {
  if (isAdmin) return children;
  return (
    <section className="panel" role="alert">
      <h2>Admin yetkisi gerekli</h2>
      <p className="panel__hint">Bu panel backend ile aynı admin yetki modelini izler. Admin rolü olmayan oturumlar için işlem yapılmaz.</p>
    </section>
  );
}

export default function App() {
  const [tokenValue, setTokenValue] = useState(() => getStoredToken() || "");
  const [savedAt, setSavedAt] = useState(0);
  const [persistToken, setPersistToken] = useState(false);

  const principal = useMemo(() => getTokenPrincipal(tokenValue), [tokenValue]);
  const isAdmin = isAdminPrincipal(principal);
  const visibleNavItems = useMemo(() => NAV_ITEMS.filter((item) => !item.requiresAdmin || isAdmin), [isAdmin]);

  const tokenHint = useMemo(() => {
    if (!tokenValue) return "Admin ve sohbet API’leri için Bearer token girin; varsayılan olarak yalnızca bellekte tutulur.";
    const roleHint = principal?.role ? ` · rol: ${principal.role}` : "";
    return `Token hazır${roleHint}${savedAt ? ` · ${new Date(savedAt).toLocaleTimeString("tr-TR")}` : ""}`;
  }, [principal?.role, savedAt, tokenValue]);

  const handleTokenSave = () => {
    setStoredToken(tokenValue, { persist: persistToken });
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
          <label className="token-toolbar__persist">
            <input type="checkbox" checked={persistToken} onChange={(e) => setPersistToken(e.target.checked)} />
            Bu cihazda kalıcı sakla
          </label>
          <button onClick={handleTokenSave}>Token Kaydet</button>
          <span className="token-toolbar__hint">{tokenHint}</span>
        </div>
      </header>

      <nav className="app__tabs" aria-label="Ana bölümler">
        {visibleNavItems.map((item) => (
          <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "is-active" : "")}>
            {item.label}
          </NavLink>
        ))}
      </nav>

      <main className="app__main">
        <Routes>
          <Route path="/" element={<Navigate to="/chat" replace />} />
          <Route path="/chat" element={withPanelErrorBoundary(<ChatPanel />)} />
          <Route path="/p2p" element={withLazyPanel(<P2PDialoguePanel />)} />
          <Route path="/swarm" element={withLazyPanel(<SwarmFlowPanel />)} />
          <Route path="/ops-qa" element={withLazyPanel(<OperationsQaPanel />)} />
          {ADMIN_ROUTES.map(({ path, Panel }) => (
            <Route key={path} path={path} element={<AdminRoute isAdmin={isAdmin}>{withLazyPanel(<Panel />)}</AdminRoute>} />
          ))}
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Routes>
      </main>
    </div>
  );
}
