import { useSwarmFlowController } from "../hooks/useSwarmFlowController.js";
import { formatTime, NODE_HEIGHT, NODE_WIDTH } from "../lib/swarmFlowGraph.js";
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

export function SwarmFlowPanel() {
  const {
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
  } = useSwarmFlowController();

  return (
    <section
      className="panel panel--stacked"
      aria-label="Swarm görev akışı paneli"
    >
      <div className="panel-toolbar">
        <div>
          <h2>Swarm Görev Akışı</h2>
          <p className="panel__hint">
            Paralel veya sıralı SwarmTask listeleri göndererek orkestrasyonu
            tetikleyin.
          </p>
        </div>
        <div className="inline-controls">
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="parallel">run_parallel</option>
            <option value="pipeline">run_pipeline</option>
          </select>
          <button onClick={() => executeSwarm()} disabled={running}>
            {running ? "Çalışıyor…" : "Swarm Başlat"}
          </button>
        </div>
      </div>

      {error && (
        <div className="banner banner--error" role="alert">
          {error}
        </div>
      )}

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
