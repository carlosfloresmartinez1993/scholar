import { useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, ClipboardCheck, Save, X } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  AttendanceRecord,
  AttendanceReportRow,
  AttendanceStatus,
  ClassSession,
  GradeGrid,
  Group,
  GroupSubject,
  Justification,
  PlanSubject,
  Student,
  Term,
} from "@/api/types";
import {
  ATTENDANCE_STATUS_LABELS,
  formatDate,
  todayISO,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const Route = createFileRoute("/_auth/asistencias")({
  component: AsistenciasPage,
});

const ROLL_STATUSES: AttendanceStatus[] = [
  "presente",
  "falta",
  "retardo",
  "justificado",
];

function AsistenciasPage() {
  const { data: terms } = useQuery({
    queryKey: queryKeys.terms,
    queryFn: () => api<Term[]>("/catalog/terms"),
  });
  const [selectedTerm, setSelectedTerm] = useState<string | null>(null);
  const termId = selectedTerm ?? terms?.find((t) => t.is_open)?.id ?? null;

  const [groupId, setGroupId] = useState<string | null>(null);
  const [groupSubjectId, setGroupSubjectId] = useState<string | null>(null);

  const { data: groups } = useQuery({
    queryKey: queryKeys.groups(termId ?? undefined),
    queryFn: () => api<Group[]>(`/catalog/groups?term_id=${termId}`),
    enabled: !!termId,
  });
  const group = groups?.find((g) => g.id === groupId);

  const { data: groupSubjects } = useQuery({
    queryKey: queryKeys.groupSubjects(groupId ?? ""),
    queryFn: () => api<GroupSubject[]>(`/catalog/groups/${groupId}/subjects`),
    enabled: !!groupId,
  });
  const { data: planSubjects } = useQuery({
    queryKey: queryKeys.planSubjects(group?.plan_version_id ?? ""),
    queryFn: () =>
      api<PlanSubject[]>(
        `/catalog/plan-versions/${group!.plan_version_id}/subjects`,
      ),
    enabled: !!group,
  });

  const subjectName = (planSubjectId: string) => {
    const s = planSubjects?.find((ps) => ps.id === planSubjectId);
    return s ? `${s.code} — ${s.name}` : "Materia";
  };

  return (
    <div className="space-y-6">
      <h1 className="text-3xl">Asistencias</h1>

      <div className="flex flex-wrap items-center gap-3">
        <Select
          value={termId ?? ""}
          onValueChange={(v) => {
            setSelectedTerm(v);
            setGroupId(null);
            setGroupSubjectId(null);
          }}
        >
          <SelectTrigger className="w-56">
            <SelectValue placeholder="Ciclo" />
          </SelectTrigger>
          <SelectContent>
            {terms?.map((t) => (
              <SelectItem key={t.id} value={t.id}>
                {t.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={groupId ?? ""}
          onValueChange={(v) => {
            setGroupId(v);
            setGroupSubjectId(null);
          }}
          disabled={!termId}
        >
          <SelectTrigger className="w-56">
            <SelectValue placeholder="Grupo" />
          </SelectTrigger>
          <SelectContent>
            {groups?.map((g) => (
              <SelectItem key={g.id} value={g.id}>
                {g.code}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={groupSubjectId ?? ""}
          onValueChange={setGroupSubjectId}
          disabled={!groupId}
        >
          <SelectTrigger className="w-80">
            <SelectValue placeholder="Materia" />
          </SelectTrigger>
          <SelectContent>
            {groupSubjects?.map((gs) => (
              <SelectItem key={gs.id} value={gs.id}>
                {subjectName(gs.plan_subject_id)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {!groupSubjectId ? (
        <EmptyState
          icon={ClipboardCheck}
          title="Seleccione ciclo, grupo y materia"
          description="Elija la materia para pasar lista, revisar el porcentaje de asistencia y el derecho a examen."
        />
      ) : (
        <>
          <RollCallSection key={groupSubjectId} groupSubjectId={groupSubjectId} />
          <ReportSection groupSubjectId={groupSubjectId} />
        </>
      )}

      <JustificationsSection />
    </div>
  );
}

// --- Roll call --------------------------------------------------------------------

function RollCallSection({ groupSubjectId }: { groupSubjectId: string }) {
  const queryClient = useQueryClient();
  const [date, setDate] = useState(todayISO());
  const [marks, setMarks] = useState<Record<string, AttendanceStatus>>({});

  const { data: grid, isLoading } = useQuery({
    queryKey: queryKeys.gradeGrid(groupSubjectId),
    queryFn: () => api<GradeGrid>(`/grades/group-subjects/${groupSubjectId}/grid`),
  });

  const { data: sessions } = useQuery({
    queryKey: queryKeys.sessions(groupSubjectId),
    queryFn: () =>
      api<ClassSession[]>(`/attendance/group-subjects/${groupSubjectId}/sessions`),
  });
  const existingSession = sessions?.find(
    (s) => s.session_date === date && s.sequence === 1,
  );

  const { data: existingRecords } = useQuery({
    queryKey: queryKeys.sessionRecords(existingSession?.id ?? ""),
    queryFn: () =>
      api<AttendanceRecord[]>(
        `/attendance/sessions/${existingSession!.id}/records`,
      ),
    enabled: !!existingSession,
  });

  useEffect(() => {
    setMarks(
      existingRecords
        ? Object.fromEntries(
            existingRecords.map((r) => [r.student_id, r.status]),
          )
        : {},
    );
  }, [date, existingRecords]);

  const save = useMutation({
    mutationFn: () =>
      api(`/attendance/sessions`, {
        method: "POST",
        body: JSON.stringify({
          group_subject_id: groupSubjectId,
          session_date: date,
          sequence: 1,
          records: (grid?.rows ?? []).map((r) => ({
            student_id: r.student_id,
            status: marks[r.student_id] ?? "presente",
          })),
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.attendanceReport(groupSubjectId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.sessions(groupSubjectId),
      });
      queryClient.invalidateQueries({ queryKey: ["session-records"] });
      toast.success("Asistencia registrada");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  if (isLoading || !grid) {
    return <Skeleton className="h-48 w-full rounded-2xl" />;
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-bold">Pase de lista</h2>
        <div className="flex items-center gap-2">
          <Label htmlFor="session-date" className="text-sm font-semibold">
            Fecha
          </Label>
          <Input
            id="session-date"
            type="date"
            className="w-44"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
          <Button
            className="font-bold"
            disabled={save.isPending || grid.rows.length === 0}
            onClick={() => save.mutate()}
          >
            <Save className="size-4" />
            {save.isPending ? "Guardando…" : "Guardar sesión"}
          </Button>
        </div>
      </div>

      {existingSession && (
        <p className="text-sm text-muted-foreground">
          Ya hay una sesión registrada para esta fecha; al guardar se
          actualizará el pase de lista existente.
        </p>
      )}

      <div className="rounded-2xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Matrícula</TableHead>
              <TableHead>Alumno</TableHead>
              <TableHead>Asistencia</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {grid.rows.map((row) => {
              const current = marks[row.student_id] ?? "presente";
              return (
                <TableRow key={row.student_id}>
                  <TableCell data-numeric>{row.enrollment_number}</TableCell>
                  <TableCell className="font-semibold">
                    {row.student_name}
                  </TableCell>
                  <TableCell>
                    <div
                      role="radiogroup"
                      aria-label={`Asistencia de ${row.student_name}`}
                      className="flex flex-wrap gap-1"
                    >
                      {ROLL_STATUSES.map((status) => (
                        <button
                          key={status}
                          type="button"
                          role="radio"
                          aria-checked={current === status}
                          onClick={() =>
                            setMarks({ ...marks, [row.student_id]: status })
                          }
                          className={cn(
                            "rounded-full border px-3 py-1 text-xs font-semibold transition-colors",
                            current === status
                              ? status === "falta"
                                ? "border-destructive bg-destructive text-white"
                                : "border-primary bg-primary text-primary-foreground"
                              : "text-muted-foreground hover:bg-muted",
                          )}
                        >
                          {ATTENDANCE_STATUS_LABELS[status]}
                        </button>
                      ))}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
            {grid.rows.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={3}
                  className="py-8 text-center text-muted-foreground"
                >
                  No hay alumnos inscritos en esta materia
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

// --- Attendance report --------------------------------------------------------------

function ReportSection({ groupSubjectId }: { groupSubjectId: string }) {
  const { data: report, isLoading } = useQuery({
    queryKey: queryKeys.attendanceReport(groupSubjectId),
    queryFn: () =>
      api<AttendanceReportRow[]>(
        `/attendance/group-subjects/${groupSubjectId}/report`,
      ),
  });

  return (
    <section className="space-y-3">
      <h2 className="text-xl font-bold">Reporte de asistencia</h2>
      <div className="rounded-2xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Matrícula</TableHead>
              <TableHead>Alumno</TableHead>
              <TableHead>Sesiones</TableHead>
              <TableHead>Asistió</TableHead>
              <TableHead>%</TableHead>
              <TableHead>Mínimo</TableHead>
              <TableHead>Derecho a examen</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={7}>
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            )}
            {report?.map((r) => (
              <TableRow key={r.student_id}>
                <TableCell data-numeric>{r.enrollment_number}</TableCell>
                <TableCell className="font-semibold">{r.student_name}</TableCell>
                <TableCell data-numeric>{r.sessions}</TableCell>
                <TableCell data-numeric>{r.attended}</TableCell>
                <TableCell data-numeric className="font-semibold">
                  {r.attendance_pct}%
                </TableCell>
                <TableCell data-numeric className="text-muted-foreground">
                  {r.min_attendance_pct}%
                </TableCell>
                <TableCell>
                  <Badge variant={r.right_to_exam ? "default" : "destructive"}>
                    {r.right_to_exam ? "Con derecho" : "Sin derecho"}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
            {report && report.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="py-8 text-center text-muted-foreground"
                >
                  Sin datos de asistencia
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

// --- Pending justifications ------------------------------------------------------------

function JustificationsSection() {
  const queryClient = useQueryClient();
  const { data: pending, isLoading } = useQuery({
    queryKey: queryKeys.justifications("pendiente"),
    queryFn: () =>
      api<Justification[]>(`/attendance/justifications?status=pendiente`),
  });
  const { data: students } = useQuery({
    queryKey: queryKeys.students(),
    queryFn: () => api<Student[]>("/students?limit=1000"),
  });

  const [rejecting, setRejecting] = useState<Justification | null>(null);
  const [notes, setNotes] = useState("");

  const review = useMutation({
    mutationFn: ({
      id,
      status,
      reviewNotes,
    }: {
      id: string;
      status: "aprobado" | "rechazado";
      reviewNotes?: string;
    }) =>
      api<Justification>(`/attendance/justifications/${id}/review`, {
        method: "POST",
        body: JSON.stringify({ status, review_notes: reviewNotes ?? "" }),
      }),
    onSuccess: (_, { status }) => {
      queryClient.invalidateQueries({ queryKey: ["justifications"] });
      toast.success(
        status === "aprobado" ? "Justificante aprobado" : "Justificante rechazado",
      );
      setRejecting(null);
      setNotes("");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al revisar"),
  });

  const studentName = (id: string) =>
    students?.find((s) => s.id === id)?.full_name ?? id.slice(0, 8);

  return (
    <section className="space-y-3">
      <h2 className="text-xl font-bold">Justificantes pendientes</h2>
      <div className="rounded-2xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Alumno</TableHead>
              <TableHead>Motivo</TableHead>
              <TableHead>Periodo</TableHead>
              <TableHead>Evidencia</TableHead>
              <TableHead className="w-52" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={5}>
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            )}
            {pending?.map((j) => (
              <TableRow key={j.id}>
                <TableCell className="font-semibold">
                  {studentName(j.student_id)}
                </TableCell>
                <TableCell className="max-w-64 truncate">{j.reason}</TableCell>
                <TableCell className="whitespace-nowrap">
                  {formatDate(j.date_from)} – {formatDate(j.date_to)}
                </TableCell>
                <TableCell className="max-w-40 truncate text-muted-foreground">
                  {j.evidence_filename || "Sin evidencia"}
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={review.isPending}
                    onClick={() =>
                      review.mutate({ id: j.id, status: "aprobado" })
                    }
                  >
                    <Check className="size-4 text-green-600" /> Aprobar
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={review.isPending}
                    onClick={() => setRejecting(j)}
                  >
                    <X className="size-4 text-destructive" /> Rechazar
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {pending && pending.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className="py-8 text-center text-muted-foreground"
                >
                  No hay justificantes pendientes de revisión
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog
        open={!!rejecting}
        onOpenChange={(v) => {
          if (!v) setRejecting(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rechazar justificante</DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (rejecting)
                review.mutate({
                  id: rejecting.id,
                  status: "rechazado",
                  reviewNotes: notes,
                });
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="rej-notes">Notas de revisión</Label>
              <Textarea
                id="rej-notes"
                required
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>
            <DialogFooter>
              <Button
                type="submit"
                variant="destructive"
                className="font-bold"
                disabled={review.isPending}
              >
                {review.isPending ? "Rechazando…" : "Rechazar"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
