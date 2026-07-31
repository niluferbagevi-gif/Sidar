import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useChatStore } from "./useChatStore.js";
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
  inferHitlActionFromNode,
  NODE_HEIGHT,
  NODE_WIDTH,
} from "../lib/swarmFlowGraph";
import type {
  AutonomyItem,
  GraphEdge,
  SwarmResult,
  SwarmTask,
  TelemetryStep,
} from "../lib/swarmFlowGraph";

type TaskDraft = Required<SwarmTask>;
type TaskField = keyof TaskDraft;
type OperationTone = "info" | "success" | "warning" | "error";

interface SwarmResponse {
  results?: SwarmResult[];
}

interface AutonomyActivity {
  items: AutonomyItem[];
  counts_by_status: Record<string, number>;
  counts_by_source: Record<string, number>;
  total?: number;
}

interface PendingApproval {
  request_id: string;
  [key: string]: unknown;
}

interface OperationLogEntry {
  id: string;
  tone: OperationTone;
  message: string;
  ts: string;
}

interface ExecuteSwarmMeta {
  mode?: string;
  sessionId?: string;
  maxConcurrency?: number;
}

interface PositionedGraphEdge extends GraphEdge {
  curve: string;
  labelX: number;
  labelY: number;
}

const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

const DEFAULT_TASKS = [
  {
    goal: "Kod tabanında güvenlik riski taşıyan noktaları tara",
    intent: "security_audit",
    preferred_agent: "",
  },
  {
    goal: "Bulunan riskler için kısa bir aksiyon planı üret",
    intent: "summarization",
    preferred_agent: "",
  },
];

const OPERATION_LOG_LIMIT = 10;

