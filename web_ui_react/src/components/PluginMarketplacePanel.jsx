import React, { useCallback, useEffect, useMemo, useState } from "react";
import { fetchJson } from "../lib/api.js";

const ACTION_LABELS = {
  install: "Yükle",
  reload: "Yeniden Yükle",
  remove: "Kaldır",
};

export function PluginMarketplacePanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyPluginId, setBusyPluginId] = useState("");
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");

  const loadMarketplace = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchJson("/api/plugin-marketplace/catalog");
      setItems(data.items || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMarketplace();
  }, [loadMarketplace]);

  const installedCount = useMemo(
    () => items.filter((item) => item.installed || item.live_registered).length,
    [items],
  );

  const handleAction = useCallback(async (pluginId, action) => {
    setBusyPluginId(`${pluginId}:${action}`);
    setFeedback("");
    setError("");
    try {
      if (action === "remove") {
        await fetchJson(`/api/plugin-marketplace/install/${encodeURIComponent(pluginId)}`, {
          method: "DELETE",
        });
      } else {
        await fetchJson(`/api/plugin-marketplace/${action}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plugin_id: pluginId }),
        });
      }
      setFeedback(`Plugin işlemi tamamlandı: ${pluginId} → ${ACTION_LABELS[action]}.`);
      await loadMarketplace();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyPluginId("");
    }
  }, [loadMarketplace]);

  return (
    <section className="panel panel--stacked">
      <div className="panel-toolbar">
        <div>
          <h2>Plugin Marketplace</h2>
          <p className="panel__hint">
            SİDAR’a restart atmadan yeni beceriler ekleyin. Marketplace kartları doğrudan hot-load API’lerine bağlıdır.
          </p>
        </div>
        <div className="inline-controls">
          <span className="pill pill--info">{installedCount} aktif plugin</span>
          <button className="button-secondary" onClick={loadMarketplace} disabled={loading}>
            {loading ? "Yükleniyor…" : "Yenile"}
          </button>
        </div>
      </div>

      {error && <div className="banner banner--error">{error}</div>}
      {feedback && <div className="banner banner--success">{feedback}</div>}

      <div className="marketplace-grid">
        {items.map((item) => {
          const isInstalled = item.installed || item.live_registered;
          const installBusy = busyPluginId === `${item.plugin_id}:install`;
          const reloadBusy = busyPluginId === `${item.plugin_id}:reload`;
          const removeBusy = busyPluginId === `${item.plugin_id}:remove`;
          return (
            <article className="marketplace-card" key={item.plugin_id}>
              <div className="marketplace-card__header">
                <div>
                  <div className="marketplace-card__eyebrow">{item.category}</div>
                  <h3>{item.name}</h3>
                </div>
                <span className={`pill ${isInstalled ? "pill--success" : "pill--warn"}`}>
                  {isInstalled ? "Canlı" : "Hazır"}
                </span>
              </div>

              <p className="marketplace-card__summary">{item.summary}</p>
              <p className="panel__hint">{item.description}</p>

              <dl className="marketplace-meta">
                <div>
                  <dt>Rol</dt>
                  <dd>{item.role_name}</dd>
                </div>
                <div>
                  <dt>Sürüm</dt>
                  <dd>{item.version}</dd>
                </div>
                <div>
                  <dt>Dosya</dt>
                  <dd>{item.entrypoint}</dd>
                </div>
              </dl>

              <div className="marketplace-capabilities">
                {(item.capabilities || []).map((capability) => (
                  <span key={capability} className="pill">{capability}</span>
                ))}
              </div>

              <div className="marketplace-card__footer">
                <button onClick={() => handleAction(item.plugin_id, "install")} disabled={installBusy || loading}>
                  {installBusy ? "Yükleniyor…" : "Anında Yükle"}
                </button>
                <button
                  className="button-secondary"
                  onClick={() => handleAction(item.plugin_id, "reload")}
                  disabled={!isInstalled || reloadBusy || loading}
                >
                  {reloadBusy ? "Yenileniyor…" : "Hot Reload"}
                </button>
                <button
                  className="button-secondary"
                  onClick={() => handleAction(item.plugin_id, "remove")}
                  disabled={!isInstalled || removeBusy || loading}
                >
                  {removeBusy ? "Kaldırılıyor…" : "Devre Dışı Bırak"}
                </button>
              </div>
            </article>
          );
        })}
      </div>

      {!loading && items.length === 0 ? (
        <div className="empty-state">Henüz marketplace girdisi bulunamadı.</div>
      ) : null}
    </section>
  );
}