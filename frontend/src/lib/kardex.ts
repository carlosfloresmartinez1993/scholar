// Shared by the Kárdex tab and its printable version: how a kárdex row reads.
import { SUBJECT_STATUS_LABELS } from "@/lib/format";
import type {
  PeriodType,
  RecognitionKind,
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

/** Rows grouped by plan period, keeping the server's order inside each one. */
export function groupByPeriod(rows: StudentKardexRow[]): [number, StudentKardexRow[]][] {
  const groups = new Map<number, StudentKardexRow[]>();
  for (const r of rows) {
    const list = groups.get(r.period_number) ?? [];
    list.push(r);
    groups.set(r.period_number, list);
  }
  return [...groups.entries()].sort(([a], [b]) => a - b);
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
