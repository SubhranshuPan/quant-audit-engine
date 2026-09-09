# AI Strategy Auditor — dashboard

Milestone 5 — React front end for the SR 11-7 audit engine built in
Milestone 4 (`../quant_audit_backend`).

The console asks one question and builds everything around answering it:
**does the 95% confidence interval for a strategy's trajectory covariance
cross zero?** If it does, the measured regret is noise. If it doesn't, the
strategy is flagged.

## Running it

The backend must be running first — the dashboard has no data of its own.

```bash
# terminal 1 — the audit engine
cd ../quant_audit_backend
venv\Scripts\activate                    # source venv/bin/activate on macOS/Linux
uvicorn app.main:app --port 8000

# terminal 2 — this dashboard
npm install
npm run dev                              # http://localhost:5173
```

The header shows a live connection badge and re-checks `/health` every 15
seconds, so a backend that stops is visible without reading a request error.

Point it somewhere else with `VITE_API_BASE`:

```bash
echo "VITE_API_BASE=http://192.168.1.20:8000" > .env.local
```

## Stack

React 19 · Vite · Tailwind CSS 3.4 · Recharts 3 · Lucide icons · `fetch`

No HTTP client dependency: the backend speaks plain JSON and one multipart
upload, both of which `fetch` covers natively.

## Design

**Colour carries meaning, nothing else.** Every surface is neutral slate. The
only colour on screen is a series identity, a verdict state, or a focus ring —
so when something is coloured, that is information. There are no gradients and
no decorative shadows; panels are separated by hairlines, the way financial
documents actually group things.

**The hero is the interval itself.** A table of figures makes a reader work out
whether the interval clears zero. A number line answers it before they have
read a digit, so that is the one place the interface spends any boldness. The
scale is symmetric about zero and the endpoint labels sit under the endpoints
they name — placing them at the container edges would imply the axis spans the
interval, making a narrow interval look like it filled the scale.

**Type.** Public Sans is the US federal design system's typeface, and SR 11-7 is
a Federal Reserve supervisory letter — the interface speaks in the same voice as
the regulation it audits against. IBM Plex Mono carries the figures, always with
tabular numerals so columns align on the decimal.

**Motion.** One moment: the interval settles into place when a verdict arrives.
Nothing else animates on load, and `prefers-reduced-motion` disables it.

### Chart colours

The categorical palette is the dataviz reference palette's dark steps, checked
with its validator against this app's panel surface rather than picked by eye:

```
node validate_palette.js "#3987e5,#d95926,#199e70,#c98500,#d55181,#008300,#9085e9,#e66767" \
  --mode dark --surface "#111823"

PASS lightness band · PASS chroma floor · PASS CVD separation (worst adjacent ΔE 8.4)
PASS normal-vision floor (worst ΔE 19.3) · PASS contrast vs surface
```

Slot **order** is the colourblind-safety mechanism, not decoration — it is what
keeps adjacent bands in a stack apart, so it is never sorted or cycled. Colour
follows the asset, not its rank, so re-running with different tickers never
repaints an asset that survived. Past eight assets the smallest allocations fold
into a single neutral "Other" band rather than inventing a ninth hue. Status
colours (passed / inconclusive / flagged) are reserved and never reused as a
series, and every verdict ships an icon and a word so state never rests on
colour alone.

## Components

| File | Role |
|---|---|
| `components/Header.jsx` | Title and live backend connection badge |
| `components/AuditControls.jsx` | Strategy form and CSV drag-and-drop, in two tabs |
| `components/VerdictPanel.jsx` | The hero: verdict, plus the interval drawn against zero |
| `components/MetricCard.jsx` | `MetricCard` for the four KPIs, `VerdictBadge` for state |
| `components/RegretChart.jsx` | Cumulative regret with the 95% HAC interval as a band |
| `components/AllocationHeatmap.jsx` | Daily portfolio weights π̂ₜ as a stacked area |
| `components/AuditReportTable.jsx` | Month-by-month contribution breakdown |
| `lib/api.js` | Backend client and error normalisation |
| `lib/palette.js` | Validated series colours and the fold-to-Other rule |
| `lib/verdict.js` | Verdict string → icon, word and colour |
| `lib/format.js` | Number, basis-point, p-value and date formatting |

## Reading the numbers

Figures are in **basis points** wherever a chart or table would otherwise show
`0.0000` — daily regret lives around 1e-4. The metric cards show the raw decimal
with the basis-point value beneath, so the two units are always tied together.

Two honest limits are stated in the interface rather than hidden:

- **The regret chart omits the first ~21 trading days.** A running mean over that
  few observations reflects the `1/t` divisor, not the strategy, and swings by
  tens of basis points — which would squash the interval into an invisible
  sliver. Every day is still included in Ĉ_T and in the interval; only the plot
  starts later, and the caption says so.
- **The monthly table's `h`, standard error and p-value are full-sample.** They
  are estimated once over the whole window by the backend. Re-deriving them per
  month in the browser would mean a second, uncertified implementation of the
  Newey-West estimator disagreeing with the one the verdict rests on. The
  monthly rows carry only exactly-derivable quantities — counts, means,
  dispersion, and each month's additive contribution to Ĉ_T, which sum to Ĉ_T by
  construction (visible in the table's footer row).

The interval and verdict describe **Ĉ_T only**. `total_regret` adds the bias
correction and is shown as a point estimate; it is labelled as not covered by
the interval, because the bias term is a deterministic function of the sample
means and carries no interval of its own.

## Uploading a CSV

One row per trading day, a date column, and a matched pair of columns per asset:

```csv
date,return_AAPL,return_MSFT,weight_AAPL,weight_MSFT
2024-01-02,0.0121,-0.0043,0.6,0.4
```

Prefixes `return_` / `ret_` / `r_` and `weight_` / `w_` / `pi_` are accepted.
The backend requires at least 2 assets, weights summing to 1 on every row,
unique parseable dates, and at least 30 rows. Negative weights are allowed —
long/short books are legitimate to audit — and the allocation chart draws a zero
line when it sees them.

## Accessibility

Verdict state is icon + word + colour, never colour alone. Charts carry a legend
and a tooltip, and the monthly table is the table view of the same data. Focus
is visible on keyboard navigation only. Contrast was computed, not eyeballed:
all status and text colours clear 4.5:1 on every surface, except the muted grey,
which clears 3:1 and is therefore used only for non-essential labels. The layout
holds down to 390px, where the wide table scrolls inside its own container
rather than scrolling the page.

## Scripts

```bash
npm run dev       # dev server with HMR
npm run build     # production build to dist/
npm run preview   # serve the production build
npm run lint      # oxlint
```
