// Reconocimiento de estudios previos (alumno que entra con certificado parcial) y
// registro de la calificación oficial de una materia en EQ / REV / CONV.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/api/client";
import type { RecognitionCandidates, RecognitionKind, Student, StudentKardexRow } from "@/api/types";
import { RECOGNITION_COLUMNS } from "@/lib/kardex";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const SKIP = "__skip__";

function invalidateStudent(queryClient: ReturnType<typeof useQueryClient>, studentId: string) {
  queryClient.invalidateQueries({ queryKey: ["kardex", studentId] });
}

export function RecognizePriorStudiesDialog({
  student,
  planVersionId,
  onClose,
}: {
  student: Student;
  planVersionId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["recognition-candidates", student.id, planVersionId],
    queryFn: () =>
      api<RecognitionCandidates>(
        `/students/${student.id}/recognitions/candidates?plan_version_id=${planVersionId}`,
      ),
  });
  const [kinds, setKinds] = useState<Record<string, RecognitionKind | typeof SKIP>>({});
  const [grades, setGrades] = useState<Record<string, string>>({});
  const [origin, setOrigin] = useState("");

  // nothing is marked by default: the whole plan is on the list
  const chosen = (data?.subjects ?? []).filter((s) => (kinds[s.plan_subject_id] ?? SKIP) !== SKIP);
  const periods = [...new Set((data?.subjects ?? []).map((s) => s.period_number))].sort((a, b) => a - b);
  const save = useMutation({
    mutationFn: () =>
      api(`/students/${student.id}/recognitions`, {
        method: "POST",
        body: JSON.stringify({
          plan_version_id: planVersionId,
          items: chosen.map((s) => ({
            plan_subject_id: s.plan_subject_id,
            kind: kinds[s.plan_subject_id],
            grade: grades[s.plan_subject_id] ? Number(grades[s.plan_subject_id]) : null,
            origin,
          })),
        }),
      }),
    onSuccess: () => {
      invalidateStudent(queryClient, student.id);
      toast.success(`${chosen.length} materias marcadas; las que no tienen nota quedan pendientes`);
      onClose();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "No se pudo guardar"),
  });

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Reconocer estudios previos</DialogTitle>
          <DialogDescription>
            Todo el plan del RVOE: marca las materias que acredita con un certificado parcial o
            dictamen, de cualquier cuatrimestre. Sin calificación quedan como «pendiente» hasta que
            la autoridad emita el documento; luego se registra la nota en el kárdex.
          </DialogDescription>
        </DialogHeader>
        {isLoading && <Skeleton className="h-40 w-full" />}
        {error && (
          <p className="text-sm text-destructive">
            {error instanceof ApiError ? error.message : "No se pudo cargar"}
          </p>
        )}
        {data && (
          <div className="grid gap-4">
            <p className="text-sm">
              Su grupo es <b>{data.group_code}</b> ({data.period_number}.º).
              {data.subjects.length === 0 && " El plan no tiene materias."}
            </p>
            <div className="grid gap-2">
              <Label htmlFor="rec-origin">Origen (escuela, RVOE o documento)</Label>
              <Input
                id="rec-origin"
                value={origin}
                placeholder="Ej. Certificado parcial · Preparatoria X · RVOE …"
                onChange={(e) => setOrigin(e.target.value)}
              />
            </div>
            {data.subjects.length > 0 && (
              <div className="max-h-[50vh] overflow-y-auto rounded-md border">
                {periods.map((period) => (
                  <div key={period}>
                    <p className="bg-muted/60 px-3 py-1 text-xs font-bold">{period}.º cuatrimestre</p>
                    <div className="divide-y">
                {data.subjects.filter((s) => s.period_number === period).map((s) => {
                  const kind = kinds[s.plan_subject_id] ?? SKIP;
                  const blocked = s.state === "evaluada" || s.state === "reconocida";
                  if (blocked) {
                    return (
                      <div
                        key={s.plan_subject_id}
                        className="flex items-center gap-3 px-3 py-2 text-sm text-muted-foreground"
                      >
                        <span className="flex-1">
                          <span className="font-semibold" data-numeric>
                            {s.code}
                          </span>{" "}
                          {s.name}
                        </span>
                        <span className="max-w-64 text-right text-xs">
                          {s.state === "evaluada"
                            ? "No se puede marcar: tiene evaluaciones registradas. Corrige su calificación en el kárdex."
                            : "Ya reconocida: se cambia con «Corregir»."}
                        </span>
                      </div>
                    );
                  }
                  return (
                    <div key={s.plan_subject_id} className="flex items-center gap-3 px-3 py-2 text-sm">
                      <span className="flex-1">
                        <span className="font-semibold" data-numeric>
                          {s.code}
                        </span>{" "}
                        {s.name}
                        {s.state === "en_curso" && kind !== SKIP && (
                          <span className="block text-xs text-muted-foreground">
                            La lleva en su grupo: al reconocerla se da de baja ahí.
                          </span>
                        )}
                      </span>
                      <Select
                        value={kind}
                        onValueChange={(v) =>
                          setKinds((prev) => ({ ...prev, [s.plan_subject_id]: v as RecognitionKind }))
                        }
                      >
                        <SelectTrigger className="h-8 w-40" aria-label={`Tipo para ${s.name}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="eq">Equivalencia</SelectItem>
                          <SelectItem value="rev">Revalidación</SelectItem>
                          <SelectItem value="conv">Convalidación</SelectItem>
                          <SelectItem value={SKIP}>No reconocer</SelectItem>
                        </SelectContent>
                      </Select>
                      <Input
                        type="number"
                        min={0}
                        max={10}
                        step="0.1"
                        className="h-8 w-20"
                        placeholder="pend."
                        disabled={kind === SKIP}
                        value={grades[s.plan_subject_id] ?? ""}
                        aria-label={`Calificación de ${s.name}`}
                        onChange={(e) =>
                          setGrades((prev) => ({ ...prev, [s.plan_subject_id]: e.target.value }))
                        }
                      />
                    </div>
                  );
                })}
                    </div>
                  </div>
                ))}
              </div>
            )}
            <DialogFooter>
              <Button
                className="font-bold"
                disabled={save.isPending || chosen.length === 0}
                onClick={() => save.mutate()}
              >
                {save.isPending ? "Guardando…" : `Marcar ${chosen.length} materias`}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function OfficialGradeDialog({
  studentId,
  row,
  onClose,
}: {
  studentId: string;
  row: StudentKardexRow;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [grade, setGrade] = useState("");
  const label = RECOGNITION_COLUMNS.find((c) => c.kind === row.recognition)?.label ?? "";
  const save = useMutation({
    mutationFn: () =>
      api(`/students/subject-enrollments/${row.subject_enrollment_id}/official-grade`, {
        method: "POST",
        body: JSON.stringify({ grade: Number(grade) }),
      }),
    onSuccess: () => {
      invalidateStudent(queryClient, studentId);
      toast.success("Calificación oficial registrada");
      onClose();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "No se pudo registrar"),
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Calificación oficial · {label}</DialogTitle>
          <DialogDescription>
            {row.code} {row.name}
            {row.origin ? ` — origen: ${row.origin}` : ""}. Asienta la calificación del documento
            de la autoridad.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="official-grade">Calificación</Label>
            <Input
              id="official-grade"
              type="number"
              min={0}
              max={10}
              step="0.1"
              required
              value={grade}
              onChange={(e) => setGrade(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="submit" className="font-bold" disabled={save.isPending || grade === ""}>
              {save.isPending ? "Guardando…" : "Registrar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
