"use client";

import { useEffect, useState } from "react";
import { Badge, Dot, PageTitle, Panel, type Tone } from "@/components/ui";
import { api, type AuditEntry } from "@/lib/api";
import { useLive } from "@/lib/live";

const tone = (s: string): Tone =>
  s === "ok" ? "ok" : s === "degraded" ? "warn" : s === "down" ? "bad" : "neutral";

const label: Record<string, string> = {
  ok: "Healthy",
  degraded: "Degraded",
  down: "Down",
  not_configured: "Not configured",
  not_deployed: "Not built yet",
};

export default function SystemPage() {
  const { status, link, lastMessageAt } = useLive();
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [chain, setChain] = useState<{ valid: boolean; entries_checked: number } | null>(null);

  useEffect(() => {
    void api<AuditEntry[]>("/audit?limit=50").then(setAudit).catch(() => undefined);
    void api<{ valid: boolean; entries_checked: number }>("/audit/verify").then(setChain).catch(() => undefined);
  }, []);

  return (
    <>
      <PageTitle title="System Monitoring" subtitle="Service health, connectivity and audit trail" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel
          title="Components"
          right={
            <span className="text-xs text-muted">
              Live link: {link}
              {lastMessageAt ? ` · updated ${new Date(lastMessageAt).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" })} IST` : ""}
            </span>
          }
        >
          {!status ? (
            <p className="text-sm text-muted">Waiting for first status update…</p>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {status.components.map((c) => (
                  <tr key={c.name} className="border-b border-line last:border-0">
                    <td className="py-2 capitalize">{c.name.replace("_", " ")}</td>
                    <td className="py-2">
                      <Badge tone={tone(c.status)}>
                        <Dot tone={tone(c.status)} /> {label[c.status] ?? c.status}
                      </Badge>
                    </td>
                    <td className="num py-2 text-right text-muted">{c.latency_ms != null ? `${c.latency_ms} ms` : c.detail ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {status && (
            <p className="mt-3 text-xs text-muted">
              v{status.version} · env {status.app_env} · trading {status.trading_env}
            </p>
          )}
        </Panel>

        <Panel
          title="Audit trail"
          right={
            chain && (
              <Badge tone={chain.valid ? "ok" : "bad"}>
                {chain.valid ? `Chain verified (${chain.entries_checked})` : "CHAIN BROKEN"}
              </Badge>
            )
          }
        >
          <div className="max-h-96 overflow-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted">
                <tr>
                  <th className="py-1 font-normal">Time</th>
                  <th className="py-1 font-normal">Action</th>
                  <th className="py-1 font-normal">Actor</th>
                  <th className="py-1 font-normal">IP</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((a) => (
                  <tr key={a.id} className="border-t border-line">
                    <td className="num py-1.5 text-muted">{new Date(a.occurred_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}</td>
                    <td className="py-1.5">{a.action}</td>
                    <td className="py-1.5 text-muted">{a.actor}</td>
                    <td className="num py-1.5 text-muted">{a.ip ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </>
  );
}
