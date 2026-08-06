import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { fetchJson } from "../lib/api.js";
import { errorMessage } from "../lib/errors.js";
import { useAsyncStatus } from "../hooks/useAsyncStatus.js";

interface PromptItem {
  id: string | number;
  role_name: string;
  prompt_text: string;
  is_active: boolean;
  version: number;
  updated_at: string;
}

interface PromptListResponse {
  items?: PromptItem[];
}

interface PromptActivationResponse {
  version: number;
}

interface PromptForm {
  role_name: string;
  prompt_text: string;
  activate: boolean;
}

const EMPTY_FORM: PromptForm = {
  role_name: "system",
  prompt_text: "",
  activate: true,
};

export function PromptAdminPanel() {
  const [items, setItems] = useState<PromptItem[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [filter, setFilter] = useState("system");
  const [form, setForm] = useState(EMPTY_FORM);
  const [feedback, setFeedback] = useState("");
  const { loading, error, setError, run } = useAsyncStatus(true);

  const loadPrompts = useCallback(async () => {
    await run(async () => {
      const query = filter.trim() ? `?role_name=${encodeURIComponent(filter.trim())}` : "";
      const data = await fetchJson<PromptListResponse>(`/admin/prompts${query}`);
      setItems(data.items || []);
    }, "Promptlar yüklenemedi.");
  }, [filter, run]);

  useEffect(() => {
    loadPrompts();
  }, [loadPrompts]);

  const activePrompt = useMemo(
    () => items.find((item) => item.role_name === form.role_name && item.is_active),
    [form.role_name, items],
  );

  const updateForm = useCallback(
    <Field extends keyof PromptForm>(field: Field, value: PromptForm[Field]) => {
      setForm((prev) => ({ ...prev, [field]: value }));
    },
    [],
  );

  const handleSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setFeedback("");
    setError("");
    try {
      await fetchJson("/admin/prompts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      setFeedback("Prompt kaydedildi.");
      setForm((prev) => ({ ...prev, prompt_text: "" }));
      await loadPrompts();
    } catch (err: unknown) {
      setError(errorMessage(err, "Prompt kaydedilemedi."));
    } finally {
      setSubmitting(false);
    }
  }, [form, loadPrompts, setError]);

  const handleActivate = useCallback(async (promptId: PromptItem["id"]) => {
    setSubmitting(true);
    setFeedback("");
    setError("");
    try {
      const data = await fetchJson<PromptActivationResponse>("/admin/prompts/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt_id: promptId }),
      });
      setFeedback(`Aktif prompt sürümü v${data.version} olarak güncellendi.`);
      await loadPrompts();
    } catch (err: unknown) {
      setError(errorMessage(err, "Prompt aktifleştirilemedi."));
    } finally {
      setSubmitting(false);
    }
  }, [loadPrompts, setError]);

  return (
    <section className="panel panel--stacked">
      <div className="panel-toolbar">
        <div>
          <h2>Prompt Registry Admin</h2>
          <p className="panel__hint">Backend prompt registry API’si ile dinamik sistem prompt yönetimi.</p>
        </div>
        <div className="inline-controls">
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="role_name filtresi"
            aria-label="role_name filtresi"
          />
          <button onClick={loadPrompts} disabled={loading}>Yenile</button>
        </div>
      </div>

      {error && <div className="banner banner--error" role="alert">{error}</div>}
      {feedback && <div className="banner banner--success">{feedback}</div>}

      <div className="grid-2">
        <form className="card form-card" onSubmit={handleSubmit}>
          <h3>Yeni Prompt Ekle</h3>
          <label>
            Rol adı
            <input
              value={form.role_name}
              onChange={(e) => updateForm("role_name", e.target.value)}
              placeholder="system"
              required
            />
          </label>
          <label>
            Prompt metni
            <textarea
              value={form.prompt_text}
              onChange={(e) => updateForm("prompt_text", e.target.value)}
              rows={10}
              placeholder="Yeni sistem promptu"
              required
            />
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.activate}
              onChange={(e) => updateForm("activate", e.target.checked)}
            />
            Kaydeder kaydetmez aktif yap
          </label>
          {activePrompt && (
            <p className="panel__hint">Seçili rol için aktif sürüm: v{activePrompt.version}</p>
          )}
          <button type="submit" disabled={submitting}>Kaydet</button>
        </form>

        <div className="card">
          <h3>Kayıtlı Promptlar</h3>
          {loading ? <div className="empty-state">Promptlar yükleniyor…</div> : null}
          {!loading && items.length === 0 ? <div className="empty-state">Kayıt bulunamadı.</div> : null}
          <div className="data-list">
            {items.map((item) => (
              <article key={item.id} className="data-list__item">
                <div className="data-list__header">
                  <strong>{item.role_name}</strong>
                  <span className={item.is_active ? "pill pill--success" : "pill"}>v{item.version}</span>
                </div>
                <p className="panel__hint">{item.prompt_text.slice(0, 220)}{item.prompt_text.length > 220 ? "…" : ""}</p>
                <div className="inline-controls inline-controls--compact">
                  <span className="panel__hint">Güncellendi: {item.updated_at}</span>
                  <button
                    type="button"
                    disabled={submitting || item.is_active}
                    onClick={() => handleActivate(item.id)}
                  >
                    {item.is_active ? "Aktif" : "Aktif Yap"}
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
