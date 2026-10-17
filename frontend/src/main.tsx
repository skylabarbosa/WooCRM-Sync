import { Component, type ReactNode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { getDashboard, postAction } from "./api";
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
  const [error, setError] = useState(""); const [notice, setNotice] = useState("Ready"); const [busy, setBusy] = useState(false);
  const normalizedPath = path === "/woocrm" ? "/woocrm/" : path;
  const load = async () => { try { setError(""); setData(await getDashboard()); } catch (reason) { setError(reason instanceof Error ? reason.message : "Backend unavailable"); } };
  useEffect(() => { load(); const handler = () => setPath(window.location.pathname.replace(/\/+$/, "") || "/woocrm"); window.addEventListener("popstate", handler); return () => window.removeEventListener("popstate", handler); }, []);
  const navigate = (href: string) => { window.history.pushState({}, "", href); setPath(window.location.pathname.replace(/\/+$/, "") || "/woocrm"); };
  const reconcile = async () => { setBusy(true); setNotice("Running reconciliation…"); try { const result = await postAction("reconcile"); setNotice(result.message); await load(); } catch (reason) { setNotice(reason instanceof Error ? reason.message : "Reconciliation failed"); } finally { setBusy(false); } };
  const notify = (message: string) => { setNotice(message); window.setTimeout(() => setNotice("Ready"), 4500); };
  const orderMatch = normalizedPath.match(/^\/woocrm\/orders\/(.+)$/);
  const page = data ? orderMatch ? <OrderInvestigationPage orderId={decodeURIComponent(orderMatch[1])} data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : normalizedPath === "/woocrm/orders" ? <OrdersPage data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : normalizedPath === "/woocrm/customers" ? <CustomersPage data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : normalizedPath === "/woocrm/import" ? <ImportPage data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : normalizedPath === "/woocrm/settings" ? <SettingsPage data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : normalizedPath === "/woocrm/risk-guard" ? <RiskGuardPage data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : <DashboardPage data={data} refresh={load} busy={busy} setBusy={setBusy} notify={notify} onNavigate={navigate} /> : error ? <ErrorState message={error} onRetry={load} /> : <LoadingState />;
  return <AppShell path={normalizedPath} onNavigate={navigate} notice={notice} busy={busy} onReconcile={reconcile} integration={data?.integration} data={data}>{page}</AppShell>;
}

createRoot(document.getElementById("root")!).render(<RenderErrorBoundary><App /></RenderErrorBoundary>);
