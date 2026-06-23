import React from "react";

export function GraphView({
  graphData,
  graphEdges,
  selectedNode,
  selectedNodeId,
  selectedTaskDraft,
  nodeWidth,
  nodeHeight,
  activityLoading,
  hitlLoading,
  actionBusy,
  running,
  onSelectNode,
  onLoadAutonomyActivity,
  onSyncOperationSurface,
  onAddDraftTaskFromSelected,
  onReplaceFirstTaskFromSelected,
  onRunSelectedNode,
  onRequestNodeReview,
  onLoadPendingApprovals,
}) {
  return (
    <div className="card">
      <div className="inline-controls inline-controls--compact">
        <div>
          <h3>Karar Grafiği</h3>
          <p className="panel__hint">Trigger → Supervisor → görev → ajan → P2P handoff → sonuç → karar telemetrisi zincirini node-graph olarak görün.</p>
        </div>
        <span className="pill">{graphData.nodes.length} node / {graphData.edges.length} edge</span>
      </div>

      <div className="swarm-graph__legend">
        <span className="pill">Role {graphData.metrics.roles}</span>
        <span className="pill">Task {graphData.metrics.tasks}</span>
        <span className="pill pill--success">Decision {graphData.metrics.decisions}</span>
        <span className="pill">Handoff {graphData.metrics.handoffs}</span>
        <span className="pill">Selected {selectedNode.title}</span>
        <button type="button" className="button-secondary" onClick={onLoadAutonomyActivity} disabled={activityLoading}>
          {activityLoading ? "Yükleniyor…" : "Aktiviteyi Yenile"}
        </button>
      </div>

      <div className="swarm-graph">
        <svg
          className="swarm-graph__edges"
          viewBox={`0 0 ${graphData.width} ${graphData.height}`}
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          {graphEdges.map((edge) => (
            <g key={edge.id}>
              <path d={edge.curve} className={`swarm-graph__edge-path swarm-graph__edge-path--${edge.emphasis || "default"}`} />
              <text x={edge.labelX} y={edge.labelY} className="swarm-graph__edge-label">
                {edge.label}
              </text>
            </g>
          ))}
        </svg>

        <div className="swarm-graph__canvas" style={{ minWidth: `${graphData.width}px`, minHeight: `${graphData.height}px` }}>
          {graphData.lanes.map((lane) => (
            <div
              key={lane.id}
              className="swarm-graph__lane"
              style={{ left: `${lane.x}px`, width: `${nodeWidth}px`, height: `${graphData.height - 56}px` }}
            >
              <span className="swarm-graph__lane-badge">{lane.label}</span>
            </div>
          ))}

          {graphData.nodes.map((node) => (
            <article
              key={node.id}
              className={`swarm-graph__node swarm-graph__node--${node.type} ${selectedNodeId === node.id ? "swarm-graph__node--selected" : ""}`}
              style={{ left: `${node.x}px`, top: `${node.y}px`, width: `${nodeWidth}px`, minHeight: `${nodeHeight}px` }}
              onClick={() => onSelectNode(node.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelectNode(node.id);
                }
              }}
            >
              <div className="swarm-graph__node-header">
                <strong>{node.title}</strong>
                <span>{node.subtitle}</span>
              </div>
              <p>{node.body}</p>
              {selectedNodeId === node.id && (
                <div className="swarm-graph__node-actions">
                  <button type="button" className="button-secondary" onClick={(event) => {
                    event.stopPropagation();
                    void onRunSelectedNode();
                  }} disabled={actionBusy || running}>
                    Run node
                  </button>
                  <button type="button" className="button-secondary" onClick={(event) => {
                    event.stopPropagation();
                    onAddDraftTaskFromSelected();
                  }} disabled={actionBusy}>
                    Task’e ekle
                  </button>
                </div>
              )}
            </article>
          ))}
        </div>
      </div>

      <div className="swarm-graph__inspector">
        <div>
          <h4>Node Inspector</h4>
          <p className="panel__hint">Seçili düğümün handoff_depth, p2p_reason ve karar zinciri detayları.</p>
        </div>
        <div className="swarm-graph__inspector-card">
          <div className="swarm-graph__inspector-header">
            <strong>{selectedNode.title}</strong>
            <span>{selectedNode.subtitle}</span>
          </div>
          <p>{selectedNode.body}</p>
          <div className="swarm-graph__operation-surface">
            <div className="swarm-graph__operation-surface-header">
              <div>
                <strong>Live Operation Surface</strong>
                <p className="panel__hint">Grafikte seçili düğüm üzerinden follow-up, rerun ve HITL müdahalesi yapın.</p>
              </div>
              <button type="button" className="button-secondary" onClick={onSyncOperationSurface} disabled={activityLoading || hitlLoading || actionBusy}>
                {activityLoading || hitlLoading ? "Yüzey yenileniyor…" : "Yüzeyi Yenile"}
              </button>
            </div>

            <div className="swarm-graph__operation-grid">
              <div className="swarm-graph__operation-card">
                <span className="pill">Selected node draft</span>
                <p><strong>{selectedTaskDraft.intent}</strong> → {selectedTaskDraft.goal}</p>
                <div className="swarm-graph__action-row">
                  <button type="button" onClick={onAddDraftTaskFromSelected} disabled={actionBusy}>Takip Görevi Ekle</button>
                  <button type="button" className="button-secondary" onClick={onReplaceFirstTaskFromSelected} disabled={actionBusy}>İlk Goal’ı Değiştir</button>
                  <button type="button" className="button-secondary" onClick={() => void onRunSelectedNode()} disabled={actionBusy || running}>Bu Node’u Çalıştır</button>
                </div>
              </div>

              <div className="swarm-graph__operation-card">
                <span className="pill">Human-in-the-loop</span>
                <p>Seçili düğüm için operatör inceleme talebi üreterek otonom akışa kontrollü müdahale edin.</p>
                <div className="swarm-graph__action-row">
                  <button type="button" onClick={() => void onRequestNodeReview()} disabled={actionBusy}>İnceleme İsteği Aç</button>
                  <button type="button" className="button-secondary" onClick={onLoadPendingApprovals} disabled={hitlLoading}>Bekleyenleri Yenile</button>
                </div>
              </div>
            </div>
          </div>
          <dl className="swarm-graph__detail-list">
            {selectedNode.details.map((item) => (
              <React.Fragment key={`${selectedNode.id}-${item.key}`}>
                <dt>{item.key}</dt>
                <dd>{item.value}</dd>
              </React.Fragment>
            ))}
          </dl>
        </div>
      </div>
    </div>
  );
}
