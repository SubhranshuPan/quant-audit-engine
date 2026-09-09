import { useMemo } from "react";
import { adaptive, monthKey, monthLabel, pValue } from "../lib/format";

const BP = 10000;

/**
 * Month-by-month breakdown of where the regret came from.
 *
 * Note what is and is not per-month here. The HAC bandwidth h, the standard
 * error and the p-value are estimated once over the whole sample - that is what
 * the backend certifies, and re-deriving them per month in the browser would
 * mean a second, uncertified implementation of the estimator disagreeing with
 * the one the verdict rests on. So they are shown once, labelled full-sample,
 * and the monthly rows carry only quantities that are exactly derivable:
 * counts, means, dispersion, and each month's additive contribution to Ĉ_T.
 */
function summarise(result) {
  const total = result.daily_series.length;
  const groups = new Map();

  for (const day of result.daily_series) {
    const key = monthKey(day.date);
    if (!groups.has(key)) groups.set(key, { key, label: monthLabel(day.date), xi: [], cost: 0 });
    const g = groups.get(key);
    g.xi.push(day.xi);
    g.cost += day.portfolio_cost;
  }

  return [...groups.values()].map((g) => {
    const days = g.xi.length;
    const sum = g.xi.reduce((a, b) => a + b, 0);
    const mean = sum / days;
    // Population sd, matching the estimator's 1/T convention.
    const variance = g.xi.reduce((a, b) => a + (b - mean) ** 2, 0) / days;
    return {
      ...g,
      days,
      mean,
      sd: Math.sqrt(variance),
      // Each month's additive share of Eq. 27: these sum exactly to Ĉ_T.
      contribution: sum / total,
      cost: g.cost,
    };
  });
}

export default function AuditReportTable({ result }) {
  const rows = useMemo(() => summarise(result), [result]);
  const peak = Math.max(...rows.map((r) => Math.abs(r.contribution)), Number.EPSILON);

  return (
    <section className="panel" aria-labelledby="report-heading">
      <div className="panel-heading">
        <div>
          <h2 id="report-heading" className="text-lead font-semibold text-ink">
            Monthly breakdown
          </h2>
          <p className="mt-0.5 text-small text-ink-2">
            Each month&apos;s additive contribution to Ĉ_T, in basis points
          </p>
        </div>
      </div>

      {/* Sample-level statistics, kept visually apart from the monthly rows so
          nobody reads a full-sample h as a per-month figure. */}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-b border-line px-5 py-3.5 sm:grid-cols-4">
        <Stat label="Bandwidth (full sample)" value={`h = ${result.hac_lags}`} />
        <Stat label="Standard error (full sample)" value={adaptive(result.standard_error, 5)} />
        <Stat label="p-value (full sample)" value={pValue(result.p_value)} />
        <Stat label="Trading days" value={String(result.observations)} />
      </dl>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-base">
          <caption className="sr-only">
            Monthly regret breakdown for {result.assets.join(", ")}
          </caption>
          <thead>
            <tr className="border-b border-line text-small text-ink-2">
              <th scope="col" className="px-5 py-2.5 text-left font-medium">
                Month
              </th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">
                Days
              </th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">
                Mean ξ
              </th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">
                σ(ξ)
              </th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">
                Cost (month total)
              </th>
              <th scope="col" className="px-5 py-2.5 text-right font-medium">
                Contribution
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className="border-b border-line/60 last:border-0 hover:bg-raised">
                <th scope="row" className="px-5 py-2.5 text-left font-normal text-ink">
                  {row.label}
                </th>
                <Cell>{row.days}</Cell>
                <Cell>{(row.mean * BP).toFixed(2)}</Cell>
                <Cell>{(row.sd * BP).toFixed(2)}</Cell>
                <Cell>{(row.cost * BP).toFixed(1)}</Cell>
                <td className="px-5 py-2.5">
                  <div className="flex items-center justify-end gap-3">
                    {/* Magnitude only - one neutral hue sized by |contribution|.
                        The sign is carried by the number, not by colour. */}
                    <span
                      className="h-1.5 rounded-full bg-ink-2/45"
                      style={{ width: `${(Math.abs(row.contribution) / peak) * 56}px` }}
                      aria-hidden
                    />
                    <span className="figures w-20 text-right font-mono text-ink">
                      {(row.contribution * BP).toFixed(3)}
                    </span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-line-strong text-ink">
              <th scope="row" className="px-5 py-3 text-left font-medium">
                Full sample
              </th>
              <Cell>{result.observations}</Cell>
              <Cell>{(result.trajectory_covariance * BP).toFixed(2)}</Cell>
              <Cell>—</Cell>
              <Cell>—</Cell>
              <td className="px-5 py-3 text-right">
                <span className="figures font-mono font-medium">
                  {(result.trajectory_covariance * BP).toFixed(3)}
                </span>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      <p className="border-t border-line px-5 py-2.5 text-micro text-ink-2">
        Figures in basis points. Mean ξ and σ(ξ) are per-day; cost is the month&apos;s total, so
        it is not comparable across months of differing length. Monthly contributions sum to Ĉ_T
        by construction.
      </p>
    </section>
  );
}

function Cell({ children }) {
  return <td className="figures px-3 py-2.5 text-right font-mono text-ink-2">{children}</td>;
}

function Stat({ label, value }) {
  return (
    <div>
      <dt className="text-micro text-ink-2">{label}</dt>
      <dd className="figures mt-0.5 font-mono text-small text-ink">{value}</dd>
    </div>
  );
}
