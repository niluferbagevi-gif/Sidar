import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { fetchJson } from "../lib/api.js";
import type { AccessPolicy, AuditLog, ItemsResponse } from "../lib/api.js";
import { errorMessage } from "../lib/errors.js";
import { useAsyncStatus } from "../hooks/useAsyncStatus.js";

interface PolicyForm {
  user_id: string;
  tenant_id: string;
  resource_type: string;
  resource_id: string;
  action: string;
  effect: string;
}

const DEFAULT_POLICY_FORM: PolicyForm = {
  user_id: "",
  tenant_id: "default",
  resource_type: "rag",
  resource_id: "*",
  action: "read",
  effect: "allow",
};

const RESOURCE_OPTIONS = ["rag", "github", "agents", "swarm", "operations", "coverage", "admin"];
const ACTION_OPTIONS = ["read", "write", "execute", "register", "manage"];
const TENANT_DATA_DEBOUNCE_MS = 300;

function normalizePolicyForm(form: PolicyForm): PolicyForm {
  return {
    user_id: form.user_id.trim(),
    tenant_id: form.tenant_id.trim() || "default",
    resource_type: form.resource_type.trim().toLowerCase(),
    resource_id: form.resource_id.trim() || "*",
    action: form.action.trim().toLowerCase(),
    effect: form.effect.trim().toLowerCase(),
  };
}

function formatDate(value?: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("tr-TR");
}

export function TenantAdminPanel() {
  const [policyForm, setPolicyForm] = useState(DEFAULT_POLICY_FORM);
  const [policies, setPolicies] = useState<AccessPolicy[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState("");
  // loadTenantData below has its own abort/debounce/request-sequencing
  // control flow (a real race guard across two parallel fetches), so it uses
  // the raw loading/error setters directly instead of useAsyncStatus's run()
  // convenience wrapper -- see that hook's docstring.
  const { loading, setLoading, error, setError } = useAsyncStatus();
  const activeRequestRef = useRef<AbortController | null>(null);
  const requestSequenceRef = useRef(0);

  const currentTenantId = policyForm.tenant_id.trim() || "default";
  const currentUserId = policyForm.user_id.trim();

  const loadTenantData = useCallback(async () => {
    activeRequestRef.current?.abort();
    const controller = new AbortController();
    activeRequestRef.current = controller;
    const requestSequence = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestSequence;
    setLoading(true);
    setError("");
    try {
      const auditQuery = new URLSearchParams({ tenant_id: currentTenantId, limit: "50" });
      if (currentUserId) auditQuery.set("user_id", currentUserId);

      const requestOptions = { signal: controller.signal };
      const auditRequest = fetchJson<ItemsResponse<AuditLog>>(
        `/admin/audit-logs?${auditQuery.toString()}`,
        requestOptions,
      );
      let policyRequest: Promise<ItemsResponse<AccessPolicy>> = Promise.resolve({ items: [] });
      if (currentUserId) {
        const policyQuery = new URLSearchParams({ tenant_id: currentTenantId });
        policyRequest = fetchJson<ItemsResponse<AccessPolicy>>(
          `/admin/policies/${encodeURIComponent(currentUserId)}?${policyQuery.toString()}`,
          requestOptions,
        );
      }

      const [policyResult, auditResult] = await Promise.all([policyRequest, auditRequest]);
      if (requestSequence !== requestSequenceRef.current) return;
      setAuditLogs(auditResult.items || []);
      setPolicies(policyResult.items || []);
    } catch (err: unknown) {
      if (controller.signal.aborted || requestSequence !== requestSequenceRef.current) return;
      setError(errorMessage(err));
    } finally {
      if (requestSequence === requestSequenceRef.current) {
        activeRequestRef.current = null;
        setLoading(false);
      }
    }
  }, [currentTenantId, currentUserId, setError, setLoading]);

  useEffect(() => {
    const timeoutId = setTimeout(loadTenantData, TENANT_DATA_DEBOUNCE_MS);
    return () => {
      clearTimeout(timeoutId);
      activeRequestRef.current?.abort();
      requestSequenceRef.current += 1;
    };
  }, [loadTenantData]);

  const updateForm = useCallback((field: keyof PolicyForm, value: string) => {
    setPolicyForm((prev) => ({ ...prev, [field]: value }));
  }, []);

  const handleSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
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
      const data = await fetchJson<ItemsResponse<AccessPolicy>>("/admin/policies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setPolicies(data.items || []);
      setFeedback(`${payload.tenant_id} tenant erişim politikası kaydedildi.`);
      await loadTenantData();
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }, [loadTenantData, policyForm, setError]);

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
