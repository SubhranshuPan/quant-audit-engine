import { useRef, useState } from "react";
import { FileUp, Loader2, Play, X } from "lucide-react";

const STRATEGIES = [
  { value: "momentum", label: "Momentum (trend following)" },
  { value: "reversion", label: "Mean reversion" },
  { value: "min_variance", label: "Minimum variance" },
];

const DEFAULTS = {
  tickers: "AAPL, MSFT, SPY, QQQ",
  startDate: "2022-01-01",
  endDate: "2024-01-01",
  strategy: "momentum",
  window: 20,
};

function parseTickers(raw) {
  // Split on commas or whitespace so a pasted column of symbols works too.
  const seen = new Set();
  for (const part of raw.split(/[\s,]+/)) {
    const symbol = part.trim().toUpperCase();
    if (symbol) seen.add(symbol);
  }
  return [...seen];
}

function Tab({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      role="tab"
      aria-selected={active}
      className={`-mb-px border-b-2 px-1 pb-2.5 text-base transition-colors ${
        active
          ? "border-accent font-medium text-ink"
          : "border-transparent text-ink-2 hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

export default function AuditControls({ onRun, onUpload, busy }) {
  const [tab, setTab] = useState("strategy");
  const [form, setForm] = useState(DEFAULTS);
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState(null);
  const inputRef = useRef(null);

  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.value }));

  function switchTab(next) {
    setTab(next);
    setLocalError(null); // an error about the other tab describes nothing here
  }
  const tickers = parseTickers(form.tickers);

  function submitStrategy(event) {
    event.preventDefault();
    // Mirror the backend's rules so the common mistakes are caught without a
    // round trip. The backend still enforces all of them; this is only speed.
    if (tickers.length < 2) {
      setLocalError("Enter at least 2 distinct tickers to form a portfolio.");
      return;
    }
    if (!form.startDate || !form.endDate) {
      setLocalError("Enter both a start and an end date.");
      return;
    }
    if (form.startDate >= form.endDate) {
      setLocalError("The start date must fall before the end date.");
      return;
    }
    setLocalError(null);
    onRun({
      tickers,
      start_date: form.startDate,
      end_date: form.endDate,
      strategy_type: form.strategy,
      rolling_window: Number(form.window),
    });
  }

  function acceptFile(candidate) {
    if (!candidate) return;
    if (!/\.(csv|txt)$/i.test(candidate.name)) {
      setLocalError(`${candidate.name} is not a CSV. Choose a .csv file.`);
      return;
    }
    setLocalError(null);
    setFile(candidate);
  }

  function drop(event) {
    event.preventDefault();
    setDragging(false);
    acceptFile(event.dataTransfer.files?.[0]);
  }

  return (
    <section className="panel" aria-labelledby="controls-heading">
      <div className="panel-heading">
        <h2 id="controls-heading" className="text-lead font-semibold text-ink">
          Audit setup
        </h2>
      </div>

      <div className="flex gap-5 border-b border-line px-5 pt-4" role="tablist">
        <Tab active={tab === "strategy"} onClick={() => switchTab("strategy")}>
          Built-in strategy
        </Tab>
        <Tab active={tab === "upload"} onClick={() => switchTab("upload")}>
          Upload CSV
        </Tab>
      </div>

      {tab === "strategy" ? (
        <form className="space-y-5 p-5" onSubmit={submitStrategy}>
          <div>
            <label className="field-label" htmlFor="tickers">
              Tickers
            </label>
            <input
              id="tickers"
              className="field"
              value={form.tickers}
              onChange={set("tickers")}
              placeholder="AAPL, MSFT, SPY"
              autoComplete="off"
              spellCheck="false"
            />
            <p className="mt-1.5 text-micro text-ink-2">
              {tickers.length} {tickers.length === 1 ? "symbol" : "symbols"}
              {tickers.length < 2 && " — a portfolio needs at least 2"}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label" htmlFor="start">
                Start date
              </label>
              <input
                id="start"
                type="date"
                className="field"
                value={form.startDate}
                onChange={set("startDate")}
              />
            </div>
            <div>
              <label className="field-label" htmlFor="end">
                End date
              </label>
              <input
                id="end"
                type="date"
                className="field"
                value={form.endDate}
                onChange={set("endDate")}
              />
            </div>
          </div>

          <div>
            <label className="field-label" htmlFor="strategy">
              Strategy
            </label>
            <select
              id="strategy"
              className="field"
              value={form.strategy}
              onChange={set("strategy")}
            >
              {STRATEGIES.map((s) => (
                <option key={s.value} value={s.value} className="bg-raised">
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="field-label flex items-baseline justify-between" htmlFor="window">
              <span>Rolling window</span>
              <span className="figures font-mono text-base text-ink">{form.window} days</span>
            </label>
            <input
              id="window"
              type="range"
              min="20"
              max="252"
              step="1"
              className="slider mt-2"
              value={form.window}
              onChange={set("window")}
            />
            <div className="mt-1.5 flex justify-between font-mono text-micro text-muted">
              <span>20</span>
              <span>252</span>
            </div>
          </div>

          {localError && <ErrorNote message={localError} />}

          <button
            type="submit"
            disabled={busy}
            className="flex w-full items-center justify-center gap-2 rounded-control bg-accent
                       px-4 py-2.5 text-base font-medium text-white transition-colors
                       hover:bg-[#2C74CC] disabled:cursor-not-allowed disabled:bg-line
                       disabled:text-muted"
          >
            {busy ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                Running audit
              </>
            ) : (
              <>
                <Play className="h-4 w-4" aria-hidden />
                Run audit
              </>
            )}
          </button>
        </form>
      ) : (
        <div className="space-y-4 p-5">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={(e) => {
              // Ignore crossings into descendants; only a real exit counts.
              if (!e.currentTarget.contains(e.relatedTarget)) setDragging(false);
            }}
            onDrop={drop}
            className={`rounded-panel border border-dashed p-6 text-center transition-colors ${
              dragging ? "border-accent bg-raised" : "border-line-strong bg-raised/40"
            }`}
          >
            <FileUp className="mx-auto h-6 w-6 text-ink-2" aria-hidden />
            <p className="mt-3 text-base text-ink">Drop a CSV here</p>
            <p className="mt-1 text-small text-ink-2">
              One row per day, with a date column plus{" "}
              <code className="font-mono text-micro text-ink">return_AAPL</code> and{" "}
              <code className="font-mono text-micro text-ink">weight_AAPL</code> for each asset.
            </p>
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="mt-4 rounded-control border border-line-strong px-3 py-1.5 text-small
                         text-ink hover:border-accent hover:text-ink"
            >
              Choose a file
            </button>
            <input
              ref={inputRef}
              type="file"
              accept=".csv,.txt,text/csv"
              className="sr-only"
              onChange={(e) => {
                acceptFile(e.target.files?.[0]);
                // Reset so picking the SAME file again still fires a change
                // event - otherwise removing a file and re-choosing it is a
                // dead end with the submit button stuck disabled.
                e.target.value = "";
              }}
            />
          </div>

          {file && (
            <div className="flex items-center justify-between gap-3 rounded-control border border-line bg-raised px-3 py-2">
              <span className="truncate text-small text-ink" title={file.name}>
                {file.name}
              </span>
              <div className="flex shrink-0 items-center gap-2">
                <span className="figures font-mono text-micro text-muted">
                  {(file.size / 1024).toFixed(0)} KB
                </span>
                <button
                  type="button"
                  onClick={() => setFile(null)}
                  aria-label={`Remove ${file.name}`}
                  className="text-ink-2 hover:text-ink"
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
              </div>
            </div>
          )}

          {localError && <ErrorNote message={localError} />}

          <button
            type="button"
            disabled={busy || !file}
            onClick={() => onUpload(file)}
            className="flex w-full items-center justify-center gap-2 rounded-control bg-accent
                       px-4 py-2.5 text-base font-medium text-white transition-colors
                       hover:bg-[#2C74CC] disabled:cursor-not-allowed disabled:bg-line
                       disabled:text-muted"
          >
            {busy ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                Running audit
              </>
            ) : (
              <>
                <Play className="h-4 w-4" aria-hidden />
                Audit this file
              </>
            )}
          </button>
        </div>
      )}
    </section>
  );
}

function ErrorNote({ message }) {
  return (
    <p className="rounded-control border border-critical/40 bg-critical/10 px-3 py-2 text-small text-ink">
      {message}
    </p>
  );
}
