import { useState } from "react";

import { DataTable } from "../components/DataTable";
import { Async, Badge, Card, Field, KpiCard, PageHeader, RoleGate, Select } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { num, pct } from "../lib/format";
import type { DataQuality, QualityCheck } from "../types/api";

export default function DataQualityPage() {
  const dq = useApi<DataQuality>("/data-quality");
  const [severity, setSeverity] = useState("");
  const [onlyFlagged, setOnlyFlagged] = useState(true);

  return (
    <RoleGate minimum="admin">
      <PageHeader title="Data quality monitoring"
        description="Results of the 79-check catalog run on the raw extract. Error-level checks block the warehouse load; warn-level issues are kept and flagged (never silently dropped)." />
      <Async state={dq}>
        {(d) => {
          const rows = d.checks.filter((c) => (!severity || c.severity === severity) && (!onlyFlagged || !c.passed));
          return (
            <>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
                <KpiCard label="Checks" value={num(d.summary.checks)} hint={`on ${d.dataset} (${num(d.orders_checked)} orders)`} />
                <KpiCard label="Error-level failures" value={num(d.summary.error_failures)} tone={d.summary.error_failures ? "critical" : "good"} />
                <KpiCard label="Flagged (warn/info)" value={num(d.summary.flagged)} tone="warning" />
                <KpiCard label="Analysis window" value={`${String(d.window.start)} → ${String(d.window.end)}`} hint={`run ${d.generated_at.slice(0, 10)}`} />
              </div>
              <Card className="mt-6" title="Checks"
                actions={
                  <div className="flex gap-3">
                    <Field label="Severity">
                      <Select value={severity} onChange={(e) => setSeverity(e.target.value)}>
                        <option value="">All</option><option value="error">Error</option><option value="warn">Warn</option><option value="info">Info</option>
                      </Select>
                    </Field>
                    <Field label="Show">
                      <Select value={onlyFlagged ? "flagged" : "all"} onChange={(e) => setOnlyFlagged(e.target.value === "flagged")}>
                        <option value="flagged">Flagged only</option><option value="all">All checks</option>
                      </Select>
                    </Field>
                  </div>
                }>
                <DataTable<QualityCheck> rows={rows} rowKey={(r) => r.check_id} searchable pageSize={15} caption="Quality checks"
                  columns={[
                    { key: "id", header: "Check", value: (r) => r.check_id, sortable: true, render: (r) => <code className="text-xs">{r.check_id}</code> },
                    { key: "sev", header: "Severity", value: (r) => r.severity, sortable: true,
                      render: (r) => <Badge tone={r.severity === "error" ? "critical" : r.severity === "warn" ? "warning" : "neutral"}>{r.severity}</Badge> },
                    { key: "res", header: "Result", value: (r) => (r.passed ? 1 : 0),
                      render: (r) => (r.passed ? <span className="text-good">pass</span> : <span className="text-warning">flagged</span>) },
                    { key: "rows", header: "Rows", value: (r) => r.failed, sortable: true, align: "right",
                      render: (r) => `${num(r.failed)} / ${num(r.total)} (${pct(r.total ? r.failed / r.total : 0, 2)})` },
                    { key: "rule", header: "Rule", value: (r) => r.description },
                  ]}
                />
              </Card>
            </>
          );
        }}
      </Async>
    </RoleGate>
  );
}