export function useSwarmFlowController() {
  const telemetryEvents = useChatStore((s: { telemetryEvents: TelemetryStep[] }) => s.telemetryEvents);
  const [tasks, setTasks] = useState<TaskDraft[]>(DEFAULT_TASKS);
  const [mode, setMode] = useState("parallel");
  const [sessionId, setSessionId] = useState("ui-swarm-session");
  const [maxConcurrency, setMaxConcurrency] = useState(3);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [response, setResponse] = useState<SwarmResponse | null>(null);
  const [autonomyActivity, setAutonomyActivity] = useState<AutonomyActivity>({
    items: [],
    counts_by_status: {},
    counts_by_source: {},
  });
  const [activityLoading, setActivityLoading] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [pendingApprovals, setPendingApprovals] = useState<PendingApproval[]>([]);
  const [hitlLoading, setHitlLoading] = useState(false);
  const [operationLog, setOperationLog] = useState<OperationLogEntry[]>([]);
  const [actionBusy, setActionBusy] = useState(false);
  const loaderErrorsRef = useRef({ activity: "", hitl: "" });

  const updateLoaderError = useCallback((source: "activity" | "hitl", message = "") => {
    const previousLoaderErrors = Object.values(loaderErrorsRef.current).filter(
      Boolean,
    );
    loaderErrorsRef.current = { ...loaderErrorsRef.current, [source]: message };
    setError((current) => {
      if (current && !previousLoaderErrors.includes(current)) return current;
      return (
        loaderErrorsRef.current.activity || loaderErrorsRef.current.hitl || ""
      );
    });
  }, []);

  const pushOperationLog = useCallback((message: string, tone: OperationTone = "info") => {
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
      const data: { pending?: PendingApproval[] } = await fetchJson("/api/hitl/pending");
      setPendingApprovals(data.pending || []);
      updateLoaderError("hitl");
    } catch (err) {
      setPendingApprovals([]);
      const message = errorMessage(err);
      updateLoaderError("hitl", message);
      pushOperationLog(
        `HITL bekleyen kayıtları alınamadı: ${message}`,
        "error",
      );
    } finally {
      setHitlLoading(false);
    }
  }, [pushOperationLog, updateLoaderError]);

  const loadAutonomyActivity = useCallback(async () => {
    setActivityLoading(true);
    try {
      const data: { activity?: AutonomyActivity } = await fetchJson(
        "/api/autonomy/activity?limit=8",
      );
      setAutonomyActivity(
        data.activity || {
          items: [],
          counts_by_status: {},
          counts_by_source: {},
        },
      );
      updateLoaderError("activity");
    } catch (err) {
      setAutonomyActivity({
        items: [],
        counts_by_status: {},
        counts_by_source: {},
      });
      const message = errorMessage(err);
      updateLoaderError("activity", message);
      pushOperationLog(
        `Autonomy aktivitesi alınamadı: ${message}`,
        "error",
      );
    } finally {
      setActivityLoading(false);
    }
  }, [pushOperationLog, updateLoaderError]);

  useEffect(() => {
    loadAutonomyActivity();
    loadPendingApprovals();
  }, [loadAutonomyActivity, loadPendingApprovals]);

  const steps = useMemo(
    () =>
      telemetryEvents
        .filter(
          (evt: TelemetryStep) =>
            evt.kind === "tool_call" ||
            evt.kind === "status" ||
            evt.kind === "thought",
        )
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

    const autonomyNodes = buildAutonomyNodes(
      autonomyActivity.items || [],
      lanes,
    );
    const supervisorNode = buildSupervisorNode({
      laneMap,
      mode,
      sessionId,
      maxConcurrency,
    });
    const taskNodes = buildTaskNodes(tasks, responseResults, laneMap);
    const agentNodes = buildAgentNodes(lanes);
    const handoffNodes = buildHandoffNodes(
      handoffEvents,
      laneMap,
      responseResults,
    );
    const resultNodes = buildResultNodes(responseResults, laneMap);
    const telemetryNodes = buildTelemetryNodes(
      telemetryWithActors,
      laneMap,
      laneDecisionCounts,
    );

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
      ...buildResultEdges(
        resultNodes,
        responseResults,
        taskNodes,
        handoffNodes,
        supervisorNode,
        mode,
      ),
      ...buildHandoffEdges(
        handoffNodes,
        handoffEvents,
        taskNodes,
        responseResults,
      ),
      ...buildTelemetryEdges(telemetryNodes, resultNodes, responseResults),
    ];

    const { width, height } = computeGraphDimensions(lanes, laneDecisionCounts);
    const metrics = computeGraphMetrics(
      lanes,
      taskNodes,
      telemetryNodes,
      handoffNodes,
    );

    const nodeMap = new Map(nodes.map((node) => [node.id, node]));
    return { nodes, edges, lanes, width, height, metrics, nodeMap };
  }, [
    autonomyActivity.items,
    maxConcurrency,
    mode,
    response,
    sessionId,
    steps,
    tasks,
  ]);

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
      .filter((edge): edge is PositionedGraphEdge => edge !== null);
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

  const updateTask = useCallback((index: number, field: TaskField, value: string) => {
    setTasks((prev) =>
      prev.map((task, idx) =>
        idx === index ? { ...task, [field]: value } : task,
      ),
    );
  }, []);

  const addTask = useCallback(() => {
    setTasks((prev) => [
      ...prev,
      { goal: "", intent: "mixed", preferred_agent: "" },
    ]);
  }, []);

  const removeTask = useCallback((index: number) => {
    setTasks((prev) => prev.filter((_, idx) => idx !== index));
  }, []);

  const executeSwarm = useCallback(
    async (overrideTasks: TaskDraft[] | null = null, overrideMeta: ExecuteSwarmMeta = {}) => {
      const sourceTasks = overrideTasks || tasks;
      const normalizedTasks = sourceTasks
        .map((task) => ({
          goal: String(task.goal || "").trim(),
          intent: String(task.intent || "").trim() || "mixed",
          preferred_agent:
            String(task.preferred_agent || "").trim() || undefined,
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
        const data: SwarmResponse = await fetchJson("/api/swarm/execute", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            mode: overrideMeta.mode || mode,
            session_id: overrideMeta.sessionId || sessionId.trim(),
            max_concurrency:
              Number(overrideMeta.maxConcurrency || maxConcurrency) || 1,
            tasks: normalizedTasks,
          }),
        });
        setResponse(data);
        setRunning(false);
        return true;
      } catch (err) {
        const message = errorMessage(err);
        setError(message);
        pushOperationLog(`Swarm tetiklenemedi: ${message}`, "error");
        setRunning(false);
        return false;
      }
    },
    [maxConcurrency, mode, pushOperationLog, sessionId, tasks],
  );

  const syncOperationSurface = useCallback(async () => {
    await Promise.all([loadAutonomyActivity(), loadPendingApprovals()]);
    pushOperationLog("Canlı operasyon yüzeyi yenilendi.", "success");
  }, [loadAutonomyActivity, loadPendingApprovals, pushOperationLog]);

  const addDraftTaskFromSelected = useCallback(() => {
    setTasks((prev) => [...prev, selectedTaskDraft]);
    pushOperationLog(
      `Seçili düğüm görev taslağına eklendi: ${selectedNode.title}`,
      "success",
    );
  }, [pushOperationLog, selectedNode, selectedTaskDraft]);

  const replaceFirstTaskFromSelected = useCallback(() => {
    setTasks((prev) =>
      prev.map((task, idx) => (idx === 0 ? selectedTaskDraft : task)),
    );
    pushOperationLog(
      `İlk görev seçili düğümden yeniden yazıldı: ${selectedNode.title}`,
      "info",
    );
  }, [pushOperationLog, selectedNode, selectedTaskDraft]);

  const runSelectedNode = useCallback(async () => {
    setActionBusy(true);
    const draft = buildTaskDraftFromNode(selectedNode);
    const ok = await executeSwarm([draft], {
      sessionId: `${sessionId.trim() || "ui-swarm-session"}-node`,
      maxConcurrency: 1,
    });
    if (ok) {
      pushOperationLog(
        `Seçili düğüm için hedefli swarm çalıştı: ${selectedNode.title}`,
        "success",
      );
    }
    setActionBusy(false);
  }, [executeSwarm, pushOperationLog, selectedNode, sessionId]);

  const requestNodeReview = useCallback(async () => {
    setActionBusy(true);
    try {
      const data: { request_id: string } = await fetchJson("/api/hitl/request", {
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
            details: Object.fromEntries(
              selectedNode.details.map((item) => [item.key, item.value]),
            ),
          },
        }),
      });
      pushOperationLog(
        `HITL isteği oluşturuldu: ${data.request_id}`,
        "success",
      );
      await loadPendingApprovals();
    } catch (err) {
      const message = errorMessage(err);
      setError(message);
      pushOperationLog(`HITL isteği oluşturulamadı: ${message}`, "error");
    } finally {
      setActionBusy(false);
    }
  }, [loadPendingApprovals, pushOperationLog, selectedNode]);

  const respondToApproval = useCallback(
    async (requestId: string, approved: boolean) => {
      setActionBusy(true);
      try {
        const data: { request_id: string; decision: string } = await fetchJson(
          `/api/hitl/respond/${encodeURIComponent(requestId)}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              approved,
              decided_by: "swarm_flow_panel",
              rejection_reason: approved
                ? ""
                : "Swarm operasyon yüzeyi üzerinden reddedildi.",
            }),
          },
        );
        pushOperationLog(
          `HITL kararı işlendi: ${data.request_id} → ${data.decision}`,
          approved ? "success" : "warning",
        );
        await loadPendingApprovals();
      } catch (err) {
        const message = errorMessage(err);
        setError(message);
        pushOperationLog(`HITL kararı gönderilemedi: ${message}`, "error");
      } finally {
        setActionBusy(false);
      }
    },
    [loadPendingApprovals, pushOperationLog],
  );

  return {
    mode,
    setMode,
    running,
    error,
    tasks,
    sessionId,
    setSessionId,
    maxConcurrency,
    setMaxConcurrency,
    executeSwarm,
    updateTask,
    addTask,
    removeTask,
    graphData,
    graphEdges,
    selectedNode,
    selectedNodeId,
    setSelectedNodeId,
    selectedTaskDraft,
    activityLoading,
    hitlLoading,
    actionBusy,
    loadAutonomyActivity,
    syncOperationSurface,
    addDraftTaskFromSelected,
    replaceFirstTaskFromSelected,
    runSelectedNode,
    requestNodeReview,
    loadPendingApprovals,
    pendingApprovals,
    operationLog,
    respondToApproval,
    autonomySummary,
    autonomyActivity,
    steps,
  };
}
