import type { ReactNode } from "react";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { COLORS } from "../lib/chartColors";
import { compact } from "../lib/format";


const axis = { stroke: COLORS.grid, tick: { fill: COLORS.text, fontSize: 11 }, tickLine: false };

function TooltipBox({ active, payload, label, format }: {
  active?: boolean; payload?: { name?: string; value?: unknown; color?: string }[]; label?: ReactNode;
  format: (v: unknown, name?: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium text-text">{label}</p>
      {payload.filter((p) => p.value !== undefined && p.value !== null).map((p) => (
        <p key={p.name} className="flex items-center gap-2 text-text-2">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: p.color }} aria-hidden="true" />
          <span>{p.name}</span>
          <span className="tabular ml-auto font-medium text-text">{format(p.value, p.name)}</span>
        </p>
      ))}
    </div>
  );
}

export interface SeriesDef {
  key: string;
  name: string;
  color: string;
  type?: "line" | "bar";
}

/** Time series with one or more line/bar series on a single axis (never dual-axis). */
export function TimeSeriesChart({ data, x, series, format, height = 280 }: {
  data: readonly object[]; x: string; series: SeriesDef[]; format: (v: unknown) => string; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={COLORS.grid} vertical={false} />
        <XAxis dataKey={x} {...axis} minTickGap={24} />
        <YAxis {...axis} tickFormatter={compact} width={56} />
        <Tooltip content={<TooltipBox format={format} />} />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {series.map((s) =>
          s.type === "bar" ? (
            <Bar key={s.key} dataKey={s.key} name={s.name} fill={s.color} radius={[4, 4, 0, 0]} />
          ) : (
            <Line key={s.key} dataKey={s.key} name={s.name} stroke={s.color} strokeWidth={2} dot={false} connectNulls />
          ),
        )}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/** Horizontal ranked bars: categories, states, segments. */
export function RankedBars({ data, label, value, format, height, color = COLORS.s1 }: {
  data: readonly object[]; label: string; value: string; format: (v: unknown) => string;
  height?: number; color?: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height ?? Math.max(160, data.length * 28 + 24)}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 8 }}>
        <CartesianGrid stroke={COLORS.grid} horizontal={false} />
        <XAxis type="number" {...axis} tickFormatter={compact} />
        <YAxis type="category" dataKey={label} {...axis} width={150} interval={0} />
        <Tooltip content={<TooltipBox format={format} />} cursor={{ fill: "var(--surface-2)" }} />
        <Bar dataKey={value} name={value.replace(/_/g, " ")} fill={color} radius={[0, 4, 4, 0]} barSize={16} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Signed bars (growth): positive and negative in two colours. */
export function SignedBars({ data, x, value, format, height = 220 }: {
  data: readonly object[]; x: string; value: string; format: (v: unknown) => string; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={COLORS.grid} vertical={false} />
        <XAxis dataKey={x} {...axis} minTickGap={24} />
        <YAxis {...axis} tickFormatter={(v) => `${Math.round(Number(v) * 100)}%`} width={48} />
        <Tooltip content={<TooltipBox format={format} />} cursor={{ fill: "var(--surface-2)" }} />
        <Bar dataKey={value} name="MoM growth" radius={[4, 4, 4, 4]}>
          {data.map((d, i) => (
            <Cell key={i} fill={Number((d as Record<string, unknown>)[value]) >= 0 ? COLORS.s1 : COLORS.s2} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export interface ForecastRow {
  date: string;
  actual?: number | null;
  forecast?: number | null;
  band?: [number, number] | null;
  [model: string]: unknown;
}

/** History + forecast with a shaded prediction interval for the highlighted model. */
export function ForecastChart({ data, others, format, height = 320 }: {
  data: ForecastRow[]; others: { key: string; name: string; color: string }[]; format: (v: unknown) => string;
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={COLORS.grid} vertical={false} />
        <XAxis dataKey="date" {...axis} minTickGap={32} />
        <YAxis {...axis} tickFormatter={compact} width={56} />
        <Tooltip content={<TooltipBox format={(v) => (Array.isArray(v) ? `${format(v[0])} – ${format(v[1])}` : format(v))} />} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Area dataKey="band" name="Prediction interval" fill={COLORS.s1} fillOpacity={0.15} stroke="none" connectNulls />
        <Line dataKey="actual" name="Actual" stroke="var(--text)" strokeWidth={1.5} dot={false} connectNulls />
        <Line dataKey="forecast" name="Forecast (highlighted)" stroke={COLORS.s1} strokeWidth={2.5} dot={false} connectNulls />
        {others.map((o) => (
          <Line key={o.key} dataKey={o.key} name={o.name} stroke={o.color} strokeWidth={1} strokeOpacity={0.7} dot={false} connectNulls />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/** Actual vs expected with flagged days as points. */
export function AnomalyChart({ data, x, actual, expected, flagged, format, height = 300 }: {
  data: readonly object[]; x: string; actual: string; expected: string;
  flagged: string; format: (v: unknown) => string; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={COLORS.grid} vertical={false} />
        <XAxis dataKey={x} {...axis} minTickGap={32} />
        <YAxis {...axis} tickFormatter={compact} width={56} />
        <Tooltip content={<TooltipBox format={format} />} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line dataKey={actual} name="Actual" stroke="var(--text)" strokeWidth={1} dot={false} />
        <Line dataKey={expected} name="Expected (trend + weekday)" stroke={COLORS.s1} strokeWidth={2} dot={false} />
        <Scatter dataKey={flagged} name="Anomaly" fill={COLORS.critical} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
