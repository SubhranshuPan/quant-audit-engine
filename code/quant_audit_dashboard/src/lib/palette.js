// Categorical series colours, in fixed slot order.
//
// These are the dataviz reference palette's dark steps, validated with
// `scripts/validate_palette.js` against this app's panel surface (#111823):
//
//   node validate_palette.js "#3987e5,...,#e66767" --mode dark --surface "#111823"
//   PASS lightness band · PASS chroma floor · PASS CVD separation (worst
//   adjacent dE 8.4) · PASS normal-vision floor (worst 19.3) · PASS contrast
//
// The ORDER is the colourblind-safety mechanism, not decoration - it is what
// keeps adjacent bands in a stack distinguishable. Never sort or cycle it.
export const SERIES = [
  "#3987E5", // blue
  "#D95926", // orange
  "#199E70", // aqua
  "#C98500", // yellow
  "#D55181", // magenta
  "#008300", // green
  "#9085E9", // violet
  "#E66767", // red
];

// A 9th series is never a generated hue. Anything past slot 8 folds into a
// single neutral "Other" band, which is honest about what it is.
export const OTHER_COLOR = "#5A6B80";
export const OTHER_LABEL = "Other";
export const MAX_SERIES = SERIES.length;

/**
 * Assign a colour to every asset, folding the smallest allocations into
 * "Other" once there are more assets than validated slots.
 *
 * Slots are assigned by position within one result, so colours are stable for
 * as long as a result is on screen. They are NOT stable across separate audits
 * of different ticker sets - a new audit is a new dataset, not a filter of the
 * old one.
 *
 * @param {string[]} assets       asset names, in backend order
 * @param {number[]} [meanWeights] average allocation, used to decide what folds
 * @returns {{ bands: {key: string, color: string, assets: string[]}[] }}
 */
export function assignSeries(assets, meanWeights) {
  if (assets.length <= MAX_SERIES) {
    return {
      bands: assets.map((asset, i) => ({
        key: asset,
        color: SERIES[i],
        assets: [asset],
      })),
    };
  }

  // Rank by |weight|, not signed weight: in a long/short book a large short is
  // one of the biggest exposures, and sorting signed would fold it into "Other"
  // while a negligible long kept its own colour slot.
  const ranked = assets
    .map((asset, i) => ({ asset, weight: Math.abs(meanWeights?.[i] ?? 0) }))
    .sort((a, b) => b.weight - a.weight);

  const kept = new Set(ranked.slice(0, MAX_SERIES - 1).map((r) => r.asset));
  const folded = assets.filter((a) => !kept.has(a));

  const bands = assets
    .filter((a) => kept.has(a))
    .map((asset, i) => ({ key: asset, color: SERIES[i], assets: [asset] }));

  // An uploaded file may legitimately contain an asset called "Other". Two
  // bands sharing a key would collide in the row objects, in React's keys and
  // in the tooltip lookup, so pick a name nothing else is using.
  let foldKey = OTHER_LABEL;
  while (assets.includes(foldKey)) foldKey = `${foldKey} (folded)`;

  bands.push({ key: foldKey, color: OTHER_COLOR, assets: folded });
  return { bands };
}
