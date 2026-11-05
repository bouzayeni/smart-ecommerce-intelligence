import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

import { useAuth } from "../hooks/useAuth";
import { cx } from "../lib/cx";
import type { ApiFailure } from "../services/api";
import type { DataNote as Note, Role } from "../types/api";

export function Card({ title, subtitle, actions, children, className }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={cx("rounded-xl border border-border bg-surface p-5 shadow-sm", className)}>
      {(title || actions) && (
        <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-text">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-text">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-text-2">{description}</p>}
      </div>
      {actions}
    </div>
  );
}

export function KpiCard({ label, value, hint, tone }: {
  label: string; value: ReactNode; hint?: ReactNode; tone?: "good" | "warning" | "critical";
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className={cx("tabular mt-2 text-2xl font-semibold text-text",
        tone === "good" && "text-good", tone === "warning" && "text-warning", tone === "critical" && "text-critical")}>
        {value}
      </p>
      {hint && <p className="mt-1 text-xs text-text-2">{hint}</p>}
    </div>
  );
}

export function KpiGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">{children}</div>;
}

const BADGE_TONES = {
  neutral: "bg-surface-2 text-text-2",
  accent: "bg-accent-soft text-accent",
  good: "bg-surface-2 text-good",
  warning: "bg-surface-2 text-warning",
  critical: "bg-surface-2 text-critical",
};

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: keyof typeof BADGE_TONES }) {
  return <span className={cx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", BADGE_TONES[tone])}>{children}</span>;
}

export function Button({ variant = "primary", className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
}) {
  return (
    <button
      {...props}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-accent text-white hover:opacity-90",
        variant === "secondary" && "border border-border bg-surface text-text hover:bg-surface-2",
        variant === "ghost" && "text-text-2 hover:bg-surface-2 hover:text-text",
        className,
      )}
    />
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-text-2">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

const inputClass =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputClass, props.className)} />;
}

export function Select({ children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(inputClass, "pr-8", props.className)}>{children}</select>;
}

export function Loading({ label = "Loading…", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-surface-2" style={{ width: `${90 - i * 15}%` }} />
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiFailure; onRetry?: () => void }) {
  const forbidden = error.status === 403;
  return (
    <div role="alert" className="rounded-lg border border-border bg-surface-2 p-4 text-sm">
      <p className="font-medium text-critical">{forbidden ? "You do not have access to this data" : "Could not load data"}</p>
      <p className="mt-1 text-text-2">{error.message}</p>
      {error.requestId && <p className="mt-1 text-xs text-muted">Request id: {error.requestId}</p>}
      {onRetry && !forbidden && <Button variant="secondary" className="mt-3" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function Empty({ children = "No data for this selection." }: { children?: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted">{children}</p>;
}

/** Renders loading / error / empty states, or children with the data. */
export function Async<T>({ state, children, empty }: {
  state: { data: T | null; error: ApiFailure | null; loading: boolean; reload?: () => void };
  children: (data: T) => ReactNode;
  empty?: (data: T) => boolean;
}) {
  if (state.loading && !state.data) return <Loading />;
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />;
  if (!state.data) return null;
  if (empty?.(state.data)) return <Empty />;
  return <>{children(state.data)}</>;
}

export function DataNote({ meta }: { meta?: Note | null }) {
  if (!meta) return null;
  const filters = Object.entries(meta.filters ?? {});
  return (
    <p className="mt-6 text-xs text-muted">
      Source: <code>{meta.source}</code>
      {meta.window && <> · Window: {meta.window}</>}
      {filters.length > 0 && <> · Filters: {filters.map(([k, v]) => `${k}=${String(v)}`).join(", ")}</>}
      {meta.note && <> · {meta.note}</>}
    </p>
  );
}

export function RoleGate({ minimum, children }: { minimum: Role; children: ReactNode }) {
  const { hasRole } = useAuth();
  if (hasRole(minimum)) return <>{children}</>;
  return (
    <Card>
      <p className="text-sm text-text-2">
        This page shows customer-level or administrative data and requires the <Badge tone="accent">{minimum}</Badge> role.
        Ask an administrator to grant it.
      </p>
    </Card>
  );
}
