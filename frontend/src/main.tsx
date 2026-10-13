import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, ArrowRight, CheckCircle2, Database, RefreshCw, RotateCcw, ShoppingCart, Users, type LucideIcon } from "lucide-react";
import "./index.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
type Order = { id:number; customer_email:string; customer_name:string; total:number; currency:string; status:string };
type Customer = { email:string; name:string; order_count:number; lifetime_value:number; last_synced_at?:string };
type Dashboard = { orders:Order[]; customers:Customer[]; eligible_order_count:number; eligible_customer_count:number; last_run:any };

function App() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("Ready to sync demo data.");
  async function load() { const response = await fetch(`${API}/api/woocrm/dashboard`); setData(await response.json()); }
  async function action(path:string, label:string) {
    setBusy(true); setNotice(`${label}...`);
    try { const response = await fetch(`${API}/api/woocrm/${path}`, { method:"POST" }); const result = await response.json(); setNotice(result.message || `${label} complete.`); await load(); }
    catch { setNotice("Backend unavailable. Start FastAPI on port 8000."); }
    finally { setBusy(false); }
  }
  useEffect(() => { load().catch(() => setNotice("Backend unavailable. Start FastAPI on port 8000.")); }, []);
  if (!data) return <main className="min-h-screen grid place-items-center text-slate-500">Loading WooCRM Sync...</main>;
  const eligible = data.orders.filter(o => ["processing","completed"].includes(o.status));
  return <main className="min-h-screen">
    <header className="bg-white border-b border-slate-200"><div className="max-w-7xl mx-auto px-6 py-5 flex items-center justify-between">
      <div className="flex items-center gap-3"><div className="bg-indigo-600 text-white rounded-xl p-2"><Activity size={22}/></div><div><h1 className="font-bold text-xl">WooCRM Sync</h1><p className="text-xs text-slate-500">WooCommerce → CRM reconciliation</p></div></div>
      <div className="flex gap-3"><button disabled={busy} onClick={() => action("reset","Resetting demo")} className="px-4 py-2 rounded-lg border border-slate-200 text-sm flex items-center gap-2 hover:bg-slate-50"><RotateCcw size={15}/> Reset demo</button><button disabled={busy} onClick={() => action("sync","Syncing")} className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-semibold flex items-center gap-2 hover:bg-indigo-700"><RefreshCw size={15}/> Sync now</button></div>
    </div></header>
    <div className="max-w-7xl mx-auto px-6 py-8"><div className="flex items-center gap-2 text-sm text-slate-500 mb-6"><span className="w-2 h-2 bg-emerald-500 rounded-full"></span> {notice}</div>
      <section className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">{([
        { label: "Eligible orders", value: data.eligible_order_count, Icon: ShoppingCart, sub: "of 10 total" },
        { label: "CRM customers", value: data.customers.length, Icon: Users, sub: `${data.eligible_customer_count} eligible groups` },
        { label: "Last sync", value: data.last_run ? "Complete" : "Not yet", Icon: CheckCircle2, sub: data.last_run ? `Run #${data.last_run.id}` : "Run a sync to begin" },
        { label: "Data source", value: "Mock", Icon: Database, sub: "Deterministic demo" },
      ] as { label: string; value: string | number; Icon: LucideIcon; sub: string }[]).map(({ label, value, Icon, sub }) => <div className="bg-white border border-slate-200 rounded-2xl p-5" key={label}><div className="flex justify-between"><p className="text-sm text-slate-500">{label}</p><Icon size={18} className="text-indigo-500"/></div><p className="text-2xl font-bold mt-3">{String(value)}</p><p className="text-xs text-slate-400 mt-1">{sub}</p></div>)}</section>
      <div className="grid lg:grid-cols-5 gap-6"><section className="lg:col-span-3 bg-white border border-slate-200 rounded-2xl overflow-hidden"><div className="px-5 py-4 border-b border-slate-100 flex justify-between"><div><h2 className="font-semibold">WooCommerce orders</h2><p className="text-xs text-slate-500 mt-1">Eligibility: processing or completed orders</p></div><span className="text-xs bg-indigo-50 text-indigo-700 px-2 py-1 rounded-full h-fit">{eligible.length} eligible</span></div><div className="divide-y divide-slate-100">{data.orders.map(o => <div className="px-5 py-3 flex items-center justify-between" key={o.id}><div className="flex items-center gap-3"><span className={`w-2 h-2 rounded-full ${["processing","completed"].includes(o.status) ? "bg-emerald-500" : "bg-slate-300"}`}></span><div><p className="text-sm font-medium">#{o.id} · {o.customer_name}</p><p className="text-xs text-slate-400">{o.customer_email}</p></div></div><div className="text-right"><p className="text-sm font-semibold">${o.total.toFixed(2)}</p><p className="text-xs text-slate-400 capitalize">{o.status}</p></div></div>)}</div></section>
      <section className="lg:col-span-2 bg-white border border-slate-200 rounded-2xl overflow-hidden"><div className="px-5 py-4 border-b border-slate-100"><h2 className="font-semibold">CRM customer groups</h2><p className="text-xs text-slate-500 mt-1">Grouped by normalized email</p></div><div className="divide-y divide-slate-100">{data.customers.map(c => <div className="px-5 py-4 flex items-center justify-between" key={c.email}><div><p className="text-sm font-medium">{c.name}</p><p className="text-xs text-slate-400">{c.email}</p></div><div className="text-right"><p className="text-sm font-semibold">${c.lifetime_value.toFixed(2)}</p><p className="text-xs text-slate-400">{c.order_count} orders</p></div></div>)}</div><div className="m-5 p-4 bg-indigo-50 rounded-xl text-sm text-indigo-900 flex gap-3"><ArrowRight size={18} className="shrink-0 mt-0.5"/><span>Replay syncs are safe: only changed customer totals are updated.</span></div></section></div>
    </div>
  </main>;
}
createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
