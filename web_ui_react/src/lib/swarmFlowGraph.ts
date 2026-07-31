/**
 * Pure graph-building logic for SwarmFlowPanel: turns swarm task/response/
 * telemetry/autonomy state into the node/edge graph the panel renders.
 * Extracted out of SwarmFlowPanel.jsx so it can be unit tested and read in
 * isolation from the React component that consumes it.
 */

type DetailValue = string | number | boolean | null | undefined | DetailValue[];
type DetailRecord = Record<string, DetailValue>;

export interface SwarmTask {
  goal?: string;
  intent?: string;
  preferred_agent?: string;
}

export interface SwarmGraph {
  sender?: string;
  receiver?: string;
  intent?: string;
  p2p_sender?: string;
  p2p_receiver?: string;
  p2p_reason?: string;
  p2p_handoff_depth?: number;
  swarm_hop?: number;
}

export interface HandoffEvent {
  task_id?: string;
  sender?: string;
  receiver?: string;
  reason?: string;
  intent?: string;
  handoff_depth?: number;
  swarm_hop?: number;
  resultIndex: number;
  handoffIndex: number;
}

export interface SwarmResult {
  task_id?: string;
  agent_role?: string;
  status?: string;
  elapsed_ms?: number;
  summary?: string;
  handoffs?: Omit<HandoffEvent, "resultIndex" | "handoffIndex">[];
  graph?: SwarmGraph;
}

export interface TelemetryStep {
  id: string | number;
  kind?: string;
  content?: string;
  ts: string | number | Date;
}

export interface TelemetryWithActor extends TelemetryStep {
  actor: string;
}

export interface Lane {
  id: string;
  label: string;
  x: number;
}

export interface DetailEntry {
  key: string;
  value: string;
}

export interface GraphNode {
  id: string;
  type: string;
  title: string;
  subtitle: string;
  body: string;
  x: number;
  y: number;
  actor?: string;
  laneId?: string;
  details: DetailEntry[];
}

export interface GraphEdge {
  id: string;
  from: string;
  to: string;
  label: string;
  emphasis?: string;
}

export interface AutonomyItem {
  trigger_id?: string;
  status?: string;
  event_name?: string;
  source?: string;
  summary?: string;
  payload?: DetailRecord;
}

function requireLane(laneMap: Map<string, Lane>, role: string): Lane {
  const lane = laneMap.get(role) || laneMap.get("supervisor");
  if (!lane) {
    throw new Error(`Graph lane is missing for role: ${role}`);
  }
  return lane;
}

const ROLE_LABELS: Record<string, string> = {
  supervisor: "Supervisor",
  coder: "Coder",
  reviewer: "Reviewer",
  researcher: "Researcher",
  planner: "Planner",
  ops: "Ops",
  security: "Security",
  system: "System",
};

export const prettifyRole = (value: unknown): string => {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return "Unknown";
  return ROLE_LABELS[normalized] || normalized.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
};

