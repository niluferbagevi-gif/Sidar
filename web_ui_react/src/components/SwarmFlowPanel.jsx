import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useChatStore } from "../hooks/useChatStore.js";
import { fetchJson } from "../lib/api.js";

const DEFAULT_TASKS = [
  { goal: "Kod tabanında güvenlik riski taşıyan noktaları tara", intent: "security_audit", preferred_agent: "" },
  { goal: "Bulunan riskler için kısa bir aksiyon planı üret", intent: "summarization", preferred_agent: "" },
];

const ROLE_LABELS = {
  supervisor: "Supervisor",
  coder: "Coder",
  reviewer: "Reviewer",
  researcher: "Researcher",
  planner: "Planner",
  ops: "Ops",
  security: "Security",
  system: "System",
};

const prettifyRole = (value) => {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return "Unknown";
  return ROLE_LABELS[normalized] || normalized.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
};

const clampText = (value, maxLength = 140) => {
  const normalized = String(value || "").replace(/\s+/g, " ").trim();
  if (!normalized) return "Açıklama bekleniyor.";
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 1)}…` : normalized;
};

const formatTime = (value) =>
  new Date(value).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

const inferTelemetryActor = (step, roleHints) => {
  const content = String(step?.content || "").trim();
  if (!content) return "system";

  const prefixed = content.match(/^([a-z0-9_-]{2,32})\s*:/i);
  if (prefixed?.[1]) return prefixed[1].toLowerCase();

  const lowered = content.toLowerCase();
  const knownRoles = ["supervisor", ...roleHints];
  for (const role of knownRoles) {
    if (role && lowered.includes(role)) return role;
  }
  return step?.kind === "tool_call" ? "supervisor" : "system";
};

const getTaskTargetRole = (task, responseResults, index) =>
  String(
    task.preferred_agent?.trim()
    || responseResults[index]?.agent_role
    || responseResults[responseResults.length - 1]?.agent_role
    || "supervisor",
  ).toLowerCase();

const NODE_WIDTH = 220;
const NODE_HEIGHT = 104;

const prettifyReason = (value) =>
  String(value || "")
    .trim()
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());

const toDetailEntries = (record) =>
  Object.entries(record || {})
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => ({
      key,
      value: Array.isArray(value) ? value.join(" · ") : String(value),
    }));

export function SwarmFlowPanel() {
  const { telemetryEvents } = useChatStore();
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

  const loadAutonomyActivity = useCallback(async () => {
    setActivityLoading(true);
    try {
      const data = await fetchJson("/api/autonomy/activity?limit=8");
      setAutonomyActivity(data.activity || { items: [], counts_by_status: {}, counts_by_source: {} });
    } catch (err) {
      setAutonomyActivity({ items: [], counts_by_status: {}, counts_by_source: {} });
      setError((prev) => prev || err.message);
    } finally {
      setActivityLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAutonomyActivity();
  }, [loadAutonomyActivity]);

  const steps = useMemo(
    () => telemetryEvents
      .filter((evt) => evt.kind === "tool_call" || evt.kind === "status" || evt.kind === "thought")
      .slice(-12),
    [telemetryEvents],
  );

  const graphData = useMemo(() => {
    const responseResults = response?.results || [];
    const handoffEvents = responseResults.flatMap((item, resultIndex) => {
      const chain = Array.isArray(item.handoffs) ? item.handoffs : [];
      if (chain.length > 0) {
        return chain.map((handoff, handoffIndex) => ({
          ...handoff,
          resultIndex,
          handoffIndex,
        }));
      }
      const graph = item.graph || {};
      if (!graph.p2p_sender || !graph.p2p_receiver) return [];
      return [{
        task_id: item.task_id,
        sender: graph.p2p_sender,
        receiver: graph.p2p_receiver,
        reason: graph.p2p_reason,
        intent: graph.intent,
        handoff_depth: graph.p2p_handoff_depth,
        swarm_hop: graph.swarm_hop,
        resultIndex,
        handoffIndex: 0,
      }];
    });
    const roleHints = Array.from(
      new Set(
        [
          ...tasks.map((task, index) => getTaskTargetRole(task, responseResults, index)),
          ...responseResults.map((item) => String(item.agent_role || "").toLowerCase()),
          ...handoffEvents.flatMap((item) => [String(item.sender || "").toLowerCase(), String(item.receiver || "").toLowerCase()]),
        ].filter(Boolean),
      ),
    );
    const telemetryWithActors = steps.map((step) => ({
      ...step,
      actor: inferTelemetryActor(step, roleHints),
    }));

    const lanes = ["supervisor", ...Array.from(new Set([...roleHints, ...telemetryWithActors.map((step) => step.actor)]))]
      .filter(Boolean)
      .map((role, index) => ({
        id: role,
        label: prettifyRole(role),
        x: 40 + index * 260,
      }));

    const laneMap = new Map(lanes.map((lane) => [lane.id, lane]));
    const laneDecisionCounts = new Map();
    const rowY = {
      autonomy: 46,
      supervisor: 182,
      tasks: 336,
      agents: 500,
      handoffs: 664,
      results: 828,
      telemetry: 992,
    };

    const nodes = [];
    const pushNode = (node) => nodes.push({ ...node, width: NODE_WIDTH, height: NODE_HEIGHT });

    const autonomyNodes = (autonomyActivity.items || []).map((item, index) => {
      const lane = lanes[Math.min(index, Math.max(lanes.length - 1, 0))] || { x: 40 };
      return {
        id: `autonomy-${item.trigger_id || index}`,
        type: item.status === "failed" ? "autonomy-warning" : "autonomy",
        title: item.event_name || "trigger",
        subtitle: `${item.source || "manual"} · ${item.status || "unknown"}`,
        body: clampText(item.summary || JSON.stringify(item.payload || {}), 160),
        x: lane.x,
        y: rowY.autonomy + Math.floor(index / Math.max(lanes.length, 1)) * 122,
      };
    });

    const supervisorNode = {
      id: "supervisor",
      type: "root",
      title: "Supervisor",
      subtitle: mode === "parallel" ? "run_parallel" : "run_pipeline",
      body: clampText(sessionId.trim() || "ui-swarm-session", 80),
      x: laneMap.get("supervisor")?.x || 40,
      y: rowY.supervisor,
    };

    const taskNodes = tasks.map((task, index) => {
      const laneId = getTaskTargetRole(task, responseResults, index);
      const lane = laneMap.get(laneId) || laneMap.get("supervisor") || lanes[0] || { x: 40 };
      return {
        id: `task-${index}`,
        type: "task",
        title: `Task ${index + 1}`,
        subtitle: task.intent?.trim() || "mixed",
        body: clampText(task.goal?.trim(), 160),
        laneId,
        x: lane.x,
        y: rowY.tasks + index * 18,
      };
    });

    const agentNodes = lanes
      .filter((lane) => lane.id !== "system")
      .map((lane) => ({
        id: `agent-${lane.id}`,
        type: lane.id === "supervisor" ? "agent-supervisor" : "agent",
        title: lane.label,
        subtitle: lane.id === "supervisor" ? "orchestrator" : "active role",
        body: lane.id === "supervisor"
          ? "Görevleri planlar, zinciri başlatır ve sonuçları toplar."
          : "Göreve atanmış veya telemetride gözlenen ajan rolü.",
        x: lane.x,
        y: rowY.agents,
      }));

    const handoffNodes = handoffEvents.map((handoff, index) => {
      const receiverRole = String(handoff.receiver || "supervisor").toLowerCase();
      const lane = laneMap.get(receiverRole) || laneMap.get("supervisor") || lanes[0] || { x: 40 };
      const sender = prettifyRole(handoff.sender || "unknown");
      const receiver = prettifyRole(handoff.receiver || "unknown");
      const reason = prettifyReason(handoff.reason || "delegation");
      return {
        id: `handoff-${handoff.task_id || handoff.resultIndex}-${index}`,
        type: "handoff",
        title: `${sender} → ${receiver}`,
        subtitle: `depth ${handoff.handoff_depth || 0} · hop ${handoff.swarm_hop || 0}`,
        body: clampText(`${reason} · ${handoff.intent || "mixed"} intent`, 170),
        x: lane.x,
        y: rowY.handoffs + index * 18,
        details: toDetailEntries({
          reason,
          intent: handoff.intent || "mixed",
          handoff_depth: handoff.handoff_depth || 0,
          swarm_hop: handoff.swarm_hop || 0,
          task_id: handoff.task_id || responseResults[handoff.resultIndex]?.task_id || "",
        }),
      };
    });

    const resultNodes = responseResults.map((item, index) => {
      const lane = laneMap.get(String(item.agent_role || "").toLowerCase()) || laneMap.get("supervisor") || lanes[0] || { x: 40 };
      const graph = item.graph || {};
      return {
        id: `result-${item.task_id || index}`,
        type: item.status === "success" ? "result-success" : item.status === "failed" ? "result-warning" : "result-neutral",
        title: prettifyRole(item.agent_role || "agent"),
        subtitle: `${item.status || "unknown"} · ${item.elapsed_ms || 0} ms`,
        body: clampText(item.summary || "Özet üretilmedi", 160),
        x: lane.x,
        y: rowY.results + index * 18,
        details: toDetailEntries({
          task_id: item.task_id,
          status: item.status,
          elapsed_ms: item.elapsed_ms,
          sender: graph.sender,
          receiver: graph.receiver,
          p2p_reason: graph.p2p_reason,
          p2p_handoff_depth: graph.p2p_handoff_depth,
        }),
      };
    });

    const telemetryNodes = telemetryWithActors.map((step) => {
      const lane = laneMap.get(step.actor) || laneMap.get("system") || laneMap.get("supervisor") || lanes[0] || { x: 40 };
      const laneCount = laneDecisionCounts.get(step.actor) || 0;
      laneDecisionCounts.set(step.actor, laneCount + 1);
      return {
        id: `telemetry-${step.id}`,
        type: step.kind,
        title: step.kind === "tool_call" ? "Tool Call" : step.kind === "thought" ? "Decision" : "Status",
        subtitle: `${prettifyRole(step.actor)} · ${formatTime(step.ts)}`,
        body: clampText(step.content, 170),
        actor: step.actor,
        x: lane.x,
        y: rowY.telemetry + laneCount * 128,
        details: toDetailEntries({
          actor: prettifyRole(step.actor),
          kind: step.kind,
          time: formatTime(step.ts),
          content: step.content,
        }),
      };
    });

    autonomyNodes.forEach(pushNode);
    pushNode(supervisorNode);
    taskNodes.forEach(pushNode);
    agentNodes.forEach(pushNode);
    handoffNodes.forEach(pushNode);
    resultNodes.forEach(pushNode);
    telemetryNodes.forEach(pushNode);

    const edges = [];
    autonomyNodes.forEach((node, index) => {
      edges.push({
        id: `edge-autonomy-${node.id}`,
        from: index === 0 ? supervisorNode.id : autonomyNodes[index - 1].id,
        to: node.id,
        label: index === 0 ? "wake signal" : "trigger chain",
        emphasis: "light",
      });
    });
    if (autonomyNodes.length) {
      edges.push({
        id: "edge-autonomy-supervisor",
        from: autonomyNodes[autonomyNodes.length - 1].id,
        to: supervisorNode.id,
        label: "activate swarm",
      });
    }

    edges.push({
      id: "edge-supervisor-role",
      from: supervisorNode.id,
      to: "agent-supervisor",
      label: "orchestrates",
      emphasis: "strong",
    });

    taskNodes.forEach((taskNode, index) => {
      const targetRole = taskNode.laneId;
      edges.push({
        id: `edge-supervisor-task-${taskNode.id}`,
        from: supervisorNode.id,
        to: taskNode.id,
        label: mode === "pipeline" ? `stage ${index + 1}` : "dispatch",
      });
      edges.push({
        id: `edge-task-agent-${taskNode.id}`,
        from: taskNode.id,
        to: `agent-${targetRole}`,
        label: taskNode.subtitle,
      });
      if (mode === "pipeline" && index > 0) {
        edges.push({
          id: `edge-pipeline-task-${index}`,
          from: taskNodes[index - 1].id,
          to: taskNode.id,
          label: "next stage",
          emphasis: "light",
        });
      }
    });

    resultNodes.forEach((resultNode, index) => {
      const result = responseResults[index];
      const role = String(result?.agent_role || taskNodes[index]?.laneId || "supervisor").toLowerCase();
      const taskNode = taskNodes.find((task) => task.id === `task-${index}`) || taskNodes[index] || taskNodes[taskNodes.length - 1];
      const resultHandoffs = handoffNodes.filter((node) => node.id.startsWith(`handoff-${result?.task_id || index}`));
      if (taskNode) {
        edges.push({
          id: `edge-task-result-${resultNode.id}`,
          from: resultHandoffs[resultHandoffs.length - 1]?.id || taskNode.id,
          to: resultNode.id,
          label: result?.status || "result",
          emphasis: result?.status === "success" ? "success" : "warning",
        });
      }
      edges.push({
        id: `edge-agent-result-${resultNode.id}`,
        from: `agent-${role}`,
        to: resultNode.id,
        label: "output",
      });
      if (mode === "pipeline" && index < taskNodes.length - 1) {
        edges.push({
          id: `edge-result-next-task-${index}`,
          from: resultNode.id,
          to: taskNodes[index + 1].id,
          label: "context handoff",
          emphasis: "light",
        });
      }
    });

    handoffNodes.forEach((node, index) => {
      const handoff = handoffEvents[index];
      const senderRole = String(handoff.sender || "supervisor").toLowerCase();
      const receiverRole = String(handoff.receiver || "supervisor").toLowerCase();
      const result = responseResults[handoff.resultIndex];
      const taskNode = taskNodes.find((task) => task.id === `task-${handoff.resultIndex}`) || taskNodes[handoff.resultIndex];
      edges.push({
        id: `edge-task-handoff-${node.id}`,
        from: taskNode?.id || "supervisor",
        to: node.id,
        label: "p2p decision",
        emphasis: "light",
      });
      edges.push({
        id: `edge-sender-handoff-${node.id}`,
        from: `agent-${senderRole}`,
        to: node.id,
        label: prettifyReason(handoff.reason || "delegation"),
        emphasis: "strong",
      });
      edges.push({
        id: `edge-handoff-receiver-${node.id}`,
        from: node.id,
        to: `agent-${receiverRole}`,
        label: `depth ${handoff.handoff_depth || 0}`,
        emphasis: "success",
      });
      if (result?.task_id) {
        edges.push({
          id: `edge-handoff-result-${node.id}`,
          from: node.id,
          to: `result-${result.task_id}`,
          label: "handoff outcome",
          emphasis: "light",
        });
      }
    });

    const latestResultByRole = new Map();
    resultNodes.forEach((node, index) => {
      latestResultByRole.set(String(responseResults[index]?.agent_role || "").toLowerCase(), node.id);
    });

    telemetryNodes.forEach((telemetryNode, index) => {
      const previousTelemetry = telemetryNodes
        .slice(0, index)
        .reverse()
        .find((item) => item.actor === telemetryNode.actor);
      edges.push({
        id: `edge-telemetry-${telemetryNode.id}`,
        from: previousTelemetry?.id || latestResultByRole.get(telemetryNode.actor) || `agent-${telemetryNode.actor}`,
        to: telemetryNode.id,
        label: telemetryNode.title.toLowerCase(),
        emphasis: telemetryNode.type === "thought" ? "strong" : "light",
      });
    });

    const width = Math.max(1180, lanes.length * 260 + 140);
    const height = Math.max(
      980,
      rowY.telemetry + Math.max(...Array.from(laneDecisionCounts.values()), 1) * 132 + 180,
    );

    const metrics = {
      roles: lanes.length,
      tasks: taskNodes.length,
      decisions: telemetryNodes.length,
      handoffs: handoffNodes.length,
    };

    const nodeMap = new Map(nodes.map((node) => [node.id, node]));
    return { nodes, edges, lanes, width, height, metrics, nodeMap };
  }, [autonomyActivity.items, mode, response, sessionId, steps, tasks]);

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
      setSelectedNodeId(graphData.nodes[0]?.id || "");
    }
  }, [graphData, selectedNodeId]);

  const selectedNode = useMemo(
    () => graphData.nodeMap.get(selectedNodeId) || graphData.nodes[0] || null,
    [graphData, selectedNodeId],
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

  const executeSwarm = useCallback(async () => {
    const normalizedTasks = tasks
      .map((task) => ({
        goal: task.goal.trim(),
        intent: task.intent.trim() || "mixed",
        preferred_agent: task.preferred_agent.trim() || undefined,
      }))
      .filter((task) => task.goal);

    if (!normalizedTasks.length) {
      setError("En az bir görev girmelisiniz.");
      return;
    }

    setRunning(true);
    setError("");
    setResponse(null);
    try {
      const data = await fetchJson("/api/swarm/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode,
          session_id: sessionId.trim(),
          max_concurrency: Number(maxConcurrency) || 1,
          tasks: normalizedTasks,
        }),
      });
      setResponse(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }, [maxConcurrency, mode, sessionId, tasks]);

  return (
    <section className="panel panel--stacked">
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
          <button onClick={executeSwarm} disabled={running}>{running ? "Çalışıyor…" : "Swarm Başlat"}</button>
        </div>
      </div>

      {error && <div className="banner banner--error">{error}</div>}

      <div className="grid-2 grid-2--wide">
        <div className="card form-card">
          <h3>Görev Tanımı</h3>
          <label>
            Session ID
            <input value={sessionId} onChange={(e) => setSessionId(e.target.value)} placeholder="ui-swarm-session" />
          </label>
          <label>
            Maksimum eşzamanlılık
            <input type="number" min="1" max="8" value={maxConcurrency} onChange={(e) => setMaxConcurrency(e.target.value)} />
          </label>
          <div className="stack-list">
            {tasks.map((task, index) => (
              <div key={`${index}-${task.goal}`} className="task-editor">
                <label>
                  Goal
                  <textarea rows={3} value={task.goal} onChange={(e) => updateTask(index, "goal", e.target.value)} placeholder="Görevin açıklaması" />
                </label>
                <div className="inline-controls inline-controls--stretch">
                  <label>
                    Intent
                    <input value={task.intent} onChange={(e) => updateTask(index, "intent", e.target.value)} placeholder="security_audit" />
                  </label>
                  <label>
                    Preferred agent
                    <input value={task.preferred_agent} onChange={(e) => updateTask(index, "preferred_agent", e.target.value)} placeholder="opsiyonel role_name" />
                  </label>
                </div>
                <button type="button" className="button-secondary" onClick={() => removeTask(index)} disabled={tasks.length === 1}>Görevi Sil</button>
              </div>
            ))}
          </div>
          <button type="button" onClick={addTask}>Yeni Görev Ekle</button>
        </div>

        <div className="stack-list">
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
              <span className="pill">Selected {selectedNode ? selectedNode.title : "n/a"}</span>
              <button type="button" className="button-secondary" onClick={loadAutonomyActivity} disabled={activityLoading}>
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
                    style={{ left: `${lane.x}px`, width: `${NODE_WIDTH}px`, height: `${graphData.height - 56}px` }}
                  >
                    <span className="swarm-graph__lane-badge">{lane.label}</span>
                  </div>
                ))}

                {graphData.nodes.map((node) => (
                  <article
                    key={node.id}
                    className={`swarm-graph__node swarm-graph__node--${node.type} ${selectedNodeId === node.id ? "swarm-graph__node--selected" : ""}`}
                    style={{ left: `${node.x}px`, top: `${node.y}px` }}
                    onClick={() => setSelectedNodeId(node.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedNodeId(node.id);
                      }
                    }}
                  >
                    <div className="swarm-graph__node-header">
                      <strong>{node.title}</strong>
                      <span>{node.subtitle}</span>
                    </div>
                    <p>{node.body}</p>
                  </article>
                ))}
              </div>
            </div>

            <div className="swarm-graph__inspector">
              <div>
                <h4>Node Inspector</h4>
                <p className="panel__hint">Seçili düğümün handoff_depth, p2p_reason ve karar zinciri detayları.</p>
              </div>
              {selectedNode ? (
                <div className="swarm-graph__inspector-card">
                  <div className="swarm-graph__inspector-header">
                    <strong>{selectedNode.title}</strong>
                    <span>{selectedNode.subtitle}</span>
                  </div>
                  <p>{selectedNode.body}</p>
                  <dl className="swarm-graph__detail-list">
                    {(selectedNode.details || toDetailEntries({
                      node_id: selectedNode.id,
                      type: selectedNode.type,
                      lane_x: selectedNode.x,
                      y: selectedNode.y,
                    })).map((item) => (
                      <React.Fragment key={`${selectedNode.id}-${item.key}`}>
                        <dt>{item.key}</dt>
                        <dd>{item.value}</dd>
                      </React.Fragment>
                    ))}
                  </dl>
                </div>
              ) : (
                <div className="empty-state">İncelemek için grafikten bir düğüm seçin.</div>
              )}
            </div>
          </div>

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
                <li key={item.trigger_id || idx} className="timeline__item">
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
                  </div>
                </li>
              ))}
            </ol>
          </div>

          <div className="card">
            <h3>Son Swarm Sonucu</h3>
            {response ? (
              <pre className="code-block">{JSON.stringify(response, null, 2)}</pre>
            ) : (
              <div className="empty-state">REST yanıtı burada gösterilir.</div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
