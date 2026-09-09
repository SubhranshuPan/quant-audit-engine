import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { assignSeries } from "../lib/palette";
import { longDate, monthLabel, percent } from "../lib/format";

const SURFACE = "#111823";

/**
 * Portfolio weights over time, as a stacked area.
 *
 * The daily weight vector comes straight from the audited policy, so this is
 * the trajectory the covariance estimator was actually computed on - it shows
 * what the strategy did, next to the chart showing what that cost.
 */
export default function AllocationHeatmap({ result }) {
  const { bands, data, hasShort } = useMemo(() => {
    const { bands } = assignSeries(result.assets, result.mean_weights);
    const index = new Map(result.assets.map((a, i) => [a, i]));

    const data = result.daily_series.map((day) => {
      const row = { date: day.date };
      for (const band of bands) {
        // A folded "Other" band sums the allocations it stands in for.
        row[band.key] = band.assets.reduce((sum, a) => sum + (day.weights[index.get(a)] ?? 0), 0);
      }
      return row;
    });

    const hasShort = data.some((row) => bands.some((b) => row[b.key] < 0));
    return { bands, data, hasShort };
  }, [result]);

  const step = Math.max(1, Math.ceil(data.length / 6));
  const ticks = data.filter((_, i) => i % step === 0).map((d) => d.date);

  const meanByKey = Object.fromEntries(
    bands.map((b) => [b.key, data.reduce((s, r) => s + r[b.key], 0) / (data.length || 1)]),
  );

  return (
    <section className="panel" aria-labelledby="allocation-heading">
      <div className="panel-heading">
        <div>
          <h2 id="allocation-heading" className="text-lead font-semibold text-ink">
            Allocation over time
          </h2>
          <p className="mt-0.5 text-small text-ink-2">
            Daily portfolio weights π̂_t held by the audited policy
          </p>
        </div>
      </div>

      {/* Legend above the plot, so identity is established before the shapes
          are read. Each entry carries the asset name and its average weight -
          colour is never the only thing telling two bands apart. */}
      <div className="flex flex-wrap gap-x-5 gap-y-2 border-b border-line px-5 py-3">
        {bands.map((band) => (
          <div key={band.key} className="flex items-center gap-2">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ backgroundColor: band.color }}
              aria-hidden
            />
            <span className="text-small text-ink">{band.key}</span>
            <span className="figures font-mono text-micro text-ink-2">
              {percent(meanByKey[band.key])}
            </span>
            {band.assets.length > 1 && (
              <span className="text-micro text-muted">({band.assets.length} assets)</span>
            )}
          </div>
        ))}
      </div>

      <div className="px-2 py-4">
        <ResponsiveContainer width="100%" height={260}>
          {/* stackOffset="sign" keeps negative weights below the zero line.
              Recharts' default ("none") cumulatively sums signed values, so a
              short would be drawn stacked on top of the longs - above zero -
              contradicting the zero line and the note underneath. */}
          <AreaChart
            data={data}
            stackOffset="sign"
            margin={{ top: 8, right: 20, bottom: 4, left: 4 }}
          >
            <CartesianGrid stroke="#223044" strokeDasharray="2 4" vertical={false} />
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
              /* Long-only weights sum to exactly 1, so the axis is pinned to
                 the simplex - an auto domain overshoots to 120% and invents
                 headroom that cannot exist. A long/short book is allowed to
                 find its own range. */
              domain={hasShort ? ["auto", "auto"] : [0, 1]}
              ticks={hasShort ? undefined : [0, 0.25, 0.5, 0.75, 1]}
              tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
              stroke="#223044"
              tick={{ fill: "#94A3B8", fontSize: 11 }}
              tickLine={false}
              width={54}
            />
            {hasShort && <ReferenceLine y={0} stroke="#94A3B8" strokeWidth={1} />}
            <Tooltip content={<AllocationTooltip bands={bands} />} cursor={{ fill: "#18212E" }} />

            {bands.map((band) => (
              <Area
                key={band.key}
                type="monotone"
                dataKey={band.key}
                stackId="weights"
                fill={band.color}
                fillOpacity={0.9}
                /* A hairline in the surface colour separates touching bands, so
                   two adjacent fills never blur into one shape. */
                stroke={SURFACE}
                strokeWidth={1}
                isAnimationActive={false}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {hasShort && (
        <p className="border-t border-line px-5 py-2.5 text-micro text-ink-2">
          This portfolio holds short positions, so bands below the zero line are negative weights.
        </p>
      )}
    </section>
  );
}

function AllocationTooltip({ active, payload, label, bands }) {
  if (!active || !payload?.length) return null;

  return (
    <div className="rounded-control border border-line-strong bg-raised px-3 py-2 shadow-lg">
      <p className="text-micro text-ink-2">{longDate(label)}</p>
      <dl className="mt-1.5 space-y-1">
        {bands.map((band) => {
          const entry = payload.find((p) => p.dataKey === band.key);
          if (!entry) return null;
          return (
            <div key={band.key} className="flex items-baseline justify-between gap-6">
              <dt className="flex items-center gap-2 text-micro text-ink-2">
                <span
                  className="h-2 w-2 rounded-sm"
                  style={{ backgroundColor: band.color }}
                  aria-hidden
                />
                {band.key}
              </dt>
              <dd className="figures font-mono text-small text-ink">{percent(entry.value)}</dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}
