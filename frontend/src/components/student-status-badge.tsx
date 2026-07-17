// Semantic student-status pill: green = inscrito/al corriente, red = baja
// definitiva, neutral otherwise. Never brand yellow for status meaning.
import type { StudentStatus } from "@/api/types";
import { STUDENT_STATUS_LABELS } from "@/lib/format";
import { cn } from "@/lib/utils";

const STATUS_CLASSES: Record<StudentStatus, string> = {
  activo:
    "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-400",
  baja_definitiva:
    "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400",
  baja_temporal: "border-border bg-muted text-muted-foreground",
  egresado: "border-border bg-muted text-muted-foreground",
};

export function StudentStatusBadge({
  status,
  className,
}: {
  status: StudentStatus;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border px-2 py-0.5 text-xs font-semibold",
        STATUS_CLASSES[status],
        className,
      )}
    >
      {STUDENT_STATUS_LABELS[status]}
    </span>
  );
}
