import { useApi } from "../hooks/useApi";
import { num } from "../lib/format";
import type { ModelMetrics } from "../types/api";
import { DataTable } from "./DataTable";
import { Async } from "./ui";

/** Test metrics of one registered customer model, one row per candidate/baseline. */
export function MetricPivot({ model, metrics }: { model: string; metrics: string[] }) {
  const m = useApi<ModelMetrics>("/models/metrics");
  return (
    <Async state={m}>
      {(data) => {
        const rows = new Map<string, Record<string, number | string>>();
        for (const r of data.customer_models.filter((x) => x.model_name === model && metrics.includes(x.metric))) {
          rows.set(r.candidate, { ...(rows.get(r.candidate) ?? { candidate: r.candidate }), [r.metric]: r.value });
        }
        return (
          <DataTable rows={[...rows.values()]} rowKey={(r) => String(r.candidate)} caption={`${model} test metrics`}
            columns={[
              { key: "candidate", header: "Model", value: (r) => String(r.candidate), sortable: true },
              ...metrics.map((k) => ({
                key: k, header: k.replace(/_/g, " "), align: "right" as const, sortable: true,
                value: (r: Record<string, number | string>) => (typeof r[k] === "number" ? (r[k] as number) : null),
                render: (r: Record<string, number | string>) => (typeof r[k] === "number" ? num(r[k], 4) : "—"),
              })),
            ]}
          />
        );
      }}
    </Async>
  );
}
