import { useCallback, useEffect, useMemo, useState } from "react";
import { useChatStore } from "../hooks/useChatStore.js";
import { fetchJson } from "../lib/api.js";
import {
  buildAgentNodes,
  buildAutonomyEdges,
  buildAutonomyNodes,
  buildHandoffEdges,
  buildHandoffEvents,
  buildHandoffNodes,
  buildLanes,
  buildResultEdges,
  buildResultNodes,
  buildRoleHints,
  buildSupervisorNode,
  buildTaskDraftFromNode,
  buildTaskEdges,
  buildTaskNodes,
  buildTelemetryEdges,
  buildTelemetryNodes,
  buildTelemetryWithActors,
  computeGraphDimensions,
  computeGraphMetrics,
  formatTime,
  inferHitlActionFromNode,
  NODE_HEIGHT,
  NODE_WIDTH,
} from "../lib/swarmFlowGraph.js";
import { AutonomyTimeline } from "./panels/swarm/AutonomyTimeline.jsx";
import { GraphView } from "./panels/swarm/GraphView.jsx";
import { HitlQueue } from "./panels/swarm/HitlQueue.jsx";
import { TaskEditor } from "./panels/swarm/TaskEditor.jsx";

export {
  buildTaskDraftFromNode,
  clampText,
  inferHitlActionFromNode,
  inferTelemetryActor,
  prettifyReason,
  prettifyRole,
  toDetailEntries,
} from "../lib/swarmFlowGraph.js";

const DEFAULT_TASKS = [
  { goal: "Kod tabanında güvenlik riski taşıyan noktaları tara", intent: "security_audit", preferred_agent: "" },
  { goal: "Bulunan riskler için kısa bir aksiyon planı üret", intent: "summarization", preferred_agent: "" },
];

const OPERATION_LOG_LIMIT = 10;

