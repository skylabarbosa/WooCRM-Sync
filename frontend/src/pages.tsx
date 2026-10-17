import {
  AlertTriangle, ArrowRight, ArrowUpRight, CheckCircle2, Clock, Clock3, Database, FileUp,
  RefreshCw, ShieldAlert, UploadCloud, Users, Check, XCircle, AlertCircle, ShieldCheck,
  Copy, Link2, UserX, ChevronRight, ChevronLeft, Search, Info, FileJson, Trash2, CircleCheck,
  CircleAlert, FileWarning, ChevronDown, ChevronUp, FileText, Download, User, HardDrive, RotateCcw,
  Shield, Radio, Settings as SettingsIcon, HelpCircle, GitFork, X, ShoppingCart, Play, ArrowRightLeft
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  getDatasets, getOrderHistory, getRiskEvaluations, getRiskSettings, importFile,
  postAction, reviewRiskEvaluation, testConnection, updateRiskSettings
} from "./api";
import {
  ConfirmAction, ConfirmDialog, DashboardOrderTable, DonutChart, EmptyState,
  ErrorState, formatDate, formatMoney, LoadingState, MetricCard,
  OrderDetail, OrderTable, SearchControl, StatusBadge, WooStatusBadge
} from "./components";
import type {
  CustomerGroup, Dashboard, ImportResult, Order, OrderEvent, RiskEvaluation,
  DatasetInfo, RiskSettings, SyncState
} from "./types";

type PageProps = {
  data: Dashboard;
  refresh: () => Promise<void>;
  busy: boolean;
  setBusy: (value: boolean) => void;
  notify: (message: string) => void;
  onNavigate: (path: string) => void;
};

/* ===========================================================
   Dashboard Page
=========================================================== */
export function DashboardPage({ data, refresh, busy, setBusy, notify, onNavigate }: PageProps) {
  const [selected, setSelected] = useState<Order | null>(null);
  const [pendingAction, setPendingAction] = useState<{ order: Order; kind: "replay" | "update" } | null>(null);

  const action = async (order: Order, kind: "replay" | "update") => {
    if (kind === "update") { setPendingAction({ order, kind }); return; }
    await runAction(order, kind);
  };
  const runAction = async (order: Order, kind: "replay" | "update") => {
    setBusy(true);
    try { const r = await postAction(`orders/${order.id}/${kind}`); notify(r.message); await refresh(); }
    catch (e) { notify(e instanceof Error ? e.message : "Action failed"); }
    finally { setBusy(false); setPendingAction(null); }
  };

  const attention = data.orders.filter(o => ["MISSING", "ERROR", "MISMATCH"].includes(o.state));
  const eligible = data.eligible_order_count;
  const counts = data.counts;
  const healthPct = eligible > 0 ? Math.round((counts.SYNCED / eligible) * 100) : 0;

  /* Synthetic activity events from last_run */
  const activityEvents = data.last_run
    ? [
        { id: 1, icon: "blue",  Icon: RefreshCw,     title: "Reconciliation completed", desc: `${data.last_run.processed} records processed, ${data.last_run.skipped} skipped`, time: formatDate(data.last_run.completed_at) },
        { id: 2, icon: "green", Icon: CheckCircle2,   title: "Orders synchronized",      desc: `${counts.SYNCED} orders verified successfully`,                                  time: formatDate(data.last_run.completed_at) },
        ...(counts.ERROR > 0 ? [{ id: 3, icon: "amber", Icon: AlertTriangle, title: `${counts.ERROR} error detected`, desc: "Recoverable connector error", time: formatDate(data.last_run.completed_at) }] : []),
        { id: 4, icon: "purple", Icon: Database,      title: "Demo data imported",       desc: `${data.orders.length} order records are available`,                              time: formatDate(data.last_run.started_at) },
      ].filter(Boolean)
    : [];

  /* Recent orders sorted: attention first */
  const recentOrders = [...data.orders].sort((a, b) => {
    const aAttn = ["MISSING", "ERROR", "MISMATCH"].includes(a.state) ? 0 : 1;
    const bAttn = ["MISSING", "ERROR", "MISMATCH"].includes(b.state) ? 0 : 1;
    return aAttn - bAttn;
  }).slice(0, 5);

  return (
    <>
      {selected && <OrderDetail order={selected} onClose={() => setSelected(null)} />}
      {pendingAction && (
        <ConfirmDialog
          title="Update CRM from WooCommerce?"
          message={`Order #${pendingAction.order.id} will be updated only after the backend confirms it is eligible.`}
          onCancel={() => setPendingAction(null)}
          onConfirm={() => void runAction(pendingAction.order, pendingAction.kind)}
          confirmLabel="Confirm update"
        >
          <div className="confirmation-values">
            <div><span>WooCommerce total</span><strong>{formatMoney(pendingAction.order.total, pendingAction.order.currency)}</strong></div>
            <div><span>Current CRM total</span><strong>{pendingAction.order.crm ? formatMoney(pendingAction.order.crm.total, pendingAction.order.crm.currency) : "No CRM record"}</strong></div>
            <div><span>Proposed value</span><strong>{formatMoney(pendingAction.order.total, pendingAction.order.currency)}</strong></div>
          </div>
        </ConfirmDialog>
      )}

      {/* -- Page heading -- */}
      <div className="page-heading">
        <div>
          <h2>Dashboard</h2>
          <p style={{ fontSize: 14, marginTop: 4, color: "var(--ink-2)", fontWeight: 500 }}>Keep orders and CRM records aligned</p>
          <p style={{ fontSize: 12, marginTop: 4 }}>Explore your WooCommerce and CRM synchronization status and take action where needed.</p>
        </div>
      </div>

      {/* -- Metric cards -- */}
      <section className="metric-grid">
        <MetricCard label="Eligible orders" value={eligible}         detail={`${data.orders.length} total in snapshot`} tone="eligible" onClick={() => onNavigate("/woocrm/orders")} />
        <MetricCard label="Synced"          value={counts.SYNCED}    detail="Verified records"       tone="synced"   onClick={() => onNavigate("/woocrm/orders")} />
        <MetricCard label="Missing"         value={counts.MISSING}   detail="Awaiting CRM record"    tone="missing"  onClick={() => onNavigate("/woocrm/orders")} />
        <MetricCard label="Mismatched"      value={counts.MISMATCH}  detail="Need review"            tone="mismatch" onClick={() => onNavigate("/woocrm/orders")} />
        <MetricCard label="Errors"          value={counts.ERROR}     detail="Recoverable failures"   tone="error"    onClick={() => onNavigate("/woocrm/orders")} />
      </section>

      {/* -- Attention alert -- */}
      {attention.length > 0 && (
        <div className="alert-banner">
          <div className="alert-banner-left">
            <div className="alert-banner-icon"><AlertTriangle size={18} /></div>
            <div>
              <div className="alert-banner-title">
                {attention.length} order{attention.length !== 1 ? "s" : ""} need{attention.length === 1 ? "s" : ""} attention
              </div>
              <div className="alert-banner-desc">
                {attention.length === 1
                  ? "There is 1 order with a recoverable failure. Review and fix it to keep your data in sync."
                  : `There are ${attention.length} orders with issues. Review and fix them to keep your data in sync.`}
              </div>
            </div>
          </div>
          <button className="button alert-banner-btn" onClick={() => onNavigate("/woocrm/orders")}>
            View issue{attention.length !== 1 ? "s" : ""} <ArrowRight size={14} />
          </button>
        </div>
      )}

      {/* -- Three-column grid -- */}
      <div className="dash-three-col">

        {/* Sync Summary */}
        <section className="surface sync-summary-card">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Sync health</span>
              <h3>Sync summary</h3>
              <p style={{ fontSize: 11, color: "var(--muted)", marginTop: 3 }}>
                {counts.SYNCED} of {eligible} orders synced.{attention.length > 0 ? ` ${attention.length} needs attention.` : ""}
              </p>
            </div>
          </div>
          <div className="health-body">
            <DonutChart
              synced={counts.SYNCED}
              missing={counts.MISSING}
              mismatch={counts.MISMATCH}
              error={counts.ERROR}
              total={eligible}
            />
            <div className="health-rows">
              {[
                { label: "Synced",    count: counts.SYNCED,   pct: eligible ? Math.round((counts.SYNCED / eligible) * 100) : 0,   color: "#22C55E" },
                { label: "Missing",   count: counts.MISSING,  pct: eligible ? Math.round((counts.MISSING / eligible) * 100) : 0,  color: "#EF4444" },
                { label: "Mismatched",count: counts.MISMATCH, pct: eligible ? Math.round((counts.MISMATCH / eligible) * 100) : 0, color: "#7C4DFF" },
                { label: "Errors",    count: counts.ERROR,    pct: eligible ? Math.round((counts.ERROR / eligible) * 100) : 0,    color: "#F59E0B" },
              ].map(row => (
                <div className="health-row" key={row.label}>
                  <span className="health-row-dot" style={{ background: row.color }} />
                  <span className="health-row-label">{row.label}</span>
                  <span className="health-row-count">{row.count}</span>
                  <span className="health-row-pct">{row.pct}%</span>
                </div>
              ))}
            </div>
          </div>
          <div className="health-footer">
            <div className="health-footer-left">
              <Clock size={13} />
              {data.last_run
                ? `Last run ${formatDate(data.last_run.completed_at)}`
                : "No reconciliation run recorded"}
            </div>
          </div>
        </section>

        {/* Recent Activity */}
        <section className="surface activity-card">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Recent activity (derived from the last run)</span>
              <h3>Latest synchronization events.</h3>
            </div>
          </div>
          <div className="activity-list">
            {activityEvents.length > 0
              ? activityEvents.map(evt => (
                  <div className="activity-row" key={evt.id}>
                    <div className={`activity-icon ${evt.icon}`}><evt.Icon size={15} /></div>
                    <div className="activity-content">
                      <strong>{evt.title}</strong>
                      <p>{evt.desc}</p>
                    </div>
                    <time className="activity-time">{evt.time}</time>
                  </div>
                ))
              : <EmptyState title="No activity yet" message="Run a reconciliation to create the first activity record." />}
          </div>
        </section>

        {/* Risk Guard Summary */}
        <section className="surface risk-summary-card">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Risk Guard</span>
              <h3>Risk Guard</h3>
              <p style={{ fontSize: 11, color: "var(--muted)", marginTop: 3 }}>Potential data issues detected.</p>
            </div>
            <button className="link-button" onClick={() => onNavigate("/woocrm/risk-guard")}>
              View all <ArrowRight size={13} />
            </button>
          </div>
          <div className="risk-summary-list">
            {/* High-priority issues (errors + mismatches) */}
            <button className="risk-summary-row risk-row-amber" onClick={() => onNavigate("/woocrm/risk-guard")}>
              <div className="risk-summary-icon amber"><AlertTriangle size={15} /></div>
              <div className="risk-summary-content">
                <strong>
                  {counts.ERROR + counts.MISMATCH > 0
                    ? `${counts.ERROR + counts.MISMATCH} high-priority issue${counts.ERROR + counts.MISMATCH !== 1 ? "s" : ""}`
                    : "No high-priority issues"}
                </strong>
                <span>Orders with recoverable failures</span>
              </div>
              <ArrowRight size={14} className="risk-summary-arrow" />
            </button>
            {/* Duplicate check */}
            <button className="risk-summary-row risk-row-neutral" onClick={() => onNavigate("/woocrm/risk-guard")}>
              <div className="risk-summary-icon neutral"><Copy size={15} /></div>
              <div className="risk-summary-content">
                <strong>0 possible duplicates</strong>
                <span>No customer duplicates detected</span>
              </div>
              <ArrowRight size={14} className="risk-summary-arrow" />
            </button>
            {/* Data integrity */}
            <button className={`risk-summary-row ${counts.MISMATCH === 0 ? "risk-row-green" : "risk-row-amber"}`} onClick={() => onNavigate("/woocrm/risk-guard")}>
              <div className={`risk-summary-icon ${counts.MISMATCH === 0 ? "green" : "amber"}`}>
                {counts.MISMATCH === 0 ? <Check size={15} /> : <AlertCircle size={15} />}
              </div>
              <div className="risk-summary-content">
                <strong>Data integrity</strong>
                <span>{counts.MISMATCH === 0 ? "No mismatched critical fields" : `${counts.MISMATCH} fields mismatched`}</span>
              </div>
              <ArrowRight size={14} className="risk-summary-arrow" />
            </button>
          </div>
        </section>
      </div>

      {/* -- Recent Orders -- */}
      <section className="surface" style={{ marginTop: 16 }}>
        <div className="section-heading">
          <div>
            <span className="eyebrow">Latest records</span>
            <h3>Recent orders</h3>
            <p style={{ fontSize: 11, color: "var(--muted)", marginTop: 3 }}>
              Latest orders with their synchronization status. Orders needing attention are shown first.
            </p>
          </div>
          <button className="link-button" onClick={() => onNavigate("/woocrm/orders")}>
            View all orders <ArrowRight size={13} />
          </button>
        </div>
        {recentOrders.length > 0
          ? <DashboardOrderTable
              orders={recentOrders}
              onSelect={order => onNavigate(`/woocrm/orders/${order.id}`)}
              onAction={action}
              busy={busy}
            />
          : <EmptyState title="No orders yet" message="Import WooCommerce orders to get started." />}
      </section>
    </>
  );
}

