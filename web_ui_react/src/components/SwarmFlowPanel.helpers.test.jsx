import {
  buildTaskDraftFromNode,
  clampText,
  inferHitlActionFromNode,
  inferTelemetryActor,
  prettifyReason,
  prettifyRole,
  toDetailEntries,
} from "./SwarmFlowPanel.js";
import {
  __swarmFlowGraphTestables,
  buildResultEdges,
  buildTelemetryEdges,
  buildTelemetryNodes,
} from "../lib/swarmFlowGraph.js";

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

  it("fails closed when a graph has neither the requested nor supervisor lane", () => {
    expect(() => __swarmFlowGraphTestables.requireLane(new Map(), "coder")).toThrow(
      "Graph lane is missing for role: coder",
    );
  });

  it("covers graph source and telemetry fallbacks", () => {
    const supervisorLane = { id: "lane-supervisor", role: "supervisor", x: 10 };
    const laneMap = new Map([["supervisor", supervisorLane]]);
    const telemetryNodes = buildTelemetryNodes(
      [{ id: "empty-kind", actor: "unknown", kind: "", content: "status", ts: "" }],
      laneMap,
      new Map(),
    );
    expect(telemetryNodes[0].type).toBe("status");

    const supervisorNode = { id: "agent-supervisor" };
    expect(
      buildResultEdges([{ id: "result-1" }], [], [], [], supervisorNode, "parallel")[0].from,
    ).toBe("agent-supervisor");

    const resultNodes = [{ id: "result-coder" }];
    const responseResults = [{ agent_role: "coder" }];
    const telemetry = [
      { id: "telemetry-first", actor: "coder", title: "Status", type: "status" },
      { id: "telemetry-second", actor: "coder", title: "Thought", type: "thought" },
      { id: "telemetry-system", actor: "system", title: "Status", type: "status" },
      { id: "telemetry-no-actor", actor: "", title: "Status", type: "status" },
    ];
    expect(buildTelemetryEdges(telemetry, resultNodes, responseResults).map((edge) => edge.from))
      .toEqual(["result-coder", "telemetry-first", "agent-system", "agent-system"]);
  });
});