export const clampText = (value: unknown, maxLength = 140): string => {
  const normalized = String(value || "").replace(/\s+/g, " ").trim();
  if (!normalized) return "Açıklama bekleniyor.";
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 1)}…` : normalized;
};

export const formatTime = (value: string | number | Date): string =>
  new Date(value).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export const inferTelemetryActor = (step: Partial<TelemetryStep>, roleHints: string[]): string => {
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

export const getTaskTargetRole = (task: SwarmTask, responseResults: SwarmResult[], index: number): string =>
  String(
    task.preferred_agent?.trim()
    || responseResults[index]?.agent_role
    || responseResults[responseResults.length - 1]?.agent_role
    || "supervisor",
  ).toLowerCase();

export const NODE_WIDTH = 220;
export const NODE_HEIGHT = 104;

export const prettifyReason = (value: unknown): string =>
  String(value || "")
    .trim()
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());

export const toDetailEntries = (record: DetailRecord | null | undefined): DetailEntry[] =>
  Object.entries(record || {})
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => ({
      key,
      value: Array.isArray(value) ? value.join(" · ") : String(value),
    }));

export const buildTaskDraftFromNode = (node: GraphNode): Required<SwarmTask> => {
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

export const inferHitlActionFromNode = (node: Partial<GraphNode>): string => {
  const type = String(node?.type || "manual").toLowerCase();
  if (type.includes("handoff")) return "handoff_review";
  if (type.includes("autonomy")) return "autonomy_review";
  if (type.includes("result-warning")) return "result_review";
  if (type.includes("task")) return "task_review";
  return "graph_review";
};

export const ROW_Y = {
  autonomy: 46,
  supervisor: 182,
  tasks: 336,
  agents: 500,
  handoffs: 664,
  results: 828,
  telemetry: 992,
};

export function buildHandoffEvents(responseResults: SwarmResult[]): HandoffEvent[] {
  return responseResults.flatMap((item, resultIndex) => {
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
}

export function buildRoleHints(tasks: SwarmTask[], responseResults: SwarmResult[], handoffEvents: HandoffEvent[]): string[] {
  return Array.from(
    new Set(
      [
        ...tasks.map((task, index) => getTaskTargetRole(task, responseResults, index)),
        ...responseResults.map((item) => String(item.agent_role || "").toLowerCase()),
        ...handoffEvents.flatMap((item) => [String(item.sender || "").toLowerCase(), String(item.receiver || "").toLowerCase()]),
      ].filter(Boolean),
    ),
  );
}

export function buildTelemetryWithActors(steps: TelemetryStep[], roleHints: string[]): TelemetryWithActor[] {
  return steps.map((step) => ({
    ...step,
    actor: inferTelemetryActor(step, roleHints),
  }));
}

export function buildLanes(roleHints: string[], telemetryWithActors: TelemetryWithActor[]): Lane[] {
  return Array.from(new Set(["supervisor", ...roleHints, ...telemetryWithActors.map((step) => step.actor)]))
    .filter(Boolean)
    .map((role, index) => ({
      id: role,
      label: prettifyRole(role),
      x: 40 + index * 260,
    }));
}

export function buildAutonomyNodes(autonomyItems: AutonomyItem[], lanes: Lane[]): GraphNode[] {
  return autonomyItems.map((item, index) => {
    const lane = lanes[Math.min(index, Math.max(lanes.length - 1, 0))];
    return {
      id: `autonomy-${item.trigger_id || index}`,
      type: item.status === "failed" ? "autonomy-warning" : "autonomy",
      title: item.event_name || "trigger",
      subtitle: `${item.source || "manual"} · ${item.status || "unknown"}`,
      body: clampText(item.summary || JSON.stringify(item.payload || {}), 160),
      x: lane.x,
      y: ROW_Y.autonomy + Math.floor(index / Math.max(lanes.length, 1)) * 122,
      details: toDetailEntries({
        trigger_id: item.trigger_id,
        source: item.source,
        status: item.status,
        event_name: item.event_name,
        summary: item.summary,
      }),
    };
  });
}

export function buildSupervisorNode({ laneMap, mode, sessionId, maxConcurrency }: { laneMap: Map<string, Lane>; mode: string; sessionId: string; maxConcurrency: string | number }): GraphNode {
  return {
    id: "supervisor",
    type: "root",
    title: "Supervisor",
    subtitle: mode === "parallel" ? "run_parallel" : "run_pipeline",
    body: clampText(sessionId.trim() || "ui-swarm-session", 80),
    x: requireLane(laneMap, "supervisor").x,
    y: ROW_Y.supervisor,
    details: toDetailEntries({
      session_id: sessionId.trim() || "ui-swarm-session",
      mode,
      max_concurrency: Number(maxConcurrency) || 1,
    }),
  };
}

export function buildTaskNodes(tasks: SwarmTask[], responseResults: SwarmResult[], laneMap: Map<string, Lane>): GraphNode[] {
  return tasks.map((task, index) => {
    const laneId = getTaskTargetRole(task, responseResults, index);
    const lane = requireLane(laneMap, laneId);
    return {
      id: `task-${index}`,
      type: "task",
      title: `Task ${index + 1}`,
      subtitle: task.intent?.trim() || "mixed",
      body: clampText(task.goal?.trim(), 160),
      laneId,
      x: lane.x,
      y: ROW_Y.tasks + index * 18,
      details: toDetailEntries({
        goal: task.goal?.trim(),
        intent: task.intent?.trim() || "mixed",
        preferred_agent: task.preferred_agent?.trim() || laneId,
      }),
    };
  });
}

export function buildAgentNodes(lanes: Lane[]): GraphNode[] {
  return lanes
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
      y: ROW_Y.agents,
      actor: lane.id,
      details: toDetailEntries({
        role: lane.id,
        lane: lane.label,
      }),
    }));
}

export function buildHandoffNodes(handoffEvents: HandoffEvent[], laneMap: Map<string, Lane>, responseResults: SwarmResult[]): GraphNode[] {
  return handoffEvents.map((handoff, index) => {
    const receiverRole = String(handoff.receiver || "supervisor").toLowerCase();
    const lane = requireLane(laneMap, receiverRole);
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
      y: ROW_Y.handoffs + index * 18,
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
}

export function buildResultNodes(responseResults: SwarmResult[], laneMap: Map<string, Lane>): GraphNode[] {
  return responseResults.map((item, index) => {
    const laneRole = String(item.agent_role || "").toLowerCase();
    const lane = requireLane(laneMap, laneRole);
    const graph = item.graph || {};
    return {
      id: `result-${item.task_id || index}`,
      type: item.status === "success" ? "result-success" : item.status === "failed" ? "result-warning" : "result-neutral",
      title: prettifyRole(item.agent_role || "agent"),
      subtitle: `${item.status || "unknown"} · ${item.elapsed_ms || 0} ms`,
      body: clampText(item.summary || "Özet üretilmedi", 160),
      x: lane.x,
      y: ROW_Y.results + index * 18,
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
}

export function buildTelemetryNodes(telemetryWithActors: TelemetryWithActor[], laneMap: Map<string, Lane>, laneDecisionCounts: Map<string, number>): GraphNode[] {
  return telemetryWithActors.map((step) => {
    const lane = requireLane(laneMap, step.actor);
    const laneCount = laneDecisionCounts.get(step.actor) || 0;
    laneDecisionCounts.set(step.actor, laneCount + 1);
    return {
      id: `telemetry-${step.id}`,
      type: step.kind || "status",
      title: step.kind === "tool_call" ? "Tool Call" : step.kind === "thought" ? "Decision" : "Status",
      subtitle: `${prettifyRole(step.actor)} · ${formatTime(step.ts)}`,
      body: clampText(step.content, 170),
      actor: step.actor,
      x: lane.x,
      y: ROW_Y.telemetry + laneCount * 128,
      details: toDetailEntries({
        actor: prettifyRole(step.actor),
        kind: step.kind,
        time: formatTime(step.ts),
        content: step.content,
      }),
    };
  });
}

export function buildAutonomyEdges(autonomyNodes: GraphNode[], supervisorNode: GraphNode): GraphEdge[] {
  const edges: GraphEdge[] = [];
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
  return edges;
}

export function buildTaskEdges(taskNodes: GraphNode[], supervisorNode: GraphNode, mode: string): GraphEdge[] {
  const edges: GraphEdge[] = [];
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
  return edges;
}

export function buildResultEdges(resultNodes: GraphNode[], responseResults: SwarmResult[], taskNodes: GraphNode[], handoffNodes: GraphNode[], supervisorNode: GraphNode, mode: string): GraphEdge[] {
  const edges: GraphEdge[] = [];
  resultNodes.forEach((resultNode, index) => {
    const result = responseResults[index];
    const role = String(result?.agent_role || taskNodes[index]?.laneId || taskNodes[taskNodes.length - 1]?.laneId).toLowerCase();
    const taskNode = taskNodes.find((task) => task.id === `task-${index}`) || taskNodes[index] || taskNodes[taskNodes.length - 1];
    const resultHandoffs = handoffNodes.filter((node) => node.id.startsWith(`handoff-${result?.task_id || index}`));
    const latestResultHandoff = resultHandoffs[resultHandoffs.length - 1];
    const resultSourceId = latestResultHandoff?.id || taskNode?.id || supervisorNode.id;
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
  return edges;
}

export function buildHandoffEdges(handoffNodes: GraphNode[], handoffEvents: HandoffEvent[], taskNodes: GraphNode[], responseResults: SwarmResult[]): GraphEdge[] {
  const edges: GraphEdge[] = [];
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
  return edges;
}

export function buildTelemetryEdges(telemetryNodes: GraphNode[], resultNodes: GraphNode[], responseResults: SwarmResult[]): GraphEdge[] {
  const latestResultByRole = new Map<string, string>();
  resultNodes.forEach((node, index) => {
    latestResultByRole.set(String(responseResults[index]?.agent_role || "").toLowerCase(), node.id);
  });

  return telemetryNodes.map((telemetryNode, index) => {
    const previousTelemetry = telemetryNodes
      .slice(0, index)
      .reverse()
      .find((item) => item.actor === telemetryNode.actor);
    return {
      id: `edge-telemetry-${telemetryNode.id}`,
      from: previousTelemetry?.id || latestResultByRole.get(telemetryNode.actor || "system") || `agent-${telemetryNode.actor || "system"}`,
      to: telemetryNode.id,
      label: telemetryNode.title.toLowerCase(),
      emphasis: telemetryNode.type === "thought" ? "strong" : "light",
    };
  });
}

export function computeGraphDimensions(lanes: Lane[], laneDecisionCounts: Map<string, number>) {
  const width = Math.max(1180, lanes.length * 260 + 140);
  const height = Math.max(
    980,
    ROW_Y.telemetry + Math.max(...Array.from(laneDecisionCounts.values()), 1) * 132 + 180,
  );
  return { width, height };
}

export function computeGraphMetrics(lanes: Lane[], taskNodes: GraphNode[], telemetryNodes: GraphNode[], handoffNodes: GraphNode[]) {
  return {
    roles: lanes.length,
    tasks: taskNodes.length,
    decisions: telemetryNodes.length,
    handoffs: handoffNodes.length,
  };
}
