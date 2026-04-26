import {
  buildTaskDraftFromNode,
  clampText,
  inferHitlActionFromNode,
  inferTelemetryActor,
  prettifyReason,
  prettifyRole,
  toDetailEntries,
} from "./SwarmFlowPanel.jsx";

describe("SwarmFlowPanel helper utilities", () => {
  it("covers helper fallback branches", () => {
    expect(prettifyRole("")).toBe("Unknown");
    expect(prettifyRole("multi_word-role")).toBe("Multi Word Role");
    expect(clampText("   ")).toBe("Açıklama bekleniyor.");
    expect(prettifyReason("")).toBe("");
    expect(toDetailEntries(null)).toEqual([]);
    expect(toDetailEntries({ key: ["a", "b"] })[0].value).toBe("a · b");
    expect(inferTelemetryActor({ content: "", kind: "status" }, [])).toBe("system");
    expect(inferTelemetryActor({ content: "reviewer did something", kind: "status" }, ["reviewer"])).toBe("reviewer");
    expect(inferTelemetryActor({ content: "no role text", kind: "tool_call" }, [])).toBe("supervisor");
    expect(inferTelemetryActor({ content: "no role text", kind: "status" }, [])).toBe("system");
    expect(buildTaskDraftFromNode({ title: "Fallback", body: "Node" }).intent).toBe("mixed");
    expect(buildTaskDraftFromNode({ subtitle: "   ", actor: "", laneId: "", title: "T", body: "B" }).intent).toBe("mixed");
    expect(inferHitlActionFromNode()).toBe("graph_review");
  });
});
