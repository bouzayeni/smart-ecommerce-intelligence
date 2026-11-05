import { Link } from "react-router";

import { RankedBars, SignedBars, TimeSeriesChart } from "../components/charts";
import { COLORS } from "../lib/chartColors";
import { Async, Card, DataNote, KpiCard, KpiGrid, PageHeader } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { brl, num, pct, signedPct, titleCase } from "../lib/format";
import type { DataNote as Note, Kpis, SalesResponse } from "../types/api";

export default function ExecutivePage() {
  const overview = useApi<{ kpis: Kpis; meta: Note }>("/dashboard/overview");
  const sales = useApi<SalesResponse>("/dashboard/sales");

  return (
    <>
      <PageHeader
        title="Executive dashboard"
        description="Headline KPIs for the analysis window. GMV is gross merchandise value (price + freight) of non-cancelled orders, not profit."
      />
      <Async state={overview}>
        {({ kpis, meta }) => (
          <>
            <KpiGrid>
              <KpiCard label="GMV" value={brl(kpis.gmv)} hint={`${brl(kpis.merchandise_value)} merchandise`} />
              <KpiCard label="Orders" value={num(kpis.revenue_orders)} hint={`AOV ${brl(kpis.avg_order_value, true)}`} />
              <KpiCard label="Customers" value={num(kpis.customers)} hint={`${pct(kpis.repeat_purchase_rate, 2)} bought again`} />
              <KpiCard label="On-time delivery" value={pct(kpis.on_time_delivery_rate)} tone="good"
                hint={`median ${num(kpis.median_delivery_days, 1)} days`} />
              <KpiCard label="Cancellation rate" value={pct(kpis.cancellation_rate, 2)} hint="canceled + unavailable" />
              <KpiCard label="Avg review score" value={num(kpis.avg_review_score, 2)} hint="per order, 1–5" />
            </KpiGrid>
            <DataNote meta={meta} />
          </>
        )}
      </Async>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card title="Monthly GMV" subtitle="August 2018 is partial (data ends on the 21st)" className="xl:col-span-2">
          <Async state={sales}>
            {(s) => (
              <TimeSeriesChart data={s.monthly} x="year_month" format={(v) => brl(v)}
                series={[{ key: "gmv", name: "GMV", color: COLORS.s1, type: "bar" }]} />
            )}
          </Async>
        </Card>
        <Card title="Month-over-month growth" subtitle="Complete months only">
          <Async state={sales}>
            {(s) => (
              <SignedBars data={s.monthly.filter((m) => m.gmv_mom_growth !== null)} x="year_month"
                value="gmv_mom_growth" format={(v) => signedPct(v)} height={280} />
            )}
          </Async>
        </Card>
        <Card title="Top categories by GMV" subtitle="Item-level GMV" className="xl:col-span-2"
          actions={<Link to="/sales" className="text-xs text-accent hover:underline">Sales analytics →</Link>}>
          <Async state={sales}>
            {(s) => (
              <RankedBars data={s.by_category.slice(0, 10).map((c) => ({ ...c, category: titleCase(c.category_name) }))}
                label="category" value="gmv" format={(v) => brl(v)} />
            )}
          </Async>
        </Card>
        <Card title="GMV by customer state" subtitle="Location at order time">
          <Async state={sales}>
            {(s) => <RankedBars data={s.by_state.slice(0, 10)} label="state" value="gmv" format={(v) => brl(v)} color={COLORS.s3} />}
          </Async>
        </Card>
      </div>
    </>
  );
}
