import { DataTable } from "../components/DataTable";
import { MetricPivot } from "../components/MetricPivot";
import { Async, Badge, Card, PageHeader } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { useApi } from "../hooks/useApi";
import { day, num, pct } from "../lib/format";
import type { ModelMetrics, ModelStatus } from "../types/api";

export default function ModelsPage() {
  const { hasRole } = useAuth();
  const status = useApi<ModelStatus>(hasRole("admin") ? "/models/status" : null);
  const metrics = useApi<ModelMetrics>("/models/metrics");

  return (
    <>
      <PageHeader title="Model monitoring"
        description="Registered model versions, freshness of the scored tables, and the held-out test metrics recorded at training time. Live drift monitoring is not implemented: the dataset is a static historical extract." />
      {hasRole("admin") && (
        <div className="grid gap-6 xl:grid-cols-2">
          <Card title="MLflow model registry">
            <Async state={status}>
              {(s) => (
                <DataTable rows={s.registry} rowKey={(r) => r.name} caption="Registered models"
                  columns={[
                    { key: "name", header: "Model", value: (r) => r.name },
                    { key: "v", header: "Latest version", value: (r) => Number(r.latest_version), align: "right" },
                    { key: "status", header: "Status", value: (r) => r.status, render: (r) => <Badge tone="good">{r.status}</Badge> },
                    { key: "created", header: "Registered", value: (r) => r.created_at, render: (r) => new Date(r.created_at).toISOString().slice(0, 16).replace("T", " ") },
                  ]}
                />
              )}
            </Async>
          </Card>
          <Card title="Scored tables">
            <Async state={status}>
              {(s) => (
                <DataTable rows={s.tables} rowKey={(r) => r.table} caption="Table freshness"
                  columns={[
                    { key: "t", header: "Table", value: (r) => r.table, render: (r) => <code className="text-xs">{r.table}</code> },
                    { key: "rows", header: "Rows", value: (r) => r.rows, align: "right", render: (r) => num(r.rows) },
                    { key: "u", header: "Updated", value: (r) => r.updated_at, render: (r) => day(r.updated_at) },
                  ]}
                />
              )}
            </Async>
          </Card>
        </div>
      )}
      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card title="Repurchase propensity (churn)">
          <MetricPivot model="repurchase_propensity" metrics={["pr_auc", "roc_auc", "lift_top_decile", "brier"]} />
        </Card>
        <Card title="90-day spend (CLV)">
          <MetricPivot model="customer_spend_90d" metrics={["rmse", "mae", "top_decile_spend_capture"]} />
        </Card>
        <Card title="Sales forecasting (90-day horizon)">
          <Async state={metrics}>
            {(m) => (
              <DataTable rows={m.forecasting.filter((r) => r.horizon === 90)} rowKey={(r) => `${r.model}-${r.split}`} caption="Forecast metrics"
                columns={[
                  { key: "model", header: "Model", value: (r) => r.model, sortable: true },
                  { key: "split", header: "Split", value: (r) => r.split, sortable: true },
                  { key: "wape", header: "WAPE", value: (r) => r.wape, sortable: true, align: "right", render: (r) => pct(r.wape) },
                  { key: "cov", header: "Coverage", value: (r) => r.interval_coverage, align: "right", render: (r) => (r.interval_coverage === null ? "—" : pct(r.interval_coverage, 0)) },
                ]}
              />
            )}
          </Async>
        </Card>
        <Card title="Model cards">
          <ul className="list-disc space-y-1 pl-5 text-sm text-text-2">
            {["repurchase_propensity", "customer_spend_90d", "rfm_segmentation", "sales_forecasting", "anomaly_detection", "recommendations"].map((c) => (
              <li key={c}><code>docs/model_cards/{c}.md</code></li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">Each card states its evaluation design, results with confidence intervals, and an explicit verdict against simple baselines.</p>
        </Card>
      </div>
    </>
  );
}
