from pathlib import Path


def test_swarm_flow_panel_renders_visual_decision_graph_markup():
    src = Path("web_ui_react/src/components/SwarmFlowPanel.jsx").read_text(encoding="utf-8")

    assert "Karar Grafiği" in src
    assert "Proaktif Aktivite Akışı" in src
    assert "Node Inspector" in src
    assert "p2p decision" in src
    assert "assistant_turn" not in src  # panel swarm P2P odaklı kalmalı
    assert "swarm-graph__node" in src
    assert "graphData.edges.length" in src
    assert "Aktiviteyi Yenile" in src


def test_swarm_flow_panel_styles_define_graph_canvas_and_nodes():
    css = Path("web_ui_react/src/index.css").read_text(encoding="utf-8")

    assert ".swarm-graph" in css
    assert ".swarm-graph__canvas" in css
    assert ".swarm-graph__legend" in css
    assert ".swarm-graph__edge-path" in css
    assert ".swarm-graph__node--handoff" in css
    assert ".swarm-graph__inspector" in css
    assert ".swarm-graph__node--root" in css
    assert ".swarm-graph__node--autonomy" in css
