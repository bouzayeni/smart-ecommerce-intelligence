import { useState } from "react";

import { RankedBars } from "../components/charts";
import { CustomerTable } from "../components/CustomerTable";
import { DataTable } from "../components/DataTable";
import { Async, Card, DataNote, PageHeader } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { useApi } from "../hooks/useApi";
import { brl, num, pct } from "../lib/format";
import type { DataNote as Note, Segment } from "../types/api";

export default function SegmentsPage() {
  const segments = useApi<{ segments: Segment[]; meta: Note }>("/customers/segments");
  const { hasRole } = useAuth();
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <>
      <PageHeader title="Customer segmentation (RFM)"
        description="Recency and monetary value are scored in quintiles. Frequency is rule-based because about 97% of customers ordered once. Rules are configurable (config/ml.yaml)." />
      <Async state={segments}>
        {({ segments: rows, meta }) => (
          <>
            <div className="grid gap-6 xl:grid-cols-2">
              <Card title="Customers per segment">
                <RankedBars data={rows} label="segment" value="customers" format={(v) => num(v)} />
              </Card>
              <Card title="Historical spend per segment" subtitle="Sum of GMV in the analysis window">
                <RankedBars data={rows} label="segment" value="total_monetary" format={(v) => brl(v)} />
              </Card>
            </div>
            <Card title="Segment profiles" className="mt-6" subtitle={hasRole("analyst") ? "Select a segment to list its customers" : undefined}>
              <DataTable<Segment> rows={rows} rowKey={(r) => r.segment} caption="Segment profiles"
                columns={[
                  { key: "segment", header: "Segment", value: (r) => r.segment, sortable: true,
                    render: (r) => hasRole("analyst")
                      ? <button className="text-accent hover:underline" onClick={() => setSelected(r.segment)}>{r.segment}</button>
                      : r.segment },
                  { key: "customers", header: "Customers", value: (r) => r.customers, sortable: true, align: "right", render: (r) => num(r.customers) },
                  { key: "rec", header: "Avg days since order", value: (r) => r.avg_recency_days, sortable: true, align: "right", render: (r) => num(r.avg_recency_days) },
                  { key: "freq", header: "Avg orders", value: (r) => r.avg_frequency, sortable: true, align: "right", render: (r) => num(r.avg_frequency, 2) },
                  { key: "mon", header: "Avg spend", value: (r) => r.avg_monetary, sortable: true, align: "right", render: (r) => brl(r.avg_monetary) },
                  { key: "p", header: "Avg P(repurchase 90d)", value: (r) => r.avg_repurchase_probability_90d, sortable: true, align: "right", render: (r) => pct(r.avg_repurchase_probability_90d, 2) },
                  { key: "spend", header: "Predicted 90d spend", value: (r) => r.predicted_spend_90d_brl, sortable: true, align: "right", render: (r) => brl(r.predicted_spend_90d_brl) },
                ]}
              />
            </Card>
            {selected && hasRole("analyst") && (
              <Card title={`Customers: ${selected}`} className="mt-6">
                <CustomerTable filters={{ segment: selected }} columns={["id", "state", "frequency", "monetary", "recency", "churn_risk", "predicted_spend"]} />
              </Card>
            )}
            <DataNote meta={meta} />
          </>
        )}
      </Async>
    </>
  );
}
