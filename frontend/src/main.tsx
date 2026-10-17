import { Component, type ReactNode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ApiError, getAccessToken, getDashboard, login, postAction, setAccessToken } from "./api";
import { AppShell, ErrorState, LoadingState } from "./components";
import { CustomersPage, DashboardPage, ImportPage, OrderInvestigationPage, OrdersPage, RiskGuardPage, SettingsPage } from "./pages";
import type { Dashboard } from "./types";
import "./index.css";

class RenderErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  reset = () => {
    this.setState({ error: null });
  };

  render() {
    return this.state.error
      ? <ErrorState message={`The page could not be rendered: ${this.state.error.message}`} onRetry={this.reset} />
      : this.props.children;
  }
}

function App() {
  const [path, setPath] = useState(window.location.pathname.replace(/\/+$/, "") || "/woocrm");
  const [data, setData] = useState<Dashboard | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [accessToken, setAccessTokenInput] = useState(getAccessToken());
  const [error, setError] = useState(""); const [notice, setNotice] = useState("Ready"); const [busy, setBusy] = useState(false);
  const normalizedPath = path === "/woocrm" ? "/woocrm/" : path;
  const load = async () => {
    try { setError(""); setAuthRequired(false); setData(await getDashboard()); }
    catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) setAuthRequired(true);
      else setError(reason instanceof Error ? reason.message : "Backend unavailable");
    }
  };
  useEffect(() => {
    load();
    const handler = () => setPath(window.location.pathname.replace(/\/+$/, "") || "/woocrm");
    const authHandler = () => setAuthRequired(true);
    window.addEventListener("popstate", handler);
    window.addEventListener("woocrm-auth-required", authHandler);
    return () => {
      window.removeEventListener("popstate", handler);
      window.removeEventListener("woocrm-auth-required", authHandler);
    };
  }, []);
  const navigate = (href: string) => { window.history.pushState({}, "", href); setPath(window.location.pathname.replace(/\/+$/, "") || "/woocrm"); };
  const reconcile = async () => { setBusy(true); setNotice("Running reconciliation…"); try { const result = await postAction("reconcile"); setNotice(result.message); await load(); } catch (reason) { setNotice(reason instanceof Error ? reason.message : "Reconciliation failed"); } finally { setBusy(false); } };
  const notify = (message: string) => { setNotice(message); window.setTimeout(() => setNotice("Ready"), 4500); };
  const orderMatch = normalizedPath.match(/^\/woocrm\/orders\/(.+)$/);
  const page = data ? orderMatch ? <OrderInvestigationPage orderId={decodeURIComponent(orderMatch[1])} data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : normalizedPath === "/woocrm/orders" ? <OrdersPage data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : normalizedPath === "/woocrm/customers" ? <CustomersPage data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : normalizedPath === "/woocrm/import" ? <ImportPage data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : normalizedPath === "/woocrm/settings" ? <SettingsPage data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : normalizedPath === "/woocrm/risk-guard" ? <RiskGuardPage data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : <DashboardPage data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : error ? <ErrorState message={error} onRetry={load} /> : <LoadingState />;
  if (authRequired) {
    return <div className="empty-state">
      <strong>Sign in to WooCRM Sync</strong>
      <input aria-label="Username" value={username} onChange={event => setUsername(event.target.value)} placeholder="Username" />
      <input aria-label="Password" type="password" value={password} onChange={event => setPassword(event.target.value)} placeholder="Password" />
      {loginError && <p>{loginError}</p>}
      <button className="button primary" onClick={() => {
        void login(username, password).then(result => {
          setAccessToken(result.access_token);
          setAccessTokenInput(result.access_token);
          setLoginError("");
          return load();
        }).catch(reason => setLoginError(reason instanceof Error ? reason.message : "Sign in failed"));
      }}>Sign in</button>
      {accessToken && <button className="button secondary" onClick={() => { setAccessToken(""); setAccessTokenInput(""); }}>Clear session</button>}
    </div>;
  }
  return <AppShell path={normalizedPath} onNavigate={navigate} notice={notice} busy={busy} onReconcile={reconcile} integration={data?.integration} data={data}>{page}</AppShell>;
}

createRoot(document.getElementById("root")!).render(<RenderErrorBoundary><App /></RenderErrorBoundary>);
