import React, { type ErrorInfo, type ReactNode } from "react";

interface PanelErrorBoundaryProps {
  children: ReactNode;
}

interface PanelErrorBoundaryState {
  error: Error | null;
}

export class PanelErrorBoundary extends React.Component<
  PanelErrorBoundaryProps,
  PanelErrorBoundaryState
> {
  state: PanelErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): PanelErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, _errorInfo: ErrorInfo): void {
    console.error("Panel render error:", error);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="error-panel" role="alert">
          Panel yüklenemedi. Lütfen sayfayı yenileyin.
        </div>
      );
    }
    return this.props.children;
  }
}

export function withPanelErrorBoundary(node: ReactNode): React.ReactElement {
  return <PanelErrorBoundary>{node}</PanelErrorBoundary>;
}
