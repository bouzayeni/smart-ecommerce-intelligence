import { useState } from "react";

import { RankedBars, TimeSeriesChart } from "../components/charts";
import { COLORS } from "../lib/chartColors";
import { DataTable } from "../components/DataTable";
import { FilterBar, type FilterValues } from "../components/FilterBar";
import { Async, Card, DataNote, KpiCard, PageHeader } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { brl, num, signedPct, titleCase } from "../lib/format";
import type { MonthlySales, SalesResponse } from "../types/api";

export default function SalesPage() {
  const [filters, setFilters] = useState<FilterValues>({});
  const sales = useApi<SalesResponse>("/dashboard/sales", { ...filters });

  return (
    <>
      <PageHeader title="Sales analytics"
        description="Revenue (GMV) by month, category and region. Choosing a category switches to item-level GMV, because an order can mix categories." />
      <FilterBar value={filters} onChange={setFilters} />
      <Async state={sales} empty={(s) => s.monthly.length === 0}>
        {(s) => (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <KpiCard label="GMV" value={brl(s.totals.gmv)} />
              <KpiCard label="Orders" value={num(s.totals.orders)} />
              <KpiCard label="Average order value" value={brl(s.totals.avg_order_value, true)} />
            </div>
            <div className="mt-6 grid gap-6 xl:grid-cols-2">
              <Card title="GMV by month">
                <TimeSeriesChart data={s.monthly} x="year_month" format={(v) => brl(v)}
                  series={[{ key: "gmv", name: "GMV", color: COLORS.s1, type: "bar" }]} />
              </Card>
              <Card title="Orders and customers by month" subtitle="Both are counts, so they share one axis">
                <TimeSeriesChart data={s.monthly} x="year_month" format={(v) => num(v)}
                  series={[{ key: "orders", name: "Orders", color: COLORS.s1 }, { key: "customers", name: "Customers", color: COLORS.s2 }]} />
              </Card>
              <Card title="Categories">
                <RankedBars data={s.by_category.map((c) => ({ ...c, category: titleCase(c.category_name) }))}
                  label="category" value="gmv" format={(v) => brl(v)} />
              </Card>
              <Card title="Customer states">
                <RankedBars data={s.by_state.slice(0, 15)} label="state" value="gmv" format={(v) => brl(v)} color={COLORS.s3} />
              </Card>
            </div>
            <Card title="Monthly detail" className="mt-6">
              <DataTable<MonthlySales>
                rows={s.monthly} rowKey={(r) => r.year_month} pageSize={24} caption="Monthly sales"
                columns={[
                  { key: "year_month", header: "Month", value: (r) => r.year_month, sortable: true,
                    render: (r) => <>{r.year_month}{!r.is_complete_month && <span className="ml-2 text-xs text-muted">partial</span>}</> },
                  { key: "gmv", header: "GMV", value: (r) => r.gmv, sortable: true, align: "right", render: (r) => brl(r.gmv) },
                  { key: "orders", header: "Orders", value: (r) => r.orders, sortable: true, align: "right", render: (r) => num(r.orders) },
                  { key: "aov", header: "AOV", value: (r) => r.avg_order_value, sortable: true, align: "right", render: (r) => brl(r.avg_order_value, true) },
                  { key: "mom", header: "MoM", value: (r) => r.gmv_mom_growth, sortable: true, align: "right", render: (r) => signedPct(r.gmv_mom_growth) },
                ]}
              />
            </Card>
            <DataNote meta={s.meta} />
          </>
        )}
      </Async>
    </>
  );
}
