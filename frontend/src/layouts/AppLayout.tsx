import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router";

import { Badge, Button } from "../components/ui";
import { cx } from "../lib/cx";
import { useAuth } from "../hooks/useAuth";
import type { Role } from "../types/api";

interface NavItem {
  to: string;
  label: string;
  minimum: Role;
}

const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: "Analytics",
    items: [
      { to: "/", label: "Executive dashboard", minimum: "viewer" },
      { to: "/sales", label: "Sales analytics", minimum: "viewer" },
      { to: "/forecast", label: "Sales forecasting", minimum: "viewer" },
      { to: "/anomalies", label: "Anomaly detection", minimum: "viewer" },
    ],
  },
  {
    section: "Customers",
    items: [
      { to: "/segments", label: "Segmentation", minimum: "viewer" },
      { to: "/customers", label: "Customer 360", minimum: "analyst" },
      { to: "/churn", label: "Churn prediction", minimum: "analyst" },
      { to: "/clv", label: "CLV prediction", minimum: "analyst" },
      { to: "/recommendations", label: "Recommendations", minimum: "analyst" },
    ],
  },
  {
    section: "Platform",
    items: [
      { to: "/assistant", label: "AI business assistant", minimum: "viewer" },
      { to: "/models", label: "Model monitoring", minimum: "viewer" },
      { to: "/data-quality", label: "Data quality", minimum: "admin" },
      { to: "/settings", label: "Settings", minimum: "viewer" },
    ],
  },
];

const THEME_KEY = "sei.theme";

function useTheme() {
  const [theme, setTheme] = useState<"system" | "light" | "dark">(() => {
    try {
      return (localStorage.getItem(THEME_KEY) as "light" | "dark" | null) ?? "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      if (theme === "system") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* per-viewer convenience only */
    }
  }, [theme]);
  return [theme, setTheme] as const;
}

export function AppLayout() {
  const { user, hasRole, logout } = useAuth();
  const [theme, setTheme] = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);

  const nav = (
    <nav aria-label="Main" className="space-y-6">
      {NAV.map((group) => {
        const items = group.items.filter((i) => hasRole(i.minimum));
        if (!items.length) return null;
        return (
          <div key={group.section}>
            <p className="px-3 text-xs font-semibold uppercase tracking-wide text-muted">{group.section}</p>
            <ul className="mt-2 space-y-0.5">
              {items.map((item) => (
                <li key={item.to}>
                  <NavLink to={item.to} end={item.to === "/"} onClick={() => setMenuOpen(false)}
                    className={({ isActive }) => cx(
                      "block rounded-lg px-3 py-2 text-sm",
                      isActive ? "bg-accent-soft font-medium text-accent" : "text-text-2 hover:bg-surface-2 hover:text-text",
                    )}>
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );

  return (
    <div className="flex min-h-full">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:p-2">
        Skip to content
      </a>
      <aside className="hidden w-64 shrink-0 border-r border-border bg-surface px-3 py-5 lg:block">
        <Brand />
        <div className="mt-6">{nav}</div>
      </aside>
      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button className="absolute inset-0 bg-black/40" aria-label="Close menu" onClick={() => setMenuOpen(false)} />
          <aside className="relative h-full w-72 overflow-y-auto bg-surface px-3 py-5">
            <Brand />
            <div className="mt-6">{nav}</div>
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-border bg-surface/95 px-4 py-3 backdrop-blur lg:px-8">
          <Button variant="ghost" className="lg:hidden" aria-label="Open menu" onClick={() => setMenuOpen(true)}>☰</Button>
          <p className="hidden text-xs text-muted sm:block">Historical Olist data · 2017-01-01 → 2018-08-21</p>
          <div className="ml-auto flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-text-2">
              <span className="sr-only sm:not-sr-only">Theme</span>
              <select value={theme} onChange={(e) => setTheme(e.target.value as typeof theme)}
                className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-text">
                <option value="system">System</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </select>
            </label>
            <span className="hidden text-sm text-text sm:inline">{user?.full_name}</span>
            <Badge tone="accent">{user?.role}</Badge>
            <Button variant="secondary" onClick={() => void logout()}>Log out</Button>
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2 px-3">
      <img src="/favicon.svg" alt="" className="h-7 w-7" />
      <div>
        <p className="text-sm font-semibold text-text">Olist Intelligence</p>
        <p className="text-xs text-muted">E-commerce analytics</p>
      </div>
    </div>
  );
}
