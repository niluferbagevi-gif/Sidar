
export function AutonomyTimeline({ autonomySummary, autonomyActivity, steps, formatTime }) {
  return (
    <>
      <div className="card">
        <div className="inline-controls inline-controls--compact">
          <div>
            <h3>Graf İçgörüleri</h3>
            <p className="panel__hint">Karar akışını özetleyen hızlı görünüm.</p>
          </div>
        </div>
        <div className="swarm-insights">
          <div className="swarm-insights__item">
            <span>Autonomy trigger</span>
            <strong>{autonomySummary.total}</strong>
          </div>
          <div className="swarm-insights__item">
            <span>Başarılı trigger</span>
            <strong>{autonomySummary.success}</strong>
          </div>
          <div className="swarm-insights__item">
            <span>Başarısız trigger</span>
            <strong>{autonomySummary.failed}</strong>
          </div>
          <div className="swarm-insights__item">
            <span>Kaynak sayısı</span>
            <strong>{autonomySummary.sources}</strong>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="inline-controls inline-controls--compact">
          <div>
            <h3>Proaktif Aktivite Akışı</h3>
            <p className="panel__hint">Webhook/cron/manual wake kayıtları son 8 olay üzerinden listelenir.</p>
          </div>
        </div>
        <ol className="timeline">
          {(autonomyActivity.items || []).length === 0 && <li className="empty-state">Henüz proaktif aktivite kaydı yok.</li>}
          {(autonomyActivity.items || []).map((item, idx) => (
            <li key={`${item.trigger_id || "trigger"}-${idx}`} className="timeline__item">
              <span className={`timeline__badge ${item.status === "success" ? "timeline__badge--success" : "timeline__badge--warning"}`}>
                {idx + 1}
              </span>
              <div>
                <strong>{item.event_name || "trigger"}</strong>
                <p>{item.summary || "Özet yok."}</p>
                <small className="panel__hint">{item.source || "manual"} · {item.status || "unknown"}</small>
              </div>
            </li>
          ))}
        </ol>
      </div>

      <div className="card">
        <h3>Canlı Karar Günlüğü</h3>
        <ol className="timeline">
          {steps.length === 0 && <li className="empty-state">Akış verisi bulunamadı.</li>}
          {steps.map((step, idx) => (
            <li key={step.id} className="timeline__item">
              <span className="timeline__badge">{idx + 1}</span>
              <div>
                <strong>{step.kind === "tool_call" ? "Tool Call" : step.kind === "thought" ? "Thought" : "Durum"}</strong>
                <p>{step.content}</p>
                <small className="panel__hint">{formatTime(step.ts)}</small>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </>
  );
}
