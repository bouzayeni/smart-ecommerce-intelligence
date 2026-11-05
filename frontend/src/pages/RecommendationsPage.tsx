import { useState } from "react";

import { DataTable } from "../components/DataTable";
import { Async, Badge, Card, Field, Input, PageHeader, RoleGate } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { num, pct, titleCase } from "../lib/format";
import type { ModelMetrics, Recommendation } from "../types/api";

const HEX = /^[0-9a-f]{32}$/;

export default function RecommendationsPage() {
  const [customer, setCustomer] = useState("");
  const [state, setState] = useState("SP");
  const [product, setProduct] = useState("");
  const recs = useApi<{ strategy: string; items: Recommendation[] }>(
    HEX.test(customer) ? `/recommendations/${customer}` : null, { state: /^[A-Z]{2}$/.test(state) ? state : undefined });
  const similar = useApi<{ items: Recommendation[] }>(HEX.test(product) ? `/recommendations/products/${product}/similar` : null);
  const metrics = useApi<ModelMetrics>("/models/metrics");

  return (
    <RoleGate minimum="analyst">
      <PageHeader title="Product recommendations"
        description="Returning customers get content-based recommendations (category, price band, size). Unknown customers get the popular list for their state. Product names are not in the dataset, only ids and categories." />
      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Recommendations for a customer">
          <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
            <Field label="Customer id (32 hex)"><Input value={customer} onChange={(e) => setCustomer(e.target.value.trim().toLowerCase())} placeholder="paste a customer_unique_id" /></Field>
            <Field label="State (cold start)"><Input value={state} maxLength={2} onChange={(e) => setState(e.target.value.toUpperCase())} /></Field>
          </div>
          <div className="mt-4">
            {!HEX.test(customer) ? <p className="text-sm text-muted">Enter a customer id. Tip: copy one from Customer 360. Any unknown id shows the cold-start list.</p> : (
              <Async state={recs}>
                {(r) => (
                  <>
                    <p className="mb-3 text-sm">Strategy: <Badge tone="accent">{r.strategy}</Badge></p>
                    <RecList items={r.items} onPick={setProduct} />
                  </>
                )}
              </Async>
            )}
          </div>
        </Card>
        <Card title="Customers also bought" subtitle="Co-purchase similarity (item-item). Most products have no co-purchases.">
          <Field label="Product id"><Input value={product} onChange={(e) => setProduct(e.target.value.trim().toLowerCase())} placeholder="click a product on the left, or paste an id" /></Field>
          <div className="mt-4">
            {!HEX.test(product) ? <p className="text-sm text-muted">Select a product.</p> : (
              <Async state={similar} empty={(s) => s.items.length === 0}>
                {(s) => <RecList items={s.items} onPick={setProduct} />}
              </Async>
            )}
          </div>
        </Card>
      </div>
      <Card title="Offline evaluation" className="mt-6" subtitle="Temporal split; hit rate = at least one bought product in the top 10. Category hit rate = one of their categories.">
        <Async state={metrics}>
          {(m) => (
            <DataTable rows={m.recommendations.filter((r) => r.split === "test")} rowKey={(r) => `${r.segment}-${r.family}-${r.params}`}
              caption="Recommendation metrics"
              columns={[
                { key: "segment", header: "Customers", value: (r) => r.segment, sortable: true },
                { key: "family", header: "Model", value: (r) => r.family, sortable: true },
                { key: "hit", header: "Hit rate@10", value: (r) => r["hit_rate@10"], sortable: true, align: "right", render: (r) => pct(r["hit_rate@10"], 2) },
                { key: "ndcg", header: "NDCG@10", value: (r) => r["ndcg@10"], sortable: true, align: "right", render: (r) => num(r["ndcg@10"], 4) },
                { key: "cat", header: "Category hit@10", value: (r) => r["category_hit_rate@10"], sortable: true, align: "right", render: (r) => pct(r["category_hit_rate@10"], 1) },
                { key: "users", header: "Users", value: (r) => r.users, align: "right", render: (r) => num(r.users) },
              ]}
            />
          )}
        </Async>
      </Card>
    </RoleGate>
  );
}

function RecList({ items, onPick }: { items: Recommendation[]; onPick: (id: string) => void }) {
  return (
    <ol className="space-y-2 text-sm">
      {items.map((r) => (
        <li key={r.product_id} className="flex items-center justify-between gap-3">
          <span><span className="tabular text-muted">{r.rank}.</span> {titleCase(r.category_name ?? "unknown")}</span>
          <button className="font-mono text-xs text-accent hover:underline" onClick={() => onPick(r.product_id)}
            title="Show similar products">{r.product_id.slice(0, 12)}…</button>
        </li>
      ))}
    </ol>
  );
}
