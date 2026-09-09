import { useRef, useState } from "react";
import { AlertTriangle, Database, ScatterChart } from "lucide-react";
import Header from "./components/Header";
import AuditControls from "./components/AuditControls";
import VerdictPanel from "./components/VerdictPanel";
import MetricCard from "./components/MetricCard";
import RegretChart from "./components/RegretChart";
import AllocationHeatmap from "./components/AllocationHeatmap";
import AuditReportTable from "./components/AuditReportTable";
import { runAudit, uploadAudit } from "./lib/api";
import { adaptive, basisPoints } from "./lib/format";

export default function App() {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(null);

  /**
   * One path for both endpoints. Any in-flight request is aborted first, so a
   * slow yfinance download can never land after a newer audit and overwrite it.
   */
  async function submit(call) {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    setBusy(true);
    setError(null);
    try {
      setResult(await call(controller.signal));
    } catch (err) {
      if (err.name === "AbortError") return; // superseded, not a failure
      setError(err.message);
      setResult(null);
    } finally {
      if (inFlight.current === controller) {
        inFlight.current = null;
        setBusy(false);
      }
    }
  }

  return (
    <div className="min-h-screen">
      <Header />

      <main className="mx-auto grid max-w-[1600px] items-start gap-5 px-6 py-6 lg:grid-cols-[340px_minmax(0,1fr)]">
        {/* min-w-0 on both columns: a grid item defaults to min-width:auto, so
            the table's min-width and the charts' intrinsic width push the whole
            page wider than the viewport and produce a horizontal scrollbar. */}
        <div className="min-w-0 lg:sticky lg:top-[89px]">
          <AuditControls
            busy={busy}
            onRun={(payload) => submit((signal) => runAudit(payload, signal))}
            onUpload={(file) => submit((signal) => uploadAudit(file, signal))}
          />
        </div>

        <div className="min-w-0 space-y-5">
          {error && <ErrorBanner message={error} />}

          {result ? (
            <>
              {result.data_source === "snapshot" && <SnapshotNotice />}
              <VerdictPanel result={result} />

              {/* One panel divided by hairlines rather than four detached cards:
                  these figures are read across, as a single decomposition. */}
              <div className="panel grid divide-y divide-line sm:grid-cols-2 sm:divide-y-0 xl:grid-cols-4">
                <div className="sm:border-r sm:border-line">
                  <MetricCard
                    name="Trajectory covariance"
                    symbol="Ĉ_T"
                    value={adaptive(result.trajectory_covariance, 5)}
                    note={basisPoints(result.trajectory_covariance)}
                    emphasis
                  />
                </div>
                <div className="border-t border-line sm:border-t-0 xl:border-r xl:border-line">
                  <MetricCard
                    name="Policy bias correction"
                    symbol="c̄ᵀb"
                    value={adaptive(result.bias_correction, 5)}
                    note={basisPoints(result.bias_correction)}
                  />
                </div>
                <div className="border-t border-line sm:border-r sm:border-line xl:border-t-0">
                  <MetricCard
                    name="Total regret"
                    symbol="Regret⁽ᵀ⁾"
                    value={adaptive(result.total_regret, 5)}
                    note={`95% CI ${adaptive(result.regret_ci_lower, 5)} to ${adaptive(result.regret_ci_upper, 5)}`}
                  />
                </div>
                <div className="border-t border-line xl:border-t-0">
                  <MetricCard
                    name="Newey-West error"
                    symbol="SE"
                    value={adaptive(result.standard_error, 5)}
                    note={`On Ĉ_T. Regret SE ${adaptive(result.regret_standard_error, 5)}`}
                  />
                </div>
              </div>

              <RegretChart result={result} />
              <AllocationHeatmap result={result} />
              <AuditReportTable result={result} />
            </>
          ) : (
            !error && <EmptyState busy={busy} />
          )}
        </div>
      </main>
    </div>
  );
}

/** Frozen prices must never be presented as current ones. */
function SnapshotNotice() {
  return (
    <div
      role="status"
      className="flex items-start gap-3 rounded-panel border border-warn/45 bg-warn/10 px-5 py-3.5"
    >
      <Database className="mt-0.5 h-4 w-4 shrink-0 text-warn" aria-hidden />
      <p className="max-w-[74ch] text-small text-ink-2">
        <span className="font-medium text-ink">Audited on the bundled snapshot.</span>{" "}
        Live market data was unavailable, so this ran on a frozen price set. The figures are
        real but not current.
      </p>
    </div>
  );
}

function ErrorBanner({ message }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-panel border border-critical/45 bg-critical/10 px-5 py-4"
    >
      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-critical" aria-hidden />
      <div>
        <h2 className="text-base font-medium text-ink">The audit did not run</h2>
        <p className="mt-1 max-w-[70ch] text-base text-ink-2">{message}</p>
      </div>
    </div>
  );
}

/** An empty screen is an invitation to act, so it says what to do next. */
function EmptyState({ busy }) {
  return (
    <div className="panel flex flex-col items-center justify-center px-6 py-24 text-center">
      <ScatterChart className="h-7 w-7 text-muted" aria-hidden />
      <p className="mt-4 max-w-[46ch] text-lead text-ink">
        {busy ? "Downloading prices and running the audit" : "No audit has been run yet"}
      </p>
      <p className="mt-2 max-w-[54ch] text-base text-ink-2">
        {busy
          ? "Fetching market data can take a few seconds."
          : "Pick a strategy and date range on the left, or upload a CSV of your own returns and weights."}
      </p>
    </div>
  );
}
