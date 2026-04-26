import React from "react";

export class PanelErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error) {
    // eslint-disable-next-line no-console
    console.error("Panel render error:", error);
  }

  render() {
    if (this.state.error) {
      return <div className="error-panel" role="alert">Panel yüklenemedi. Lütfen sayfayı yenileyin.</div>;
    }
    return this.props.children;
  }
}

export function withPanelErrorBoundary(node) {
  return <PanelErrorBoundary>{node}</PanelErrorBoundary>;
}
