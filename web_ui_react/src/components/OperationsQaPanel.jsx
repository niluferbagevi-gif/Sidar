import { useCallback, useEffect, useMemo, useState } from "react";
import {
  analyzeCoverage,
  generateCampaignCopy,
  generateLandingPage,
  listHitlPending,
  respondHitl,
  runCoverageBatch,
} from "../lib/api.js";
import { useWebSocket } from "../hooks/useWebSocket.js";

const OPS_ROOM_ID = "ops:control";
const QA_ROOM_ID = "qa:coverage";

export function OperationsQaPanel() {
  const [activeRoom, setActiveRoom] = useState(OPS_ROOM_ID);
  const [events, setEvents] = useState([]);
  const [hitlPending, setHitlPending] = useState([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [output, setOutput] = useState(null);
  const [landingForm, setLandingForm] = useState({
    brand_name: "Sidar",
    offer: "Kurumsal ajan operasyon merkezi",
    audience: "Pazarlama ve QA ekipleri",
    call_to_action: "Demo planla",
    tone: "güven veren",
  });
  const [campaignForm, setCampaignForm] = useState({
    campaign_name: "Operasyon Kontrol Sprinti",
    objective: "Poyraz ve Coverage ajanlarını sahaya almak",
    audience: "Operasyon liderleri",
    channels: "LinkedIn,email",
    offer: "Canlı ajan kontrol paneli",
    tone: "net",
  });
  const [coverageForm, setCoverageForm] = useState({ coverage_xml: "coverage.xml", coveragerc: ".coveragerc", limit: 10 });
  const [batchForm, setBatchForm] = useState({ coverage_xml: "coverage.xml", coveragerc: ".coveragerc", limit: 5, batch_size: 1, append: true });

  const ws = useWebSocket("ops-qa", {
    roomId: activeRoom,
    displayName: "Ops QA Panel",
    onRoomEvent: (event) => setEvents((prev) => [event, ...prev].slice(0, 50)),
    onStatus: (message) => setStatus(message),
    onError: (message) => setError(message),
  });

  const loadHitl = useCallback(async () => {
    try {
      const data = await listHitlPending();
      setHitlPending(data.pending || []);
    } catch (exc) {
      setError(exc.message);
    }
  }, []);

  useEffect(() => {
    loadHitl();
  }, [loadHitl]);

  const runAction = useCallback(async (label, fn) => {
    setError("");
    setStatus(`${label} başlatıldı...`);
    try {
      const result = await fn();
      setOutput(result);
      setStatus(`${label} tamamlandı.`);
      await loadHitl();
    } catch (exc) {
      setError(exc.message);
      setStatus(`${label} başarısız.`);
    }
  }, [loadHitl]);

  const respond = useCallback(async (requestId, approved) => {
    await runAction(approved ? "HITL onay" : "HITL red", () => respondHitl(requestId, {
      approved,
      decided_by: "ops-qa-panel",
      rejection_reason: approved ? "" : "Operatör panelinden reddedildi.",
    }));
  }, [runAction]);

  const eventItems = useMemo(() => events.map((event) => ({
    id: event.id || `${event.ts}-${event.content}`,
    title: `${event.source || "api"} · ${event.kind || "status"}`,
    content: event.content || "",
    ts: event.ts || "",
  })), [events]);

  return (
    <section className="panel panel--stacked" aria-label="Poyraz ve Coverage Operasyonları">
      <div className="panel-toolbar">
        <div>
          <h2>Poyraz & Coverage Kontrol Paneli</h2>
          <p className="panel__hint">REST tetikleme, WebSocket durum izleme ve HITL onay kuyruğu tek sprint yüzeyi.</p>
        </div>
        <div className="inline-controls inline-controls--compact">
          <span className="pill pill--info">WS: {ws.status}</span>
          <button type="button" className="button-secondary" onClick={() => setActiveRoom(activeRoom === OPS_ROOM_ID ? QA_ROOM_ID : OPS_ROOM_ID)}>
            Oda: {activeRoom}
          </button>
        </div>
      </div>

      {error && <div className="banner banner--error" role="alert">{error}</div>}
      {status && <div className="banner banner--success">{status}</div>}

      <div className="grid-2 grid-2--wide">
        <form className="card form-card" onSubmit={(event) => {
          event.preventDefault();
          runAction("Landing page", () => generateLandingPage({ ...landingForm, room_id: OPS_ROOM_ID }));
        }}>
          <h3>Poyraz Landing Page</h3>
          {Object.entries(landingForm).map(([key, value]) => (
            <label key={key}>{key}<input value={value} onChange={(e) => setLandingForm((prev) => ({ ...prev, [key]: e.target.value }))} /></label>
          ))}
          <button type="submit">Landing üret</button>
        </form>

        <form className="card form-card" onSubmit={(event) => {
          event.preventDefault();
          runAction("Kampanya kopyası", () => generateCampaignCopy({
            ...campaignForm,
            channels: campaignForm.channels.split(",").map((item) => item.trim()).filter(Boolean),
            room_id: OPS_ROOM_ID,
          }));
        }}>
          <h3>Poyraz Kampanya</h3>
          {Object.entries(campaignForm).map(([key, value]) => (
            <label key={key}>{key}<input value={value} onChange={(e) => setCampaignForm((prev) => ({ ...prev, [key]: e.target.value }))} /></label>
          ))}
          <button type="submit">Kopya üret</button>
        </form>
      </div>

      <div className="grid-2 grid-2--wide">
        <form className="card form-card" onSubmit={(event) => {
          event.preventDefault();
          runAction("Coverage analiz", () => analyzeCoverage({ ...coverageForm, room_id: QA_ROOM_ID }));
        }}>
          <h3>Coverage Analizi</h3>
          <label>coverage_xml<input value={coverageForm.coverage_xml} onChange={(e) => setCoverageForm((prev) => ({ ...prev, coverage_xml: e.target.value }))} /></label>
          <label>coveragerc<input value={coverageForm.coveragerc} onChange={(e) => setCoverageForm((prev) => ({ ...prev, coveragerc: e.target.value }))} /></label>
          <label>limit<input type="number" value={coverageForm.limit} onChange={(e) => setCoverageForm((prev) => ({ ...prev, limit: Number(e.target.value) }))} /></label>
          <button type="submit">Analiz et</button>
        </form>

        <form className="card form-card" onSubmit={(event) => {
          event.preventDefault();
          runAction("Coverage batch", () => runCoverageBatch({ ...batchForm, room_id: QA_ROOM_ID }));
        }}>
          <h3>Coverage Batch</h3>
          <label>coverage_xml<input value={batchForm.coverage_xml} onChange={(e) => setBatchForm((prev) => ({ ...prev, coverage_xml: e.target.value }))} /></label>
          <label>limit<input type="number" value={batchForm.limit} onChange={(e) => setBatchForm((prev) => ({ ...prev, limit: Number(e.target.value) }))} /></label>
          <label>batch_size<input type="number" value={batchForm.batch_size} onChange={(e) => setBatchForm((prev) => ({ ...prev, batch_size: Number(e.target.value) }))} /></label>
          <label className="checkbox-row"><input type="checkbox" checked={batchForm.append} onChange={(e) => setBatchForm((prev) => ({ ...prev, append: e.target.checked }))} /> append</label>
          <button type="submit">Batch çalıştır</button>
        </form>
      </div>

      <div className="grid-2 grid-2--wide">
        <div className="card">
          <div className="data-list__header">
            <h3>WebSocket Durum Akışı</h3>
            <button type="button" className="button-secondary" onClick={() => setEvents([])}>Temizle</button>
          </div>
          <div className="data-list">
            {eventItems.length === 0 && <p className="empty-state">Henüz durum olayı yok.</p>}
            {eventItems.map((item) => (
              <div key={item.id} className="data-list__item">
                <strong>{item.title}</strong>
                <p className="panel__hint">{item.content}</p>
                <small>{item.ts}</small>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="data-list__header">
            <h3>HITL Onay Kuyruğu</h3>
            <button type="button" className="button-secondary" onClick={loadHitl}>Yenile</button>
          </div>
          <div className="data-list">
            {hitlPending.length === 0 && <p className="empty-state">Bekleyen HITL isteği yok.</p>}
            {hitlPending.map((item) => (
              <div key={item.request_id} className="data-list__item">
                <strong>{item.action}</strong>
                <p>{item.description}</p>
                <pre className="code-block">{JSON.stringify(item.payload || {}, null, 2)}</pre>
                <div className="inline-controls inline-controls--compact">
                  <button type="button" onClick={() => respond(item.request_id, true)}>Onayla</button>
                  <button type="button" className="button-secondary" onClick={() => respond(item.request_id, false)}>Reddet</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Son REST Çıktısı</h3>
        <pre className="code-block">{JSON.stringify(output || {}, null, 2)}</pre>
      </div>
    </section>
  );
}
