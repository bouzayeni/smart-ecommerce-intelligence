import { useState } from "react";

import { CustomerTable } from "../components/CustomerTable";
import { Card, Field, Input, PageHeader, RoleGate, Select } from "../components/ui";

export default function CustomersPage() {
  const [search, setSearch] = useState("");
  const [state, setState] = useState("");
  const [band, setBand] = useState("");
  const validSearch = /^[0-9a-f]{0,32}$/.test(search);

  return (
    <RoleGate minimum="analyst">
      <PageHeader title="Customer 360"
        description="Every customer (customer_unique_id) with RFM, churn risk and predicted spend. Open a customer for orders, model explanations and recommendations." />
      <div className="mb-6 flex flex-wrap items-end gap-3 rounded-xl border border-border bg-surface p-4">
        <Field label="Customer id prefix" hint={validSearch ? undefined : "Hex characters only"}>
          <Input value={search} placeholder="e.g. 8d50f5ea" onChange={(e) => setSearch(e.target.value.trim().toLowerCase())} />
        </Field>
        <Field label="State">
          <Input value={state} maxLength={2} placeholder="SP" onChange={(e) => setState(e.target.value.toUpperCase())} />
        </Field>
        <Field label="Churn-risk band">
          <Select value={band} onChange={(e) => setBand(e.target.value)}>
            <option value="">All</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </Select>
        </Field>
      </div>
      <Card>
        <CustomerTable filters={{
          search: validSearch && search ? search : undefined,
          state: /^[A-Z]{2}$/.test(state) ? state : undefined,
          risk_band: band || undefined,
        }} />
      </Card>
    </RoleGate>
  );
}
