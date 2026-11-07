"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { ApiError, api, setCsrfToken, type SessionState } from "@/lib/api";

type Step = "password" | "enroll" | "verify";

interface Enrollment {
  secret: string;
  otpauth_uri: string;
  qr_svg_data_uri: string;
}

export default function LoginPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setError("Too many attempts. Wait 15 minutes and try again.");
      else if (e instanceof ApiError && e.status === 401) setError(step === "password" ? "Invalid email or password." : "Invalid or already-used code.");
      else setError("Something went wrong. Check the server is running.");
    } finally {
      setBusy(false);
    }
  }

  const submitPassword = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const s = await api<SessionState>("/auth/login", { method: "POST", json: { email, password } });
      setCsrfToken(s.csrf_token);
      setPassword("");
      if (s.mfa_enrolled) {
        setStep("verify");
      } else {
        setEnrollment(await api<Enrollment>("/auth/mfa/enroll/start", { method: "POST" }));
        setStep("enroll");
      }
    });
  };

  const submitCode = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const path = step === "enroll" ? "/auth/mfa/enroll/confirm" : "/auth/mfa/verify";
      const s = await api<SessionState>(path, { method: "POST", json: { code } });
      setCsrfToken(s.csrf_token);
      router.replace("/");
    });
  };

  const input =
    "w-full rounded-md border border-line bg-panel-2 px-3 py-2 text-sm outline-none focus:border-accent";

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm rounded-xl border border-line bg-panel p-6 shadow-2xl">
        <div className="mb-6">
          <div className="text-lg font-semibold">AlgoTrader</div>
          <div className="text-sm text-muted">
            {step === "password" && "Sign in to your trading terminal"}
            {step === "enroll" && "Set up two-factor authentication (required)"}
            {step === "verify" && "Enter the 6-digit code from your authenticator app"}
          </div>
        </div>

        {step === "password" && (
          <form onSubmit={submitPassword} className="space-y-3">
            <input className={input} type="email" autoComplete="username" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            <input className={input} type="password" autoComplete="current-password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            <button disabled={busy} className="w-full rounded-md bg-accent py-2 text-sm font-medium text-white disabled:opacity-50">
              {busy ? "Signing in…" : "Continue"}
            </button>
          </form>
        )}

        {step !== "password" && (
          <form onSubmit={submitCode} className="space-y-4">
            {step === "enroll" && enrollment && (
              <div className="space-y-3 text-sm">
                <p className="text-muted">Scan with Google Authenticator, Authy, 1Password or similar:</p>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={enrollment.qr_svg_data_uri} alt="TOTP QR code" className="mx-auto rounded bg-white p-2" width={200} height={200} />
                <details className="text-xs text-muted">
                  <summary className="cursor-pointer">Can&apos;t scan? Enter the key manually</summary>
                  <code className="num mt-2 block break-all rounded bg-panel-2 p-2 text-ink">{enrollment.secret}</code>
                </details>
              </div>
            )}
            <input
              className={`${input} num text-center text-lg tracking-[0.4em]`}
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              placeholder="000000"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              required
              autoFocus
            />
            <button disabled={busy || code.length !== 6} className="w-full rounded-md bg-accent py-2 text-sm font-medium text-white disabled:opacity-50">
              {busy ? "Verifying…" : step === "enroll" ? "Activate 2FA and sign in" : "Verify"}
            </button>
          </form>
        )}

        {error && <p className="mt-4 rounded border border-down/30 bg-down/10 px-3 py-2 text-sm text-down">{error}</p>}
      </div>
    </main>
  );
}
