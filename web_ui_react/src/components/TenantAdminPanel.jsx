import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchJson } from "../lib/api.js";

const DEFAULT_POLICY_FORM = {
  user_id: "",
  tenant_id: "default",
  resource_type: "rag",
  resource_id: "*",
  action: "read",
  effect: "allow",
};

const RESOURCE_OPTIONS = ["rag", "github", "agents", "swarm", "operations", "coverage", "admin"];
const ACTION_OPTIONS = ["read", "write", "execute", "register", "manage"];

function normalizePolicyForm(form) {
  return {
    user_id: form.user_id.trim(),
    tenant_id: form.tenant_id.trim() || "default",
    resource_type: form.resource_type.trim().toLowerCase(),
    resource_id: form.resource_id.trim() || "*",
    action: form.action.trim().toLowerCase(),
    effect: form.effect.trim().toLowerCase(),
  };
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("tr-TR");
}

export function TenantAdminPanel() {
  const [policyForm, setPolicyForm] = useState(DEFAULT_POLICY_FORM);
  const [policies, setPolicies] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");

  const currentTenantId = policyForm.tenant_id.trim() || "default";
  const currentUserId = policyForm.user_id.trim();

  const loadTenantData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const auditQuery = new URLSearchParams({ tenant_id: currentTenantId, limit: "50" });
      if (currentUserId) auditQuery.set("user_id", currentUserId);

      const requests = [fetchJson(`/admin/audit-logs?${auditQuery.toString()}`)];
      if (currentUserId) {
        const policyQuery = new URLSearchParams({ tenant_id: currentTenantId });
        requests.unshift(fetchJson(`/admin/policies/${encodeURIComponent(currentUserId)}?${policyQuery.toString()}`));
      }

      const results = await Promise.all(requests);
      const auditResult = results[results.length - 1];
      setAuditLogs(auditResult.items || []);
      setPolicies(currentUserId ? (results[0].items || []) : []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [currentTenantId, currentUserId]);

  useEffect(() => {
    loadTenantData();
  }, [loadTenantData]);

  const updateForm = useCallback((field, value) => {
    setPolicyForm((prev) => ({ ...prev, [field]: value }));
  }, []);

  const handleSubmit = useCallback(async (event) => {
    event.preventDefault();
    const payload = normalizePolicyForm(policyForm);
    if (!payload.user_id) {
      setError("RBAC politikası kaydetmek için kullanıcı ID zorunludur.");
      return;
    }
    setSubmitting(true);
    setFeedback("");
    setError("");
    try {
      const data = await fetchJson("/admin/policies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setPolicies(data.items || []);
      setFeedback(`${payload.tenant_id} tenant erişim politikası kaydedildi.`);
      await loadTenantData();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }, [loadTenantData, policyForm]);

  const tenantStats = useMemo(() => {
    const allowed = auditLogs.filter((item) => item.allowed === true).length;
    return {
      policies: policies.length,
      auditEvents: auditLogs.length,
      allowed,
      denied: auditLogs.length - allowed,
    };
  }, [auditLogs, policies]);

  return (
    <section className="panel panel--stacked" aria-label="Tenant RBAC ve audit paneli">
      <div className="panel-toolbar">
        <div>
          <h2>Tenant Yönetim Paneli</h2>
          <p className="panel__hint">
            Gerçek backend RBAC politikaları ve audit trail kayıtları ile tenant erişimlerini yönetin.
          </p>
        </div>
        <button onClick={loadTenantData} disabled={loading}>{loading ? "Yükleniyor..." : "Yenile"}</button>
      </div>

      {error && <div className="banner banner--error" role="alert">{error}</div>}
      {feedback && <div className="banner banner--success">{feedback}</div>}

      <div className="tenant-summary" aria-label="Tenant özet metrikleri">
        <div className="metric-card"><strong>{currentTenantId}</strong><span>Aktif tenant</span></div>
        <div className="metric-card"><strong>{tenantStats.policies}</strong><span>RBAC politika</span></div>
        <div className="metric-card"><strong>{tenantStats.allowed}</strong><span>İzinli audit</span></div>
        <div className="metric-card metric-card--warning"><strong>{tenantStats.denied}</strong><span>Reddedilen audit</span></div>
      </div>

      <div className="grid-2">
        <form className="card form-card" onSubmit={handleSubmit}>
          <h3>RBAC Politikası</h3>
          <label>
            Kullanıcı ID
            <input
              value={policyForm.user_id}
              onChange={(e) => updateForm("user_id", e.target.value)}
              placeholder="user-123"
              aria-label="Kullanıcı ID"
              required
            />
          </label>
          <label>
            Tenant ID
            <input
              value={policyForm.tenant_id}
              onChange={(e) => updateForm("tenant_id", e.target.value)}
              placeholder="default"
              aria-label="Tenant ID"
              required
            />
          </label>
          <div className="form-row">
            <label>
              Kaynak tipi
              <select value={policyForm.resource_type} onChange={(e) => updateForm("resource_type", e.target.value)}>
                {RESOURCE_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label>
              Aksiyon
              <select value={policyForm.action} onChange={(e) => updateForm("action", e.target.value)}>
                {ACTION_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
          </div>
          <div className="form-row">
            <label>
              Kaynak ID
              <input value={policyForm.resource_id} onChange={(e) => updateForm("resource_id", e.target.value)} placeholder="*" />
            </label>
            <label>
              Etki
              <select value={policyForm.effect} onChange={(e) => updateForm("effect", e.target.value)}>
                <option value="allow">allow</option>
                <option value="deny">deny</option>
              </select>
            </label>
          </div>
          <button type="submit" disabled={submitting}>{submitting ? "Kaydediliyor..." : "Politikayı Kaydet"}</button>
        </form>

        <div className="card">
          <h3>Mevcut Politikalar</h3>
          {!currentUserId && <p className="panel__hint">Politika listelemek için kullanıcı ID girin.</p>}
          {currentUserId && policies.length === 0 && !loading && <p className="panel__hint">Bu kullanıcı/tenant için politika yok.</p>}
          <div className="policy-list">
            {policies.map((policy) => (
              <article key={policy.id} className="policy-item">
                <strong>{policy.effect.toUpperCase()} · {policy.resource_type}:{policy.resource_id}</strong>
                <span>{policy.action} · user:{policy.user_id} · tenant:{policy.tenant_id}</span>
              </article>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Audit Trail</h3>
        {auditLogs.length === 0 && !loading && <p className="panel__hint">Seçili tenant için audit kaydı bulunamadı.</p>}
        <div className="audit-table" role="table" aria-label="Tenant audit kayıtları">
          <div className="audit-table__row audit-table__row--head" role="row">
            <span>Durum</span><span>Aksiyon</span><span>Kaynak</span><span>Kullanıcı</span><span>Zaman</span>
          </div>
          {auditLogs.map((item) => (
            <div className="audit-table__row" role="row" key={item.id}>
              <span className={item.allowed === true ? "status-pill status-pill--ok" : "status-pill status-pill--danger"}>
                {item.allowed === true ? "İzin" : "Red"}
              </span>
              <span>{item.action}</span>
              <span>{item.resource}</span>
              <span>{item.user_id || "anonim"}</span>
              <span>{formatDate(item.timestamp)}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
