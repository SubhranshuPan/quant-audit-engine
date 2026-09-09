import { adaptive, pValue } from "../lib/format";
import { VerdictBadge } from "./MetricCard";
import { verdictStyle } from "../lib/verdict";

/**
 * The hero: the confidence interval drawn against zero.
 *
 * Every other number on this page supports one question - does the 95% interval
 * for the trajectory covariance cross zero? A table of figures makes a reader
 * work that out; a number line answers it before they have read a digit. This
 * is the one place the interface spends any visual boldness.
 */
export default function VerdictPanel({ result }) {
  const { trajectory_covariance: point, ci_lower: lo, ci_upper: hi } = result;
  const style = verdictStyle(result.audit_verdict);

  // A symmetric domain keeps zero in the middle, so "clears zero" reads as a
  // position rather than something to be inferred from the axis labels.
  const reach = Math.max(Math.abs(lo), Math.abs(hi), Math.abs(point)) || 1;
  const span = reach * 1.35;
  const pct = (x) => 50 + (50 * x) / span;

  const [loPct, hiPct, pointPct] = [pct(lo), pct(hi), pct(point)];
  const width = Math.max(hiPct - loPct, 0.6); // a degenerate interval stays visible
  // Grow the band out from the point estimate, which is where the statistic is.
  const settleOrigin = `${((pointPct - loPct) / width) * 100}%`;

  // Explain the verdict in the reader's terms rather than restating the string.
  const reading =
    style.key === "flagged"
      ? "The whole interval sits above zero, so this strategy's regret is not explained by sampling noise."
      : style.key === "inconclusive"
        ? "The trajectory has zero variance, so no interval can be formed and no verdict is defensible."
        : hi < 0
          ? "The whole interval sits below zero, so the strategy beat the benchmark by more than noise."
          : lo === 0 && hi === 0
            ? // Buy-and-hold gives xi identically 0, so the interval is a point
              // AT zero, not one straddling it. The backend treats that as a
              // real answer, and calling it "within noise" would undersell it.
              "The regret is exactly zero: this policy's weights never co-move with cost, so there is nothing for the estimator to find."
            : "The interval straddles zero, so the measured regret is within what noise alone would produce.";

  return (
    <section className="panel overflow-hidden" aria-labelledby="verdict-heading">
      <div className="panel-heading">
        <h2 id="verdict-heading" className="text-lead font-semibold text-ink">
          Compliance verdict
        </h2>
        <span className="font-mono text-micro text-muted">
          95% Newey-West HAC interval on Ĉ_T
        </span>
      </div>

      <div className="px-5 py-5">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
          <VerdictBadge verdict={result.audit_verdict} size="large" />
          <p className="max-w-[62ch] text-base text-ink-2">{reading}</p>
        </div>

        {/* The number line. Percentages rather than SVG so the labels stay real
            text at a real size no matter how wide the panel gets. */}
        <div className="mt-7">
          <div className="relative h-16" role="img" aria-label={ariaLabel(lo, hi, point)}>
            {/* Axis */}
            <div className="absolute left-0 right-0 top-7 h-px bg-line-strong" />

            {/* Zero: the thing the interval is being compared against. */}
            <div className="absolute left-1/2 top-2 h-11 w-px -translate-x-1/2 bg-ink-2" />
            <span className="absolute left-1/2 top-[46px] -translate-x-1/2 font-mono text-micro text-ink-2">
              0
            </span>

            {/* The interval */}
            <div
              className="interval-settle absolute top-[18px] h-[18px] rounded-[3px] border"
              style={{
                left: `${loPct}%`,
                width: `${width}%`,
                borderColor: style.stroke,
                backgroundColor: `${style.stroke}26`, // 15% alpha
                "--settle-origin": settleOrigin,
              }}
            />

            {/* The point estimate */}
            <div
              className="absolute top-[11px] h-8 w-[2px] -translate-x-1/2 rounded-full"
              style={{ left: `${pointPct}%`, backgroundColor: style.stroke }}
            />

            {/* Ĉ_T rides above its own tick. */}
            <span
              className="absolute top-0 -translate-x-1/2 whitespace-nowrap font-mono text-micro text-ink"
              style={{ left: `${clamp(pointPct)}%` }}
            >
              Ĉ_T {adaptive(point, 5)}
            </span>
          </div>

          {/* Endpoint labels sit under the endpoints they name. Putting them at
              the container edges would imply the axis runs from lo to hi, when
              it actually runs symmetrically about zero - so the interval would
              look like it filled the whole scale no matter how narrow it is.
              Zero gets its own row so it can never collide with a nearby bound. */}
          <div className="relative h-4">
            <span
              className="absolute -translate-x-1/2 font-mono text-micro text-ink-2"
              style={{ left: `${clamp(loPct)}%` }}
            >
              {adaptive(lo, 5)}
            </span>
            <span
              className="absolute -translate-x-1/2 font-mono text-micro text-ink-2"
              style={{ left: `${clamp(hiPct)}%` }}
            >
              {adaptive(hi, 5)}
            </span>
          </div>
        </div>

        <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-line pt-4 sm:grid-cols-4">
          <Fact label="Observations" value={`${result.observations} days`} />
          <Fact label="HAC lags" value={`h = ${result.hac_lags}`} />
          <Fact label="p-value" value={pValue(result.p_value)} />
          <Fact label="Assets" value={result.assets.join(", ")} />
        </dl>
      </div>
    </section>
  );
}

/** Keep a label fully inside the track when its mark sits at the extreme edge. */
function clamp(pct) {
  return Math.min(Math.max(pct, 5), 95);
}

function Fact({ label, value }) {
  return (
    <div>
      <dt className="text-micro text-ink-2">{label}</dt>
      <dd className="figures mt-0.5 truncate font-mono text-small text-ink" title={value}>
        {value}
      </dd>
    </div>
  );
}

function ariaLabel(lo, hi, point) {
  const position =
    lo > 0 ? "entirely above zero" : hi < 0 ? "entirely below zero" : "crossing zero";
  return `95% confidence interval from ${adaptive(lo, 5)} to ${adaptive(hi, 5)}, ${position}. Point estimate ${adaptive(point, 5)}.`;
}
