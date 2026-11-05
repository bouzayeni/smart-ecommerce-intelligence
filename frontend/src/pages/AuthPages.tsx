import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";

import { Button, Field, Input } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { toFailure } from "../services/api";

function AuthShell({ title, children, footer }: { title: string; children: ReactNode; footer: ReactNode }) {
  return (
    <main className="flex min-h-full items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="h-8 w-8" />
          <span className="text-lg font-semibold text-text">Olist Intelligence</span>
        </div>
        <div className="rounded-xl border border-border bg-surface p-6 shadow-sm">
          <h1 className="text-lg font-semibold text-text">{title}</h1>
          {children}
        </div>
        <p className="mt-4 text-center text-sm text-text-2">{footer}</p>
        <p className="mt-6 text-center text-xs text-muted">
          Portfolio project on the public Olist dataset (2016–2018). Historical data, not live.
        </p>
      </div>
    </main>
  );
}

function useSubmit(action: () => Promise<void>) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      const f = toFailure(err);
      setError(f.code === "validation_error" ? "Please check the fields: " + f.message : f.message);
    } finally {
      setBusy(false);
    }
  };
  return { error, busy, submit };
}

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const { error, busy, submit } = useSubmit(async () => {
    await login(email, password);
    navigate(from, { replace: true });
  });
  if (user) return <Navigate to={from} replace />;
  return (
    <AuthShell title="Sign in" footer={<>No account? <Link className="text-accent hover:underline" to="/register">Create one</Link></>}>
      <form onSubmit={submit} className="mt-4 space-y-4" noValidate>
        <Field label="Email"><Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password"><Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        {error && <p role="alert" className="text-sm text-critical">{error}</p>}
        <Button type="submit" className="w-full" disabled={busy || !email || !password}>{busy ? "Signing in…" : "Sign in"}</Button>
      </form>
    </AuthShell>
  );
}

export function RegisterPage() {
  const { user, register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const { error, busy, submit } = useSubmit(async () => {
    await register(form.email, form.password, form.name);
    navigate("/", { replace: true });
  });
  if (user) return <Navigate to="/" replace />;
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <AuthShell title="Create an account" footer={<>Already registered? <Link className="text-accent hover:underline" to="/login">Sign in</Link></>}>
      <p className="mt-1 text-sm text-text-2">New accounts get the <strong>viewer</strong> role (aggregated dashboards). An admin can grant analyst access.</p>
      <form onSubmit={submit} className="mt-4 space-y-4" noValidate>
        <Field label="Full name"><Input autoComplete="name" required value={form.name} onChange={set("name")} /></Field>
        <Field label="Email"><Input type="email" autoComplete="email" required value={form.email} onChange={set("email")} /></Field>
        <Field label="Password" hint="12+ characters with upper- and lower-case letters and a digit.">
          <Input type="password" autoComplete="new-password" required minLength={12} value={form.password} onChange={set("password")} />
        </Field>
        {error && <p role="alert" className="text-sm text-critical">{error}</p>}
        <Button type="submit" className="w-full" disabled={busy || !form.email || !form.password || !form.name}>
          {busy ? "Creating…" : "Create account"}
        </Button>
      </form>
    </AuthShell>
  );
}
