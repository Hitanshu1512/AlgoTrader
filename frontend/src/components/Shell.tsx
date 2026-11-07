"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError, api, setCsrfToken, type SessionState } from "@/lib/api";
import { LiveProvider, useLive } from "@/lib/live";
import { Badge, Dot, type Tone } from "./ui";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/market", label: "Market Watch" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/orders", label: "Orders" },
  { href: "/strategies", label: "Strategy Center" },
  { href: "/risk", label: "Risk" },
  { href: "/analytics", label: "Analytics" },
  { href: "/system", label: "System" },
];

function componentTone(status: string | undefined): Tone {
  if (status === "ok") return "ok";
  if (status === "degraded") return "warn";
  if (status === "down") return "bad";
  return "neutral";
}

function TopBar({ session, onLogout }: { session: SessionState; onLogout: () => void }) {
  const { link, status } = useLive();
  const get = (n: string) => status?.components.find((c) => c.name === n)?.status;
  const ist = status ? new Date(status.server_time_ist).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" }) : "--:--:--";

  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-line bg-panel px-4 py-2.5">
      <div className="flex items-center gap-2 text-xs">
        <span title="Dashboard live link">
          <Badge tone={link === "open" ? "ok" : link === "connecting" ? "warn" : "bad"}>
            <Dot tone={link === "open" ? "ok" : link === "connecting" ? "warn" : "bad"} /> Live {link}
          </Badge>
        </span>
        {(["database", "redis", "broker"] as const).map((n) => (
          <Badge key={n} tone={componentTone(get(n))}>
            <Dot tone={componentTone(get(n))} />
            {n === "broker" ? "Broker" : n === "database" ? "DB" : "Redis"}
          </Badge>
        ))}
      </div>
      <div className="ml-auto flex items-center gap-3 text-xs">
        {status && (
          <Badge tone={status.trading_env === "live" ? "bad" : "info"}>
            {status.trading_env === "live" ? "LIVE" : "PAPER"}
          </Badge>
        )}
        <span className="num text-muted" title="Server time (IST)">{ist} IST</span>
        <span className="hidden text-muted sm:inline">{session.email}</span>
        <button onClick={onLogout} className="rounded border border-line px-2 py-1 text-muted hover:text-ink">
          Log out
        </button>
      </div>
    </header>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [session, setSession] = useState<SessionState | null>(null);
  const [navOpen, setNavOpen] = useState(false);

  const toLogin = useCallback(() => router.replace("/login"), [router]);

  useEffect(() => {
    api<SessionState>("/auth/me")
      .then((s) => {
        if (!s.mfa_verified) return toLogin();
        setCsrfToken(s.csrf_token);
        setSession(s);
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 401) toLogin();
      });
  }, [toLogin]);

  const logout = async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      toLogin();
    }
  };

  if (!session) {
    return <div className="flex min-h-screen items-center justify-center text-sm text-muted">Checking session…</div>;
  }

  return (
    <LiveProvider onUnauthorized={toLogin}>
      <div className="flex min-h-screen">
        <nav className={`${navOpen ? "block" : "hidden"} fixed inset-y-0 z-20 w-56 border-r border-line bg-panel md:static md:block`}>
          <div className="px-4 py-4 text-sm font-semibold tracking-wide">AlgoTrader</div>
          <ul className="space-y-0.5 px-2">
            {NAV.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={() => setNavOpen(false)}
                    className={`block rounded px-3 py-2 text-sm ${active ? "bg-panel-2 text-ink" : "text-muted hover:bg-panel-2 hover:text-ink"}`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center md:block">
            <button className="px-3 text-muted md:hidden" onClick={() => setNavOpen((v) => !v)} aria-label="Toggle navigation">
              ☰
            </button>
            <div className="flex-1">
              <TopBar session={session} onLogout={logout} />
            </div>
          </div>
          <main className="flex-1 p-4 md:p-6">{children}</main>
        </div>
      </div>
    </LiveProvider>
  );
}