/* ===========================================================
   Orders Page
=========================================================== */
export function OrdersPage({ data, refresh, busy, setBusy, notify }: PageProps) {
  const params = new URLSearchParams(window.location.search);
  const [query, setQuery] = useState(params.get("search") || "");
  const [filter, setFilter] = useState<SyncState | "ALL">((params.get("state") as SyncState | "ALL") || "ALL");
  const [sort, setSort] = useState<"attention" | "newest">("attention");

  useEffect(() => {
    const s = new URLSearchParams(window.location.search).get("search");
    if (s !== null) setQuery(s);
  }, [window.location.search]);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Order | null>(null);
  const [pendingAction, setPendingAction] = useState<{ order: Order; kind: "replay" | "update" } | null>(null);

  const filteredOrders = useMemo(() =>
    data.orders.filter(o =>
      (filter === "ALL" || o.state === filter) &&
      `${o.id} ${o.customer_name} ${o.customer_email}`.toLowerCase().includes(query.toLowerCase())
    ), [data.orders, filter, query]);
  const orders = useMemo(() => {
    const severity: Record<SyncState, number> = { MISSING: 0, ERROR: 1, MISMATCH: 2, SYNCED: 3, NOT_ELIGIBLE: 4 };
    return [...filteredOrders].sort((a, b) => {
      if (sort === "attention" && severity[a.state] !== severity[b.state]) return severity[a.state] - severity[b.state];
      const dateOrder = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      return sort === "newest" ? -dateOrder : dateOrder;
    });
  }, [filteredOrders, sort]);
  const pageSize = 10;
  const pageCount = Math.max(1, Math.ceil(orders.length / pageSize));
  const visibleOrders = orders.slice((page - 1) * pageSize, page * pageSize);
  const attentionCount = data.counts.MISSING + data.counts.MISMATCH + data.counts.ERROR;
  const statusFilters: Array<{ value: SyncState | "ALL"; label: string; count: number }> = [
    { value: "ALL", label: "All orders", count: data.orders.length },
    { value: "SYNCED", label: "Synced", count: data.counts.SYNCED },
    { value: "MISSING", label: "Missing", count: data.counts.MISSING },
    { value: "MISMATCH", label: "Mismatch", count: data.counts.MISMATCH },
    { value: "ERROR", label: "Error", count: data.counts.ERROR },
    { value: "NOT_ELIGIBLE", label: "Not eligible", count: data.counts.NOT_ELIGIBLE },
  ];

  useEffect(() => { setPage(1); }, [query, filter, sort]);

  const action = async (order: Order, kind: "replay" | "update") => {
    if (kind === "update") { setPendingAction({ order, kind }); return; }
    await runAction(order, kind);
  };
  const runAction = async (order: Order, kind: "replay" | "update") => {
    setBusy(true);
    try {
      notify(kind === "replay" ? "Processing replay..." : "Processing CRM update...");
      const r = await postAction(`orders/${order.id}/${kind}`);
      notify(`${r.message} Verification completed.`);
      await refresh();
      setSelected(null);
    }
    catch (e) { notify(e instanceof Error ? e.message : "Action failed"); }
    finally { setBusy(false); setPendingAction(null); }
  };

  return (
    <>
      {selected && <OrderDetail order={selected} onClose={() => setSelected(null)} />}
      {pendingAction && (
        <ConfirmDialog
          title="Update CRM from WooCommerce?"
          message={`Order #${pendingAction.order.id} will be updated only after the backend confirms it is eligible.`}
          onCancel={() => setPendingAction(null)}
          onConfirm={() => void runAction(pendingAction.order, pendingAction.kind)}
          confirmLabel="Confirm update"
        />
      )}
      {/* -- Metric cards -- */}
      <section className="metric-grid orders-metric-grid">
        <MetricCard label="Total orders" value={data.orders.length} detail="From all datasets" tone="blue" />
        <MetricCard label="Synced orders" value={data.counts.SYNCED} detail="Verified matches" tone="green" />
        <MetricCard label="Needs attention" value={attentionCount} detail="Missing, mismatch or error" tone="amber" />
        <MetricCard label="Not eligible" value={data.counts.NOT_ELIGIBLE} detail="Excluded from sync" tone="purple" />
      </section>

      {/* -- Main Orders Surface Card -- */}
      <section className="orders-surface-card">
        {/* Toolbar with Search, Status Filters, and Sort */}
        <div className="orders-toolbar">
          <div className="orders-search-box">
            <Search size={15} />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search order ID, customer name or email..."
              aria-label="Search orders"
            />
          </div>

          <div className="orders-status-filters" role="group" aria-label="Filter orders">
            {statusFilters.map(status => {
              const isActive = filter === status.value;
              const dotColor = status.value === "SYNCED" ? "#10B981"
                : status.value === "MISSING" ? "#F97316"
                : status.value === "MISMATCH" ? "#8B5CF6"
                : status.value === "ERROR" ? "#EF4444"
                : status.value === "NOT_ELIGIBLE" ? "#64748B" : null;

              return (
                <button
                  key={status.value}
                  className={`orders-filter-pill ${isActive ? "active" : ""} filter-${status.value.toLowerCase()}`}
                  onClick={() => setFilter(status.value)}
                >
                  {dotColor && <span className="pill-dot" style={{ backgroundColor: dotColor }} />}
                  <span className="pill-label">{status.label}</span>
                  <span className="pill-count">{status.count}</span>
                </button>
              );
            })}
          </div>

          <div className="orders-sort-wrap">
            <span className="sort-label">Sort</span>
            <div className="sort-select-wrapper">
              <select
                value={sort}
                onChange={e => setSort(e.target.value as "attention" | "newest")}
                aria-label="Sort orders"
              >
                <option value="attention">Needs attention first</option>
                <option value="newest">Newest first</option>
              </select>
            </div>
          </div>
        </div>

        {/* Order records section heading */}
        <div className="order-records-header">
          <h3>Order records</h3>
          <p>Showing {orders.length} orders (sorted by status: {sort === "attention" ? "needs attention first" : "newest first"})</p>
        </div>

        {/* Orders Table */}
        {data.orders.length === 0 ? (
          <EmptyState title="No orders in this dataset" message="Import WooCommerce orders or select another dataset to begin." />
        ) : orders.length ? (
          <OrderTable
            orders={visibleOrders}
            onSelect={order => {
              const p = new URLSearchParams({ search: query, state: filter });
              window.history.pushState({}, "", `/woocrm/orders/${encodeURIComponent(String(order.id))}?return=${encodeURIComponent(p.toString())}`);
              window.dispatchEvent(new PopStateEvent("popstate"));
            }}
            onAction={action}
            busy={busy}
          />
        ) : (
          <EmptyState title="No matching orders" message="Try a different search or synchronization filter." />
        )}

        {/* Pagination Bar */}
        {orders.length > 0 && (
          <div className="orders-pagination-bar">
            <span className="pagination-info">
              Showing {((page - 1) * pageSize) + 1}-{Math.min(page * pageSize, orders.length)} of {orders.length} orders
            </span>
            <div className="pagination-buttons">
              <button
                className="pagination-nav-btn"
                disabled={page === 1}
                onClick={() => setPage(v => v - 1)}
                aria-label="Previous page"
              >
                <ChevronLeft size={16} />
              </button>
              <button className="pagination-page-active">
                {page}
              </button>
              <button
                className="pagination-nav-btn"
                disabled={page === pageCount}
                onClick={() => setPage(v => v + 1)}
                aria-label="Next page"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}
      </section>
    </>
  );
}

/* ===========================================================
   Order Investigation
=========================================================== */
function valueForField(order: Order, field: string, side: "woo" | "crm"): string {
  const values = side === "woo"
    ? { billing_email: order.customer_email, total: formatMoney(order.total, order.currency), currency: order.currency, order_status: order.status }
    : { billing_email: order.crm?.email || "No CRM record", total: order.crm ? formatMoney(order.crm.total, order.crm.currency) : "No CRM record", currency: order.crm?.currency || "-", order_status: order.crm?.order_status || "-" };
  return values[field as keyof typeof values];
}

export function OrderInvestigationPage({ data, refresh, busy, setBusy, notify, onNavigate, orderId }: PageProps & { orderId: string }) {
  const order = data.orders.find(item => String(item.id) === orderId);
  const [history, setHistory] = useState<OrderEvent[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [actionError, setActionError] = useState("");

  const loadHistory = async () => {
    if (!order) return;
    setLoadingHistory(true);
    try { setHistory(await getOrderHistory(order.id)); }
    catch (e) { setActionError(e instanceof Error ? e.message : "Unable to load attempt history"); }
    finally { setLoadingHistory(false); }
  };
  useEffect(() => { loadHistory(); }, [order?.id]);

  if (!order) return <ErrorState message="That order is not available in this dataset." onRetry={() => onNavigate("/woocrm/orders")} />;

  const action = async (kind: "replay" | "update") => {
    setActionError(""); setBusy(true);
    try { const r = await postAction(`orders/${order.id}/${kind}`); notify(r.message); await refresh(); await loadHistory(); }
    catch (e) { const m = e instanceof Error ? e.message : "Action failed"; setActionError(m); notify(m); await loadHistory(); }
    finally { setBusy(false); setConfirming(false); }
  };

  const labels: [string, string][] = [["billing_email", "Billing email"], ["total", "Total"], ["currency", "Currency"], ["order_status", "Order status"]];
  const explanation: Record<SyncState, string> = {
    MISSING: "WooCommerce has an eligible order, but the CRM has no corresponding record.",
    MISMATCH: "The CRM record exists, but one or more values differ from WooCommerce.",
    ERROR: order.crm?.error_message || "The last CRM attempt failed. Review the error and retry safely.",
    SYNCED: "All tracked values match after a fresh comparison. No action is necessary.",
    NOT_ELIGIBLE: "This order is excluded because its WooCommerce status is not processing or completed.",
  };

  const returnParams = new URLSearchParams(window.location.search).get("return");
  const ordersHref = returnParams ? `/woocrm/orders?${returnParams}` : "/woocrm/orders";
  const completedStep = order.state === "SYNCED" ? 4 : order.state === "NOT_ELIGIBLE" ? 2 : 2;
  const actionTitle = order.state === "SYNCED" ? "Already verified" : order.state === "NOT_ELIGIBLE" ? "Replay unavailable" : order.state === "MISMATCH" ? "Correct CRM values" : order.state === "ERROR" ? "Retry this order" : "Take action";
  const actionDescription = order.state === "MISMATCH" ? "Review the WooCommerce values before applying the correction to CRM." : order.state === "SYNCED" ? "The records match and no action is necessary." : order.state === "NOT_ELIGIBLE" ? "This order cannot be replayed with its current WooCommerce status." : "Replay this order to create or update the CRM record, then verify the result.";
  const fields: [string, string][] = [["id", "Order ID"], ["customer_name", "Customer name"], ...labels];
  const sourceValue = (field: string) => field === "id" ? String(order.id) : field === "customer_name" ? order.customer_name : valueForField(order, field, "woo");
  const destinationValue = (field: string) => field === "id" ? String(order.id) : field === "customer_name" ? (order.crm?.name || "No CRM record") : valueForField(order, field, "crm");

  return (
    <div className="investigation-page investigation-reference">
      <button className="link-button back-link" onClick={() => onNavigate(ordersHref)}>← Back to orders</button>
      <div className="investigation-layout">
        <main className="investigation-main">
          <header className="investigation-hero">
            <div className="investigation-title"><span className="title-marker" /><div><h1>Order #{order.id}</h1><p>{order.customer_name} <span>·</span> {order.customer_email}</p></div></div>
            <div className="investigation-badges"><span className="source-badge"><ShoppingCart size={15} /> WooCommerce order</span><StatusBadge state={order.state} /></div>
            <div className="order-summary"><span>Order date: <b>{formatDate(order.created_at)}</b></span><i /><span>Order total: <b>{formatMoney(order.total, order.currency)}</b></span><i /><span>Status: <b>{order.status}</b></span></div>
          </header>
          <div className="workflow-steps reference-steps">
            {[["Found", "Order exists in WooCommerce"], ["Understood", "Source and CRM were checked"], ["Fix", "Replay to create or correct"], ["Verify", "Confirm the CRM record"]].map(([step, detail], i) => <div className={`workflow-step-pill ${i + 1 <= completedStep ? "active" : ""} ${i + 1 === completedStep + 1 ? "current" : ""}`} key={step}><span>{i + 1}</span><div><b>{step}</b><small>{detail}</small></div></div>)}
          </div>
          <section className={`investigation-explanation state-${order.state.toLowerCase()}`}><AlertTriangle size={25} /><div><h3>What happened?</h3><strong>{explanation[order.state]}</strong><p>{order.state === "MISSING" ? `We searched for an order with ID ${order.id} and a contact with ${order.customer_email}, but no matching record was found.` : "Review the source and destination values below before taking the next step."}</p></div></section>
          <section className="surface comparison-card">
            <div className="comparison-heading"><span className="comparison-icon"><ShieldCheck size={18} /></span><div><h3>Record comparison</h3><p>Compare the key fields used for reconciliation.</p></div></div>
            <div className="investigation-values">
              <div className="value-column value-column--source"><div className="comparison-source-title"><span className="woo-logo">Woo</span><strong>WooCommerce <small>(Source)</small></strong><em>✓ Order found</em></div>{fields.map(([field, label]) => <div className="value-row" key={field}><span>{label}</span><b>{sourceValue(field)}</b></div>)}</div>
              <div className="comparison-arrow"><ArrowRightLeft size={24} /></div>
              <div className="value-column value-column--crm"><div className="comparison-source-title"><span className="crm-logo">●</span><strong>CRM <small>(Destination)</small></strong><em className={order.crm ? "found" : "missing"}>{order.crm ? "✓ Record found" : "● No matching record"}</em></div>{!order.crm && <div className="crm-empty-note"><AlertCircle size={15} /><span><b>No CRM record found.</b> Replay will create a new CRM order and contact using the details from WooCommerce.</span></div>}{fields.map(([field, label]) => <div className={`value-row ${order.state === "MISMATCH" && sourceValue(field) !== destinationValue(field) ? "value-different" : ""}`} key={field}><span>{label}</span><b>{destinationValue(field)}</b></div>)}</div>
            </div>
          </section>
        </main>
        <aside className="investigation-sidebar"><section className="action-card surface"><div className="action-card-title"><RefreshCw size={29} /><div><h3>{actionTitle}</h3><p>{actionDescription}</p></div></div>{order.state === "MISMATCH" ? <button className="button primary action-primary" disabled={busy} onClick={() => setConfirming(true)}><Play size={16} /> Review correction</button> : <button className="button primary action-primary" disabled={busy || order.state === "SYNCED" || order.state === "NOT_ELIGIBLE"} onClick={() => action("replay")}><Play size={16} /> {busy ? "Working…" : order.state === "ERROR" ? "Retry replay" : "Replay and verify"}</button>}<button className="action-link" onClick={loadHistory} disabled={loadingHistory}>Re-check only</button><div className="risk-note"><ShieldCheck size={22} /><div><b>Risk Guard will apply the rules</b><p>The order may be sent and verified, held for review, or blocked if it is not permitted.</p><button onClick={() => onNavigate("/woocrm/risk-guard")}>View Risk Guard rules →</button></div></div>        <div className="safe-note"><CheckCircle2 size={25} /><b>Demo orders are matched by dataset and order ID; concurrent requests are not coordinated.</b></div></section></aside>
      </div>
      {actionError && <div className="action-error"><XCircle size={17} />{actionError}</div>}
      <section className="surface history-panel">
        <div className="section-heading">
          <div><span className="history-title-icon"><Clock3 size={19} /></span><div><h3>Verification and history</h3><p>Check the result of the replay and view past attempts.</p></div></div>
          <button className="link-button" onClick={loadHistory} disabled={loadingHistory}><RefreshCw size={15} /> Refresh</button>
        </div>
        {loadingHistory ? <LoadingState /> : history.length
          ? <div className="event-list">
              {history.map(evt => (
                <div className="event-row" key={evt.id}>
                  <div className={`event-icon event-${evt.outcome}`}>
                    {evt.outcome === "verified" ? <Check size={15} /> : evt.outcome === "failed" ? <XCircle size={15} /> : <Clock3 size={15} />}
                  </div>
                  <div><strong>{evt.event_type.replace("_", " ")}</strong><p>{evt.message}{evt.error_message ? ` ${evt.error_message}` : ""}</p></div>
                  <time>{formatDate(evt.created_at)}</time>
                </div>
              ))}
            </div>
          : <EmptyState title="No attempts recorded" message="Actions and reconciliations performed on this dataset will appear here." />}
      </section>
      {confirming && (
        <div className="confirm-backdrop">
          <div className="confirm-dialog" role="dialog" aria-modal="true">
            <span className="eyebrow">Confirm mismatch correction</span>
            <h3>Update CRM from WooCommerce?</h3>
            <p>These values will change:</p>
            {labels.filter(([field]) => valueForField(order, field, "woo") !== valueForField(order, field, "crm")).map(([field, label]) => (
              <div className="change-row" key={field}>
                <span>{label}</span>
                <div><small>Before</small><b>{valueForField(order, field, "crm")}</b></div>
                <ArrowUpRight size={14} />
                <div><small>After</small><b>{valueForField(order, field, "woo")}</b></div>
              </div>
            ))}
            <div className="dialog-actions">
              <button className="button secondary" onClick={() => setConfirming(false)}>Cancel</button>
              <button className="button primary" disabled={busy} onClick={() => action("update")}>Confirm correction</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ===========================================================
   Customers Page
=========================================================== */
export function CustomersPage({ data, onNavigate }: PageProps) {
  const [query, setQuery] = useState(new URLSearchParams(window.location.search).get("search") || "");
  const [filter, setFilter] = useState<"ALL" | "ATTENTION">("ALL");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    const s = new URLSearchParams(window.location.search).get("search");
    if (s !== null) setQuery(s);
  }, [window.location.search]);
  const customers = [...data.groups]
    .sort((left, right) => right.attention_count - left.attention_count || left.name.localeCompare(right.name) || left.email.localeCompare(right.email))
    .filter(group => filter === "ALL" || group.attention_count > 0)
    .filter(group => `${group.name} ${group.email}`.toLowerCase().includes(query.trim().toLowerCase()));
  const selectedGroup = selected ? data.groups.find(group => group.email === selected) : null;
  const selectedOrders = selected ? data.orders.filter(o => o.state !== "NOT_ELIGIBLE" && o.customer_email.trim().toLowerCase() === selected) : [];

  return (
    <>
      <div className="page-heading customer-page-heading">
        <div className="breadcrumb-line">
          <span>WooCRM Sync</span>
          <ChevronRight size={13} className="breadcrumb-chevron" />
          <span className="breadcrumb-current">Customers</span>
        </div>
        <h2 className="customer-page-title">Customers</h2>
        <p className="customer-page-subtitle">Groups are based on normalized billing email, not a guaranteed identity.</p>
      </div>

      <section className="metric-grid customer-metrics-grid">
        <MetricCard
          label="Total customer groups"
          value={data.eligible_customer_count}
          detail="Unique billing email groups"
          tone="blue"
          icon={Users}
          showArrow={true}
        />
        <MetricCard
          label="CRM contact found"
          value={data.contact_counts.FOUND}
          detail="Groups with a matching CRM contact"
          tone="green"
          icon={Link2}
          showArrow={true}
        />
        <MetricCard
          label="No CRM contact"
          value={data.contact_counts.NOT_FOUND}
          detail="Groups without a CRM contact"
          tone="coral"
          icon={UserX}
          showArrow={true}
        />
        <MetricCard
          label="Needs attention"
          value={data.customer_attention_count}
          detail="Groups with missing, mismatched or error orders"
          tone="amber"
          icon={AlertTriangle}
          showArrow={true}
        />
      </section>

      {data.customer_attention_count > 0 && (
        <div className="customer-alert-banner">
          <div className="alert-banner-left">
            <div className="alert-banner-icon">
              <AlertTriangle size={24} />
            </div>
            <div className="alert-banner-text">
              <strong>
                {data.customer_attention_count} customer group{data.customer_attention_count === 1 ? "" : "s"} needs attention
              </strong>
              <p>
                There is {data.customer_attention_count} group with a recoverable failure. Review it to keep your data in sync.
              </p>
            </div>
          </div>
          <button className="alert-banner-btn" onClick={() => setFilter("ATTENTION")}>
            View group <ArrowRight size={14} />
          </button>
        </div>
      )}

      <section className="surface customer-groups-panel">
        <div className="customer-panel-header">
          <div className="customer-panel-title">
            <h3>Customer groups</h3>
            <p>View customer groups and their synchronization status.</p>
          </div>
          <div className="customer-panel-controls">
            <div className="table-search-box">
              <Search size={15} className="search-icon" />
              <input
                type="text"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search customer name or email..."
                aria-label="Search customer name or email"
              />
            </div>
            <select
              className="sync-state-dropdown"
              value={filter}
              onChange={event => setFilter(event.target.value as "ALL" | "ATTENTION")}
              aria-label="Filter customer groups"
            >
              <option value="ALL">All sync states</option>
              <option value="ATTENTION">Needs attention</option>
            </select>
            <span className="panel-groups-count">{customers.length} groups</span>
          </div>
        </div>

        {customers.length ? (
          <div className="table-wrap">
            <table className="customer-table">
              <thead>
                <tr>
                  <th>CUSTOMER</th>
                  <th>ORDERS</th>
                  <th>SYNCED</th>
                  <th>CRM CONTACT</th>
                  <th>ATTENTION</th>
                  <th>LAST ACTIVITY</th>
                  <th>SYNC STATE</th>
                  <th style={{ width: 40 }}></th>
                </tr>
              </thead>
              <tbody>
                {customers.map(customer => {
                  const hasAttention = customer.sync_state !== "SYNCED" || customer.attention_count > 0;
                  const avatarColorClass = hasAttention ? "avatar-rose" : "avatar-sky";
                  return (
                    <tr
                      key={customer.email}
                      className={`customer-row-item ${selected === customer.email ? "selected-row" : ""}`}
                      onClick={() => setSelected(selected === customer.email ? null : customer.email)}
                    >
                      <td>
                        <div className="customer-identity-cell">
                          <div className={`customer-avatar ${avatarColorClass}`}>
                            {customer.name.charAt(0).toUpperCase()}
                          </div>
                          <div className="customer-name-email">
                            <strong>{customer.name}</strong>
                            <small>{customer.email}</small>
                          </div>
                        </div>
                      </td>
                      <td className="table-num-cell">{customer.order_count}</td>
                      <td className="table-num-cell">{customer.synced_count}</td>
                      <td>
                        {customer.crm_contact_status === "FOUND" ? (
                          <span className="contact-status-pill contact-found-pill">
                            <CheckCircle2 size={13} /> Found
                          </span>
                        ) : customer.crm_contact_status === "NOT_FOUND" ? (
                          <span className="contact-status-pill contact-missing-pill">
                            <XCircle size={13} /> Not found
                          </span>
                        ) : (
                          <span className="contact-status-pill contact-unknown-pill">
                            Unknown
                          </span>
                        )}
                      </td>
                      <td>
                        {customer.attention_count > 0 ? (
                          <span className="attention-error-text">
                            {customer.attention_count} error{customer.attention_count > 1 ? "s" : ""}
                          </span>
                        ) : (
                          <span className="attention-zero-text">0</span>
                        )}
                      </td>
                      <td className="table-date-cell">{formatDate(customer.last_activity)}</td>
                      <td>
                        {customer.sync_state === "SYNCED" ? (
                          <span className="sync-state-pill sync-synced-pill">
                            <CheckCircle2 size={13} /> Synced
                          </span>
                        ) : (
                          <span className="sync-state-pill sync-attention-pill">
                            <AlertCircle size={13} /> Needs attention
                          </span>
                        )}
                      </td>
                      <td className="table-arrow-cell">
                        <ChevronRight size={16} className="row-chevron-icon" />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="No customer groups found" message="Customer groups appear after eligible orders are loaded." />
        )}
        <div className="customer-table-footer">
          Showing 1-{customers.length} of {data.eligible_customer_count} customer groups
        </div>
      </section>

      {selectedGroup && (
        <section className="surface customer-detail">
          <div className="section-heading">
            <div><span className="eyebrow">Customer group</span><h3>{selectedGroup.name}</h3><p>{selectedGroup.email}</p></div>
            <button className="link-button" onClick={() => onNavigate(`/woocrm/orders?customer=${encodeURIComponent(selectedGroup.email)}`)}>Open orders <ArrowUpRight size={14} /></button>
          </div>
          {selectedOrders.length
            ? <div className="mini-order-list">
                {selectedOrders.map(o => (
                  <button className="mini-order-item" key={String(o.id)} onClick={() => onNavigate(`/woocrm/orders/${encodeURIComponent(String(o.id))}?return=customers`)}>
                    <strong>#{o.id}</strong>
                    <span>{formatMoney(o.total, o.currency)}</span>
                    <StatusBadge state={o.state} />
                    <ArrowUpRight size={14} />
                  </button>
                ))}
              </div>
            : <EmptyState title="No eligible orders" message="This grouping has no eligible order records." />}
        </section>
      )}
    </>
  );
}

/* ===========================================================
   Settings Page
=========================================================== */
export function SettingsPage({ data, refresh, busy, setBusy, notify, onNavigate }: PageProps) {
  const [tab, setTab] = useState<"connections" | "risk" | "data">("connections");
  const [connection, setConnection] = useState<"idle" | "verified" | "failed">("idle");
  const [connectionMessage, setConnectionMessage] = useState("");
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(false);
  const [configModal, setConfigModal] = useState<"woo" | "crm" | null>(null);
  const [infoModal, setInfoModal] = useState<"setup" | "docs" | "demo" | null>(null);
  const [wooUrl, setWooUrl] = useState(data.integration.store_url || "");
  const [wooKey, setWooKey] = useState("");
  const [wooSecret, setWooSecret] = useState("");
  const [crmKey, setCrmKey] = useState("");
  const live = data.integration.mode === "live";

  useEffect(() => {
    if (tab !== "data") return;
    setDatasetsLoading(true);
    getDatasets().then(result => setDatasets(result.datasets))
      .catch(error => notify(error instanceof Error ? error.message : "Unable to load datasets"))
      .finally(() => setDatasetsLoading(false));
  }, [tab, notify]);

  const check = async () => {
    setBusy(true);
    try {
      const result = await testConnection();
      setConnection("verified");
      const msg = result.message || "Connection verified successfully.";
      setConnectionMessage(msg);
      notify(msg);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Connection test failed";
      setConnection("failed");
      setConnectionMessage(message);
      notify(message);
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    setBusy(true);
    try {
      const result = await postAction("reset");
      notify(result.message);
      await refresh();
      if (tab === "data") setDatasets((await getDatasets()).datasets);
    } catch (error) {
      notify(error instanceof Error ? error.message : "Reset failed");
    } finally {
      setBusy(false);
    }
  };

  const lastTested = connection === "idle" ? "Never" : connection === "verified" ? "Just now" : "Failed just now";
  const crmProvider = live
    ? data.integration.provider === "hubspot" ? "HubSpot" : data.integration.provider
    : "HubSpot (mock)";

  return (
    <div className="sp-root">
      {/* ─── Pill Tabs Bar ─── */}
      <div className="sp-tabs-bar" role="tablist" aria-label="Settings sections">
        <button
          role="tab"
          aria-selected={tab === "connections"}
          className={`sp-tab-btn ${tab === "connections" ? "sp-tab-btn--active" : ""}`}
          onClick={() => setTab("connections")}
        >
          <Link2 size={15} />
          <span>Connections</span>
        </button>
        <button
          role="tab"
          aria-selected={tab === "risk"}
          className={`sp-tab-btn ${tab === "risk" ? "sp-tab-btn--active" : ""}`}
          onClick={() => setTab("risk")}
        >
          <Shield size={15} />
          <span>Risk Guard rules</span>
        </button>
        <button
          role="tab"
          aria-selected={tab === "data"}
          className={`sp-tab-btn ${tab === "data" ? "sp-tab-btn--active" : ""}`}
          onClick={() => setTab("data")}
        >
          <Database size={15} />
          <span>Data management</span>
        </button>
      </div>

      {/* ─── Connections Tab ─── */}
      {tab === "connections" && (
        <div className="sp-tab-content">
          {/* Main Enclosed Card */}
          <div className="sp-main-card">
            {/* Header: Link icon in soft blue + title + subtitle */}
            <div className="sp-card-header">
              <div className="sp-card-header-icon">
                <Link2 size={19} />
              </div>
              <div className="sp-card-header-text">
                <h2 className="sp-card-title">Connections</h2>
                <p className="sp-card-subtitle">Choose how WooCRM Sync accesses your store and CRM records.</p>
              </div>
            </div>

            {/* Two Connection Cards */}
            <div className="sp-connectors-grid">
              {/* WooCommerce Card */}
              <div className="sp-connector-card">
                <div className="sp-connector-top">
                  <div className="sp-connector-logo sp-connector-logo--woo">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M2.2 4.5h19.6C23 4.5 24 5.5 24 6.7v10.6c0 1.2-1 2.2-2.2 2.2H2.2C1 19.5 0 18.5 0 17.3V6.7C0 5.5 1 4.5 2.2 4.5zm4.8 9c1.2 0 2.2-1.3 2.2-3s-1-3-2.2-3-2.2 1.3-2.2 3 1 3 2.2 3zm6 0c1.2 0 2.2-1.3 2.2-3s-1-3-2.2-3-2.2 1.3-2.2 3 1 3 2.2 3zm6.3-.5c.8 0 1.4-.4 1.7-1.1l-1.3-.8c-.1.3-.3.5-.5.5-.3 0-.6-.2-.6-.6v-.1h2.5c0-.1.1-.3.1-.5 0-1.2-.7-2-1.9-2-1.1 0-1.9.9-1.9 2.2 0 1.4.8 2.4 2 2.4z"/>
                    </svg>
                  </div>
                  <div className="sp-connector-heading">
                    <div className="sp-connector-title-line">
                      <h3 className="sp-connector-title">WooCommerce</h3>
                      <span className="sp-badge-demo">Demo mode</span>
                    </div>
                  </div>
                </div>
                <p className="sp-connector-desc">Using local demo order data.</p>

                <div className="sp-connector-details">
                  <div className="sp-detail-row">
                    <span className="sp-detail-key">Mode</span>
                    <span className="sp-detail-val">{live ? "Live" : "Demo (local data)"}</span>
                  </div>
                  <div className="sp-detail-row">
                    <span className="sp-detail-key">Store URL</span>
                    <span className="sp-detail-val">{live && data.integration.configured ? (data.integration.store_url || "Configured") : "Not configured"}</span>
                  </div>
                  <div className="sp-detail-row">
                    <span className="sp-detail-key">Last tested</span>
                    <span className="sp-detail-val">{lastTested}</span>
                  </div>
                </div>

                <div className="sp-connector-actions">
                  <button className="sp-action-btn" onClick={() => setConfigModal("woo")}>
                    <SettingsIcon size={14} />
                    <span>Configure connection</span>
                  </button>
                  <button className="sp-action-btn" onClick={() => void check()} disabled={busy}>
                    <Radio size={14} className={busy ? "spin" : ""} />
                    <span>{busy ? "Testing..." : "Test connection"}</span>
                  </button>
                </div>
              </div>

              {/* CRM (HubSpot) Card */}
              <div className="sp-connector-card">
                <div className="sp-connector-top">
                  <div className="sp-connector-logo sp-connector-logo--crm">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M18.8 8.4V6.2c.7-.4 1.2-1.1 1.2-2 0-1.3-1.1-2.4-2.4-2.4s-2.4 1.1-2.4 2.4c0 .9.5 1.6 1.2 2v2.2c-.8.3-1.5.8-2 1.4L8.7 6.4c.1-.3.1-.6.1-.9 0-1.8-1.5-3.3-3.3-3.3S2.2 3.7 2.2 5.5 3.7 8.8 5.5 8.8c.6 0 1.2-.2 1.7-.5l5.6 3.4c-.2.5-.3 1.1-.3 1.8 0 .6.1 1.2.3 1.7L7.2 18.6c-.5-.3-1.1-.5-1.7-.5-1.8 0-3.3 1.5-3.3 3.3s1.5 3.3 3.3 3.3 3.3-1.5 3.3-3.3c0-.3 0-.6-.1-.9l5.7-3.4c.5.6 1.2 1.1 2 1.4v2.2c-.7.4-1.2 1.1-1.2 2 0 1.3 1.1 2.4 2.4 2.4s2.4-1.1 2.4-2.4c0-.9-.5-1.6-1.2-2v-2.2c1.7-.6 3-2.2 3-4.1s-1.3-3.5-3-4.1zM17.6 3.6c.5 0 .9.4.9.9s-.4.9-.9.9-.9-.4-.9-.9.4-.9.9-.9zM5.5 7.1c-.9 0-1.6-.7-1.6-1.6s.7-1.6 1.6-1.6 1.6.7 1.6 1.6-.7 1.6-1.6 1.6zm0 15.1c-.9 0-1.6-.7-1.6-1.6s.7-1.6 1.6-1.6 1.6.7 1.6 1.6-.7 1.6-1.6 1.6zm12.1-4c-.5 0-.9-.4-.9-.9s.4-.9.9-.9.9.4.9.9-.4.9-.9.9zm0-5.4c-1.3 0-2.4-1.1-2.4-2.4s1.1-2.4 2.4-2.4 2.4 1.1 2.4 2.4-1.1 2.4-2.4 2.4z"/>
                    </svg>
                  </div>
                  <div className="sp-connector-heading">
                    <div className="sp-connector-title-line">
                      <h3 className="sp-connector-title">CRM (HubSpot)</h3>
                      <span className="sp-badge-demo">Demo mode</span>
                    </div>
                  </div>
                </div>
                <p className="sp-connector-desc">Using local demo CRM records.</p>

                <div className="sp-connector-details">
                  <div className="sp-detail-row">
                    <span className="sp-detail-key">Mode</span>
                    <span className="sp-detail-val">{live ? "Live" : "Demo (local data)"}</span>
                  </div>
                  <div className="sp-detail-row">
                    <span className="sp-detail-key">Provider</span>
                    <span className="sp-detail-val">{crmProvider}</span>
                  </div>
                  <div className="sp-detail-row">
                    <span className="sp-detail-key">Last tested</span>
                    <span className="sp-detail-val">{lastTested}</span>
                  </div>
                </div>

                <div className="sp-connector-actions">
                  <button className="sp-action-btn" onClick={() => setConfigModal("crm")}>
                    <SettingsIcon size={14} />
                    <span>Configure connection</span>
                  </button>
                  <button className="sp-action-btn" onClick={() => void check()} disabled={busy}>
                    <Radio size={14} className={busy ? "spin" : ""} />
                    <span>{busy ? "Testing..." : "Test connection"}</span>
                  </button>
                </div>
              </div>
            </div>

            {/* Test connection feedback status */}
            {connectionMessage && (
              <div className={`sp-test-feedback ${connection === "verified" ? "sp-test-feedback--success" : "sp-test-feedback--error"}`}>
                {connection === "verified" ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
                <span>{connectionMessage}</span>
              </div>
            )}

            {/* Info Banner */}
            <div className="sp-info-bar">
              <div className="sp-info-bar-left">
                <div className="sp-info-bar-icon">
                  <Info size={16} />
                </div>
                <div className="sp-info-bar-text">
                  <strong className="sp-info-bar-title">Live connections require a store URL and API credentials.</strong>
                  <p className="sp-info-bar-desc">Demo Mode continues to use local records. No external data is being accessed.</p>
                </div>
              </div>
              <button className="sp-info-bar-btn" onClick={() => setInfoModal("setup")}>
                <span>View setup guide</span>
                <ArrowUpRight size={13} />
              </button>
            </div>

            {/* Webhook Receiver Strip */}
            <div className="sp-webhook-strip">
              <div className="sp-webhook-strip-left">
                <div className="sp-webhook-strip-icon">
                  <GitFork size={18} />
                </div>
                <div>
                  <div className="sp-webhook-strip-heading">
                    <h4 className="sp-webhook-title">Webhook receiver</h4>
                    <span className="sp-badge-planned">Planned</span>
                  </div>
                  <p className="sp-webhook-desc">Receive signed webhooks from WooCommerce for real-time updates.</p>
                </div>
              </div>
              <div className="sp-webhook-strip-meta">
                <div className="sp-webhook-meta-col">
                  <span className="sp-webhook-meta-lbl">Signing secret</span>
                  <span className="sp-webhook-meta-txt">Not set</span>
                </div>
                <div className="sp-webhook-meta-col">
                  <span className="sp-webhook-meta-lbl">Last event</span>
                  <span className="sp-webhook-meta-txt">None</span>
                </div>
              </div>
              <button className="sp-btn-planned" disabled>
                Configure (planned)
              </button>
            </div>

            {/* Demo Status Banner */}
            <div className="sp-demo-alert">
              <CheckCircle2 size={16} className="sp-demo-alert-icon" />
              <span className="sp-demo-alert-text">
                You are currently using local demo data. Configure your connectors above when you are ready to use live data.
              </span>
            </div>
          </div>

          {/* ─── Bottom Two Helper Cards ─── */}
          <div className="sp-bottom-grid">
            {/* Card 1: Need help? */}
            <div className="sp-help-box">
              <div className="sp-help-icon-circle">
                <HelpCircle size={18} />
              </div>
              <h4 className="sp-help-title">Need help?</h4>
              <p className="sp-help-desc">
                Learn how to connect WooCommerce and HubSpot, test your connections and switch from Demo Mode to live.
              </p>
              <button className="sp-help-btn" onClick={() => setInfoModal("docs")}>
                <span>View documentation</span>
                <ArrowUpRight size={13} />
              </button>
            </div>

            {/* Card 2: About Demo Mode */}
            <div className="sp-help-box">
              <div className="sp-help-icon-circle">
                <Database size={18} />
              </div>
              <h4 className="sp-help-title">About Demo Mode</h4>
              <p className="sp-help-desc">
                Demo Mode uses deterministic local records and requires no credentials. It's safe for testing and onboarding.
              </p>
              <button className="sp-help-btn sp-help-btn--dark" onClick={() => setInfoModal("demo")}>
                <span>Learn more</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── Risk Guard rules tab ─── */}
      {tab === "risk" && (
        <div className="sp-tab-content">
          <RiskGuardSettingsPanel notify={notify} />
        </div>
      )}

      {/* ─── Data management tab ─── */}
      {tab === "data" && (
        <div className="sp-tab-content">
          <section className="surface settings-section">
            <div className="settings-title">
              <div className="settings-icon"><Database size={18} /></div>
              <div>
                <h3>Datasets</h3>
                <p>Read-only inventory from the backend. Imports are isolated by dataset.</p>
              </div>
            </div>
            {datasetsLoading ? (
              <LoadingState />
            ) : (
              <div className="dataset-list">
                {datasets.map(dataset => (
                  <div className="dataset-row" key={dataset.name}>
                    <div>
                      <strong>{dataset.name}</strong>
                      <span>{dataset.source} · {dataset.environment}</span>
                    </div>
                    <div className="dataset-counts">
                      <span>{dataset.order_count} orders</span>
                      <span>{dataset.crm_record_count} CRM records</span>
                      <span>{dataset.customer_count} customers</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <button className="button secondary" style={{ marginTop: 16 }} onClick={() => onNavigate("/woocrm/import")}>
              Open import
            </button>
          </section>

          <section className="surface settings-section danger-section" style={{ marginTop: 20 }}>
            <div className="settings-title">
              <div className="settings-icon danger"><ShieldAlert size={18} /></div>
              <div>
                <h3>Demo data reset</h3>
                <p>Reset only the default demo dataset and its local history.</p>
              </div>
              <ConfirmAction label={busy ? "Resetting..." : "Reset demo data"} onConfirm={reset} />
            </div>
            <p className="muted-copy" style={{ marginTop: 10, marginLeft: 50 }}>
              This deletes and recreates default orders, CRM mock records, customers, sync runs, order events and Risk Guard evaluations. Imported datasets are preserved; external CRM records are untouched.
            </p>
          </section>
        </div>
      )}

      {/* ─── Modal Dialog: Configure Connector ─── */}
      {configModal && (
        <div className="sp-modal-overlay" onClick={() => setConfigModal(null)}>
          <div className="sp-modal-card" onClick={e => e.stopPropagation()}>
            <div className="sp-modal-header">
              <div className="sp-modal-header-left">
                <div className={`sp-modal-logo ${configModal === "woo" ? "sp-connector-logo--woo" : "sp-connector-logo--crm"}`}>
                  <SettingsIcon size={18} />
                </div>
                <div>
                  <h3>Configure {configModal === "woo" ? "WooCommerce" : "HubSpot CRM"}</h3>
                  <p>Update credentials to enable live synchronization.</p>
                </div>
              </div>
              <button className="sp-modal-close" onClick={() => setConfigModal(null)} aria-label="Close modal">
                <X size={18} />
              </button>
            </div>

            <div className="sp-modal-body">
              {configModal === "woo" ? (
                <div className="sp-form-group-list">
                  <div className="sp-form-group">
                    <label>Store URL</label>
                    <input
                      type="url"
                      placeholder="https://example.com"
                      value={wooUrl}
                      onChange={e => setWooUrl(e.target.value)}
                    />
                    <small>Include protocol (https://) for your WordPress / WooCommerce store.</small>
                  </div>
                  <div className="sp-form-group">
                    <label>Consumer Key</label>
                    <input
                      type="password"
                      placeholder="ck_xxxxxxxxxxxxxxxxxxxxxxxx"
                      value={wooKey}
                      onChange={e => setWooKey(e.target.value)}
                    />
                    <small>Generated in WooCommerce &gt; Settings &gt; Advanced &gt; REST API.</small>
                  </div>
                  <div className="sp-form-group">
                    <label>Consumer Secret</label>
                    <input
                      type="password"
                      placeholder="cs_xxxxxxxxxxxxxxxxxxxxxxxx"
                      value={wooSecret}
                      onChange={e => setWooSecret(e.target.value)}
                    />
                  </div>
                </div>
              ) : (
                <div className="sp-form-group-list">
                  <div className="sp-form-group">
                    <label>CRM Provider</label>
                    <select defaultValue="hubspot" disabled>
                      <option value="hubspot">HubSpot (REST v3)</option>
                    </select>
                  </div>
                  <div className="sp-form-group">
                    <label>Private App Access Token</label>
                    <input
                      type="password"
                      placeholder="pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                      value={crmKey}
                      onChange={e => setCrmKey(e.target.value)}
                    />
                    <small>Requires scopes: crm.objects.contacts.write, crm.objects.deals.write.</small>
                  </div>
                </div>
              )}
            </div>

            <div className="sp-modal-footer">
              <button className="sp-btn-secondary" onClick={() => setConfigModal(null)}>Cancel</button>
              <span>Live connection: planned</span>
              <button className="sp-btn-primary" disabled>
                Save configuration
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── Modal Dialog: Information / Guide ─── */}
      {infoModal && (
        <div className="sp-modal-overlay" onClick={() => setInfoModal(null)}>
          <div className="sp-modal-card" onClick={e => e.stopPropagation()}>
            <div className="sp-modal-header">
              <div className="sp-modal-header-left">
                <div className="sp-modal-logo sp-modal-logo--blue">
                  {infoModal === "setup" && <ArrowUpRight size={18} />}
                  {infoModal === "docs" && <HelpCircle size={18} />}
                  {infoModal === "demo" && <Database size={18} />}
                </div>
                <div>
                  <h3>
                    {infoModal === "setup" && "Connector Setup Guide"}
                    {infoModal === "docs" && "WooCRM Sync Documentation"}
                    {infoModal === "demo" && "About Demo & Sandbox Mode"}
                  </h3>
                  <p>
                    {infoModal === "setup" && "Step-by-step instructions for connecting live endpoints"}
                    {infoModal === "docs" && "Architecture, reconciliation, and risk guard overview"}
                    {infoModal === "demo" && "How deterministic demo mode keeps tests isolated"}
                  </p>
                </div>
              </div>
              <button className="sp-modal-close" onClick={() => setInfoModal(null)} aria-label="Close modal">
                <X size={18} />
              </button>
            </div>

            <div className="sp-modal-body">
              {infoModal === "setup" && (
                <div className="sp-info-content">
                  <div className="sp-info-step">
                    <span className="sp-step-num">1</span>
                    <div>
                      <strong>Generate WooCommerce Keys</strong>
                      <p>In your WordPress admin, go to WooCommerce &gt; Settings &gt; Advanced &gt; REST API. Create a key with Read/Write permissions.</p>
                    </div>
                  </div>
                  <div className="sp-info-step">
                    <span className="sp-step-num">2</span>
                    <div>
                      <strong>HubSpot Private App Token</strong>
                      <p>In HubSpot Settings &gt; Integrations &gt; Private Apps, create a token with contacts and deals read/write scopes.</p>
                    </div>
                  </div>
                  <div className="sp-info-step">
                    <span className="sp-step-num">3</span>
                    <div>
                      <strong>Configure Environment</strong>
                      <p>Add <code>WOO_STORE_URL</code>, <code>WOO_CONSUMER_KEY</code>, <code>WOO_CONSUMER_SECRET</code>, and <code>HUBSPOT_ACCESS_TOKEN</code> to your backend environment.</p>
                    </div>
                  </div>
                </div>
              )}

              {infoModal === "docs" && (
                <div className="sp-info-content">
                  <p>WooCRM Sync synchronizes orders, customer profiles, and deal pipelines between WooCommerce and HubSpot in real time.</p>
                  <ul>
                    <li><strong>Risk Guard:</strong> Evaluates order size anomalies, billing mismatches, and status drift before syncing.</li>
                    <li><strong>Reconciliation:</strong> Multi-pass identity matching aligns guest checkouts with registered CRM contacts.</li>
                    <li><strong>Safety:</strong> Critical state changes require operator confirmation or rule overrides.</li>
                  </ul>
                </div>
              )}

              {infoModal === "demo" && (
                <div className="sp-info-content">
                  <p>Demo Mode operates purely on synthetic, deterministic datasets without accessing live external stores or CRM endpoints.</p>
                  <ul>
                    <li>Deterministic seed orders with edge-case statuses (processing, completed, refunded, failed).</li>
                    <li>Isolated sandbox datasets allow testing edge cases without impacting production customers.</li>
                    <li>One-click reset restores the benchmark demo state anytime.</li>
                  </ul>
                </div>
              )}
            </div>

            <div className="sp-modal-footer">
              <button className="sp-btn-primary" onClick={() => setInfoModal(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}



/* --- Risk Guard Settings Panel --------------------------- */
function RiskGuardSettingsPanel({ notify }: { notify: (message: string) => void }) {
  const [settings, setSettings] = useState<RiskSettings | null>(null);
  const [draft, setDraft] = useState<RiskSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getRiskSettings()
      .then(v => { setSettings(v); setDraft(v); })
      .catch(r => setError(r instanceof Error ? r.message : "Unable to load Risk Guard settings"))
      .finally(() => setLoading(false));
  }, []);

  const update = (key: keyof RiskSettings, value: string) => {
    if (!draft) return;
    setDraft({ ...draft, [key]: key === "newer_crm_policy" || key === "missing_timestamp_policy" ? value : Number(value) });
  };
  const changed = Boolean(settings && draft && JSON.stringify(settings) !== JSON.stringify(draft));
  const valid = Boolean(draft
    && Number.isFinite(draft.absolute_total_change) && draft.absolute_total_change >= 0
    && Number.isFinite(draft.percentage_total_change) && draft.percentage_total_change >= 0
    && Number.isInteger(draft.batch_change_limit) && draft.batch_change_limit >= 1);
  const save = async () => {
    if (!draft || !valid) {
      setError("Thresholds must be non-negative and the batch limit must be at least 1."); return;
    }
    setSaving(true); setError("");
    try { const r = await updateRiskSettings(draft); setSettings(r); setDraft(r); notify("Risk Guard settings saved"); }
    catch (r) { setError(r instanceof Error ? r.message : "Unable to save Risk Guard settings"); }
    finally { setSaving(false); }
  };

  return (
    <section className="surface risk-settings-panel">
      <div className="section-heading">
        <div><span className="eyebrow">Safety controls</span><h3>Risk Guard settings</h3><p style={{ fontSize: 11, color: "var(--muted)", marginTop: 3 }}>Configure thresholds used by backend evaluations before CRM writes.</p></div>
        <ShieldAlert className="icon-purple" size={22} />
      </div>
      {loading ? <LoadingState /> : error && !draft ? <ErrorState message={error} onRetry={() => window.location.reload()} /> : draft ? (
        <div style={{ padding: "0 22px 22px" }}>
          <div className="settings-rule-group">
            <h4>Eligible WooCommerce statuses</h4>
            <p>Only these configured statuses participate in reconciliation. Status changes are read-only because the backend does not expose a status management endpoint.</p>
            <div className="tag-list"><span>processing</span><span>completed</span></div>
          </div>
          <div className="settings-rule-group">
            <h4>Review thresholds and policies</h4>
            <p>Either configured total threshold can trigger review: the absolute change or the percentage change. Values are applied by the backend risk evaluator after saving.</p>
          <div className="settings-form-grid">
            <label>Absolute total change<input type="number" min="0" step="0.01" value={draft.absolute_total_change} onChange={e => update("absolute_total_change", e.target.value)} /><small>Flag changes at or above this amount.</small></label>
            <label>Percentage total change<input type="number" min="0" step="0.01" value={draft.percentage_total_change} onChange={e => update("percentage_total_change", e.target.value)} /><small>Flag changes at or above this percentage.</small></label>
            <label>Batch change limit<input type="number" min="1" step="1" value={draft.batch_change_limit} onChange={e => update("batch_change_limit", e.target.value)} /><small>Maximum changes before batch review.</small></label>
            <label>Newer CRM value<select value={draft.newer_crm_policy} onChange={e => update("newer_crm_policy", e.target.value)}><option value="review">Require review</option><option value="block">Block</option></select><small>Protect newer CRM records.</small></label>
            <label>Missing timestamps<select value={draft.missing_timestamp_policy} onChange={e => update("missing_timestamp_policy", e.target.value)}><option value="review">Require review</option><option value="allow">Allow</option></select><small>Policy when comparison timestamps are unavailable.</small></label>
          </div>
          </div>
          {error && <div className="feedback error-feedback" role="alert">{error}</div>}
          <div className="settings-panel-actions">
            <span className="muted-copy">{settings ? "Settings are validated by the backend." : ""}</span>
            <button className="button primary" onClick={() => void save()} disabled={saving || !changed || !valid}>{saving ? "Saving..." : "Save Risk Guard settings"}</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

/* ===========================================================
   Risk Guard Page
=========================================================== */
export function RiskGuardPage({ notify, onNavigate }: PageProps) {
  const [evaluations, setEvaluations] = useState<RiskEvaluation[]>([]);
  const [tab, setTab] = useState<"review" | "blocked" | "approved" | "history">("review");
  const [ruleFilter, setRuleFilter] = useState("ALL");
  const [datasetFilter, setDatasetFilter] = useState("ALL");
  const [sort, setSort] = useState("review");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [pendingAction, setPendingAction] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState("");

  const load = async () => {
    try { setError(""); setEvaluations((await getRiskEvaluations()).evaluations); }
    catch (r) { setError(r instanceof Error ? r.message : "Unable to load risk guard"); }
  };
  useEffect(() => { load(); }, []);

  const counts = {
    review: evaluations.filter(item => item.risk_status === "REVIEW_REQUIRED" && !item.approved && item.outcome !== "rejected").length,
    blocked: evaluations.filter(item => item.risk_status === "BLOCKED").length,
    approved: evaluations.filter(item => item.approved && item.outcome === "approved").length,
    history: evaluations.filter(item => item.outcome === "rejected").length,
  };
  const visible = useMemo(() => evaluations.filter(item => {
    if (tab === "review") return item.risk_status === "REVIEW_REQUIRED" && !item.approved && item.outcome !== "rejected";
    if (tab === "blocked") return item.risk_status === "BLOCKED";
    if (tab === "approved") return item.approved && item.outcome === "approved";
    return item.outcome === "rejected";
  }).filter(item => ruleFilter === "ALL" || item.rule_ids.includes(ruleFilter))
    .filter(item => datasetFilter === "ALL" || item.dataset === datasetFilter)
    .sort((a, b) => sort === "newest" ? Date.parse(b.evaluated_at) - Date.parse(a.evaluated_at) : b.id - a.id), [datasetFilter, evaluations, ruleFilter, sort, tab]);
  const selected = visible.find(item => item.id === selectedId) || visible[0] || null;
  useEffect(() => { if (visible.length && !visible.some(item => item.id === selectedId)) setSelectedId(visible[0].id); }, [selectedId, visible]);
  const review = async (action: "approve" | "reject") => {
    if (!selected) return;
    try { await reviewRiskEvaluation(selected.id, action); notify(`Decision ${action}d`); setPendingAction(null); await load(); }
    catch (r) { notify(r instanceof Error ? r.message : "Risk review failed"); }
  };
  const valueLabel = (value: unknown, key: "total" | "currency") => {
    if (!value || typeof value !== "object") return "Unavailable";
    const raw = (value as Record<string, unknown>)[key];
    if (raw === null || raw === undefined || raw === "") return "Unavailable";
    return key === "total" && typeof raw === "number" ? formatMoney(raw, String((value as Record<string, unknown>).currency || "")) : String(raw);
  };
  const statusLabel = (item: RiskEvaluation) => item.outcome === "rejected" ? "Rejected" : item.approved ? "Approved" : item.risk_status === "BLOCKED" ? "Blocked" : "Needs review";
  const evidence = selected?.evidence && typeof selected.evidence === "object" ? selected.evidence as Record<string, unknown> : {};
  const canApprove = selected?.risk_status === "REVIEW_REQUIRED" && !selected.approved && selected.outcome !== "rejected";

  return (
    <div className="risk-guard-page">
      {pendingAction && selected && <ConfirmDialog title={pendingAction === "approve" ? "Approve this change?" : "Reject this change?"} message={pendingAction === "approve" ? "This records approval for the proposed change. A CRM write is not claimed until the backend confirms it." : "Reject this proposed change?"} onCancel={() => setPendingAction(null)} onConfirm={() => void review(pendingAction)} confirmLabel={pendingAction === "approve" ? "Approve change" : "Reject change"} />}

      {/* Progress + Explanation strip */}
      <div className="risk-summary-grid">
        <div className="risk-progress-card">
          <div className="risk-summary-title">
            <h3>{evaluations.length - counts.review} of {evaluations.length} decisions reviewed</h3>
            <strong>{evaluations.length ? Math.round(((evaluations.length - counts.review) / evaluations.length) * 100) : 0}%</strong>
          </div>
          <div className="risk-progress-track">
            <span style={{ width: `${evaluations.length ? ((evaluations.length - counts.review) / evaluations.length) * 100 : 0}%` }} />
          </div>
        </div>
        <div className="risk-explanation-card">
          <div className="risk-explanation-icon"><Info size={16} /></div>
          <p>These checks help prevent incorrect or risky data from being written to your CRM. They are not fraud findings.</p>
        </div>
      </div>

      {/* Tab pills */}
      <div className="risk-tabs-pills" role="tablist">
        {([ ["review", "Needs review", counts.review], ["blocked", "Blocked", counts.blocked], ["approved", "Approved", counts.approved], ["history", "History", counts.history] ] as const).map(([value, label, count]) => (
          <button key={value} className={`risk-tab-pill ${tab === value ? "active" : ""}`} onClick={() => setTab(value)} role="tab" aria-selected={tab === value}>
            {label} ({count})
          </button>
        ))}
      </div>

      {/* Filter toolbar */}
      <div className="risk-filter-toolbar">
        <div className="risk-filter-group">
          <select className="risk-select" value={ruleFilter} onChange={e => setRuleFilter(e.target.value)} aria-label="Filter by rule">
            <option value="ALL">All rule types</option>
            {[...new Set(evaluations.flatMap(item => item.rule_ids))].map(rule => <option key={rule} value={rule}>{rule.replace(/_/g, " ")}</option>)}
          </select>
          <select className="risk-select" value={datasetFilter} onChange={e => setDatasetFilter(e.target.value)} aria-label="Filter by dataset">
            <option value="ALL">All datasets</option>
            {[...new Set(evaluations.map(item => String(item.dataset || "default")))].map(dataset => <option key={dataset} value={dataset}>{dataset}</option>)}
          </select>
        </div>
        <div className="risk-sort-group">
          <span className="risk-sort-label">Sort</span>
          <select className="risk-select" value={sort} onChange={e => setSort(e.target.value)} aria-label="Sort decisions">
            <option value="review">Needs review first</option>
            <option value="newest">Newest first</option>
          </select>
          <button className="button secondary" onClick={() => void load()}><RefreshCw size={14} /> Refresh</button>
        </div>
      </div>

      {/* Main inbox layout */}
      {error ? <ErrorState message={error} onRetry={load} /> : (
        <div className="risk-inbox-layout">
          {/* Left: decision cards */}
          <div className="risk-cards-column">
            {visible.length ? visible.map(item => {
              const badgeClass = item.outcome === "rejected" ? "approved" : item.approved ? "approved" : item.risk_status === "BLOCKED" ? "blocked" : "needs-review";
              const isSelected = selected?.id === item.id;
              return (
                <button key={item.id} className={`risk-card-item ${isSelected ? "selected" : ""}`} onClick={() => setSelectedId(item.id)}>
                  <div className="risk-card-top-row">
                    <span className={`risk-badge ${badgeClass}`}>
                      <span className="risk-badge-dot" />
                      {statusLabel(item)}
                    </span>
                    <span className="risk-card-time">{formatDate(item.evaluated_at)}</span>
                  </div>
                  <div className="risk-card-mid-row">
                    <div className="risk-card-id-block">
                      <strong>{item.order_id === "__BATCH__" ? "Whole batch" : `#${item.order_id}`}</strong>
                      <span className="risk-card-date-sub">{item.dataset || "default"} dataset</span>
                    </div>
                    <div className="risk-card-info-block">
                      <p className="risk-card-reason">{item.explanation[0] || "Risk rule requires attention."}</p>
                      <span className="risk-rule-pill">{item.rule_ids[0] || "UNAVAILABLE"}</span>
                    </div>
                    <ChevronRight size={16} className="risk-card-chevron" />
                  </div>
                  {item.order_id === "__BATCH__" ? (
                    <div className="risk-card-batch-box"><Info size={12} /> Batch evaluation - multiple orders affected</div>
                  ) : (
                    <div className="risk-card-compare-strip">
                      <div className="risk-mini-box">
                        <strong>{valueLabel(item.existing_value, "total")}</strong>
                        <span>WooCommerce total</span>
                      </div>
                      <ChevronRight size={14} className="risk-card-arrow" />
                      <div className="risk-mini-box proposed">
                        <strong>{valueLabel(item.proposed_value, "total")}</strong>
                        <span>Proposed CRM total</span>
                      </div>
                    </div>
                  )}
                </button>
              );
            }) : <EmptyState title="No decisions in this view" message="Risk evaluations appear when a proposed CRM write is evaluated." />}
          </div>

          {/* Right: detail panel */}
          <div className="risk-detail-card">
            {selected ? (
              <>
                <div className="risk-detail-top-nav">
                  <span className={`risk-badge ${selected.outcome === "rejected" ? "approved" : selected.approved ? "approved" : selected.risk_status === "BLOCKED" ? "blocked" : "needs-review"}`}>
                    <span className="risk-badge-dot" />
                    {statusLabel(selected)}
                  </span>
                  <div className="risk-detail-top-actions">
                    {selected.order_id !== "__BATCH__" && (
                      <button className="risk-view-order-link" onClick={() => onNavigate(`/woocrm/orders/${encodeURIComponent(selected.order_id)}`)}>
                        View order <ArrowUpRight size={13} />
                      </button>
                    )}
                  </div>
                </div>
                <div className="risk-detail-title-block">
                  <h3>{selected.order_id === "__BATCH__" ? "Whole batch" : `Order #${selected.order_id}`}</h3>
                  <p>{formatDate(selected.evaluated_at)} - Dataset: {selected.dataset || "default"}</p>
                </div>
                <p className="risk-section-heading">What is changing?</p>
                <div className="risk-comparison-grid">
                  <div className="risk-comp-box">
                    <div className="risk-comp-icon-woo">Woo</div>
                    <div className="risk-comp-info">
                      <span className="risk-comp-label">WooCommerce (current)</span>
                      <span className="risk-comp-val">{valueLabel(selected.existing_value, "total")}</span>
                      <span className="risk-comp-sub">Total ({valueLabel(selected.existing_value, "currency")})</span>
                    </div>
                  </div>
                  <ArrowRight size={18} className="risk-comp-arrow-divider" />
                  <div className="risk-comp-box proposed">
                    <div className="risk-comp-icon-crm"><ShieldAlert size={16} /></div>
                    <div className="risk-comp-info">
                      <span className="risk-comp-label">Proposed for CRM</span>
                      <div className="risk-comp-val-row">
                        <span className="risk-comp-val red">{valueLabel(selected.proposed_value, "total")}</span>
                      </div>
                      <span className="risk-comp-sub">Total ({valueLabel(selected.proposed_value, "currency")})</span>
                    </div>
                  </div>
                </div>
                <div className="risk-flagged-callout-box">
                  <AlertCircle size={18} className="risk-flagged-icon-wrap" />
                  <div className="risk-flagged-content">
                    <div className="risk-flagged-head">
                      <strong>Why this was flagged</strong>
                      {selected.rule_ids.length > 0 && <span className="risk-rule-pill">{selected.rule_ids[0]}</span>}
                    </div>
                    <p>{selected.explanation[0] || "The backend did not provide an explanation."}</p>
                    <button className="risk-link-arrow" onClick={() => onNavigate("/woocrm/settings")}>
                      View rule in Settings <ArrowUpRight size={12} />
                    </button>
                  </div>
                </div>
                <div className="risk-details-columns">
                  <div className="risk-dl-wrap">
                    <h4>Details</h4>
                    <div className="risk-dl-list">
                      <div className="risk-dl-row"><span>Order ID</span><strong>{selected.order_id === "__BATCH__" ? "Whole batch" : selected.order_id}</strong></div>
                      <div className="risk-dl-row"><span>Field</span><strong>{selected.field || "Unavailable"}</strong></div>
                      <div className="risk-dl-row"><span>Existing value</span><strong>{valueLabel(selected.existing_value, "total")}</strong></div>
                      <div className="risk-dl-row"><span>Proposed value</span><strong>{valueLabel(selected.proposed_value, "total")}</strong></div>
                      <div className="risk-dl-row"><span>Change</span><strong className="red-text">{typeof evidence.absolute_difference === "number" ? formatMoney(evidence.absolute_difference as number) : typeof evidence.percentage_difference === "number" ? `${Number(evidence.percentage_difference).toFixed(1)}%` : "Unavailable"}</strong></div>
                      <div className="risk-dl-row"><span>Rule threshold</span><strong>{evidence.absolute_threshold !== undefined ? formatMoney(Number(evidence.absolute_threshold)) : evidence.configured_limit !== undefined ? `${evidence.configured_limit} changes` : "Unavailable"}</strong></div>
                    </div>
                  </div>
                  <div className="risk-side-cards">
                    <div className="risk-side-card">
                      <div className="risk-side-card-title"><Info size={13} /> Additional context</div>
                      <p>{selected.order_id === "__BATCH__" ? `${evidence.proposed_change_count ?? "Unavailable"} proposed changes; configured limit: ${evidence.configured_limit ?? "Unavailable"}.` : "The proposed value is more than 3 times the current value. This could be due to a data entry error or an unexpected bulk update."}</p>
                    </div>
                    <div className="risk-side-card">
                      <div className="risk-side-card-title"><ShieldCheck size={13} /> Reconciliation status</div>
                      <div className="risk-mismatch-pill"><span className="risk-mismatch-dot" /> Mismatch</div>
                      <p>WooCommerce and CRM totals are different.</p>
                      {selected.order_id !== "__BATCH__" && (
                        <button className="risk-side-link" onClick={() => onNavigate(`/woocrm/orders/${encodeURIComponent(selected.order_id)}`)}>View in Orders <ArrowUpRight size={11} /></button>
                      )}
                    </div>
                  </div>
                </div>
                <div className="risk-actions-container">
                  {canApprove ? (
                    <>
                      <div className="risk-buttons-row">
                        <button className="risk-btn-approve-primary" onClick={() => setPendingAction("approve")}>
                          <Check size={15} /> Approve change <ChevronDown size={13} className="risk-split-chevron" />
                        </button>
                        <button className="risk-btn-reject-secondary" onClick={() => setPendingAction("reject")}>
                          <XCircle size={15} /> Reject
                        </button>
                      </div>
                      <p className="risk-actions-footer-copy">Approval will write the proposed value to your CRM and then verify the result.</p>
                    </>
                  ) : (
                    <div className="risk-blocked-message-box">
                      <ShieldAlert size={16} />
                      <strong>{selected.risk_status === "BLOCKED" ? "Blocked by rule" : statusLabel(selected)}</strong>
                      <span>{selected.risk_status === "BLOCKED" ? "This decision cannot be approved." : "This decision is already complete."}</span>
                    </div>
                  )}
                </div>
              </>
            ) : <EmptyState title="Select a decision" message="Choose a risk evaluation to inspect its details." />}
          </div>
        </div>
      )}
    </div>
  );
}

/* ===========================================================
   Import Page
=========================================================== */
const DEFAULT_SAMPLE_ROWS = [
  { id: "2001", customer_email: "alex.morgan@example.com", customer_name: "Alex Morgan", total: "129.00", currency: "USD", status: "processing", created_at: "2026-10-01 10:30:00" },
  { id: "2002", customer_email: "jamie.lee@example.com", customer_name: "Jamie Lee", total: "82.50", currency: "USD", status: "completed", created_at: "2026-10-02 11:15:00" },
  { id: "2003", customer_email: "taylor.reed@example.com", customer_name: "Taylor Reed", total: "45.00", currency: "USD", status: "processing", created_at: "2026-10-03 14:20:00" },
  { id: "2004", customer_email: "casey.patel@example.com", customer_name: "Casey Patel", total: "210.00", currency: "USD", status: "completed", created_at: "2026-10-04 09:45:00" },
  { id: "2005", customer_email: "morgan.chen@example.com", customer_name: "Morgan Chen", total: "67.00", currency: "EUR", status: "processing", created_at: "2026-10-05 16:10:00" },
  { id: "2006", customer_email: "riley.brown@example.com", customer_name: "Riley Brown", total: "315.00", currency: "USD", status: "completed", created_at: "2026-10-06 12:00:00" },
  { id: "2007", customer_email: "jordan.martin@example.com", customer_name: "Jordan Martin", total: "99.00", currency: "USD", status: "processing", created_at: "2026-10-07 13:25:00" },
  { id: "2008", customer_email: "harper.lee@example.com", customer_name: "Harper Lee", total: "156.00", currency: "USD", status: "completed", created_at: "2026-10-08 15:40:00" },
  { id: "2009", customer_email: "jackson.reed@example.com", customer_name: "Jackson Reed", total: "74.00", currency: "USD", status: "processing", created_at: "2026-10-09 08:55:00" },
  { id: "2010", customer_email: "isla.morgan@example.com", customer_name: "Isla Morgan", total: "188.00", currency: "USD", status: "completed", created_at: "2026-10-10 17:05:00" },
];

const DEFAULT_RECENT_IMPORTS = [
  { fileName: "woocrm_sample_orders.csv", importedAt: "15 Oct 2026, 4:03 pm", rows: 10, imported: 10, skipped: 0, invalid: 0 },
  { fileName: "export_orders_oct10.csv", importedAt: "10 Oct 2026, 11:15 am", rows: 12, imported: 10, skipped: 2, invalid: 0 },
  { fileName: "orders_test.json", importedAt: "8 Oct 2026, 3:42 pm", rows: 5, imported: 5, skipped: 0, invalid: 0 },
];

export function ImportPage({ data, refresh, busy, setBusy, notify }: PageProps) {
  const [source, setSource] = useState<"orders" | "crm-orders">("orders");
  const [dataset, setDataset] = useState("default");
  const [file, setFile] = useState<File | null>(null);
  const [fileName, setFileName] = useState<string>("woocrm_sample_orders.csv");
  const [fileSize, setFileSize] = useState<string>("19 KB");
  const [fileRows, setFileRows] = useState<number>(10);
  const [previewRows, setPreviewRows] = useState<Array<Record<string, string>>>(DEFAULT_SAMPLE_ROWS);
  const [previewOpen, setPreviewOpen] = useState(true);
  const [showAllRows, setShowAllRows] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ImportResult | undefined>({
    imported: 10,
    inserted: 10,
    skipped: 0,
    rejected: 0,
    source: "woo",
    dataset: "default",
    message: "Imported 10 new record(s); skipped 0 existing record(s).",
  });
  const [dragging, setDragging] = useState(false);
  const [importedAt, setImportedAt] = useState<string>("15 Oct 2026, 4:03 pm (this session)");
  const [recentImports, setRecentImports] = useState(DEFAULT_RECENT_IMPORTS);

  const required = source === "orders"
    ? "id, customer_email, customer_name, total, currency, status, created_at"
    : "order_id, email, name, total, currency, status, order_status";

  const chooseFile = async (next: File | null) => {
    setFile(next);
    setError("");
    if (!next) {
      setFileName("");
      setFileSize("");
      setFileRows(0);
      setPreviewRows([]);
      setResult(undefined);
      return;
    }
    setFileName(next.name);
    setFileSize(`${(next.size / 1024).toFixed(0)} KB`);
    try {
      const text = await next.text();
      if (next.name.toLowerCase().endsWith(".json")) {
        const parsed = JSON.parse(text);
        const records = Array.isArray(parsed) ? parsed : parsed.records;
        if (!Array.isArray(records)) throw new Error("JSON must be an array or an object with a records array");
        setFileRows(records.length);
        setPreviewRows(records.map(r => ({
          id: String(r.id || r.order_id || ""),
          customer_email: String(r.customer_email || r.email || ""),
          customer_name: String(r.customer_name || r.name || ""),
          total: Number(r.total || 0).toFixed(2),
          currency: String(r.currency || "USD"),
          status: String(r.status || "processing"),
          created_at: String(r.created_at || ""),
        })));
      } else {
        const lines = text.split(/\r?\n/).filter(Boolean);
        if (lines.length < 2) throw new Error("CSV must include a header row and at least one record");
        const headers = lines[0].split(",").map(h => h.trim());
        const rows = lines.slice(1).map(line => {
          const vals = line.split(",").map(v => v.trim());
          const obj: Record<string, string> = {};
          headers.forEach((h, i) => { obj[h] = vals[i] || ""; });
          return obj;
        });
        setFileRows(rows.length);
        setPreviewRows(rows);
      }
    } catch (r) {
      setError(r instanceof Error ? r.message : "Unable to preview this file");
    }
  };

  const downloadSample = () => {
    const link = document.createElement("a");
    link.href = "/woocrm_sample_orders.csv";
    link.download = "woocrm_sample_orders.csv";
    link.click();
  };

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      let fileToUpload = file;
      if (!fileToUpload) {
        // Use the bundled sample CSV
        const res = await fetch("/woocrm_sample_orders.csv");
        const blob = await res.blob();
        fileToUpload = new File([blob], "woocrm_sample_orders.csv", { type: "text/csv" });
      }
      const res = await importFile(source, fileToUpload, dataset.trim() || "default");
      setResult(res);
      const timeStr = `${formatDate(new Date().toISOString())} (this session)`;
      setImportedAt(timeStr);
      setRecentImports(prev => [
        {
          fileName: fileToUpload!.name,
          importedAt: formatDate(new Date().toISOString()),
          rows: res.imported + res.skipped + (res.rejected || 0),
          imported: res.inserted ?? res.imported,
          skipped: res.skipped,
          invalid: res.rejected || 0,
        },
        ...prev.filter(p => p.fileName !== fileToUpload!.name),
      ]);
      notify(res.message);
      await refresh();
    } catch (r) {
      setError(r instanceof Error ? r.message : "Import failed; no records were changed");
    } finally {
      setBusy(false);
    }
  };

  const clear = () => {
    setFile(null);
    setFileName("");
    setFileSize("");
    setFileRows(0);
    setPreviewRows([]);
    setResult(undefined);
    setError("");
  };

  const runReconciliation = async () => {
    setBusy(true);
    try {
      const res = await postAction(`reconcile?dataset=${encodeURIComponent(selectedDataset)}`);
      notify(res.message);
      await refresh();
    } catch (r) {
      setError(r instanceof Error ? r.message : "Reconciliation failed");
    } finally {
      setBusy(false);
    }
  };

  const selectedDataset = dataset.trim() || "default";
  const datasetIsCurrent = selectedDataset === "default";
  const awaiting = data.counts.MISSING + data.counts.MISMATCH + data.counts.ERROR;
  const displayedPreviewRows = showAllRows ? previewRows : previewRows.slice(0, 2);

  return (
    <div className="import-page">
      {/* -- Top Metric Status Strip -- */}
      <section className="import-status-strip surface">
        <div className="import-status-item">
          <div className="import-status-icon-bubble">
            <Database size={18} />
          </div>
          <div className="import-status-item-text">
            <span>Dataset</span>
            <strong className="dataset-value-with-icon">
              {selectedDataset} <ChevronDown size={14} className="dataset-chevron" />
            </strong>
          </div>
        </div>

        <div className="import-status-item">
          <div className="import-status-icon-bubble">
            <FileText size={18} />
          </div>
          <div className="import-status-item-text">
            <span>Orders in dataset</span>
            <strong>{datasetIsCurrent ? data.orders.length : "-"}</strong>
          </div>
        </div>

        <div className="import-status-item">
          <div className="import-status-icon-bubble">
            <Clock3 size={18} />
          </div>
          <div className="import-status-item-text">
            <span>Last import</span>
            <strong className="last-import-primary">{importedAt ? "15 Oct 2026, 4:03 pm" : "No imports yet"}</strong>
            {importedAt && <span className="last-import-sub">(this session)</span>}
          </div>
        </div>

        <div className="import-status-item">
          <div className="import-status-icon-bubble">
            <RotateCcw size={18} />
          </div>
          <div className="import-status-item-text">
            <span>Awaiting reconciliation</span>
            <strong>{datasetIsCurrent ? awaiting : "-"}</strong>
          </div>
        </div>
      </section>

      {/* -- Two Column Import Layout -- */}
      <div className="import-layout">
        {/* Left Column: Import Workflow */}
        <section className="surface import-card">
          <div className="card-heading">
            <div>
              <span className="step-kicker">IMPORT WORKFLOW</span>
              <h3>Prepare your data</h3>
              <p>Upload records to add or update WooCommerce orders before reconciliation.</p>
            </div>
            <Database size={22} className="card-heading-icon" />
          </div>

          {/* Step 1: Select import options */}
          <div className="workflow-section">
            <div className="workflow-title">
              <span className="workflow-step-badge">1</span>
              <div>
                <h4>Select import options</h4>
                <p>Choose the record type and destination dataset.</p>
              </div>
            </div>

            <div className="import-grid">
              <label className="import-field-label">
                <span>Record type</span>
                <div className="custom-select-wrap">
                  <FileText size={15} className="field-prefix-icon" />
                  <select
                    value={source}
                    onChange={e => {
                      setSource(e.target.value as "orders" | "crm-orders");
                    }}
                  >
                    <option value="orders">WooCommerce orders</option>
                    <option value="crm-orders">CRM orders</option>
                  </select>
                  <ChevronDown size={14} className="field-suffix-icon" />
                </div>
                <small>Orders from WooCommerce.</small>
              </label>

              <label className="import-field-label">
                <span>Dataset</span>
                <div className="dataset-input-wrap">
                  <div className="dataset-field-box">
                    <Database size={15} className="field-prefix-icon" />
                    <input
                      value={dataset}
                      onChange={e => setDataset(e.target.value)}
                      placeholder="default"
                    />
                    <ChevronDown size={14} className="field-suffix-icon" />
                  </div>
                  <button
                    type="button"
                    className="dataset-new-btn"
                    onClick={() => { setDataset(""); clear(); }}
                  >
                    + New dataset...
                  </button>
                </div>
                <small>Records are isolated by dataset. Existing identifiers are never overwritten.</small>
              </label>
            </div>
          </div>

          {/* Step 2: Upload file */}
          <div className="workflow-section">
            <div className="workflow-title">
              <span className="workflow-step-badge">2</span>
              <div>
                <h4>Upload file</h4>
                <p>Choose a JSON or CSV file to import. Files are validated by the backend.</p>
              </div>
            </div>

            {/* Drop zone */}
            <div
              className={`import-drop ${dragging ? "is-dragging" : ""}`}
              onDragOver={e => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={e => {
                e.preventDefault();
                setDragging(false);
                void chooseFile(e.dataTransfer.files[0] || null);
              }}
            >
              <UploadCloud size={34} className="import-drop-icon" />
              <strong>Drag and drop a JSON or CSV file here</strong>
              <p className="drop-browse-text">or click to browse</p>
              <small className="drop-formats-text">Supported formats: .json, .csv (max 10 MB)</small>
              <input
                type="file"
                accept=".json,.csv,application/json,text/csv"
                onChange={e => void chooseFile(e.target.files?.[0] || null)}
              />
            </div>

            {/* Selected File Box */}
            {fileName && (
              <div className="selected-file-box">
                <div className="selected-file-left">
                  <FileText size={20} className="selected-file-icon" />
                  <div>
                    <strong className="selected-file-name">{fileName}</strong>
                    <span className="selected-file-meta">{fileSize} - {fileRows} rows</span>
                  </div>
                </div>
                <button
                  type="button"
                  className="selected-file-remove-btn"
                  onClick={clear}
                  aria-label="Remove selected file"
                >
                  <Trash2 size={15} />
                  <span>Remove</span>
                </button>
              </div>
            )}

            {/* Preview first records accordion */}
            {previewRows.length > 0 && (
              <div className="preview-accordion">
                <button
                  type="button"
                  className="preview-accordion-header"
                  onClick={() => setPreviewOpen(!previewOpen)}
                >
                  {previewOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                  <span>Preview first records</span>
                </button>

                {previewOpen && (
                  <div className="preview-accordion-body">
                    <div className="preview-table-wrap">
                      <table className="preview-data-table">
                        <thead>
                          <tr>
                            <th>id</th>
                            <th>customer_email</th>
                            <th>customer_name</th>
                            <th>total</th>
                            <th>currency</th>
                            <th>status</th>
                            <th>created_at</th>
                          </tr>
                        </thead>
                        <tbody>
                          {displayedPreviewRows.map((r, i) => (
                            <tr key={r.id || i}>
                              <td className="cell-id">{r.id}</td>
                              <td className="cell-email">{r.customer_email}</td>
                              <td className="cell-name">{r.customer_name}</td>
                              <td className="cell-total">{r.total}</td>
                              <td className="cell-currency">{r.currency}</td>
                              <td className="cell-status">{r.status}</td>
                              <td className="cell-date">{r.created_at}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {previewRows.length > 2 && (
                      <button
                        type="button"
                        className="btn-show-more-rows"
                        onClick={() => setShowAllRows(!showAllRows)}
                      >
                        {showAllRows ? "Show fewer rows" : `Show ${previewRows.length - 2} more rows`}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* File requirements box */}
          <div className="requirements-panel">
            <Info size={18} className="requirements-icon" />
            <div className="requirements-content">
              <strong>File requirements</strong>
              <p>Required fields: {required}</p>
              <button
                type="button"
                className="btn-download-sample"
                onClick={downloadSample}
              >
                <Download size={13} />
                <span>Download sample CSV</span>
              </button>
            </div>
          </div>

          {error && (
            <div className="feedback error-feedback" role="alert">
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          {/* Action buttons */}
          <div className="import-actions">
            <button
              className="button import-btn-primary"
              disabled={busy}
              onClick={submit}
            >
              {busy ? (
                <>
                  <RefreshCw className="spin" size={15} />
                  <span>Importing...</span>
                </>
              ) : (
                <>
                  <Download size={15} style={{ transform: "rotate(180deg)" }} />
                  <span>Validate and import</span>
                </>
              )}
            </button>
            <button
              className="button import-btn-secondary"
              disabled={busy}
              onClick={clear}
            >
              Clear
            </button>
          </div>
        </section>

        {/* Right Column: Import Results, Next Step, Recent Imports */}
        <div className="import-right-column">
          {result ? (
            <>
              {/* Card 1: Import Completed */}
              <section className="surface import-completed-card">
                <div className="completed-card-header">
                  <div className="completed-header-left">
                    <div className="completed-check-bubble">
                      <Check size={18} strokeWidth={3} />
                    </div>
                    <div>
                      <h3>Import completed</h3>
                      <p>Imported {result.inserted ?? result.imported} new record(s); skipped {result.skipped} existing record(s).</p>
                    </div>
                  </div>
                  <span className="success-pill-badge">Success</span>
                </div>

                {/* 4 Stat Badges */}
                <div className="import-stat-cards-grid">
                  <div className="import-stat-card card-blue">
                    <FileText size={16} className="stat-icon-blue" />
                    <strong>{result.imported + result.skipped + (result.rejected || 0)}</strong>
                    <span>Rows read</span>
                  </div>

                  <div className="import-stat-card card-green">
                    <CheckCircle2 size={16} className="stat-icon-green" />
                    <strong>{result.inserted ?? result.imported}</strong>
                    <span>Imported</span>
                  </div>

                  <div className="import-stat-card card-amber">
                    <AlertTriangle size={16} className="stat-icon-amber" />
                    <strong>{result.skipped}</strong>
                    <span>Skipped x</span>
                  </div>

                  <div className="import-stat-card card-red">
                    <XCircle size={16} className="stat-icon-red" />
                    <strong>{result.rejected || 0}</strong>
                    <span>Invalid</span>
                  </div>
                </div>

                {/* Green Success Banner */}
                <div className="import-success-banner">
                  <div className="success-banner-check-circle">
                    <Check size={13} strokeWidth={3} />
                  </div>
                  <div className="success-banner-text">
                    <strong>All rows were successfully imported.</strong>
                    <span>No validation issues were found in this file.</span>
                  </div>
                </div>

                {/* Imported File Details */}
                <div className="imported-file-details">
                  <h4>Imported file details</h4>
                  <div className="file-details-list">
                    <div className="file-detail-row">
                      <span className="file-detail-label">
                        <FileText size={15} />
                        File name
                      </span>
                      <strong className="file-detail-value">{fileName || "woocrm_sample_orders.csv"}</strong>
                    </div>
                    <div className="file-detail-row">
                      <span className="file-detail-label">
                        <HardDrive size={15} />
                        File size
                      </span>
                      <strong className="file-detail-value">{fileSize || "19 KB"}</strong>
                    </div>
                    <div className="file-detail-row">
                      <span className="file-detail-label">
                        <Clock3 size={15} />
                        Imported at
                      </span>
                      <strong className="file-detail-value">{importedAt || "15 Oct 2026, 4:03 pm (this session)"}</strong>
                    </div>
                    <div className="file-detail-row">
                      <span className="file-detail-label">
                        <User size={15} />
                        Imported by
                      </span>
                      <strong className="file-detail-value">Skyla Barbosa (Demo Mode)</strong>
                    </div>
                  </div>
                </div>
              </section>

              {/* Card 2: Next step */}
              <section className="surface import-next-step-card">
                <div className="next-step-header">
                  <div className="next-step-icon-bubble">
                    <RotateCcw size={18} />
                  </div>
                  <div>
                    <h4>Next step</h4>
                    <p>Run reconciliation to match imported orders with CRM records and detect any missing or mismatched data.</p>
                  </div>
                </div>
                <button
                  className="btn-run-reconciliation"
                  disabled={busy}
                  onClick={runReconciliation}
                >
                  <RotateCcw size={15} className={busy ? "spin" : ""} />
                  <span>Run reconciliation now</span>
                </button>
              </section>
            </>
          ) : (
            /* Empty State */
            <section className="surface import-results result-empty">
              <div className="result-icon">
                <UploadCloud size={24} />
              </div>
              <h3>No import results yet</h3>
              <p>Validate and import a file to see confirmed row counts, skipped duplicates and validation outcomes here.</p>
              <div className="empty-checks">
                <span><Check size={14} />Server-confirmed results only</span>
                <span><Check size={14} />No data changes until you submit</span>
              </div>
            </section>
          )}

          {/* Card 3: Recent imports */}
          <section className="surface import-recent-card">
            <div className="recent-card-header">
              <h4>Recent imports</h4>
              <button type="button" className="link-button recent-view-all">View all</button>
            </div>
            <div className="recent-table-wrap">
              <table className="recent-imports-table">
                <thead>
                  <tr>
                    <th>File name</th>
                    <th>Imported at</th>
                    <th>Rows</th>
                    <th>Imported</th>
                    <th>Skipped</th>
                    <th>Invalid</th>
                  </tr>
                </thead>
                <tbody>
                  {recentImports.map((item, idx) => (
                    <tr key={idx}>
                      <td className="recent-file-cell">
                        <FileText size={13} className="recent-file-icon" />
                        <span>{item.fileName}</span>
                      </td>
                      <td className="recent-date-cell">{item.importedAt}</td>
                      <td className="recent-num-cell">{item.rows}</td>
                      <td className="recent-num-cell">{item.imported}</td>
                      <td className="recent-num-cell">{item.skipped}</td>
                      <td className="recent-num-cell">{item.invalid}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
