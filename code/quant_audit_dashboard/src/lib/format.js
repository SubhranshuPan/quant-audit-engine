// Number formatting. The audit deals in daily log-return space, where real
// values sit around 1e-4, so a naive toFixed(4) would render most of the
// interesting numbers as "0.0000".

/** Signed fixed-decimal, the default for headline audit figures. */
export function signed(value, digits = 4) {
  if (value == null || !Number.isFinite(value)) return "--";
  const s = value.toFixed(digits);
  return value > 0 ? `+${s}` : s; // toFixed already carries the minus sign
}

/**
 * Fixed decimals, but widened when the value would otherwise round to zero.
 * Keeps a column readable without hiding a real non-zero result.
 */
export function adaptive(value, digits = 4) {
  if (value == null || !Number.isFinite(value)) return "--";
  if (value !== 0 && Math.abs(value) < 0.5 * 10 ** -digits) {
    // Prefix the positive case too: in a column where every other figure
    // carries a leading + or -, an unsigned one reads as ambiguous, and sign
    // is the whole point of a regret figure.
    const e = value.toExponential(2);
    return value > 0 ? `+${e}` : e;
  }
  return signed(value, digits);
}

export function percent(value, digits = 1) {
  if (value == null || !Number.isFinite(value)) return "--";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Basis points - the unit a portfolio manager actually thinks in. */
export function basisPoints(value, digits = 1) {
  if (value == null || !Number.isFinite(value)) return "--";
  return `${(value * 10000).toFixed(digits)} bp`;
}

/**
 * P-values are read as thresholds, not as digits: below 0.001 the exact value
 * carries no extra meaning, so say so rather than printing noise.
 */
export function pValue(value) {
  if (value == null || !Number.isFinite(value)) return "not defined";
  if (value < 0.001) return "< 0.001";
  return value.toFixed(3);
}

/** "2023-04-17" -> "17 Apr 2023". Parsed as UTC so the day never shifts. */
export function longDate(iso) {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** "2023-04-17" -> "Apr 2023", for month grouping and axis ticks. */
export function monthLabel(iso) {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function monthKey(iso) {
  return String(iso).slice(0, 7);
}
