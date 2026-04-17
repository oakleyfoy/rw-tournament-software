import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";
import App from "./App";
import "./index.css";

// #region agent log
if (typeof window !== "undefined") {
  fetch('http://127.0.0.1:7519/ingest/37bb460e-befc-4ee4-99d2-a2eb163c26d3',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'00c0ef'},body:JSON.stringify({sessionId:'00c0ef',runId:'pre-fix',hypothesisId:'H7',location:'main.tsx:boot',message:'frontend main boot executed',data:{href:window.location.href,origin:window.location.origin,pathname:window.location.pathname,host:window.location.host,isSecure:window.isSecureContext,swController:!!navigator.serviceWorker?.controller,apiBase:(import.meta as any)?.env?.VITE_API_BASE_URL||'/api'},timestamp:Date.now()})}).catch(()=>{});
  navigator.serviceWorker?.getRegistration?.().then((registration) => {
    fetch('http://127.0.0.1:7519/ingest/37bb460e-befc-4ee4-99d2-a2eb163c26d3',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'00c0ef'},body:JSON.stringify({sessionId:'00c0ef',runId:'pre-fix',hypothesisId:'H9',location:'main.tsx:serviceWorker',message:'service worker registration snapshot',data:{hasRegistration:!!registration,activeScriptURL:registration?.active?.scriptURL||null,waitingScriptURL:registration?.waiting?.scriptURL||null,installingScriptURL:registration?.installing?.scriptURL||null,controllerScriptURL:navigator.serviceWorker?.controller?.scriptURL||null},timestamp:Date.now()})}).catch(()=>{});
  }).catch(()=>{});
  const badge = document.createElement('div');
  badge.id = 'rw-debug-badge-00c0ef';
  badge.textContent = 'DBG 00c0ef-main';
  Object.assign(badge.style, {
    position: 'fixed',
    right: '8px',
    top: '8px',
    zIndex: '2147483647',
    padding: '4px 8px',
    borderRadius: '6px',
    background: '#111827',
    color: '#fff',
    fontSize: '11px',
    fontWeight: '700',
    fontFamily: 'monospace',
    boxShadow: '0 2px 8px rgba(0,0,0,0.25)',
    pointerEvents: 'none',
    opacity: '0.92'
  } as CSSStyleDeclaration);
  window.addEventListener('DOMContentLoaded', () => {
    if (!document.getElementById('rw-debug-badge-00c0ef')) {
      document.body.appendChild(badge);
    }
  });
  if (document.body && !document.getElementById('rw-debug-badge-00c0ef')) {
    document.body.appendChild(badge);
  }
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
