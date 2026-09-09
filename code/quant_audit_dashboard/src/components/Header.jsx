import { useEffect, useState } from "react";
import { Activity } from "lucide-react";
import { API_BASE, checkHealth } from "../lib/api";

const STATES = {
  checking: { label: "Checking engine", dot: "bg-muted" },
  online: { label: "Engine connected", dot: "bg-good" },
  offline: { label: "Engine unreachable", dot: "bg-critical" },
};

/**
 * Polls the backend so the connection state is always current - an audit that
 * fails because uvicorn stopped should be diagnosable from the header alone,
 * without reading a request error.
 */
function useBackendStatus() {
  const [status, setStatus] = useState("checking");
  const [version, setVersion] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    let timer;

    async function poll() {
      try {
        // Bound each probe. A stalled connection - socket accepted, nothing
        // ever returned - is exactly the "unreachable" case this badge exists
        // to show, and without a timeout it would hang forever instead.
        const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(8000)]);
        const body = await checkHealth(signal);
        if (!cancelled) {
          setStatus("online");
          setVersion(body?.version ?? null);
        }
      } catch {
        if (!cancelled) setStatus("offline");
      } finally {
        // Chain the next probe from this one's completion rather than firing on
        // a fixed interval, so slow responses cannot pile up against the
        // browser's per-host connection limit.
        if (!cancelled) timer = setTimeout(poll, 15000);
      }
    }

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, []);

  return { status, version };
}

export default function Header() {
  const { status, version } = useBackendStatus();
  const state = STATES[status];

  return (
    <header className="sticky top-0 z-20 border-b border-line bg-canvas/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-4 px-6 py-4">
        <div className="flex items-center gap-3">
          <Activity className="h-5 w-5 shrink-0 text-accent" strokeWidth={2} aria-hidden />
          <div>
            <h1 className="text-title font-semibold text-ink">AI Strategy Auditor</h1>
            <p className="text-small text-ink-2">
              SR 11-7 model risk and black-box compliance engine
            </p>
          </div>
        </div>

        <div
          className="flex items-center gap-2.5 rounded-control border border-line bg-panel px-3 py-2"
          /* Polite, not assertive: the status changing must not interrupt
             someone mid-way through filling in the audit form. */
          role="status"
          aria-live="polite"
        >
          <span className={`h-2 w-2 shrink-0 rounded-full ${state.dot}`} aria-hidden />
          <span className="text-small text-ink">{state.label}</span>
          <span className="hidden font-mono text-micro text-muted sm:inline">
            {version ? `v${version}` : API_BASE.replace(/^https?:\/\//, "")}
          </span>
        </div>
      </div>
    </header>
  );
}
