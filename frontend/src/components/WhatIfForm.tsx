import { useState, type FormEvent } from "react";

import { api, toFailure, type ApiFailure } from "../services/api";
import { Button, Card, ErrorState, Field, Input, Select } from "./ui";

const NUMERIC_FIELDS: { key: string; label: string; step?: string }[] = [
  { key: "recency_days", label: "Days since last order" },
  { key: "tenure_days", label: "Days since first order" },
  { key: "frequency", label: "Orders" },
  { key: "monetary", label: "Total spend (BRL)", step: "0.01" },
  { key: "avg_order_value", label: "Average order value (BRL)", step: "0.01" },
  { key: "last_review_score", label: "Last review score (1–5)" },
];

/** On-demand prediction with the latest registered model (POST /predictions/{endpoint}). */
export function WhatIfForm({ endpoint, render }: {
  endpoint: "churn" | "clv";
  render: (result: Record<string, unknown>) => React.ReactNode;
}) {
  const [values, setValues] = useState<Record<string, string>>({
    recency_days: "45", tenure_days: "200", frequency: "2", monetary: "320", avg_order_value: "160",
    last_review_score: "5", customer_state: "SP", last_order_category: "health_beauty",
  });
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<ApiFailure | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const n = (k: string) => Number(values[k]);
    const features = {
      recency_days: n("recency_days"), tenure_days: n("tenure_days"), frequency: n("frequency"),
      monetary: n("monetary"), avg_order_value: n("avg_order_value"), max_order_value: n("avg_order_value"),
      last_order_value: n("avg_order_value"), last_review_score: n("last_review_score"),
      mean_review_score: n("last_review_score"), min_review_score: n("last_review_score"),
      customer_state: values.customer_state, last_order_category: values.last_order_category,
      last_payment_type: values.last_payment_type ?? "credit_card",
    };
    try {
      setResult((await api.post(`/predictions/${endpoint}`, { features })).data);
    } catch (err) {
      setError(toFailure(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="What-if prediction" subtitle="Runs the latest registered model on a hypothetical customer. Unlisted features are imputed as in training.">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {NUMERIC_FIELDS.map((f) => (
          <Field key={f.key} label={f.label}>
            <Input type="number" min={0} step={f.step ?? "1"} value={values[f.key]}
              onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
          </Field>
        ))}
        <Field label="State">
          <Input value={values.customer_state} maxLength={2} pattern="[A-Z]{2}"
            onChange={(e) => setValues({ ...values, customer_state: e.target.value.toUpperCase() })} />
        </Field>
        <Field label="Payment type">
          <Select value={values.last_payment_type ?? "credit_card"} onChange={(e) => setValues({ ...values, last_payment_type: e.target.value })}>
            {["credit_card", "boleto", "voucher", "debit_card"].map((p) => <option key={p}>{p}</option>)}
          </Select>
        </Field>
        <div className="flex items-end sm:col-span-2 lg:col-span-4">
          <Button type="submit" disabled={busy}>{busy ? "Predicting…" : "Predict"}</Button>
        </div>
      </form>
      {error && <div className="mt-4"><ErrorState error={error} /></div>}
      {result && <div className="mt-4 rounded-lg bg-surface-2 p-4 text-sm">{render(result)}</div>}
    </Card>
  );
}
