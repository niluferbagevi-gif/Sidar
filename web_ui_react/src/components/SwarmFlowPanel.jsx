import React, { useCallback, useMemo, useState } from "react";
import { useChatStore } from "../hooks/useChatStore.js";
import { fetchJson } from "../lib/api.js";

const DEFAULT_TASKS = [
  { goal: "Kod tabanında güvenlik riski taşıyan noktaları tara", intent: "security_audit", preferred_agent: "" },
  { goal: "Bulunan riskler için kısa bir aksiyon planı üret", intent: "summarization", preferred_agent: "" },
];

export function SwarmFlowPanel() {
  const { telemetryEvents } = useChatStore();
  const [tasks, setTasks] = useState(DEFAULT_TASKS);
  const [mode, setMode] = useState("parallel");
  const [sessionId, setSessionId] = useState("ui-swarm-session");
  const [maxConcurrency, setMaxConcurrency] = useState(3);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [response, setResponse] = useState(null);

  const steps = useMemo(
    () => telemetryEvents.filter((evt) => evt.kind === "tool_call" || evt.kind === "status" || evt.kind === "thought").slice(-12),
    [telemetryEvents],
  );

  const graphData = useMemo(() => {
    const taskNodes = tasks.map((task, index) => ({
      id: `task-${index}`,
      type: "task",
      title: task.preferred_agent?.trim() ? task.preferred_agent.trim() : `Task ${index + 1}`,
      subtitle: task.intent?.trim() || "mixed",
      body: task.goal?.trim() || "Görev açıklaması bekleniyor",
      x: 180,
      y: 36 + index * 118,
    }));

    const resultNodes = (response?.results || []).map((item, index) => ({
      id: `result-${item.task_id || index}`,
      type: item.status === "success" ? "result-success" : "result-warning",
      title: item.agent_role || "agent",
      subtitle: item.status || "unknown",
      body: item.summary || "Özet üretilmedi",
      x: 470,
      y: 36 + index * 118,
    }));

    const telemetryNodes = steps.map((step, index) => ({
      id: `telemetry-${step.id}`,
      type: step.kind,
      title: step.kind === "tool_call" ? "Tool Call" : step.kind === "thought" ? "Thought" : "Status",
      subtitle: new Date(step.ts).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
      body: step.content,
      x: 760,
      y: 36 + index * 92,
    }));

    const nodes = [
      {
        id: "supervisor",
        type: "root",
        title: "Supervisor",
        subtitle: mode === "parallel" ? "run_parallel" : "run_pipeline",
        body: sessionId.trim() || "ui-swarm-session",
        x: 24,
        y: 32,
      },
      ...taskNodes,
      ...resultNodes,
      ...telemetryNodes,
    ];

    const edges = [];
    taskNodes.forEach((taskNode) => {
      edges.push({ id: `edge-supervisor-${taskNode.id}`, from: "supervisor", to: taskNode.id, label: taskNode.subtitle });
    });
    resultNodes.forEach((resultNode, index) => {
      const sourceTask = taskNodes[index] || taskNodes[taskNodes.length - 1];
      if (sourceTask) {
        edges.push({ id: `edge-task-result-${index}`, from: sourceTask.id, to: resultNode.id, label: "delegation" });
      }
    });
    telemetryNodes.forEach((telemetryNode, index) => {
      const previous = telemetryNodes[index - 1] || resultNodes[resultNodes.length - 1] || taskNodes[taskNodes.length - 1] || nodes[0];
      edges.push({ id: `edge-telemetry-${index}`, from: previous.id, to: telemetryNode.id, label: telemetryNode.title.toLowerCase() });
    });

    return { nodes, edges };
  }, [mode, response, sessionId, steps, tasks]);

  const graphEdges = useMemo(() => {
    const nodeMap = new Map(graphData.nodes.map((node) => [node.id, node]));
    return graphData.edges
      .map((edge) => {
        const from = nodeMap.get(edge.from);
        const to = nodeMap.get(edge.to);
        if (!from || !to) return null;
        const x1 = from.x + 210;
        const y1 = from.y + 40;
        const x2 = to.x;
        const y2 = to.y + 40;
        const curve = `M ${x1} ${y1} C ${x1 + 80} ${y1}, ${x2 - 80} ${y2}, ${x2} ${y2}`;
        return { ...edge, curve, labelX: (x1 + x2) / 2, labelY: (y1 + y2) / 2 - 10 };
      })
      .filter(Boolean);
  }, [graphData]);

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
                <p className="panel__hint">Supervisor → görev → ajan çıktısı → canlı telemetri akışını node-graph olarak izleyin.</p>
              </div>
              <span className="pill">{graphData.nodes.length} node / {graphData.edges.length} edge</span>
            </div>
            <div className="swarm-graph">
              <svg className="swarm-graph__edges" viewBox="0 0 1080 760" preserveAspectRatio="none" aria-hidden="true">
                {graphEdges.map((edge) => (
                  <g key={edge.id}>
                    <path d={edge.curve} className="swarm-graph__edge-path" />
                    <text x={edge.labelX} y={edge.labelY} className="swarm-graph__edge-label">
                      {edge.label}
                    </text>
                  </g>
                ))}
              </svg>
              <div className="swarm-graph__canvas">
                {graphData.nodes.map((node) => (
                  <article
                    key={node.id}
                    className={`swarm-graph__node swarm-graph__node--${node.type}`}
                    style={{ left: `${node.x}px`, top: `${node.y}px` }}
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
          </div>

          <div className="card">
            <h3>Canlı Telemetri</h3>
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
