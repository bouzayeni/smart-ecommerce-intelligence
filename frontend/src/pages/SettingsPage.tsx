import { Badge, Button, Card, PageHeader } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { day } from "../lib/format";

const ACCESS = {
  viewer: "Aggregated dashboards, forecasts, anomalies and segment summaries.",
  analyst: "Everything a viewer sees, plus customer-level data, predictions and recommendations.",
  admin: "Everything, plus model registry status, data quality and user role management (API).",
};

export default function SettingsPage() {
  const { user, logout } = useAuth();
  if (!user) return null;
  return (
    <>
      <PageHeader title="Settings" />
      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Profile">
          <dl className="grid grid-cols-2 gap-y-3 text-sm">
            <dt className="text-muted">Name</dt><dd>{user.full_name}</dd>
            <dt className="text-muted">Email</dt><dd>{user.email}</dd>
            <dt className="text-muted">Role</dt><dd><Badge tone="accent">{user.role}</Badge></dd>
            <dt className="text-muted">Member since</dt><dd>{day(user.created_at)}</dd>
            <dt className="text-muted">Last login</dt><dd>{day(user.last_login_at)}</dd>
          </dl>
          <p className="mt-4 text-sm text-text-2">{ACCESS[user.role]}</p>
        </Card>
        <Card title="Session">
          <p className="text-sm text-text-2">
            The access token lives in memory and expires after 15 minutes. It is renewed automatically with a rotating
            refresh token kept for this browser tab only. Logging out revokes the refresh token on the server.
          </p>
          <Button className="mt-4" variant="secondary" onClick={() => void logout()}>Log out</Button>
        </Card>
        <Card title="About the data" className="xl:col-span-2">
          <p className="text-sm text-text-2">
            Brazilian E-Commerce Public Dataset by Olist (Kaggle, CC BY-NC-SA 4.0): about 99k orders, 2016–2018. Analysis window
            2017-01-01 → 2018-08-21 (the extract is sparse before and truncated after). All figures are historical. GMV is not
            profit, because the dataset has no cost data.
          </p>
        </Card>
      </div>
    </>
  );
}
