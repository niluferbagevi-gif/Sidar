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

export const prettifyRole = (value) => {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return "Unknown";
  return ROLE_LABELS[normalized] || normalized.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
};

export const clampText = (value, maxLength = 140) => {
  const normalized = String(value || "").replace(/\s+/g, " ").trim();
  if (!normalized) return "Açıklama bekleniyor.";
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 1)}…` : normalized;
};

const formatTime = (value) =>
  new Date(value).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export const inferTelemetryActor = (step, roleHints) => {
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
const OPERATION_LOG_LIMIT = 10;

export const prettifyReason = (value) =>
  String(value || "")
    .trim()
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());

export const toDetailEntries = (record) =>
  Object.entries(record || {})
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => ({
      key,
      value: Array.isArray(value) ? value.join(" · ") : String(value),
    }));

export const buildTaskDraftFromNode = (node) => {
  const intent = String(node.subtitle || "mixed")
    .split("·")[0]
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_") || "mixed";
  const preferredAgent = String(node.actor || node.laneId || "")
    .trim()
    .toLowerCase();
  return {
    goal: `${node.title}: ${node.body}`.trim(),
    intent,
    preferred_agent: preferredAgent,
  };
};

export const inferHitlActionFromNode = (node) => {
  const type = String(node?.type || "manual").toLowerCase();
  if (type.includes("handoff")) return "handoff_review";
  if (type.includes("autonomy")) return "autonomy_review";
  if (type.includes("result-warning")) return "result_review";
  if (type.includes("task")) return "task_review";
  return "graph_review";
};

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

    const lanes = Array.from(new Set(["supervisor", ...roleHints, ...telemetryWithActors.map((step) => step.actor)]))
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
      const lane = lanes[Math.min(index, Math.max(lanes.length - 1, 0))];
      return {
        id: `autonomy-${item.trigger_id || index}`,
        type: item.status === "failed" ? "autonomy-warning" : "autonomy",
        title: item.event_name || "trigger",
        subtitle: `${item.source || "manual"} · ${item.status || "unknown"}`,
        body: clampText(item.summary || JSON.stringify(item.payload || {}), 160),
        x: lane.x,
        y: rowY.autonomy + Math.floor(index / Math.max(lanes.length, 1)) * 122,
        details: toDetailEntries({
          trigger_id: item.trigger_id,
          source: item.source,
          status: item.status,
          event_name: item.event_name,
          summary: item.summary,
        }),
      };
    });

    const supervisorNode = {
      id: "supervisor",
      type: "root",
      title: "Supervisor",
      subtitle: mode === "parallel" ? "run_parallel" : "run_pipeline",
      body: clampText(sessionId.trim() || "ui-swarm-session", 80),
      x: laneMap.get("supervisor").x,
      y: rowY.supervisor,
      details: toDetailEntries({
        session_id: sessionId.trim() || "ui-swarm-session",
        mode,
        max_concurrency: Number(maxConcurrency) || 1,
      }),
    };

    const taskNodes = tasks.map((task, index) => {
      const laneId = getTaskTargetRole(task, responseResults, index);
      const lane = laneMap.get(laneId);
      return {
        id: `task-${index}`,
        type: "task",
        title: `Task ${index + 1}`,
        subtitle: task.intent?.trim() || "mixed",
        body: clampText(task.goal?.trim(), 160),
        laneId,
        x: lane.x,
        y: rowY.tasks + index * 18,
        details: toDetailEntries({
          goal: task.goal?.trim(),
          intent: task.intent?.trim() || "mixed",
          preferred_agent: task.preferred_agent?.trim() || laneId,
        }),
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
        actor: lane.id,
        details: toDetailEntries({
          role: lane.id,
          lane: lane.label,
        }),
      }));

    const handoffNodes = handoffEvents.map((handoff, index) => {
      const receiverRole = String(handoff.receiver || "supervisor").toLowerCase();
      const lane = laneMap.get(receiverRole);
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
        actor: receiverRole,
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
      const laneRole = String(item.agent_role || "").toLowerCase();
      const lane = laneMap.get(laneRole) || laneMap.get("supervisor");
      const graph = item.graph || {};
      return {
        id: `result-${item.task_id || index}`,
        type: item.status === "success" ? "result-success" : item.status === "failed" ? "result-warning" : "result-neutral",
        title: prettifyRole(item.agent_role || "agent"),
        subtitle: `${item.status || "unknown"} · ${item.elapsed_ms || 0} ms`,
        body: clampText(item.summary || "Özet üretilmedi", 160),
        x: lane.x,
        y: rowY.results + index * 18,
        actor: laneRole,
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
      const lane = laneMap.get(step.actor);
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
      const role = String(result?.agent_role || taskNodes[index]?.laneId || taskNodes[taskNodes.length - 1]?.laneId).toLowerCase();
      const taskNode = taskNodes.find((task) => task.id === `task-${index}`) || taskNodes[index] || taskNodes[taskNodes.length - 1];
      const resultHandoffs = handoffNodes.filter((node) => node.id.startsWith(`handoff-${result?.task_id || index}`));
      const latestResultHandoff = resultHandoffs[resultHandoffs.length - 1];
      const resultSourceId = [latestResultHandoff?.id, taskNode?.id, supervisorNode.id].find(Boolean);
      edges.push({
        id: `edge-task-result-${resultNode.id}`,
        from: resultSourceId,
        to: resultNode.id,
        label: result?.status || "result",
        emphasis: result?.status === "success" ? "success" : "warning",
      });
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
      const taskNode = taskNodes.find((task) => task.id === `task-${handoff.resultIndex}`) || taskNodes[handoff.resultIndex] || taskNodes[taskNodes.length - 1];
      edges.push({
        id: `edge-task-handoff-${node.id}`,
        from: taskNode.id,
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
      const data = await fetchJson(`/api/hitl/respond/${requestId}`, {
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
          <button onClick={() => executeSwarm()} disabled={running}>{running ? "Çalışıyor…" : "Swarm Başlat"}</button>
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
              <span className="pill">Selected {selectedNode.title}</span>
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
                    {selectedNodeId === node.id && (
                      <div className="swarm-graph__node-actions">
                        <button type="button" className="button-secondary" onClick={(event) => {
                          event.stopPropagation();
                          void runSelectedNode();
                        }} disabled={actionBusy || running}>
                          Run node
                        </button>
                        <button type="button" className="button-secondary" onClick={(event) => {
                          event.stopPropagation();
                          addDraftTaskFromSelected();
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
                      <button type="button" className="button-secondary" onClick={syncOperationSurface} disabled={activityLoading || hitlLoading || actionBusy}>
                        {activityLoading || hitlLoading ? "Yüzey yenileniyor…" : "Yüzeyi Yenile"}
                      </button>
                    </div>

                    <div className="swarm-graph__operation-grid">
                      <div className="swarm-graph__operation-card">
                        <span className="pill">Selected node draft</span>
                        <p><strong>{selectedTaskDraft.intent}</strong> → {selectedTaskDraft.goal}</p>
                        <div className="swarm-graph__action-row">
                          <button type="button" onClick={addDraftTaskFromSelected} disabled={actionBusy}>Takip Görevi Ekle</button>
                          <button type="button" className="button-secondary" onClick={replaceFirstTaskFromSelected} disabled={actionBusy}>İlk Goal’ı Değiştir</button>
                          <button type="button" className="button-secondary" onClick={() => void runSelectedNode()} disabled={actionBusy || running}>Bu Node’u Çalıştır</button>
                        </div>
                      </div>

                      <div className="swarm-graph__operation-card">
                        <span className="pill">Human-in-the-loop</span>
                        <p>Seçili düğüm için operatör inceleme talebi üreterek otonom akışa kontrollü müdahale edin.</p>
                        <div className="swarm-graph__action-row">
                          <button type="button" onClick={() => void requestNodeReview()} disabled={actionBusy}>İnceleme İsteği Aç</button>
                          <button type="button" className="button-secondary" onClick={loadPendingApprovals} disabled={hitlLoading}>Bekleyenleri Yenile</button>
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
                        <button type="button" onClick={() => void respondToApproval(item.request_id, true)} disabled={actionBusy}>Approve</button>
                        <button type="button" className="button-secondary" onClick={() => void respondToApproval(item.request_id, false)} disabled={Boolean(actionBusy)}>Reject</button>
                      </div>
                    </article>
                  ))}
                </div>
              </div>

              <div className="swarm-graph__operation-card">
                <strong>Operasyon Günlüğü</strong>
                <ol className="timeline swarm-graph__operation-log">
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
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </section>
  );
}