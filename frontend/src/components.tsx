import {
  AlertCircle, AlertTriangle, Check, ChevronRight, ChevronLeft, ChevronDown, CircleHelp, Database,
  Home, Menu, Package, RefreshCw, RotateCcw, Search, Settings, ShieldAlert, ShieldCheck, Upload, UserRound, Users, X,
  ShoppingCart, CheckCircle2, Zap, Clock, Bell, Lightbulb, Link2, UserX, ArrowRight,
  FileText, Ban, Pencil
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Dashboard, IntegrationStatus, Order, SyncState } from "./types";

export const navItems = [
  { href: "/woocrm/", label: "Dashboard", icon: Home },
  { href: "/woocrm/orders", label: "Orders", icon: ShoppingCart },
  { href: "/woocrm/customers", label: "Customers", icon: Users },
  { href: "/woocrm/import", label: "Import Data", icon: Upload },
  { href: "/woocrm/risk-guard", label: "Risk Guard", icon: ShieldCheck },
  { href: "/woocrm/settings", label: "Settings", icon: Settings },
];

export function formatMoney(value: number | null | undefined, currency?: string | null) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  const formatted = value.toFixed(2);
  const symbol = currency === "EUR" ? "€" : "$";
  return `${symbol}${formatted}`;
}

export function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const day = date.getDate();
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const month = months[date.getMonth()];
  const year = date.getFullYear();
  let hours = date.getHours();
  const minutes = date.getMinutes().toString().padStart(2, "0");
  const ampm = hours >= 12 ? "pm" : "am";
  hours = hours % 12;
  hours = hours ? hours : 12;
  return `${day} ${month} ${year}, ${hours}:${minutes} ${ampm}`;
}

const stateLabels: Record<SyncState, string> = {
  SYNCED: "Synced", MISSING: "Missing", ERROR: "Error", MISMATCH: "Mismatch", NOT_ELIGIBLE: "Not eligible",
};

export function StatusBadge({ state }: { state: SyncState }) {
  const dotColor: Record<SyncState, string> = {
    SYNCED: "#10B981",
    MISSING: "#F97316",
    MISMATCH: "#8B5CF6",
    ERROR: "#EF4444",
    NOT_ELIGIBLE: "#64748B",
  };
  return (
    <span className={`status-pill status-${state.toLowerCase()}`}>
      <span className="status-dot" style={{ backgroundColor: dotColor[state] }} />
      <span>{stateLabels[state]}</span>
    </span>
  );
}

export function WooStatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  const label = status.charAt(0).toUpperCase() + status.slice(1).toLowerCase();
  return <span className={`woo-status-badge ${s}`}>{label}</span>;
}

export function EmptyState({ title, message, icon: Icon = CircleHelp }: { title: string; message: string; icon?: typeof CircleHelp }) {
  return <div className="empty-state"><Icon size={22} /><strong>{title}</strong><p>{message}</p></div>;
}

export function LoadingState() {
  return <div className="empty-state"><RefreshCw className="spin" size={22} /><strong>Loading data</strong><p>Fetching the latest snapshot from the API.</p></div>;
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="empty-state error-state"><AlertCircle size={22} /><strong>Could not load data</strong><p>{message}</p><button className="button secondary" onClick={onRetry}>Try again</button></div>;
}

