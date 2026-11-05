import { RankedBars } from "../components/charts";
import { CustomerTable } from "../components/CustomerTable";
import { MetricPivot } from "../components/MetricPivot";
import { Async, Card, PageHeader, RoleGate } from "../components/ui";
import { WhatIfForm } from "../components/WhatIfForm";
import { useApi } from "../hooks/useApi";
import { brl } from "../lib/format";
import type { Segment } from "../types/api";

export default function ClvPage() {
  const segments = useApi<{ segments: Segment[] }>("/customers/segments");
  return (
    <RoleGate minimum="analyst">
      <PageHeader title="Customer lifetime value (90-day spend)"
        description="Predicted GMV in the next 90 days. Not profit (no cost data). More than 99% of customers spend nothing in the horizon, so models barely beat simple baselines; use this for ranking and portfolio totals, not individual promises." />
      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Predicted 90-day spend by segment">
          <Async state={segments}>
            {(s) => <RankedBars data={s.segments} label="segment" value="predicted_spend_90d_brl" format={(v) => brl(v)} />}
          </Async>
        </Card>
        <Card title="Model quality (test cutoff 2018-05-01)" subtitle="RMSE vs baselines; top-decile capture = share of actual spend among the top 10% predicted">
          <MetricPivot model="customer_spend_90d" metrics={["rmse", "mae", "top_decile_spend_capture", "spearman"]} />
        </Card>
      </div>
      <Card title="Highest predicted spend" className="mt-6">
        <CustomerTable defaultSort="predicted_spend"
          columns={["id", "state", "segment", "frequency", "monetary", "recency", "predicted_spend"]} />
      </Card>
      <div className="mt-6">
        <WhatIfForm endpoint="clv" render={(r) => (
          <p>Predicted spend in the next 90 days: <strong>{brl(r.predicted_spend_brl, true)}</strong>
            <span className="block text-xs text-muted">model v{String(r.model_version)} · {String(r.note)}</span></p>
        )} />
      </div>
    </RoleGate>
  );
}
