import { useApi } from "../hooks/useApi";
import { titleCase } from "../lib/format";
import type { Filters } from "../types/api";
import { Button, Field, Select } from "./ui";

export interface FilterValues {
  date_from?: string;
  date_to?: string;
  state?: string;
  category?: string;
}

/** One filter row above the charts; options come from the API (no hard-coded lists). */
export function FilterBar({ value, onChange, fields = ["months", "state", "category"] }: {
  value: FilterValues;
  onChange: (v: FilterValues) => void;
  fields?: ("months" | "state" | "category")[];
}) {
  const { data } = useApi<Filters>("/dashboard/filters");
  const set = (patch: FilterValues) => onChange({ ...value, ...patch });
  const months = data?.months ?? [];
  return (
    <div className="mb-6 flex flex-wrap items-end gap-3 rounded-xl border border-border bg-surface p-4">
      {fields.includes("months") && (
        <>
          <Field label="From month">
            <Select value={value.date_from ?? ""} onChange={(e) => set({ date_from: e.target.value || undefined })}>
              <option value="">Window start</option>
              {months.map((m) => <option key={m} value={m}>{m}</option>)}
            </Select>
          </Field>
          <Field label="To month">
            <Select value={value.date_to ?? ""} onChange={(e) => set({ date_to: e.target.value || undefined })}>
              <option value="">Window end</option>
              {months.map((m) => <option key={m} value={m}>{m}</option>)}
            </Select>
          </Field>
        </>
      )}
      {fields.includes("state") && (
        <Field label="Customer state">
          <Select value={value.state ?? ""} onChange={(e) => set({ state: e.target.value || undefined })}>
            <option value="">All states</option>
            {(data?.states ?? []).map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
        </Field>
      )}
      {fields.includes("category") && (
        <Field label="Category">
          <Select value={value.category ?? ""} onChange={(e) => set({ category: e.target.value || undefined })}>
            <option value="">All categories</option>
            {(data?.categories ?? []).map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
          </Select>
        </Field>
      )}
      <Button variant="ghost" onClick={() => onChange({})}>Reset</Button>
    </div>
  );
}
