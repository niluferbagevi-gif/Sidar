import React from "react";

export function HitlQueue({
  pendingApprovals,
  operationLog,
  actionBusy,
  onRespondToApproval,
  formatTime,
}) {
  return (
    <div className="card">
      <div className="inline-controls inline-controls--compact">
        <div>
          <h3>Canlı Operasyon Yüzeyi</h3>
          <p className="panel__hint">Graf üstünden yapılan müdahaleler, HITL karar kuyruğu ve son operasyon günlükleri.</p>
        </div>
        <span className="pill">Pending HITL {pendingApprovals.length}</span>
      </div>

      <div className="swarm-graph__operation-grid">
        <div className="swarm-graph__operation-card">
          <strong>Bekleyen Onaylar</strong>
          <div className="swarm-graph__approval-list">
            {pendingApprovals.length === 0 && <div className="empty-state">Bekleyen HITL kaydı yok.</div>}
            {pendingApprovals.map((item, idx) => (
              <article key={`${item.request_id || "pending"}-${idx}`} className="swarm-graph__approval-item">
                <div>
                  <strong>{item.action || "manual"}</strong>
                  <p>{item.description || "Açıklama yok."}</p>
                  <small className="panel__hint">{item.requested_by || "operator"}</small>
                </div>
                <div className="swarm-graph__action-row">
                  <button type="button" onClick={() => void onRespondToApproval(item.request_id, true)} disabled={actionBusy}>Approve</button>
                  <button type="button" className="button-secondary" onClick={() => void onRespondToApproval(item.request_id, false)} disabled={Boolean(actionBusy)}>Reject</button>
                </div>
              </article>
            ))}
          </div>
        </div>

        <div className="swarm-graph__operation-card">
          <strong>Operasyon Günlüğü</strong>
          <ol className="timeline swarm-graph__operation-log" aria-live="polite" aria-label="Operasyon günlüğü">
            {operationLog.length === 0 && <li className="empty-state">Henüz kullanıcı aksiyonu kaydedilmedi.</li>}
            {operationLog.map((entry, idx) => (
              <li key={entry.id} className="timeline__item">
                <span className={`timeline__badge ${entry.tone === "success" ? "timeline__badge--success" : entry.tone === "warning" ? "timeline__badge--warning" : ""}`}>{idx + 1}</span>
                <div>
                  <strong>{entry.message}</strong>
                  <p>{formatTime(entry.ts)}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
