import { useCallback, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { buildAuthHeaders } from "../lib/api.js";

interface AgentRegistrationForm {
  roleName: string;
  className: string;
  capabilities: string;
  description: string;
  version: string;
}

interface RegisteredAgent {
  role_name: string;
  version: string;
  capabilities?: string[];
  [key: string]: unknown;
}

const DEFAULT_FORM: AgentRegistrationForm = {
  roleName: "",
  className: "",
  capabilities: "",
  description: "",
  version: "1.0.0",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function registrationError(payload: unknown): string {
  if (isRecord(payload)) {
    if (typeof payload.detail === "string" && payload.detail) return payload.detail;
    if (typeof payload.error === "string" && payload.error) return payload.error;
  }
  return "Ajan yüklenemedi";
}

function registeredAgent(payload: unknown): RegisteredAgent {
  if (!isRecord(payload) || !isRecord(payload.agent)) {
    throw new Error("Ajan kayıt cevabı geçersiz");
  }
  const { agent } = payload;
  if (typeof agent.role_name !== "string" || typeof agent.version !== "string") {
    throw new Error("Ajan kayıt cevabı geçersiz");
  }
  if (
    agent.capabilities !== undefined &&
    (!Array.isArray(agent.capabilities) ||
      !agent.capabilities.every((capability) => typeof capability === "string"))
  ) {
    throw new Error("Ajan kayıt cevabı geçersiz");
  }
  return {
    ...agent,
    role_name: agent.role_name,
    version: agent.version,
    capabilities: agent.capabilities,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Ajan yüklenemedi";
}

export function AgentManagerPanel() {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<RegisteredAgent | null>(null);

  const capabilityList = useMemo(
    () => form.capabilities.split(",").map((item) => item.trim()).filter(Boolean),
    [form.capabilities],
  );

  const updateField = useCallback(
    <Field extends keyof AgentRegistrationForm>(
      field: Field,
      value: AgentRegistrationForm[Field],
    ) => {
      setForm((prev) => ({ ...prev, [field]: value }));
    },
    [],
  );

  const handleSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    if (!file) {
      setError("Lütfen bir Python ajan dosyası seçin.");
      return;
    }

    setSubmitting(true);
    setError("");
    setResult(null);
    try {
      const payload = new FormData();
      payload.append("file", file);
      if (form.roleName.trim()) payload.append("role_name", form.roleName.trim());
      if (form.className.trim()) payload.append("class_name", form.className.trim());
      if (form.capabilities.trim()) payload.append("capabilities", form.capabilities.trim());
      if (form.description.trim()) payload.append("description", form.description.trim());
      payload.append("version", form.version.trim() || "1.0.0");

      const response = await fetch("/api/agents/register-file", {
        method: "POST",
        headers: buildAuthHeaders(),
        body: payload,
      });
      const data: unknown = await response.json();
      if (!response.ok) {
        throw new Error(registrationError(data));
      }
      setResult(registeredAgent(data));
      setFile(null);
      setForm(DEFAULT_FORM);
      formElement.reset();
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }, [file, form]);

  return (
    <section className="panel panel--stacked" aria-label="Agent Manager paneli">
      <div className="panel-toolbar">
        <div>
          <h2>Agent Manager</h2>
          <p className="panel__hint">Çalışma zamanında Python plugin ajanlarını yükleyin ve swarm ekosistemine katın.</p>
        </div>
      </div>

      {error && <div className="banner banner--error" role="alert">{error}</div>}
      {result && (
        <div className="banner banner--success">
          <strong>{result.role_name}</strong> ajanı yüklendi. Sürüm: {result.version}
        </div>
      )}

      <div className="grid-2">
        <form className="card form-card" onSubmit={handleSubmit}>
          <h3>Plugin Dosyası Yükle</h3>
          <label>
            Python dosyası (.py)
            <input type="file" accept=".py,text/x-python" onChange={(e) => setFile(e.target.files?.[0] || null)} required />
          </label>
          <label>
            Role name
            <input value={form.roleName} onChange={(e) => updateField("roleName", e.target.value)} placeholder="security-auditor" />
          </label>
          <label>
            Class name
            <input value={form.className} onChange={(e) => updateField("className", e.target.value)} placeholder="MyCustomAgent" />
          </label>
          <label>
            Capabilities
            <input value={form.capabilities} onChange={(e) => updateField("capabilities", e.target.value)} placeholder="security_audit, quality_check" />
          </label>
          <label>
            Açıklama
            <textarea value={form.description} onChange={(e) => updateField("description", e.target.value)} rows={4} placeholder="Plugin ajanının kısa açıklaması" />
          </label>
          <label>
            Sürüm
            <input value={form.version} onChange={(e) => updateField("version", e.target.value)} placeholder="1.0.0" />
          </label>
          <button type="submit" disabled={submitting}>{submitting ? "Yükleniyor…" : "Ajanı Kaydet"}</button>
        </form>

        <div className="card">
          <h3>Önizleme</h3>
          <p className="panel__hint">Bu form doğrudan <code>/api/agents/register-file</code> endpoint’ine multipart istek gönderir.</p>
          <ul className="meta-list">
            <li><strong>Dosya:</strong> {file?.name || "Seçilmedi"}</li>
            <li><strong>Role:</strong> {form.roleName || (file?.name ? file.name.replace(/\.py$/, "") : "Otomatik")}</li>
            <li><strong>Class:</strong> {form.className || "Otomatik keşif"}</li>
            <li><strong>Capabilities:</strong> {capabilityList.length ? capabilityList.join(", ") : "Belirtilmedi"}</li>
            <li><strong>Sürüm:</strong> {form.version || "1.0.0"}</li>
          </ul>
          {result ? (
            <pre className="code-block">{JSON.stringify(result, null, 2)}</pre>
          ) : (
            <div className="empty-state">Yükleme sonrası ajan meta verisi burada gösterilir.</div>
          )}
        </div>
      </div>
    </section>
  );
}
