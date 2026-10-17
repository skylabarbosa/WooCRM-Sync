import type { Dashboard, DatasetInfo, ImportResult, IntegrationStatus, OrderEvent, RiskEvaluation, RiskSettings } from "./types";

export const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function getDashboard(): Promise<Dashboard> {
  const response = await fetch(`${API}/api/woocrm/dashboard`);
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(result?.detail || "Unable to load dashboard data");
  return result;
}

export async function testConnection(): Promise<IntegrationStatus & { message: string }> {
  const response = await fetch(`${API}/api/woocrm/test-connection`, { method: "POST" });
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(result?.detail || "Connection test failed");
  return result;
}

export async function getDatasets(): Promise<{ datasets: DatasetInfo[] }> {
  const response = await fetch(`${API}/api/woocrm/datasets`);
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(result?.detail || "Unable to load datasets");
  return result;
}

export async function postAction(path: string): Promise<{ message: string; state?: string }> {
  const response = await fetch(`${API}/api/woocrm/${path}`, { method: "POST" });
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(result?.detail || result?.message || "Request failed");
  return result;
}

export async function getOrderHistory(orderId: string | number): Promise<OrderEvent[]> {
  const response = await fetch(`${API}/api/woocrm/orders/${encodeURIComponent(String(orderId))}/history`);
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(result?.detail || "Unable to load order history");
  return result.events;
}

export async function importFile(source: "orders" | "crm-orders", file: File, dataset: string): Promise<ImportResult> {
  const format = file.name.toLowerCase().endsWith(".csv") ? "csv" : "json";
  const response = await fetch(`${API}/api/woocrm/import/${source}?dataset=${encodeURIComponent(dataset || "default")}&format=${format}`, {
    method: "POST",
    headers: { "content-type": format === "csv" ? "text/csv" : "application/json" },
    body: file,
  });
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(result?.detail || "Import failed; no records were changed");
  return result;
}

export async function getRiskEvaluations(): Promise<{ evaluations: RiskEvaluation[] }> {
  const response = await fetch(`${API}/api/woocrm/risk-guard/evaluations`);
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(result?.detail || "Unable to load risk evaluations");
  return result;
}

export async function reviewRiskEvaluation(id: number, action: "approve" | "reject"): Promise<RiskEvaluation> {
  const response = await fetch(`${API}/api/woocrm/risk-guard/evaluations/${id}/${action}`, {
    method: "POST", headers: { "content-type": "application/json", "x-actor": "operator" }, body: JSON.stringify({ actor: "operator" }),
  });
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(result?.detail?.message || result?.detail || "Risk review failed");
  return result;
}

export async function getRiskSettings(): Promise<RiskSettings> {
  const response = await fetch(`${API}/api/woocrm/risk-guard/settings`);
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(result?.detail || "Unable to load Risk Guard settings");
  return result;
}

export async function updateRiskSettings(settings: RiskSettings): Promise<RiskSettings> {
  const response = await fetch(`${API}/api/woocrm/risk-guard/settings`, {
    method: "PUT",
    headers: { "content-type": "application/json", "x-actor": "operator" },
    body: JSON.stringify(settings),
  });
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(result?.detail || "Unable to save Risk Guard settings");
  return result;
}
