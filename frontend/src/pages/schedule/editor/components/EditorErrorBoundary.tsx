import React from "react";

type Props = { children: React.ReactNode };

type State = { hasError: boolean; message?: string };

export class EditorErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: unknown): State {
    const message = error instanceof Error ? error.message : String(error);
    return { hasError: true, message };
  }

  componentDidCatch(error: unknown) {
    // Keep this; it surfaces route-level errors without blank screen
    console.error("Manual Schedule Editor crashed:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 16 }}>
          <h2>Manual Schedule Editor Error</h2>
          <p>The editor crashed while rendering. Check console for details.</p>
          {this.state.message ? (
            <pre style={{ whiteSpace: "pre-wrap" }}>{this.state.message}</pre>
          ) : null}
        </div>
      );
    }
    return this.props.children;
  }
}