/* ─── Metric Card (Horizontal layout matching Image 1) ───── */
export function MetricCard({
  label, value, detail, tone = "blue", icon: CustomIcon, onClick
}: {
  label: string;
  value: number;
  detail: string;
  tone?: string;
  icon?: any;
  onClick?: () => void;
  showArrow?: boolean;
}) {
  let DefaultIcon = FileText;
  if (tone === "green" || tone === "synced" || label.toLowerCase().includes("synced")) DefaultIcon = CheckCircle2;
  else if (tone === "coral" || tone === "amber" || tone === "missing" || tone === "error" || label.toLowerCase().includes("attention") || label.toLowerCase().includes("missing")) DefaultIcon = AlertTriangle;
  else if (tone === "purple" || tone === "not_eligible" || label.toLowerCase().includes("not eligible") || label.toLowerCase().includes("mismatch")) DefaultIcon = Ban;
  else if (tone === "blue" || tone === "eligible" || label.toLowerCase().includes("total") || label.toLowerCase().includes("eligible")) DefaultIcon = FileText;

  const Icon = CustomIcon || DefaultIcon;

  let normalizedTone = tone;
  if (label.toLowerCase().includes("total") || tone === "eligible" || tone === "blue") normalizedTone = "blue";
  else if (label.toLowerCase().includes("synced") || tone === "synced" || tone === "green") normalizedTone = "green";
  else if (label.toLowerCase().includes("attention") || tone === "amber" || tone === "coral" || tone === "missing" || tone === "error") normalizedTone = "amber";
  else if (label.toLowerCase().includes("not eligible") || tone === "purple" || tone === "not_eligible" || tone === "mismatch") normalizedTone = "purple";

  return (
    <div
      className={`metric-card tone-${normalizedTone}`}
      onClick={onClick}
      style={onClick ? { cursor: "pointer" } : {}}
    >
      <div className={`metric-icon-box tone-${normalizedTone}`}>
        <Icon size={24} />
      </div>
      <div className="metric-info">
        <span className="metric-label">{label}</span>
        <span className="metric-value">{value}</span>
        <span className="metric-detail">{detail}</span>
      </div>
    </div>
  );
}

/* ─── Donut Chart ─────────────────────────────────────────── */
export function DonutChart({
  synced, missing, mismatch, error, total
}: { synced: number; missing: number; mismatch: number; error: number; total: number }) {
  const r = 52;
  const stroke = 10;
  const circ = 2 * Math.PI * r;
  const pct = (n: number) => total > 0 ? (n / total) * circ : 0;

  const segments = [
    { value: synced,   color: "#22C55E", label: "Synced" },
    { value: missing,  color: "#EF4444", label: "Missing" },
    { value: mismatch, color: "#7C4DFF", label: "Mismatch" },
    { value: error,    color: "#F59E0B", label: "Error" },
  ];

  let offset = 0;
  const healthPct = total > 0 ? Math.round((synced / total) * 100) : 0;
  const size = (r + stroke) * 2 + 4;
  const center = size / 2;

  return (
    <div className="donut-container" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        {/* Background track */}
        <circle
          cx={center} cy={center} r={r}
          fill="none"
          stroke="#E8EFF8"
          strokeWidth={stroke}
        />
        {total === 0 ? (
          <circle cx={center} cy={center} r={r} fill="none" stroke="#E8EFF8" strokeWidth={stroke} />
        ) : (
          segments.map((seg, i) => {
            const dash = pct(seg.value);
            const el = (
              <circle
                key={i}
                cx={center} cy={center} r={r}
                fill="none"
                stroke={seg.color}
                strokeWidth={stroke}
                strokeDasharray={`${dash} ${circ - dash}`}
                strokeDashoffset={-offset}
                strokeLinecap="round"
              />
            );
            offset += dash;
            return el;
          })
        )}
      </svg>
      <div className="donut-label">
        <strong>{healthPct}%</strong>
        <span>Synced</span>
      </div>
    </div>
  );
}

function getReason(order: Order): string {
  if (order.state === "SYNCED") return "-";
  if (order.state === "MISSING") return "CRM order not found";
  if (order.state === "MISMATCH") {
    if (order.crm && order.currency !== order.crm.currency) {
      return `Currency differs (${order.currency} → ${order.crm.currency})`;
    }
    if (order.crm && Math.abs(order.total - order.crm.total) >= 0.01) {
      return "Total differs";
    }
    if (order.crm && order.customer_email.trim().toLowerCase() !== order.crm.email.trim().toLowerCase()) {
      return "Email differs";
    }
    return "Total differs";
  }
  if (order.state === "ERROR") {
    return order.crm?.error_message || "Replay timed out";
  }
  if (order.state === "NOT_ELIGIBLE") {
    return "Excluded from sync";
  }
  return "-";
}

