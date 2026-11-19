// Inscripciones por ciclo: a compact list of every group the student was in — the
// same story as the kárdex, one row per cuatrimestre instead of one per materia.
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { formatDate } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface EnrollmentHistoryRow {
  group_enrollment_id: string;
  campus: string;
  term_name: string;
  group_code: string;
  period_number: number;
  program: string;
  plan_label: string;
  plan_version_id: string;
  enrollment_number: string;
  enrolled_at: string;
  kind: "inscripcion" | "reinscripcion" | "otro_grupo" | "eq" | "rev" | "conv";
  status: "activa" | "baja";
  term_open: boolean;
  subjects: { total: number; aprobadas: number; reprobadas: number; cursando: number; baja: number };
}

const KIND_LABELS: Record<EnrollmentHistoryRow["kind"], string> = {
  inscripcion: "Inscripción",
  reinscripcion: "Reinscripción",
  otro_grupo: "Materias en otro grupo",
  eq: "Equivalencia",
  rev: "Revalidación",
  conv: "Convalidación",
};

function subjectsSummary(s: EnrollmentHistoryRow["subjects"]): string {
  const parts = [
    s.aprobadas ? `${s.aprobadas} aprobada${s.aprobadas === 1 ? "" : "s"}` : "",
    s.reprobadas ? `${s.reprobadas} reprobada${s.reprobadas === 1 ? "" : "s"}` : "",
    s.cursando ? `${s.cursando} en curso` : "",
    s.baja ? `${s.baja} de baja` : "",
  ].filter(Boolean);
  return `${s.total} materia${s.total === 1 ? "" : "s"}` + (parts.length ? ` · ${parts.join(", ")}` : "");
}

export function EnrollmentHistoryTab({ studentId }: { studentId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["enrollment-history", studentId],
    queryFn: () => api<EnrollmentHistoryRow[]>(`/students/${studentId}/enrollment-history`),
  });
  // more than one carrera or plan: say which on each row
  const manyPlans = new Set((data ?? []).map((r) => r.plan_version_id)).size > 1;

  if (isLoading) return <Skeleton className="h-40 w-full rounded-md" />;
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-xl font-bold">Inscripciones por ciclo</h2>
        <p className="text-sm text-muted-foreground">
          Cada grupo en el que ha estado el alumno, del ciclo más reciente al más antiguo. El
          detalle de cada materia está en el Kárdex.
        </p>
      </div>
      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Plantel</TableHead>
              <TableHead>Ciclo escolar</TableHead>
              <TableHead>Grupo</TableHead>
              <TableHead>Cuatrimestre</TableHead>
              <TableHead>Matrícula</TableHead>
              <TableHead>Fecha de inscripción</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>Materias</TableHead>
              <TableHead>Estatus</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data ?? []).map((r) => (
              <TableRow key={r.group_enrollment_id}>
                <TableCell>{r.campus}</TableCell>
                <TableCell data-numeric>{r.term_name}</TableCell>
                <TableCell>
                  <span className="font-semibold" data-numeric>
                    {r.group_code}
                  </span>
                  {manyPlans && (
                    <div className="text-xs text-muted-foreground">
                      {r.program} · {r.plan_label}
                    </div>
                  )}
                </TableCell>
                <TableCell data-numeric>{r.period_number}.º</TableCell>
                <TableCell data-numeric>{r.enrollment_number}</TableCell>
                <TableCell data-numeric>{formatDate(r.enrolled_at)}</TableCell>
                <TableCell>{KIND_LABELS[r.kind]}</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {subjectsSummary(r.subjects)}
                </TableCell>
                <TableCell>
                  {/* activa in an open cycle: in course; in a closed one: concluded;
                      baja: every subject dropped there, or moved to another group */}
                  <Badge
                    variant={
                      r.status === "baja" ? "secondary" : r.term_open ? "default" : "outline"
                    }
                  >
                    {r.status === "baja" ? "Baja" : r.term_open ? "En curso" : "Concluida"}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
            {data && data.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className="py-8 text-center text-muted-foreground">
                  Sin inscripciones
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}
