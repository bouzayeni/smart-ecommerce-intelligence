import { Link, useParams } from "react-router";

import { DataTable } from "../components/DataTable";
import { Async, Badge, Card, KpiCard, PageHeader, RoleGate } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { brl, day, num, pct, titleCase } from "../lib/format";
import type { CustomerDetail } from "../types/api";

export default function CustomerDetailPage() {
  const { customerId = "" } = useParams();
  const detail = useApi<CustomerDetail>(/^[0-9a-f]{32}$/.test(customerId) ? `/customers/${customerId}` : null);

  return (
    <RoleGate minimum="analyst">
      <PageHeader title="Customer 360" description={<span className="font-mono">{customerId}</span>}
        actions={<Link to="/customers" className="text-sm text-accent hover:underline">← All customers</Link>} />
      {!/^[0-9a-f]{32}$/.test(customerId) && <p className="text-sm text-critical">Invalid customer id.</p>}
      <Async state={detail}>
        {(c) => (
          <>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
              <KpiCard label="Segment" value={c.segment} hint={`RFM ${c.r_score}${c.f_score}${c.m_score}`} />
              <KpiCard label="Orders" value={num(c.frequency)} hint={`${num(c.recency_days)} days since last`} />
              <KpiCard label="Historical spend" value={brl(c.monetary)} />
              <KpiCard label="Churn risk (90 days)" value={pct(c.churn_risk_90d, 2)}
                hint={<>decile {c.propensity_decile}/10 · <Badge tone={c.churn_risk_band === "high" ? "critical" : c.churn_risk_band === "medium" ? "warning" : "good"}>{c.churn_risk_band}</Badge></>} />
              <KpiCard label="Predicted 90-day spend" value={brl(c.predicted_spend_brl, true)} hint={`rule baseline ${brl(c.baseline_spend_brl, true)}`} />
            </div>
            <div className="mt-6 grid gap-6 xl:grid-cols-3">
              <Card title="Why this churn score" subtitle={`Top SHAP drivers · model v${c.churn_model_version} · scored at ${day(c.scored_at_cutoff)}`}>
                <ul className="space-y-3">
                  {c.top_reasons.map((r) => (
                    <li key={r.feature} className="text-sm">
                      <span className="font-medium text-text">{titleCase(r.feature)}</span>
                      <span className="text-text-2"> = {r.value ?? "unknown"}</span>
                      <p className={r.shap > 0 ? "text-xs text-good" : "text-xs text-critical"}>{r.effect}</p>
                    </li>
                  ))}
                </ul>
                <p className="mt-4 text-xs text-muted">Churn = no repurchase within 90 days (an operational definition). The model barely beats a simple frequency rule; see the model card.</p>
              </Card>
              <Card title="Profile" className="xl:col-span-2">
                <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
                  {[
                    ["City / state", `${c.customer_city} / ${c.customer_state}`], ["Zip prefix", c.customer_zip_code_prefix],
                    ["First order", day(c.first_order_at)], ["Last order", day(c.last_order_at)],
                    ["Revenue orders", num(c.revenue_order_count)], ["P(repurchase 90d)", pct(c.repurchase_probability_90d, 2)],
                  ].map(([k, v]) => (
                    <div key={k}><dt className="text-xs text-muted">{k}</dt><dd className="text-text">{v}</dd></div>
                  ))}
                </dl>
              </Card>
            </div>
            <div className="mt-6 grid gap-6 xl:grid-cols-2">
              <Card title="Orders">
                <DataTable rows={c.orders} rowKey={(o) => o.order_id} caption="Orders"
                  columns={[
                    { key: "date", header: "Date", value: (o) => o.purchased_at, sortable: true, render: (o) => day(o.purchased_at) },
                    { key: "status", header: "Status", value: (o) => o.order_status },
                    { key: "gmv", header: "GMV", value: (o) => o.gmv, sortable: true, align: "right", render: (o) => brl(o.gmv, true) },
                    { key: "items", header: "Items", value: (o) => o.item_count, align: "right" },
                    { key: "review", header: "Review", value: (o) => o.review_score, align: "right", render: (o) => o.review_score ?? "—" },
                    { key: "late", header: "Late", value: (o) => (o.is_late === null ? null : o.is_late ? 1 : 0),
                      render: (o) => (o.is_late === null ? "—" : o.is_late ? <Badge tone="critical">late</Badge> : "on time") },
                  ]}
                />
              </Card>
              <Card title="Recommended products" subtitle="Personalised (content-based); products are anonymised in the dataset">
                <ol className="space-y-2 text-sm">
                  {c.recommendations.map((r) => (
                    <li key={r.product_id} className="flex items-center justify-between gap-3">
                      <span><span className="tabular text-muted">{r.rank}.</span> {titleCase(r.category_name ?? "unknown")}</span>
                      <span className="font-mono text-xs text-muted">{r.product_id.slice(0, 10)}…</span>
                    </li>
                  ))}
                </ol>
              </Card>
            </div>
          </>
        )}
      </Async>
    </RoleGate>
  );
}
