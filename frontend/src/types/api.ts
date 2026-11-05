// Response shapes of the FastAPI backend (docs/api.md). Numbers come straight from the warehouse.

export type Role = "viewer" | "analyst" | "admin";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface DataNote {
  source: string;
  window: string | null;
  filters: Record<string, unknown>;
  note: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Kpis {
  window_start: string;
  window_end: string;
  gmv: number;
  merchandise_value: number;
  freight_value: number;
  revenue_orders: number;
  avg_order_value: number;
  avg_freight_per_order: number;
  freight_share_of_gmv: number;
  customers: number;
  repeat_customers: number;
  repeat_purchase_rate: number;
  avg_orders_per_customer: number;
  all_orders: number;
  cancellation_rate: number;
  delivery_eligible_orders: number;
  avg_delivery_days: number;
  median_delivery_days: number;
  late_delivery_rate: number;
  on_time_delivery_rate: number;
  avg_review_score: number;
}

export interface MonthlySales {
  year_month: string;
  gmv: number;
  orders: number;
  customers: number;
  avg_order_value: number | null;
  is_complete_month: boolean;
  gmv_mom_growth: number | null;
}

export interface SalesResponse {
  totals: { gmv: number; orders: number; avg_order_value: number | null };
  monthly: MonthlySales[];
  by_category: { category_name: string; gmv: number; units: number }[];
  by_state: { state: string; gmv: number; orders: number }[];
  meta: DataNote;
}

export interface OperationsResponse {
  monthly: {
    year_month: string;
    all_orders: number;
    cancellation_rate: number;
    delivery_eligible_orders: number;
    avg_delivery_days: number | null;
    late_delivery_rate: number | null;
    avg_freight_per_order: number | null;
  }[];
  review_distribution: { review_score: number; orders: number; late_orders: number }[];
  delivery_by_state: {
    state: string;
    delivery_eligible_orders: number;
    avg_delivery_days: number;
    late_delivery_rate: number;
  }[];
  meta: DataNote;
}

export interface Filters {
  months: string[];
  states: string[];
  categories: string[];
}

export interface CustomerRow {
  customer_unique_id: string;
  customer_state: string;
  customer_city: string;
  first_order_at: string;
  last_order_at: string;
  order_count: number;
  recency_days: number;
  frequency: number;
  monetary: number;
  r_score: number;
  f_score: number;
  m_score: number;
  segment: string;
  repurchase_probability_90d: number;
  churn_risk_90d: number;
  propensity_decile: number;
  churn_risk_band: "high" | "medium" | "low";
  predicted_spend_brl: number;
}

export interface Reason {
  feature: string;
  value: number | string | null;
  effect: string;
  shap: number;
}

export interface Recommendation {
  rank: number;
  product_id: string;
  category_name: string | null;
  score: number;
  strategy?: string;
  similarity?: number;
}

export interface CustomerDetail extends CustomerRow {
  customer_zip_code_prefix: string;
  latitude: number | null;
  longitude: number | null;
  revenue_order_count: number;
  top_reasons: Reason[];
  scored_at_cutoff: string;
  churn_model_version: number;
  baseline_spend_brl: number;
  spend_model_version: number;
  orders: {
    order_id: string;
    purchased_at: string;
    order_status: string;
    gmv: number;
    item_count: number;
    review_score: number | null;
    is_late: boolean | null;
    delivery_days: number | null;
    customer_state_at_order: string;
  }[];
  recommendations: Recommendation[];
}

export interface Segment {
  segment: string;
  customers: number;
  avg_recency_days: number;
  avg_frequency: number;
  avg_monetary: number;
  total_monetary: number;
  avg_repurchase_probability_90d: number;
  predicted_spend_90d_brl: number;
}

export interface ForecastPoint {
  model: string;
  forecast_date: string;
  horizon_day: number;
  yhat: number;
  lower: number | null;
  upper: number | null;
  interval_source: string;
  is_selected: boolean;
}

export interface ForecastResponse {
  meta: DataNote & {
    selected_model: string;
    series_end: string;
    interval_level: number;
    generated_at: string;
  };
  points: ForecastPoint[];
  totals: { model: string; gmv_forecast: number; is_selected: boolean }[];
  history: { date_day: string; gmv: number }[];
}

export interface AnomalyDay {
  date: string;
  gmv_actual: number;
  gmv_expected: number;
  revenue_orders_actual: number;
  revenue_orders_expected: number;
  iforest_score: number;
  is_anomaly: boolean;
  is_anomaly_zrule: boolean;
  is_sustained_shift: boolean;
  driver_metric: string;
  driver_z: number;
  direction: "spike" | "drop";
  calendar_event: string;
  is_explained_by_calendar: boolean;
  explanation: string;
}

export interface ShiftEpisode {
  start: string;
  end: string;
  days: number;
  metric: string;
  peak_rolling_z: number;
  direction: "drop" | "rise";
  calendar_events: string;
}

export interface ModelMetrics {
  customer_models: {
    model_name: string;
    model_version: number;
    candidate: string;
    metric: string;
    value: number;
    trained_at: string;
  }[];
  forecasting: {
    model: string;
    split: "backtest" | "test";
    horizon: number;
    mae: number;
    rmse: number;
    wape: number;
    mape: number | null;
    interval_coverage: number | null;
  }[];
  recommendations: {
    split: string;
    segment: string;
    family: string;
    params: string;
    "hit_rate@10": number;
    "ndcg@10": number;
    "category_hit_rate@10": number;
    users: number;
  }[];
}

export interface ModelStatus {
  registry: { name: string; latest_version: string; created_at: number; run_id: string; status: string }[];
  tables: { table: string; rows: number; updated_at: string | null }[];
}

export interface QualityCheck {
  check_id: string;
  table: string;
  severity: "error" | "warn" | "info";
  description: string;
  failed: number;
  total: number;
  passed: boolean;
}

export interface DataQuality {
  generated_at: string;
  summary: { checks: number; error_failures: number; flagged: number };
  checks: QualityCheck[];
  window: Record<string, string | number>;
  dataset: string;
  orders_checked: number | null;
}

export interface ApiErrorBody {
  error: { code: string; message: string; request_id: string | null; details: unknown };
}
