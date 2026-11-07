"use client";

// Single dashboard WebSocket with automatic reconnect (exponential backoff + jitter).
// The server pushes system status every few seconds; later phases add ticks, orders, etc.

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { SystemStatus } from "./api";

export type LinkState = "connecting" | "open" | "closed";

interface LiveState {
  link: LinkState;
  status: SystemStatus | null;
  lastMessageAt: number | null;
}

const LiveContext = createContext<LiveState>({ link: "connecting", status: null, lastMessageAt: null });

function wsUrl(): string {
  const configured = process.env.NEXT_PUBLIC_WS_URL;
  if (configured) return configured;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/ws`;
}

export function LiveProvider({ children, onUnauthorized }: { children: ReactNode; onUnauthorized: () => void }) {
  const [state, setState] = useState<LiveState>({ link: "connecting", status: null, lastMessageAt: null });
  const unauthorized = useRef(onUnauthorized);
  unauthorized.current = onUnauthorized;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const connect = () => {
      setState((s) => ({ ...s, link: "connecting" }));
      socket = new WebSocket(wsUrl());
      socket.onopen = () => {
        attempt = 0;
        setState((s) => ({ ...s, link: "open" }));
      };
      socket.onmessage = (ev) => {
        const msg = JSON.parse(ev.data as string) as { topic: string; data: unknown };
        setState((s) => ({
          ...s,
          lastMessageAt: Date.now(),
          status: msg.topic === "system.status" ? (msg.data as SystemStatus) : s.status,
        }));
      };
      socket.onclose = (ev) => {
        setState((s) => ({ ...s, link: "closed" }));
        if (stopped) return;
        if (ev.code === 1008) {
          unauthorized.current(); // session expired or revoked
          return;
        }
        const delay = Math.min(30_000, 1_000 * 2 ** attempt) * (0.5 + Math.random() / 2);
        attempt += 1;
        timer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    };
  }, []);

  return <LiveContext.Provider value={state}>{children}</LiveContext.Provider>;
}

export function useLive(): LiveState {
  return useContext(LiveContext);
}
