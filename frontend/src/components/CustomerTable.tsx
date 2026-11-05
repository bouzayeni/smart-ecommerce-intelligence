import { useState } from "react";
import { Link } from "react-router";

import { useApi } from "../hooks/useApi";
import { brl, day, num, pct, shortId } from "../lib/format";
import type { CustomerRow, Page } from "../types/api";
import { DataTable, type Column } from "./DataTable";
import { Async, Badge } from "./ui";

export type CustomerSort = "monetary" | "recency" | "frequency" | "churn_risk" | "repurchase_probability" | "predicted_spend" | "last_order";

const BAND_TONE = { high: "critical", medium: "warning", low: "good" } as const;

/** Server-paginated customer list (analyst+). Sorting and filtering happen in the API. */
export function CustomerTable({ path = "/customers", filters = {}, defaultSort = "monetary", columns }: {
  path?: string;
  filters?: Record<string, string | undefined>;
  defaultSort?: CustomerSort;
  columns?: string[];
}) {
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<CustomerSort>(defaultSort);
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const state = useApi<Page<CustomerRow>>(path, { ...filters, page, page_size: 15, sort, order });

  const all: Column<CustomerRow>[] = [
    { key: "id", header: "Customer", render: (r) => <Link className="font-mono text-accent hover:underline" to={`/customers/${r.customer_unique_id}`}>{shortId(r.customer_unique_id)}</Link> },
    { key: "state", header: "State", render: (r) => r.customer_state },
    { key: "segment", header: "Segment", render: (r) => r.segment },
    { key: "frequency", header: "Orders", sortable: true, align: "right", render: (r) => num(r.frequency) },
    { key: "monetary", header: "Spend", sortable: true, align: "right", render: (r) => brl(r.monetary) },
    { key: "recency", header: "Days since order", sortable: true, align: "right", render: (r) => num(r.recency_days) },
    { key: "churn_risk", header: "Churn risk (90d)", sortable: true, align: "right", render: (r) => pct(r.churn_risk_90d, 2) },
    { key: "band", header: "Band", render: (r) => <Badge tone={BAND_TONE[r.churn_risk_band]}>{r.churn_risk_band}</Badge> },
    { key: "predicted_spend", header: "Predicted 90d spend", sortable: true, align: "right", render: (r) => brl(r.predicted_spend_brl, true) },
    { key: "last_order", header: "Last order", sortable: true, render: (r) => day(r.last_order_at) },
  ];
  const shown = columns ? all.filter((c) => columns.includes(c.key)) : all;

  return (
    <Async state={state}>
      {(p) => (
        <DataTable<CustomerRow>
          rows={p.items} rowKey={(r) => r.customer_unique_id} columns={shown} caption="Customers"
          server={{
            total: p.total, page: p.page, pageSize: p.page_size, onPage: setPage, sort, order,
            onSort: (key) => {
              if (key === sort) setOrder(order === "desc" ? "asc" : "desc");
              else { setSort(key as CustomerSort); setOrder("desc"); }
              setPage(1);
            },
          }}
        />
      )}
    </Async>
  );
}
