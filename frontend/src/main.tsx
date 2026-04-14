import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";
import App from "./App";
import "./index.css";

// #region agent log
if (typeof window !== "undefined") {
  fetch('http://127.0.0.1:7242/ingest/3aa7eda4-e97a-402c-ac3d-b6b632d2544d',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({runId:'pre-fix',hypothesisId:'H9',location:'main.tsx:boot',message:'frontend app boot',data:{href:window.location.href,origin:window.location.origin,pathname:window.location.pathname,host:window.location.host,isSecure:window.isSecureContext,swController:!!navigator.serviceWorker?.controller,apiBase:(import.meta as any)?.env?.VITE_API_BASE_URL||'/api'},timestamp:Date.now()})}).catch(()=>{});
}
// #endregion

class RootErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("RootErrorBoundary:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 24 }}>
          <h2>UI Crash</h2>
          <pre style={{ whiteSpace: "pre-wrap" }}>
            {String(this.state.error?.stack || this.state.error?.message)}
          </pre>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RootErrorBoundary>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </RootErrorBoundary>
  </React.StrictMode>
);

registerSW({ immediate: true });
