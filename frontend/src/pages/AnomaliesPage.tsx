import { useMemo } from "react";

import { AnomalyChart } from "../components/charts";
import { DataTable } from "../components/DataTable";
import { Async, Badge, Card, DataNote, PageHeader } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { brl, day, num, titleCase } from "../lib/format";
import type { AnomalyDay, DataNote as Note, ShiftEpisode } from "../types/api";

interface AnomalyResponse {
  days: AnomalyDay[];
  episodes: ShiftEpisode[];
  meta: Note;
}

export default function AnomaliesPage() {
  const all = useApi<AnomalyResponse>("/anomalies", { only_flagged: false });

  return (
    <>
      <PageHeader title="Anomaly detection"
        description="Days and multi-day stretches that deviate from trend and weekday seasonality (STL). Flags are leads to investigate, not confirmed incidents: there are no labelled incidents to measure precision against." />
      <Async state={all}>
        {(a) => <AnomalyView a={a} />}
      </Async>
    </>
  );
}

function AnomalyView({ a }: { a: AnomalyResponse }) {
  const series = useMemo(
    () => a.days.map((d) => ({
      date: day(d.date),
      actual: d.gmv_actual,
      expected: d.gmv_expected,
      flagged: d.is_anomaly && d.driver_metric === "gmv" ? d.gmv_actual : null,
    })),
    [a.days],
  );
  const flagged = a.days.filter((d) => d.is_anomaly);
  const explained = flagged.filter((d) => d.is_explained_by_calendar).length;

  return (
    <>
      <Card title="Daily GMV: actual vs expected" subtitle={`${flagged.length} anomaly days (${explained} coincide with a calendar event) · ${a.episodes.length} sustained shifts`}>
        <AnomalyChart data={series} x="date" actual="actual" expected="expected" flagged="flagged" format={(v) => brl(v)} />
      </Card>
      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card title="Anomaly days (Isolation Forest)" subtitle="Driver = the metric with the largest seasonally adjusted deviation">
          <DataTable<AnomalyDay> rows={flagged} rowKey={(r) => r.date} caption="Anomaly days"
            columns={[
              { key: "date", header: "Date", value: (r) => r.date, sortable: true, render: (r) => day(r.date) },
              { key: "driver", header: "Driver", value: (r) => r.driver_metric, render: (r) => titleCase(r.driver_metric) },
              { key: "dir", header: "Direction", value: (r) => r.direction,
                render: (r) => <Badge tone={r.direction === "drop" ? "critical" : "accent"}>{r.direction}</Badge> },
              { key: "z", header: "z", value: (r) => r.driver_z, sortable: true, align: "right", render: (r) => num(r.driver_z, 1) },
              { key: "event", header: "Calendar", value: (r) => r.calendar_event,
                render: (r) => (r.calendar_event ? <Badge tone="warning">{r.calendar_event}</Badge> : <span className="text-muted">—</span>) },
            ]}
          />
          <ul className="mt-4 space-y-2 text-xs text-text-2">
            {flagged.slice(0, 5).map((d) => <li key={d.date}><strong>{day(d.date)}</strong>: {d.explanation}</li>)}
          </ul>
        </Card>
        <Card title="Sustained shifts" subtitle="Seven-day mean of residual z beyond ±3 (GMV or orders)">
          <DataTable<ShiftEpisode> rows={a.episodes} rowKey={(r) => r.start} caption="Shift episodes"
            columns={[
              { key: "start", header: "Start", value: (r) => r.start, sortable: true, render: (r) => day(r.start) },
              { key: "end", header: "End", value: (r) => r.end, render: (r) => day(r.end) },
              { key: "days", header: "Days", value: (r) => r.days, align: "right" },
              { key: "dir", header: "Direction", value: (r) => r.direction,
                render: (r) => <Badge tone={r.direction === "drop" ? "critical" : "accent"}>{r.direction}</Badge> },
              { key: "z", header: "Peak z", value: (r) => r.peak_rolling_z, align: "right", render: (r) => num(r.peak_rolling_z, 1) },
              { key: "events", header: "Calendar events", value: (r) => r.calendar_events,
                render: (r) => r.calendar_events || <span className="text-muted">none (unexplained)</span> },
            ]}
          />
        </Card>
      </div>
      <DataNote meta={a.meta} />
    </>
  );
}
