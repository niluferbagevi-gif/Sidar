import React from "react";

export function TaskEditor({
  tasks,
  sessionId,
  maxConcurrency,
  onSessionIdChange,
  onMaxConcurrencyChange,
  onTaskChange,
  onAddTask,
  onRemoveTask,
}) {
  return (
    <div className="card form-card">
      <h3>Görev Tanımı</h3>
      <label>
        Session ID
        <input value={sessionId} onChange={(e) => onSessionIdChange(e.target.value)} placeholder="ui-swarm-session" />
      </label>
      <label>
        Maksimum eşzamanlılık
        <input type="number" min="1" max="8" value={maxConcurrency} onChange={(e) => onMaxConcurrencyChange(e.target.value)} />
      </label>
      <div className="stack-list">
        {tasks.map((task, index) => (
          <div key={`${index}-${task.goal}`} className="task-editor">
            <label>
              Goal
              <textarea rows={3} value={task.goal} onChange={(e) => onTaskChange(index, "goal", e.target.value)} placeholder="Görevin açıklaması" />
            </label>
            <div className="inline-controls inline-controls--stretch">
              <label>
                Intent
                <input value={task.intent} onChange={(e) => onTaskChange(index, "intent", e.target.value)} placeholder="security_audit" />
              </label>
              <label>
                Preferred agent
                <input value={task.preferred_agent} onChange={(e) => onTaskChange(index, "preferred_agent", e.target.value)} placeholder="opsiyonel role_name" />
              </label>
            </div>
            <button type="button" className="button-secondary" onClick={() => onRemoveTask(index)} disabled={tasks.length === 1}>Görevi Sil</button>
          </div>
        ))}
      </div>
      <button type="button" onClick={onAddTask}>Yeni Görev Ekle</button>
    </div>
  );
}
