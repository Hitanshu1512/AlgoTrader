import type { ReactNode } from "react";

export function Panel({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-panel">
      <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">{title}</h2>
        {right}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

const tones = {
  ok: "bg-up/15 text-up border-up/30",
  warn: "bg-warn/15 text-warn border-warn/30",
  bad: "bg-down/15 text-down border-down/30",
  neutral: "bg-panel-2 text-muted border-line",
  info: "bg-accent/15 text-accent border-accent/30",
} as const;

export type Tone = keyof typeof tones;

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function Dot({ tone }: { tone: Tone }) {
  const color = { ok: "bg-up", warn: "bg-warn", bad: "bg-down", neutral: "bg-muted", info: "bg-accent" }[tone];
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel p-4">
      <div className="text-xs uppercase tracking-wider text-muted">{label}</div>
      <div className="num mt-1 text-xl text-ink">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function UpcomingPhase({ phase, items }: { phase: number; items: string[] }) {
  return (
    <div className="rounded-lg border border-dashed border-line p-5">
      <Badge tone="neutral">Phase {phase}</Badge>
      <p className="mt-3 text-sm text-muted">This section is built in Phase {phase}. It will show:</p>
      <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-ink/80">
        {items.map((i) => (
          <li key={i}>{i}</li>
        ))}
      </ul>
    </div>
  );
}

export function PageTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-5">
      <h1 className="text-lg font-semibold">{title}</h1>
      {subtitle && <p className="text-sm text-muted">{subtitle}</p>}
    </div>
  );
}
