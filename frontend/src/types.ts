export type SyncState = "SYNCED" | "MISSING" | "ERROR" | "MISMATCH" | "NOT_ELIGIBLE";

export type CrmOrder = {
  total: number;
  currency: string;
  email: string;
  name?: string;
  status: string;
  order_status?: string;
  updated_at?: string;
  error_message?: string | null;
};

export type Order = {
  id: number | string;
  customer_email: string;
  customer_name: string;
  total: number;
  currency: string;
  status: string;
  created_at: string;
  state: SyncState;
  crm: CrmOrder | null;
};

export type CustomerGroup = {
  email: string;
  name: string;
  order_count: number;
  lifetime_value: number;
  synced_count: number;
  attention_count: number;
  attention_details: string[];
  crm_contact_status: "FOUND" | "NOT_FOUND" | "UNKNOWN";
  crm_contact_id: string | null;
  crm_contact_verified_at: string | null;
  last_activity: string | null;
  sync_state: "SYNCED" | "NEEDS_ATTENTION";
};

export type SyncRun = {
  id: number;
  started_at: string;
  completed_at?: string | null;
  processed: number;
  created: number;
  updated: number;
  skipped: number;
  status: string;
};

export type Dashboard = {
  orders: Order[];
  groups: CustomerGroup[];
  customers: Array<Record<string, unknown>>;
  eligible_order_count: number;
  eligible_customer_count: number;
  contact_counts: { FOUND: number; NOT_FOUND: number; UNKNOWN: number };
  customer_attention_count: number;
  counts: Record<SyncState, number>;
  last_run: SyncRun | null;
  integration: IntegrationStatus;
};

export type IntegrationStatus = {
  mode: "demo" | "live";
  provider: string;
  writes_enabled: boolean;
  configured: boolean;
  connection?: string;
  store_url?: string;
};

export type OrderEvent = {
  id: number;
  event_type: "replay" | "mismatch_correction" | "reconciliation";
  outcome: "verified" | "failed" | "blocked" | "completed";
  message: string;
  error_message?: string | null;
  before_values?: Record<string, string | number> | null;
  after_values?: Record<string, string | number> | null;
  created_at: string;
};

export type ImportResult = {
  imported: number;
  inserted: number;
  skipped: number;
  rejected: number;
  source: "woo" | "crm";
  dataset: string;
  message: string;
};

export type RiskEvaluation = {
  id: number;
  dataset: string;
  order_id: string;
  field: string;
  risk_status: "CLEAR" | "REVIEW_REQUIRED" | "BLOCKED";
  rule_ids: string[];
  explanation: string[];
  existing_value: Record<string, unknown> | null;
  proposed_value: Record<string, unknown> | null;
  evidence: unknown;
  required_action: string;
  evaluated_at: string;
  approved: boolean;
  outcome: string;
  rules?: Array<{ id: string; explanation: string; evidence: unknown; status: string }>;
  fingerprint?: string;
  approval_at?: string | null;
};

export type RiskSettings = {
  absolute_total_change: number;
  percentage_total_change: number;
  batch_change_limit: number;
  newer_crm_policy: "review" | "block";
  missing_timestamp_policy: "review" | "allow";
};

export type DatasetInfo = {
  name: string;
  order_count: number;
  crm_record_count: number;
  customer_count: number;
  source: string;
  environment: string;
  last_run: { completed_at?: string | null; status: string } | null;
  resettable: boolean;
};
