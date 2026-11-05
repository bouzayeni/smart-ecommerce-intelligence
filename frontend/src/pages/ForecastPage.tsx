import { useMemo, useState } from "react";

import { ForecastChart, type ForecastRow } from "../components/charts";
import { COLORS } from "../lib/chartColors";
import { DataTable } from "../components/DataTable";
import { Async, Badge, Card, DataNote, Field, PageHeader, Select } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { brl, pct } from "../lib/format";
import type { ForecastResponse, ModelMetrics } from "../types/api";

const OTHER_COLORS = [COLORS.s2, COLORS.s3, COLORS.s4, COLORS.muted];

export default function ForecastPage() {
  const [horizon, setHorizon] = useState(30);
  const [highlight, setHighlight] = useState<string>("");
  const forecast = useApi<ForecastResponse>("/predictions/forecast", { horizon });
  const metrics = useApi<ModelMetrics>("/models/metrics");

  return (
    <>
      <PageHeader title="Sales forecasting"
        description="Daily GMV forecast for the days after the historical extract (no actuals exist for them). All five models are shown; the selected one was chosen on backtests." />
      <div className="mb-6 flex flex-wrap items-end gap-3 rounded-xl border border-border bg-surface p-4">
        <Field label="Horizon">
          <Select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
            {[30, 60, 90].map((h) => <option key={h} value={h}>{h} days</option>)}
          </Select>
        </Field>
        <Field label="Highlighted model">
          <Select value={highlight} onChange={(e) => setHighlight(e.target.value)}>
            <option value="">Selected model</option>
            {["seasonal_naive", "sarima", "prophet", "xgboost", "lstm"].map((m) => <option key={m} value={m}>{m}</option>)}
          </Select>
        </Field>
      </div>
      <Async state={forecast} empty={(f) => f.points.length === 0}>
        {(f) => <ForecastView f={f} highlight={highlight || f.meta.selected_model} />}
      </Async>

      <Card title="How the models performed" className="mt-6"
        subtitle="WAPE = Σ|error| ÷ Σ actual (lower is better). Backtest: mean of 3 rolling origins. Test: last 90 days of the data, used once.">
        <Async state={metrics}>
          {(m) => (
            <DataTable rows={m.forecasting.filter((r) => r.horizon === horizon)} rowKey={(r) => `${r.model}-${r.split}`}
              caption="Forecast accuracy"
              columns={[
                { key: "model", header: "Model", value: (r) => r.model, sortable: true },
                { key: "split", header: "Split", value: (r) => r.split, sortable: true },
                { key: "wape", header: `WAPE @${horizon}`, value: (r) => r.wape, sortable: true, align: "right", render: (r) => pct(r.wape) },
                { key: "mae", header: "MAE", value: (r) => r.mae, sortable: true, align: "right", render: (r) => brl(r.mae) },
                { key: "cov", header: "Interval coverage", value: (r) => r.interval_coverage, align: "right",
                  render: (r) => (r.interval_coverage === null ? "—" : pct(r.interval_coverage, 0)) },
              ]}
            />
          )}
        </Async>
        <p className="mt-3 text-xs text-text-2">
          The backtest-selected model did not beat the seasonal naive baseline on the test period, and its intervals were too narrow.
          The selection was not changed after seeing the test result (see the model card).
        </p>
      </Card>
    </>
  );
}

function ForecastView({ f, highlight }: { f: ForecastResponse; highlight: string }) {
  const models = useMemo(() => [...new Set(f.points.map((p) => p.model))], [f.points]);
  const rows = useMemo(() => {
    const byDate = new Map<string, ForecastRow>();
    for (const h of f.history) byDate.set(h.date_day.slice(0, 10), { date: h.date_day.slice(0, 10), actual: h.gmv });
    for (const p of f.points) {
      const d = p.forecast_date.slice(0, 10);
      const row = byDate.get(d) ?? { date: d };
      if (p.model === highlight) {
        row.forecast = p.yhat;
        row.band = p.lower !== null && p.upper !== null ? [p.lower, p.upper] : null;
      } else {
        row[p.model] = p.yhat;
      }
      byDate.set(d, row);
    }
    return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  }, [f, highlight]);
  const others = models.filter((m) => m !== highlight).map((m, i) => ({ key: m, name: m, color: OTHER_COLORS[i % OTHER_COLORS.length]! }));

  return (
    <>
      <Card title={`Daily GMV: last 120 days of data and the next ${f.points.length / models.length} days`}
        subtitle={<>Highlighted: <Badge tone="accent">{highlight}</Badge>{highlight === f.meta.selected_model && " (selected)"} · shaded band = {pct(f.meta.interval_level, 0)} prediction interval</>}>
        <ForecastChart data={rows} others={others} format={(v) => brl(v)} />
      </Card>
      <Card title="Forecast totals over the horizon" className="mt-6">
        <DataTable rows={f.totals} rowKey={(r) => r.model} caption="Forecast totals"
          columns={[
            { key: "model", header: "Model", value: (r) => r.model, sortable: true,
              render: (r) => <>{r.model} {r.is_selected && <Badge tone="accent">selected</Badge>}</> },
            { key: "gmv", header: "Forecast GMV", value: (r) => r.gmv_forecast, sortable: true, align: "right", render: (r) => brl(r.gmv_forecast) },
          ]}
        />
      </Card>
      <DataNote meta={f.meta} />
    </>
  );
}
