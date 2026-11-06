// Shared by the Kárdex tab and its printable version: how a kárdex row reads.
import { SUBJECT_STATUS_LABELS } from "@/lib/format";
import type {
  PeriodType,
  RecognitionKind,
  StudentKardex,
  StudentKardexRow,
} from "@/api/types";

export const RECOGNITION_COLUMNS: { kind: RecognitionKind; label: string }[] = [
  { kind: "eq", label: "EQ" },
  { kind: "rev", label: "REV" },
  { kind: "conv", label: "CONV" },
];

const PERIOD_NOUN: Record<PeriodType, string> = {
  cuatrimestral: "Cuatrimestre",
  semestral: "Semestre",
  anual: "Año",
};

export function periodHeading(periodType: PeriodType | null, n: number): string {
  return `${PERIOD_NOUN[periodType ?? "cuatrimestral"]} ${n}`;
}

export interface KardexSection {
  period: number;
  heading: string;
  /** RVOE to show next to the heading: only where it changes, null otherwise. */
  rvoe: string | null;
  rows: StudentKardexRow[];
}

/** Rows grouped by plan period (server order kept inside each one), each section
 *  carrying its RVOE only where it differs from the previous period's. */
export function kardexSections(kardex: StudentKardex): KardexSection[] {
  const groups = new Map<number, StudentKardexRow[]>();
  for (const r of kardex.rows) {
    const list = groups.get(r.period_number) ?? [];
    list.push(r);
    groups.set(r.period_number, list);
  }
  const periods = new Map(kardex.periods.map((p) => [p.period_number, p]));
  return [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([period, rows]) => {
      const info = periods.get(period);
      return {
        period,
        heading: periodHeading(kardex.period_type, period),
        rvoe: info?.rvoe_changed ? info.rvoe : null,
        rows,
      };
    });
}

/** EQ / REV / CONV cell: the authority's grade, or the mark while it is pending. */
export function recognitionCell(r: StudentKardexRow, kind: RecognitionKind): string {
  if (r.recognition !== kind) return "";
  return r.final_grade != null ? String(r.final_grade) : kind.toUpperCase();
}

export const grade = (v: number | null) => (v == null ? "" : String(v));

export function statusLabel(r: StudentKardexRow): string {
  if (r.status === "pendiente") return "Pendiente";
  if (r.recognition && r.final_grade == null) {
    return `${r.recognition.toUpperCase()} pendiente`;
  }
  return SUBJECT_STATUS_LABELS[r.status];
}

export const isRetake = (r: StudentKardexRow) => (r.attempt_number ?? 1) > 1;

// Flat text columns for the printed and PDF kárdex. E2 only when someone has it.
export const showE2 = (kardex: StudentKardex) => kardex.rows.some((r) => r.e2 != null);

export function kardexHeaders(withE2: boolean): string[] {
  return [
    "Clave", "Asignatura", "Créd.", "Ciclo", "Grupo", "CF", "E1",
    ...(withE2 ? ["E2"] : []),
    ...RECOGNITION_COLUMNS.map((c) => c.label),
    "Estatus",
  ];
}

export function kardexCells(r: StudentKardexRow, withE2: boolean): string[] {
  return [
    r.code, r.name, String(r.credits), r.term_name ?? "", r.group_code ?? "",
    grade(r.cf), grade(r.e1),
    ...(withE2 ? [grade(r.e2)] : []),
    ...RECOGNITION_COLUMNS.map((c) => recognitionCell(r, c.kind)),
    statusLabel(r) + (isRetake(r) ? " (recursamiento)" : ""),
  ];
}