/* ─── Order Table (Matching Image 1) ─────────────────────── */
export function OrderTable({ orders, onSelect, onAction, busy }: {
  orders: Order[];
  onSelect: (order: Order) => void;
  onAction: (order: Order, action: "replay" | "update") => void;
  busy: boolean;
}) {
  return (
    <div className="table-wrap">
      <table className="orders-table">
        <thead>
          <tr>
            <th>
              <span className="th-content">Order <span className="sort-arrows">↑↓</span></span>
            </th>
            <th>
              <span className="th-content">Customer <span className="sort-arrows">↑↓</span></span>
            </th>
            <th>
              <span className="th-content">Total <span className="sort-arrows">↑↓</span></span>
            </th>
            <th>WooCommerce status</th>
            <th>
              <span className="th-content">CRM status <span className="sort-arrows">↑↓</span></span>
            </th>
            <th>
              <span className="th-content">Sync state <span className="sort-arrows">↑↓</span></span>
            </th>
            <th>Reason</th>
            <th className="th-action">Action</th>
          </tr>
        </thead>
        <tbody>
          {orders.map(order => {
            const reason = getReason(order);
            const isCrmError = order.state === "ERROR" || order.crm?.status?.toLowerCase() === "error";

            return (
              <tr key={String(order.id)} onClick={() => onSelect(order)} className="clickable-row">
                <td>
                  <button className="link-button order-id-link" onClick={e => { e.stopPropagation(); onSelect(order); }}>
                    #{order.id}
                  </button>
                  <small className="order-subtext">{formatDate(order.created_at)}</small>
                </td>
                <td>
                  <strong className="customer-name-text">{order.customer_name}</strong>
                  <small className="order-subtext">{order.customer_email}</small>
                </td>
                <td>
                  <strong className="order-total-text">{formatMoney(order.total, order.currency)}</strong>
                  <small className="order-subtext">{order.currency}</small>
                </td>
                <td><WooStatusBadge status={order.status} /></td>
                <td>
                  {order.crm ? (
                    <>
                      <span className={isCrmError ? "crm-status-error" : "crm-status-text"}>
                        {isCrmError ? "Error" : order.crm.status}
                      </span>
                      <small className="order-subtext">
                        {order.crm.updated_at ? formatDate(order.crm.updated_at) : "-"}
                      </small>
                    </>
                  ) : (
                    <>
                      <span className="crm-status-text">No record</span>
                      <small className="order-subtext">-</small>
                    </>
                  )}
                </td>
                <td><StatusBadge state={order.state} /></td>
                <td>
                  <span className="order-reason-text">{reason}</span>
                </td>
                <td className="td-action" onClick={e => e.stopPropagation()}>
                  {(order.state === "MISSING" || order.state === "ERROR") && (
                    <button
                      className="btn-order-action replay"
                      disabled={busy}
                      onClick={() => onAction(order, "replay")}
                    >
                      <RotateCcw size={14} />
                      <span>Replay</span>
                    </button>
                  )}
                  {order.state === "MISMATCH" && (
                    <button
                      className="btn-order-action update"
                      disabled={busy}
                      onClick={() => onAction(order, "update")}
                    >
                      <Pencil size={14} />
                      <span>Update CRM</span>
                    </button>
                  )}
                  {order.state === "SYNCED" && (
                    <span className="synced-action-badge">
                      <Check size={16} />
                      <span>Synced</span>
                    </span>
                  )}
                  {order.state === "NOT_ELIGIBLE" && (
                    <span className="text-subtle">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Order Table (Dashboard variant — with last sync col) ── */
export function DashboardOrderTable({ orders, onSelect, onAction, busy }: {
  orders: Order[];
  onSelect: (order: Order) => void;
  onAction: (order: Order, action: "replay" | "update") => void;
  busy: boolean;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Order</th>
            <th>Customer</th>
            <th>Total</th>
            <th>Woo status</th>
            <th>CRM status</th>
            <th>Sync state</th>
            <th>Last sync</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {orders.map(order => {
            const needsAttention = order.state !== "SYNCED" && order.state !== "NOT_ELIGIBLE";
            return (
              <tr key={String(order.id)} onClick={() => onSelect(order)} className="clickable-row">
                <td>
                  <button className="link-button" onClick={e => { e.stopPropagation(); onSelect(order); }}>
                    #{order.id}
                  </button>
                  <small>{formatDate(order.created_at)}</small>
                </td>
                <td>
                  <span style={{ fontWeight: 600, fontSize: 12, color: "var(--ink)" }}>{order.customer_name}</span>
                  <small>{order.customer_email}</small>
                </td>
                <td>
                  <span style={{ fontWeight: 600 }}>{formatMoney(order.total, order.currency)}</span>
                  <small>{order.currency}</small>
                </td>
                <td><WooStatusBadge status={order.status} /></td>
                <td>
                  {order.crm
                    ? <span className="plain-status">{order.crm.status}</span>
                    : <small style={{ color: "var(--muted)" }}>No record</small>}
                </td>
                <td>
                  {needsAttention
                    ? <span className="status-badge status-attention"><span className="status-dot" />Needs attention</span>
                    : <StatusBadge state={order.state} />}
                </td>
                <td>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>
                    {order.crm?.updated_at ? formatDate(order.crm.updated_at) : "—"}
                  </span>
                </td>
                <td onClick={e => e.stopPropagation()}>
                  <button className="table-action" title="More actions">···</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Order Detail ────────────────────────────────────────── */
export function OrderDetail({ order, onClose }: { order: Order; onClose: () => void }) {
  const differences = [
    ["Total", formatMoney(order.total, order.currency), order.crm ? formatMoney(order.crm.total, order.crm.currency) : "No CRM value", order.crm && Math.abs(order.total - order.crm.total) >= 0.001],
    ["Currency", order.currency, order.crm?.currency || "No CRM value", order.crm && order.currency !== order.crm.currency],
    ["Billing email", order.customer_email, order.crm?.email || "No CRM value", order.crm && order.customer_email.trim().toLowerCase() !== order.crm.email.trim().toLowerCase()],
    ["Order status", order.status, order.crm?.order_status || "No CRM value", order.crm && order.status !== order.crm.order_status],
  ] as const;
  const stateExplanation: Record<SyncState, string> = {
    SYNCED: "Compared values match.",
    MISSING: "No corresponding CRM order exists. Replay is available for eligible orders.",
    MISMATCH: "One or more compared values differ. Use Update CRM only after explicit confirmation.",
    ERROR: "A CRM or synchronization error requires attention. Replay is available when recoverable.",
    NOT_ELIGIBLE: "This order is excluded by the current processing and completed eligibility rules.",
  };
  return (
    <div className="detail-backdrop" role="presentation" onClick={onClose}>
      <aside className="detail-panel" role="dialog" aria-label={`Order ${order.id} details`} onClick={e => e.stopPropagation()}>
        <div className="detail-header">
          <div><span className="eyebrow">Order detail</span><h2>#{order.id}</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Close details"><X size={18} /></button>
        </div>
        <StatusBadge state={order.state} />
        <p className="state-explanation">{stateExplanation[order.state]}</p>
        <div className="detail-section">
          <h3>Compared fields</h3>
          {differences.map(([label, woo, crm, different]) => (
            <div className={`compare-row ${different ? "different" : ""}`} key={label}>
              <span>{label}</span>
              <div><small>WooCommerce</small><strong>{woo}</strong></div>
              <ChevronRight size={15} />
              <div><small>CRM</small><strong>{crm}</strong></div>
            </div>
          ))}
        </div>
        <div className="detail-section">
          <h3>Synchronization</h3>
          <p className="muted-copy">Open the order investigation to review persistent reconciliation and action history.</p>
          {order.crm?.updated_at && <div className="sync-timestamp"><RefreshCw size={15} /> Last CRM update {formatDate(order.crm.updated_at)}</div>}
        </div>
      </aside>
    </div>
  );
}

/* ─── App Shell ───────────────────────────────────────────── */
export function AppShell({ path, children, onNavigate, notice, busy, onReconcile, integration, data }: {
  path: string;
  children: React.ReactNode;
  onNavigate: (href: string) => void;
  notice: string;
  busy: boolean;
  onReconcile: () => void;
  integration?: IntegrationStatus;
  data?: Dashboard | null;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const searchContainerRef = useRef<HTMLDivElement>(null);

  const active = (href: string) => href === "/woocrm/" ? path === href : path.startsWith(href);
  const currentPage = navItems.find(item => active(item.href));

  // Global shortcut listeners (Ctrl+K, Cmd+K, /, Escape)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchInputRef.current?.focus();
        setSearchOpen(true);
      } else if (e.key === "/" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
        e.preventDefault();
        searchInputRef.current?.focus();
        setSearchOpen(true);
      } else if (e.key === "Escape" && searchOpen) {
        setSearchOpen(false);
        searchInputRef.current?.blur();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [searchOpen]);

  // Click outside to close dropdown
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchContainerRef.current && !searchContainerRef.current.contains(e.target as Node)) {
        setSearchOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const cleanQuery = searchQuery.trim().toLowerCase();

  // Search Results
  const matchingOrders = useMemo(() => {
    if (!data?.orders) return [];
    if (!cleanQuery) return data.orders.slice(0, 3);
    return data.orders.filter(o =>
      String(o.id).toLowerCase().includes(cleanQuery) ||
      o.customer_name.toLowerCase().includes(cleanQuery) ||
      o.customer_email.toLowerCase().includes(cleanQuery) ||
      o.state.toLowerCase().includes(cleanQuery) ||
      o.status.toLowerCase().includes(cleanQuery)
    ).slice(0, 4);
  }, [data?.orders, cleanQuery]);

  const matchingCustomers = useMemo(() => {
    if (!data?.groups) return [];
    if (!cleanQuery) return data.groups.slice(0, 2);
    return data.groups.filter(c =>
      c.name.toLowerCase().includes(cleanQuery) ||
      c.email.toLowerCase().includes(cleanQuery)
    ).slice(0, 3);
  }, [data?.groups, cleanQuery]);

  const allPagesAndRules = useMemo(() => [
    { type: "rule", title: "Risk Guard Rules", desc: "Evaluate order modifications & safety limits", path: "/woocrm/risk-guard", icon: ShieldAlert },
    { type: "page", title: "Connections & API Settings", desc: "Configure WooCommerce & HubSpot connectors", path: "/woocrm/settings", icon: Settings },
    { type: "page", title: "Datasets & Demo Reset", desc: "Switch datasets and reset demo records", path: "/woocrm/settings", icon: Database },
    { type: "page", title: "Import Data", desc: "Upload and validate external order datasets", path: "/woocrm/import", icon: Database },
    { type: "page", title: "Orders Manager", desc: "Explore all orders with status filtering", path: "/woocrm/orders", icon: Package },
    { type: "page", title: "Customer Identity Directory", desc: "Verify customer sync and CRM contact alignment", path: "/woocrm/customers", icon: Users },
  ], []);

  const matchingPages = useMemo(() => {
    if (!cleanQuery) return allPagesAndRules.slice(0, 3);
    return allPagesAndRules.filter(item =>
      item.title.toLowerCase().includes(cleanQuery) ||
      item.desc.toLowerCase().includes(cleanQuery)
    );
  }, [allPagesAndRules, cleanQuery]);

  // Flattened items for unified keyboard navigation
  const selectableItems = useMemo(() => {
    const list: Array<{
      id: string;
      category: string;
      title: string;
      subtitle: string;
      badge?: string;
      badgeState?: SyncState;
      action: () => void;
    }> = [];

    matchingOrders.forEach(o => {
      list.push({
        id: `order-${o.id}`,
        category: "Orders",
        title: `Order #${o.id} · ${o.customer_name}`,
        subtitle: `${formatMoney(o.total, o.currency)} · ${o.customer_email}`,
        badge: o.state,
        badgeState: o.state,
        action: () => {
          onNavigate(`/woocrm/orders/${o.id}`);
          setSearchOpen(false);
          setSearchQuery("");
        }
      });
    });

    matchingCustomers.forEach(c => {
      list.push({
        id: `cust-${c.email}`,
        category: "Customers",
        title: c.name || "Customer",
        subtitle: `${c.email} · ${c.order_count} orders`,
        badge: c.sync_state === "SYNCED" ? "SYNCED" : "ATTENTION",
        action: () => {
          onNavigate(`/woocrm/customers?search=${encodeURIComponent(c.email)}`);
          setSearchOpen(false);
          setSearchQuery("");
        }
      });
    });

    matchingPages.forEach(p => {
      list.push({
        id: `page-${p.path}-${p.title}`,
        category: "Navigation & Rules",
        title: p.title,
        subtitle: p.desc,
        action: () => {
          onNavigate(p.path);
          setSearchOpen(false);
          setSearchQuery("");
        }
      });
    });

    return list;
  }, [matchingOrders, matchingCustomers, matchingPages, onNavigate]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [cleanQuery]);

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex(prev => (prev < selectableItems.length - 1 ? prev + 1 : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex(prev => (prev > 0 ? prev - 1 : selectableItems.length - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (selectableItems[selectedIndex]) {
        selectableItems[selectedIndex].action();
      } else if (searchQuery.trim()) {
        onNavigate(`/woocrm/orders?search=${encodeURIComponent(searchQuery.trim())}`);
        setSearchOpen(false);
        setSearchQuery("");
      }
    } else if (e.key === "Escape") {
      setSearchOpen(false);
      searchInputRef.current?.blur();
    }
  };

  let globalItemIndex = 0;

  return (
    <div className="app-shell">
      {/* ── Sidebar ── */}
      <aside className={`sidebar ${mobileOpen ? "sidebar-open" : ""}`}>
        <div className="sidebar-brand" aria-label="WooCRM Sync">
          <img src="/images/woocrm-sync-logo-sidebar.png" alt="WooCRM Sync" />
        </div>
        <nav>
          {navItems.map(item => (
            <button
              key={item.href}
              className={`nav-item ${active(item.href) ? "active" : ""}`}
              onClick={() => { onNavigate(item.href); setMobileOpen(false); }}
            >
              <item.icon size={17} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
      </aside>

      {/* ── Main ── */}
      <div className="main-area">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
            <Menu size={20} />
          </button>

          {/* Left: breadcrumb + title + subtitle */}
          <div className="topbar-heading">
            <div className="breadcrumb">
              WooCRM Sync <ChevronRight size={13} /> {currentPage?.label || "Orders"}
            </div>
            <h1>{currentPage?.label || "Orders"}</h1>
            <p className="topbar-subtitle">
              {currentPage?.href === "/woocrm/orders"
                ? "Review every order and resolve synchronization issues safely."
                : currentPage?.href === "/woocrm/"
                ? "Keep orders and CRM records aligned across all connected systems."
                : currentPage?.href === "/woocrm/customers"
                ? "Manage and verify synchronized customer records and identity."
                : currentPage?.href === "/woocrm/import"
                ? "Upload and validate external order datasets safely."
                : currentPage?.href === "/woocrm/risk-guard"
                ? "Review proposed changes before they reach your CRM. These are risk-rule evaluations, not fraud findings."
                : currentPage?.href === "/woocrm/settings"
                ? "Manage connections, safety rules and datasets."
                : "Review synchronization status and resolve issues safely."}
            </p>
          </div>

          {/* Right: search + bell + user */}
          <div className="topbar-actions">
            <div className="topbar-search-container" ref={searchContainerRef}>
              <div
                className={`topbar-search-capsule ${searchOpen ? "topbar-search-capsule--open" : ""}`}
                onClick={() => {
                  searchInputRef.current?.focus();
                  setSearchOpen(true);
                }}
              >
                <Search size={15} />
                <input
                  ref={searchInputRef}
                  type="text"
                  placeholder="Search orders, customers or rules..."
                  aria-label="Search orders, customers or rules"
                  value={searchQuery}
                  onChange={e => {
                    setSearchQuery(e.target.value);
                    if (!searchOpen) setSearchOpen(true);
                  }}
                  onFocus={() => setSearchOpen(true)}
                  onKeyDown={handleInputKeyDown}
                />
                {searchQuery && (
                  <button
                    type="button"
                    className="topbar-search-clear"
                    onClick={e => {
                      e.stopPropagation();
                      setSearchQuery("");
                      searchInputRef.current?.focus();
                    }}
                    aria-label="Clear search"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>

              {/* Real-time Search Dropdown Menu */}
              {searchOpen && (
                <div className="topbar-search-dropdown" role="listbox">
                  <div className="topbar-search-header-info">
                    {cleanQuery ? `Results for "${searchQuery}"` : "Quick actions & suggestions"}
                  </div>

                  {selectableItems.length === 0 ? (
                    <div className="topbar-search-empty">
                      <Search size={22} className="topbar-search-empty-icon" />
                      <p>No matching orders, customers or rules found</p>
                      <button
                        className="topbar-search-fallback-btn"
                        onClick={() => {
                          onNavigate(`/woocrm/orders?search=${encodeURIComponent(searchQuery)}`);
                          setSearchOpen(false);
                        }}
                      >
                        Search all orders for "{searchQuery}"
                      </button>
                    </div>
                  ) : (
                    <>
                      {/* Orders Section */}
                      {matchingOrders.length > 0 && (
                        <div className="topbar-search-group">
                          <div className="topbar-search-group-title">Orders</div>
                          {matchingOrders.map(o => {
                            const thisIndex = globalItemIndex++;
                            const isSelected = selectedIndex === thisIndex;
                            return (
                              <button
                                key={`order-${o.id}`}
                                className={`topbar-search-item ${isSelected ? "topbar-search-item--active" : ""}`}
                                onClick={() => {
                                  onNavigate(`/woocrm/orders/${o.id}`);
                                  setSearchOpen(false);
                                  setSearchQuery("");
                                }}
                              >
                                <div className="topbar-search-item-left">
                                  <div className="topbar-search-item-icon topbar-search-item-icon--order">
                                    <Package size={15} />
                                  </div>
                                  <div className="topbar-search-item-info">
                                    <div className="topbar-search-item-title">
                                      Order #{o.id} · {o.customer_name}
                                    </div>
                                    <div className="topbar-search-item-subtitle">
                                      {formatMoney(o.total, o.currency)} · {o.customer_email}
                                    </div>
                                  </div>
                                </div>
                                <span className={`topbar-search-badge topbar-search-badge--${o.state.toLowerCase()}`}>
                                  {o.state}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      )}

                      {/* Customers Section */}
                      {matchingCustomers.length > 0 && (
                        <div className="topbar-search-group">
                          <div className="topbar-search-group-title">Customers</div>
                          {matchingCustomers.map(c => {
                            const thisIndex = globalItemIndex++;
                            const isSelected = selectedIndex === thisIndex;
                            return (
                              <button
                                key={`cust-${c.email}`}
                                className={`topbar-search-item ${isSelected ? "topbar-search-item--active" : ""}`}
                                onClick={() => {
                                  onNavigate(`/woocrm/customers?search=${encodeURIComponent(c.email)}`);
                                  setSearchOpen(false);
                                  setSearchQuery("");
                                }}
                              >
                                <div className="topbar-search-item-left">
                                  <div className="topbar-search-item-icon topbar-search-item-icon--cust">
                                    <Users size={15} />
                                  </div>
                                  <div className="topbar-search-item-info">
                                    <div className="topbar-search-item-title">{c.name || "Customer"}</div>
                                    <div className="topbar-search-item-subtitle">
                                      {c.email} · {c.order_count} orders
                                    </div>
                                  </div>
                                </div>
                                <span className="topbar-search-badge topbar-search-badge--neutral">
                                  {formatMoney(c.lifetime_value)}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      )}

                      {/* Navigation & Rules Section */}
                      {matchingPages.length > 0 && (
                        <div className="topbar-search-group">
                          <div className="topbar-search-group-title">Navigation & Rules</div>
                          {matchingPages.map(p => {
                            const thisIndex = globalItemIndex++;
                            const isSelected = selectedIndex === thisIndex;
                            const IconComponent = p.icon;
                            return (
                              <button
                                key={`page-${p.path}-${p.title}`}
                                className={`topbar-search-item ${isSelected ? "topbar-search-item--active" : ""}`}
                                onClick={() => {
                                  onNavigate(p.path);
                                  setSearchOpen(false);
                                  setSearchQuery("");
                                }}
                              >
                                <div className="topbar-search-item-left">
                                  <div className="topbar-search-item-icon topbar-search-item-icon--nav">
                                    <IconComponent size={15} />
                                  </div>
                                  <div className="topbar-search-item-info">
                                    <div className="topbar-search-item-title">{p.title}</div>
                                    <div className="topbar-search-item-subtitle">{p.desc}</div>
                                  </div>
                                </div>
                                <ArrowRight size={13} className="topbar-search-arrow" />
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </>
                  )}

                  {/* Dropdown Footer Navigation Shortcuts */}
                  <div className="topbar-search-footer">
                    <span><kbd>↑</kbd> <kbd>↓</kbd> navigate</span>
                    <span><kbd>↵</kbd> select</span>
                    <span><kbd>esc</kbd> close</span>
                  </div>
                </div>
              )}
            </div>

            <button className="topbar-bell-btn" aria-label="Notifications" title={notice}>
              <Bell size={18} />
              <span className="bell-badge" />
            </button>

            <div className="topbar-user">
              <div className="topbar-avatar">SB</div>
              <div className="topbar-user-name">
                <strong>Skyla Barbosa</strong>
                <span>{integration?.mode === "live" ? "Live Mode" : "Demo Mode"}</span>
              </div>
              <ChevronDown size={14} className="user-dropdown-chevron" />
            </div>
          </div>
        </header>

        <main className="content">{children}</main>
      </div>
    </div>
  );
}


/* ─── Search Control ──────────────────────────────────────── */
export function SearchControl({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
  return (
    <label className="search-control">
      <Search size={16} />
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder} />
    </label>
  );
}

/* ─── Confirm Action ──────────────────────────────────────── */
export function ConfirmAction({ label, onConfirm }: { label: string; onConfirm: () => void }) {
  const [open, setOpen] = useState(false);
  const message = label.toLowerCase().includes("reset")
    ? "Reset the default demo dataset? Its orders, local CRM mock records, customers, sync runs, order events and Risk Guard evaluations will be deleted and recreated. Imported datasets and external CRM records are preserved."
    : `Are you sure you want to ${label.toLowerCase()}?`;
  return <>
    <button className="button secondary" onClick={() => setOpen(true)}><RotateCcw size={15} />{label}</button>
    {open && <ConfirmDialog title={label} message={message} onCancel={() => setOpen(false)} onConfirm={() => { setOpen(false); onConfirm(); }} />}
  </>;
}

/* ─── Confirm Dialog ──────────────────────────────────────── */
export function ConfirmDialog({ title, message, children, onCancel, onConfirm, confirmLabel = "Confirm" }: {
  title: string; message: string; children?: React.ReactNode;
  onCancel: () => void; onConfirm: () => void; confirmLabel?: string;
}) {
  const initialFocus = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    initialFocus.current?.focus();
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onCancel]);
  return (
    <div className="confirm-backdrop" role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-message" onMouseDown={e => e.stopPropagation()}>
        <div className="detail-header">
          <div><span className="eyebrow">Confirmation required</span><h3 id="confirm-title">{title}</h3></div>
          <button className="icon-button" onClick={onCancel} aria-label="Close confirmation"><X size={18} /></button>
        </div>
        <p id="confirm-message">{message}</p>
        {children}
        <div className="dialog-actions">
          <button className="button secondary" onClick={onCancel}>Cancel</button>
          <button ref={initialFocus} className="button primary" onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
