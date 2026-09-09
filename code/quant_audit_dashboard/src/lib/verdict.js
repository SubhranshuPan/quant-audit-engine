import { CheckCircle2, HelpCircle, ShieldAlert } from "lucide-react";

/**
 * Verdict presentation. Status is never carried by colour alone - each state
 * ships an icon and a word, so it survives colourblindness, greyscale print
 * and forced-colours mode.
 *
 * The backend emits four verdicts. "PASSED: Model Outperforms Benchmark" is a
 * significant result too, so it must not be styled like the neutral pass.
 */
export function verdictStyle(verdict = "") {
  if (verdict.startsWith("FLAGGED")) {
    return {
      key: "flagged",
      word: "Flagged",
      Icon: ShieldAlert,
      text: "text-critical",
      border: "border-critical/45",
      fill: "bg-critical/10",
      stroke: "#FF6B6B",
    };
  }
  if (verdict.startsWith("INCONCLUSIVE")) {
    return {
      key: "inconclusive",
      word: "Inconclusive",
      Icon: HelpCircle,
      text: "text-warn",
      border: "border-warn/45",
      fill: "bg-warn/10",
      stroke: "#F2B441",
    };
  }
  return {
    key: "passed",
    word: "Passed",
    Icon: CheckCircle2,
    text: "text-good",
    border: "border-good/45",
    fill: "bg-good/10",
    stroke: "#3DDC97",
  };
}
