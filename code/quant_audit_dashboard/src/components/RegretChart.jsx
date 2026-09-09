import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { adaptive, longDate, monthLabel } from "../lib/format";
import { verdictStyle } from "../lib/verdict";

// Daily regret lives around 1e-4, where raw decimals all render as "0.0000".
// Basis points is the unit this audience actually reads, so the axis works in
// bp and the tooltip carries the raw figure for anyone reconciling against the
// API response.
const BP = 10000;

export default function RegretChart({ result }) {
  const style = verdictStyle(result.audit_verdict);

  // A running mean over a handful of days is dominated by 1/t, not by the
  // strategy: the first fortnight swings by tens of basis points and squashes
  // the interval - the thing this chart exists to show - into an invisible
  // sliver. Those days are dropped from the plot and the omission is stated
  // below the chart rather than done silently.
  const burnIn = Math.min(21, Math.floor(result.daily_series.length / 10));
  const series = result.daily_series.slice(burnIn);

  const data = series.map((d) => ({
    date: d.date,
    cumulative: d.cumulative_regret * BP,
    daily: d.xi * BP,
  }));

  const lo = result.ci_lower * BP;
  const hi = result.ci_upper * BP;

  // Include the band and zero in the domain explicitly - letting Recharts infer
  // from the line alone can push the interval off-canvas, which would hide the
  // one comparison this chart exists to show.
  const values = data.map((d) => d.cumulative);
  const min = Math.min(...values, lo, 0);
  const max = Math.max(...values, hi, 0);
  const pad = (max - min || 1) * 0.12;

  // Roughly six date ticks, whatever the sample length.
  const step = Math.max(1, Math.ceil(data.length / 6));
  const ticks = data.filter((_, i) => i % step === 0).map((d) => d.date);

  return (
    <section className="panel" aria-labelledby="regret-heading">
      <div className="panel-heading">
        <div>
          <h2 id="regret-heading" className="text-lead font-semibold text-ink">
            Cumulative regret
          </h2>
          <p className="mt-0.5 text-small text-ink-2">
            Running mean of the daily covariance contribution, converging on Ĉ_T
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span
            className="h-2.5 w-4 rounded-sm border"
            style={{ borderColor: style.stroke, backgroundColor: `${style.stroke}26` }}
            aria-hidden
          />
          <span className="text-micro text-ink-2">95% HAC interval</span>
        </div>
      </div>

      <div className="px-2 pb-1 pt-4">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data} margin={{ top: 8, right: 20, bottom: 4, left: 4 }}>
            <CartesianGrid stroke="#223044" strokeDasharray="2 4" vertical={false} />

            {/* The interval the verdict was drawn from, as a band the line can
                be seen leaving or staying inside. */}
            <ReferenceArea
              y1={lo}
              y2={hi}
              fill={style.stroke}
              fillOpacity={0.12}
              stroke={style.stroke}
              strokeOpacity={0.5}
              strokeDasharray="3 3"
            />
            <ReferenceLine y={0} stroke="#94A3B8" strokeWidth={1} />

            <XAxis
              dataKey="date"
              ticks={ticks}
              tickFormatter={monthLabel}
              stroke="#223044"
              tick={{ fill: "#94A3B8", fontSize: 11 }}
              tickLine={false}
              minTickGap={12}
            />
            <YAxis
              domain={[min - pad, max + pad]}
              tickFormatter={(v) => v.toFixed(1)}
              stroke="#223044"
              tick={{ fill: "#94A3B8", fontSize: 11 }}
              tickLine={false}
              width={54}
              label={{
                value: "basis points",
                angle: -90,
                position: "insideLeft",
                fill: "#64748B",
                fontSize: 11,
                style: { textAnchor: "middle" },
              }}
            />

            <Tooltip
              content={<RegretTooltip />}
              cursor={{ stroke: "#2E3F56", strokeWidth: 1 }}
            />

            <Line
              type="monotone"
              dataKey="cumulative"
              stroke="#3987E5"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: "#3987E5", stroke: "#111823", strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <p className="border-t border-line px-5 py-2.5 text-micro text-ink-2">
        {burnIn > 0
          ? `First ${burnIn} trading days omitted: a running mean over that few observations reflects the 1/t divisor, not the strategy. All ${result.observations} days are included in Ĉ_T and in the interval.`
          : `All ${result.observations} trading days shown.`}
      </p>
    </section>
  );
}

function RegretTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const { date, cumulative, daily } = payload[0].payload;

  return (
    <div className="rounded-control border border-line-strong bg-raised px-3 py-2 shadow-lg">
      <p className="text-micro text-ink-2">{longDate(date)}</p>
      <dl className="mt-1.5 space-y-1">
        <Row label="Cumulative" bp={cumulative} />
        <Row label="That day" bp={daily} />
      </dl>
    </div>
  );
}

function Row({ label, bp }) {
  return (
    <div className="flex items-baseline justify-between gap-6">
      <dt className="text-micro text-ink-2">{label}</dt>
      <dd className="figures font-mono text-small text-ink">
        {bp.toFixed(2)} bp
        <span className="ml-2 text-micro text-muted">{adaptive(bp / BP, 5)}</span>
      </dd>
    </div>
  );
}