export function SwarmFlowPanel() {
  const telemetryEvents = useChatStore((s) => s.telemetryEvents);
  const [tasks, setTasks] = useState(DEFAULT_TASKS);
  const [mode, setMode] = useState("parallel");
  const [sessionId, setSessionId] = useState("ui-swarm-session");
  const [maxConcurrency, setMaxConcurrency] = useState(3);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [response, setResponse] = useState(null);
  const [autonomyActivity, setAutonomyActivity] = useState({ items: [], counts_by_status: {}, counts_by_source: {} });
  const [activityLoading, setActivityLoading] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [pendingApprovals, setPendingApprovals] = useState([]);
  const [hitlLoading, setHitlLoading] = useState(false);
  const [operationLog, setOperationLog] = useState([]);
  const [actionBusy, setActionBusy] = useState(false);

  const pushOperationLog = useCallback((message, tone = "info") => {
    const entry = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      tone,
      message,
      ts: new Date().toISOString(),
    };
    setOperationLog((prev) => [entry, ...prev].slice(0, OPERATION_LOG_LIMIT));
  }, []);

  const loadPendingApprovals = useCallback(async () => {
    setHitlLoading(true);
    try {
      const data = await fetchJson("/api/hitl/pending");
      setPendingApprovals(data.pending || []);
    } catch (err) {
      setPendingApprovals([]);
      setError((prev) => prev || err.message);
      pushOperationLog(`HITL bekleyen kayıtları alınamadı: ${err.message}`, "error");
    } finally {
      setHitlLoading(false);
    }
  }, [pushOperationLog]);

  const loadAutonomyActivity = useCallback(async () => {
    setActivityLoading(true);
    try {
      const data = await fetchJson("/api/autonomy/activity?limit=8");
      setAutonomyActivity(data.activity || { items: [], counts_by_status: {}, counts_by_source: {} });
    } catch (err) {
      setAutonomyActivity({ items: [], counts_by_status: {}, counts_by_source: {} });
      setError((prev) => prev || err.message);
      pushOperationLog(`Autonomy aktivitesi alınamadı: ${err.message}`, "error");
    } finally {
      setActivityLoading(false);
    }
  }, [pushOperationLog]);

  useEffect(() => {
    loadAutonomyActivity();
    loadPendingApprovals();
  }, [loadAutonomyActivity, loadPendingApprovals]);

  const steps = useMemo(
    () => telemetryEvents
      .filter((evt) => evt.kind === "tool_call" || evt.kind === "status" || evt.kind === "thought")
      .slice(-12),
    [telemetryEvents],
  );

  const graphData = useMemo(() => {
    const responseResults = response?.results || [];
    const handoffEvents = buildHandoffEvents(responseResults);
    const roleHints = buildRoleHints(tasks, responseResults, handoffEvents);
    const telemetryWithActors = buildTelemetryWithActors(steps, roleHints);
    const lanes = buildLanes(roleHints, telemetryWithActors);

    const laneMap = new Map(lanes.map((lane) => [lane.id, lane]));
    const laneDecisionCounts = new Map();

    const autonomyNodes = buildAutonomyNodes(autonomyActivity.items || [], lanes);
    const supervisorNode = buildSupervisorNode({ laneMap, mode, sessionId, maxConcurrency });
    const taskNodes = buildTaskNodes(tasks, responseResults, laneMap);
    const agentNodes = buildAgentNodes(lanes);
    const handoffNodes = buildHandoffNodes(handoffEvents, laneMap, responseResults);
    const resultNodes = buildResultNodes(responseResults, laneMap);
    const telemetryNodes = buildTelemetryNodes(telemetryWithActors, laneMap, laneDecisionCounts);

    const nodes = [
      ...autonomyNodes,
      supervisorNode,
      ...taskNodes,
      ...agentNodes,
      ...handoffNodes,
      ...resultNodes,
      ...telemetryNodes,
    ].map((node) => ({ ...node, width: NODE_WIDTH, height: NODE_HEIGHT }));

    const edges = [
      ...buildAutonomyEdges(autonomyNodes, supervisorNode),
      {
        id: "edge-supervisor-role",
        from: supervisorNode.id,
        to: "agent-supervisor",
        label: "orchestrates",
        emphasis: "strong",
      },
      ...buildTaskEdges(taskNodes, supervisorNode, mode),
      ...buildResultEdges(resultNodes, responseResults, taskNodes, handoffNodes, supervisorNode, mode),
      ...buildHandoffEdges(handoffNodes, handoffEvents, taskNodes, responseResults),
      ...buildTelemetryEdges(telemetryNodes, resultNodes, responseResults),
    ];

    const { width, height } = computeGraphDimensions(lanes, laneDecisionCounts);
    const metrics = computeGraphMetrics(lanes, taskNodes, telemetryNodes, handoffNodes);

    const nodeMap = new Map(nodes.map((node) => [node.id, node]));
    return { nodes, edges, lanes, width, height, metrics, nodeMap };
  }, [autonomyActivity.items, maxConcurrency, mode, response, sessionId, steps, tasks]);

  const autonomySummary = useMemo(() => {
    const counts = autonomyActivity.counts_by_status || {};
    const sources = autonomyActivity.counts_by_source || {};
    return {
      total: autonomyActivity.total || autonomyActivity.items?.length || 0,
      success: counts.success || 0,
      failed: counts.failed || 0,
      sources: Object.keys(sources).length,
    };
  }, [autonomyActivity]);

  const graphEdges = useMemo(() => {
    const nodeMap = new Map(graphData.nodes.map((node) => [node.id, node]));
    return graphData.edges
      .map((edge) => {
        const from = nodeMap.get(edge.from);
        const to = nodeMap.get(edge.to);
        if (!from || !to) return null;
        const x1 = from.x + NODE_WIDTH / 2;
        const y1 = from.y + NODE_HEIGHT;
        const x2 = to.x + NODE_WIDTH / 2;
        const y2 = to.y;
        const midY = (y1 + y2) / 2;
        const curve = `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;
        return {
          ...edge,
          curve,
          labelX: (x1 + x2) / 2,
          labelY: midY - 10,
        };
      })
      .filter(Boolean);
  }, [graphData]);

  useEffect(() => {
    if (!selectedNodeId && graphData.nodes.length) {
      setSelectedNodeId(graphData.nodes[0].id);
    } else if (selectedNodeId && !graphData.nodeMap.has(selectedNodeId)) {
      setSelectedNodeId(graphData.nodes[0].id);
    }
  }, [graphData, selectedNodeId]);

  const selectedNode = useMemo(
    () => graphData.nodeMap.get(selectedNodeId) || graphData.nodes[0],
    [graphData, selectedNodeId],
  );

  const selectedTaskDraft = useMemo(
    () => buildTaskDraftFromNode(selectedNode),
    [selectedNode],
  );

  const updateTask = useCallback((index, field, value) => {
    setTasks((prev) => prev.map((task, idx) => (idx === index ? { ...task, [field]: value } : task)));
  }, []);

  const addTask = useCallback(() => {
    setTasks((prev) => [...prev, { goal: "", intent: "mixed", preferred_agent: "" }]);
  }, []);

  const removeTask = useCallback((index) => {
    setTasks((prev) => prev.filter((_, idx) => idx !== index));
  }, []);

  const executeSwarm = useCallback(async (overrideTasks = null, overrideMeta = {}) => {
    const sourceTasks = overrideTasks || tasks;
    const normalizedTasks = sourceTasks
      .map((task) => ({
        goal: String(task.goal || "").trim(),
        intent: String(task.intent || "").trim() || "mixed",
        preferred_agent: String(task.preferred_agent || "").trim() || undefined,
      }))
      .filter((task) => task.goal);

    if (!normalizedTasks.length) {
      setError("En az bir görev girmelisiniz.");
      return false;
    }

    setRunning(true);
    setError("");
    setResponse(null);
    try {
      const data = await fetchJson("/api/swarm/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: overrideMeta.mode || mode,
          session_id: overrideMeta.sessionId || sessionId.trim(),
          max_concurrency: Number(overrideMeta.maxConcurrency || maxConcurrency) || 1,
          tasks: normalizedTasks,
        }),
      });
      setResponse(data);
      setRunning(false);
      return true;
    } catch (err) {
      setError(err.message);
      pushOperationLog(`Swarm tetiklenemedi: ${err.message}`, "error");
      setRunning(false);
      return false;
    }
  }, [maxConcurrency, mode, pushOperationLog, sessionId, tasks]);

  const syncOperationSurface = useCallback(async () => {
    await Promise.all([loadAutonomyActivity(), loadPendingApprovals()]);
    pushOperationLog("Canlı operasyon yüzeyi yenilendi.", "success");
  }, [loadAutonomyActivity, loadPendingApprovals, pushOperationLog]);

  const addDraftTaskFromSelected = useCallback(() => {
    setTasks((prev) => [...prev, selectedTaskDraft]);
    pushOperationLog(`Seçili düğüm görev taslağına eklendi: ${selectedNode.title}`, "success");
  }, [pushOperationLog, selectedNode, selectedTaskDraft]);

  const replaceFirstTaskFromSelected = useCallback(() => {
    setTasks((prev) => prev.map((task, idx) => (idx === 0 ? selectedTaskDraft : task)));
    pushOperationLog(`İlk görev seçili düğümden yeniden yazıldı: ${selectedNode.title}`, "info");
  }, [pushOperationLog, selectedNode, selectedTaskDraft]);

  const runSelectedNode = useCallback(async () => {
    setActionBusy(true);
    const draft = buildTaskDraftFromNode(selectedNode);
    const ok = await executeSwarm([draft], {
      sessionId: `${sessionId.trim() || "ui-swarm-session"}-node`,
      maxConcurrency: 1,
    });
    if (ok) {
      pushOperationLog(`Seçili düğüm için hedefli swarm çalıştı: ${selectedNode.title}`, "success");
    }
    setActionBusy(false);
  }, [executeSwarm, pushOperationLog, selectedNode, sessionId]);

  const requestNodeReview = useCallback(async () => {
    setActionBusy(true);
    try {
      const data = await fetchJson("/api/hitl/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: inferHitlActionFromNode(selectedNode),
          description: `${selectedNode.title} düğümü için operatör incelemesi`,
          requested_by: "swarm_flow_panel",
          payload: {
            node_id: selectedNode.id,
            node_type: selectedNode.type,
            title: selectedNode.title,
            subtitle: selectedNode.subtitle,
            body: selectedNode.body,
            details: Object.fromEntries(selectedNode.details.map((item) => [item.key, item.value])),
          },
        }),
      });
      pushOperationLog(`HITL isteği oluşturuldu: ${data.request_id}`, "success");
      await loadPendingApprovals();
    } catch (err) {
      setError(err.message);
      pushOperationLog(`HITL isteği oluşturulamadı: ${err.message}`, "error");
    } finally {
      setActionBusy(false);
    }
  }, [loadPendingApprovals, pushOperationLog, selectedNode]);

  const respondToApproval = useCallback(async (requestId, approved) => {
    setActionBusy(true);
    try {
      const data = await fetchJson(`/api/hitl/respond/${encodeURIComponent(requestId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approved,
          decided_by: "swarm_flow_panel",
          rejection_reason: approved ? "" : "Swarm operasyon yüzeyi üzerinden reddedildi.",
        }),
      });
      pushOperationLog(`HITL kararı işlendi: ${data.request_id} → ${data.decision}`, approved ? "success" : "warning");
      await loadPendingApprovals();
    } catch (err) {
      setError(err.message);
      pushOperationLog(`HITL kararı gönderilemedi: ${err.message}`, "error");
    } finally {
      setActionBusy(false);
    }
  }, [loadPendingApprovals, pushOperationLog]);

  return (
    <section className="panel panel--stacked" role="region" aria-label="Swarm görev akışı paneli">
      <div className="panel-toolbar">
        <div>
          <h2>Swarm Görev Akışı</h2>
          <p className="panel__hint">Paralel veya sıralı SwarmTask listeleri göndererek orkestrasyonu tetikleyin.</p>
        </div>
        <div className="inline-controls">
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="parallel">run_parallel</option>
            <option value="pipeline">run_pipeline</option>
          </select>
          <button onClick={() => executeSwarm()} disabled={running}>{running ? "Çalışıyor…" : "Swarm Başlat"}</button>
        </div>
      </div>

      {error && <div className="banner banner--error" role="alert">{error}</div>}

      <div className="grid-2 grid-2--wide">
        <TaskEditor
          tasks={tasks}
          sessionId={sessionId}
          maxConcurrency={maxConcurrency}
          onSessionIdChange={setSessionId}
          onMaxConcurrencyChange={setMaxConcurrency}
          onTaskChange={updateTask}
          onAddTask={addTask}
          onRemoveTask={removeTask}
        />

        <div className="stack-list">
          <GraphView
            graphData={graphData}
            graphEdges={graphEdges}
            selectedNode={selectedNode}
            selectedNodeId={selectedNodeId}
            selectedTaskDraft={selectedTaskDraft}
            nodeWidth={NODE_WIDTH}
            nodeHeight={NODE_HEIGHT}
            activityLoading={activityLoading}
            hitlLoading={hitlLoading}
            actionBusy={actionBusy}
            running={running}
            onSelectNode={setSelectedNodeId}
            onLoadAutonomyActivity={loadAutonomyActivity}
            onSyncOperationSurface={syncOperationSurface}
            onAddDraftTaskFromSelected={addDraftTaskFromSelected}
            onReplaceFirstTaskFromSelected={replaceFirstTaskFromSelected}
            onRunSelectedNode={runSelectedNode}
            onRequestNodeReview={requestNodeReview}
            onLoadPendingApprovals={loadPendingApprovals}
          />

          <HitlQueue
            pendingApprovals={pendingApprovals}
            operationLog={operationLog}
            actionBusy={actionBusy}
            onRespondToApproval={respondToApproval}
            formatTime={formatTime}
          />

          <AutonomyTimeline
            autonomySummary={autonomySummary}
            autonomyActivity={autonomyActivity}
            steps={steps}
            formatTime={formatTime}
          />
        </div>
      </div>
    </section>
  );
}
