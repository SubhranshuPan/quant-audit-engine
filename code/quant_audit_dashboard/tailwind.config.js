/** @type {import('tailwindcss').Config} */

// Design tokens for the audit console. Two rules hold the whole system together:
//   1. Colour appears only where it carries meaning - series identity, verdict
//      state, focus. All chrome is neutral slate. There are no gradients.
//   2. Every series and status colour below was checked with the dataviz
//      validator against the panel surface (#111823), not chosen by eye.
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Surfaces: a cool slate ladder, darkest at the page ground.
        canvas: "#0A0F16",
        panel: "#111823", // the validated chart surface
        raised: "#18212E",
        line: "#223044",
        "line-strong": "#2E3F56",

        // Ink. `muted` clears 3:1 only - never use it for essential small text.
        ink: "#E6EDF5",
        "ink-2": "#94A3B8",
        muted: "#64748B",

        // Status. Reserved for verdict state; never reused as a series colour.
        // All three clear 4.5:1 on every surface above.
        good: "#3DDC97",
        warn: "#F2B441",
        critical: "#FF6B6B",

        accent: "#3987E5",
      },
      fontFamily: {
        // Public Sans is the US federal design system's typeface. SR 11-7 is a
        // Federal Reserve supervisory letter, so the interface speaks in the
        // same voice as the regulation it audits against.
        sans: ["Public Sans Variable", "system-ui", "sans-serif"],
        // Figures only, where digit alignment is the point.
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      fontSize: {
        micro: ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.01em" }],
        small: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.875rem", { lineHeight: "1.375rem" }],
        lead: ["1.09375rem", { lineHeight: "1.5rem" }],
        title: ["1.375rem", { lineHeight: "1.75rem", letterSpacing: "-0.011em" }],
        display: ["1.71875rem", { lineHeight: "2.125rem", letterSpacing: "-0.018em" }],
        figure: ["2.75rem", { lineHeight: "1", letterSpacing: "-0.025em" }],
      },
      borderRadius: {
        // Radius encodes hierarchy rather than being one value everywhere:
        // controls are tight, panels are looser.
        control: "4px",
        panel: "10px",
      },
    },
  },
  plugins: [],
};
