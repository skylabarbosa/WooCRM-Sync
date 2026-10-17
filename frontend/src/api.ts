import type { Dashboard, DatasetInfo, ImportResult, IntegrationStatus, OrderEvent, RiskEvaluation, RiskSettings } from "./types";

export const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const ACCESS_TOKEN_STORAGE = "woocrm-access-token";

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

export function getAccessToken(): string {
  return sessionStorage.getItem(ACCESS_TOKEN_STORAGE) || "";
}

export function setAccessToken(value: string): void {
  if (value.trim()) sessionStorage.setItem(ACCESS_TOKEN_STORAGE, value.trim());
  else sessionStorage.removeItem(ACCESS_TOKEN_STORAGE);
}

export async function login(username: string, password: string): Promise<{ access_token: string; role: string }> {
  return request("/api/woocrm/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

async function request(path: string, init: RequestInit = {}): Promise<any> {
  const headers = new Headers(init.headers);
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API}${path}`, { ...init, headers });
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new Event("woocrm-auth-required"));
      throw new ApiError(401, "Authentication required");
    }
    throw new ApiError(response.status, result?.detail || result?.message || "Request failed");
  }
  return result;
}

export async function getDashboard(): Promise<Dashboard> {
  return request("/api/woocrm/dashboard");
}

export async function testConnection(): Promise<IntegrationStatus & { message: string }> {
  return request("/api/woocrm/test-connection", { method: "POST" });
}

export async function getDatasets(): Promise<{ datasets: DatasetInfo[] }> {
  return request("/api/woocrm/datasets");
}

export async function postAction(path: string): Promise<{ message: string; state?: string }> {
  return request(`/api/woocrm/${path}`, { method: "POST" });
}

export async function getOrderHistory(orderId: string | number): Promise<OrderEvent[]> {
  const result = await request(`/api/woocrm/orders/${encodeURIComponent(String(orderId))}/history`);
  return result.events;
}

export async function importFile(source: "orders" | "crm-orders", file: File, dataset: string): Promise<ImportResult> {
  const format = file.name.toLowerCase().endsWith(".csv") ? "csv" : "json";
  return request(`/api/woocrm/import/${source}?dataset=${encodeURIComponent(dataset || "default")}&format=${format}`, {
    method: "POST",
    headers: { "content-type": format === "csv" ? "text/csv" : "application/json" },
    body: file,
  });
}

export async function getRiskEvaluations(): Promise<{ evaluations: RiskEvaluation[] }> {
  return request("/api/woocrm/risk-guard/evaluations");
}

export async function reviewRiskEvaluation(id: number, action: "approve" | "reject"): Promise<RiskEvaluation> {
  return request(`/api/woocrm/risk-guard/evaluations/${id}/${action}`, {
    method: "POST", headers: { "content-type": "application/json" },
  });
}

export async function getRiskSettings(): Promise<RiskSettings> {
  return request("/api/woocrm/risk-guard/settings");
}

export async function updateRiskSettings(settings: RiskSettings): Promise<RiskSettings> {
  return request("/api/woocrm/risk-guard/settings", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(settings),
  });
}
