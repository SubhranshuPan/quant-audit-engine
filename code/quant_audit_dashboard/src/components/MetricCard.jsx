import { verdictStyle } from "../lib/verdict";

export function VerdictBadge({ verdict, size = "base" }) {
  const { word, Icon, text, border, fill } = verdictStyle(verdict);
  const scale = size === "large" ? "gap-2.5 px-3.5 py-2 text-lead" : "gap-2 px-2.5 py-1 text-small";

  return (
    <span
      className={`inline-flex items-center rounded-control border font-medium ${border} ${fill} ${text} ${scale}`}
    >
      <Icon className={size === "large" ? "h-5 w-5" : "h-4 w-4"} aria-hidden />
      {word}
    </span>
  );
}

/**
 * One audited quantity. The symbol is shown next to the name because these
 * numbers are read alongside the paper, and Ĉ_T is how the paper names them.
 */
export default function MetricCard({ name, symbol, value, note, emphasis = false }) {
  return (
    <div className="flex flex-col justify-between gap-3 px-5 py-4">
      <div className="flex items-baseline gap-2">
        <h3 className="text-small font-medium text-ink-2">{name}</h3>
        {symbol && <span className="font-mono text-micro text-muted">{symbol}</span>}
      </div>
      <div>
        <p
          className={`figures font-mono tabular-nums ${
            emphasis ? "text-display text-ink" : "text-title text-ink"
          }`}
        >
          {value}
        </p>
        {note && <p className="mt-1 text-micro text-ink-2">{note}</p>}
      </div>
    </div>
  );
}
