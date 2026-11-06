// Evaluation rules shared by the evaluation-scheme dialog and grade capture; they
// mirror the backend (REPLACEMENT_KINDS, ordinary_grade, PASSING_GRADE).
import type { EvaluationComponent, EvaluationKind } from "@/api/types";

export const PASSING_GRADE = 6;

// extraordinario / título de suficiencia replace the final grade: no weight, never
// "cuenta para final", and only for whoever failed the ordinario
export const REPLACES_FINAL: EvaluationKind[] = ["extraordinario", "titulo_suficiencia"];

export const replacesFinal = (c: Pick<EvaluationComponent, "kind">) =>
  REPLACES_FINAL.includes(c.kind);

export const weighsInFinal = (c: EvaluationComponent) =>
  c.counts_towards_final && !replacesFinal(c);

/** Weighted ordinario (CF), one decimal; null until every weighing component has a value. */
export function ordinaryGrade(
  components: EvaluationComponent[],
  values: Record<string, number | null | undefined>,
): number | null {
  const weighing = components.filter(weighsInFinal);
  const total = weighing.reduce((sum, c) => sum + c.weight_pct, 0);
  if (!weighing.length || total <= 0) return null;
  let acc = 0;
  for (const c of weighing) {
    const v = values[c.id];
    if (v == null || Number.isNaN(v)) return null;
    acc += v * c.weight_pct;
  }
  return Math.round((acc / total) * 10) / 10;
}

/** Whether an extraordinario-type cell can be captured given the ordinario. */
export const canCaptureReplacement = (ordinary: number | null) =>
  ordinary != null && ordinary < PASSING_GRADE;
