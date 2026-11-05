import { useState } from "react";

import { CustomerTable } from "../components/CustomerTable";
import { MetricPivot } from "../components/MetricPivot";
import { Card, Field, PageHeader, RoleGate, Select } from "../components/ui";
import { WhatIfForm } from "../components/WhatIfForm";
import { pct } from "../lib/format";

const SHOWN = ["pr_auc", "pr_auc_ci_low", "pr_auc_ci_high", "roc_auc", "lift_top_decile", "brier"];

export default function ChurnPage() {
  const [band, setBand] = useState("high");
  const [sort, setSort] = useState<"monetary" | "churn_risk" | "predicted_spend">("monetary");

  return (
    <RoleGate minimum="analyst">
      <PageHeader title="Churn prediction"
        description="Churn risk = 1 − P(repurchase within 90 days). With a 0.6% base rate almost everyone's risk is above 99%, so bands use propensity deciles (high = deciles 1–5). The list shows high-value customers in a band first." />
      <div className="mb-6 flex flex-wrap items-end gap-3 rounded-xl border border-border bg-surface p-4">
        <Field label="Risk band">
          <Select value={band} onChange={(e) => setBand(e.target.value)}>
            <option value="high">High (deciles 1–5)</option>
            <option value="medium">Medium (6–8)</option>
            <option value="low">Low (9–10)</option>
          </Select>
        </Field>
        <Field label="Order by">
          <Select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
            <option value="monetary">Historical spend</option>
            <option value="churn_risk">Churn risk</option>
            <option value="predicted_spend">Predicted spend</option>
          </Select>
        </Field>
      </div>
      <Card title="Customers to retain">
        <CustomerTable key={`${band}-${sort}`} path="/customers/churn-risk" filters={{ band }} defaultSort={sort}
          columns={["id", "state", "segment", "frequency", "monetary", "recency", "churn_risk", "band"]} />
      </Card>
      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card title="Model quality (untouched test cutoff 2018-05-01)"
          subtitle="PR-AUC is the primary metric (base rate ~0.6%). The selected model is not distinguishable from the frequency rule.">
          <MetricPivot model="repurchase_propensity" metrics={SHOWN} />
        </Card>
        <WhatIfForm endpoint="churn" render={(r) => (
          <p>
            P(repurchase within 90 days) = <strong>{pct(r.repurchase_probability_90d, 2)}</strong> · churn risk{" "}
            <strong>{pct(r.churn_risk_90d, 2)}</strong> · higher than {pct(r.propensity_percentile, 0)} of scored customers
            <span className="block text-xs text-muted">model v{String(r.model_version)} · {String(r.note)}</span>
          </p>
        )} />
      </div>
    </RoleGate>
  );
}
