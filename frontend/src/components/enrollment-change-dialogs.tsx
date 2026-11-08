// Baja de materias y cambio de grupo de un alumno ya inscrito (página de Grupos).
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/api/client";
import type { Campus, Group } from "@/api/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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

export interface GroupStudentSubjects {
  student_id: string;
  name: string;
  subjects: {
    planSubjectId: string;
    subjectEnrollmentId: string;
    finalGrade: number | null; // with a final grade it can no longer be dropped
  }[];
}

// Baja de materias: they leave the group's lists; in the kárdex the subject stays in
// its period, pending (history kept in the bitácora). Only subjects without a final grade; dropping all of them closes
// the student's enrollment in the group.
export function DropSubjectsDialog({
  group,
  student,
  subjectName,
  onClose,
  onDone,
}: {
  group: Group;
  student: GroupStudentSubjects;
  subjectName: (planSubjectId: string) => string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [ids, setIds] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const all = ids.length > 0 && ids.length === student.subjects.length;
  const drop = useMutation({
    mutationFn: () =>
      api(`/students/subject-enrollments/drop`, {
        method: "POST",
        body: JSON.stringify({ subject_enrollment_ids: ids, reason }),
      }),
    onSuccess: () => {
      onDone();
      toast.success(ids.length === 1 ? "Materia dada de baja" : "Materias dadas de baja");
      onClose();
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "No se pudo dar de baja", {
        duration: 8000,
      }),
  });
  const subjects = [...student.subjects].sort((a, b) =>
    subjectName(a.planSubjectId).localeCompare(subjectName(b.planSubjectId), "es"),
  );
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Baja de materias — {student.name}</DialogTitle>
          <DialogDescription>
            La materia deja de aparecer en las listas de {group.code} (calificaciones,
            asistencia, actas). En el kárdex sigue en su periodo, pendiente de cursar; la baja
            queda en la bitácora. Solo materias sin calificación final.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            drop.mutate();
          }}
        >
          <div className="max-h-72 space-y-1 overflow-y-auto rounded-md border p-2">
            {subjects.map((s) => {
              const closed = s.finalGrade != null;
              return (
                <label
                  key={s.subjectEnrollmentId}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-2 py-1 text-sm",
                    closed ? "text-muted-foreground" : "hover:bg-muted",
                  )}
                >
                  <Checkbox
                    disabled={closed}
                    checked={ids.includes(s.subjectEnrollmentId)}
                    onCheckedChange={(v) =>
                      setIds(
                        v === true
                          ? [...ids, s.subjectEnrollmentId]
                          : ids.filter((id) => id !== s.subjectEnrollmentId),
                      )
                    }
                  />
                  <span className="truncate">{subjectName(s.planSubjectId)}</span>
                  {closed && (
                    <span className="ml-auto text-xs" data-numeric>
                      Calificada ({s.finalGrade})
                    </span>
                  )}
                </label>
              );
            })}
          </div>
          <div className="grid gap-2">
            <Label htmlFor="drop-reason">Motivo (opcional)</Label>
            <Input
              id="drop-reason"
              value={reason}
              maxLength={255}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          {all && (
            <p className="text-sm text-destructive">
              Son todas sus materias del grupo: el alumno también queda dado de baja de{" "}
              {group.code}.
            </p>
          )}
          <DialogFooter>
            <Button
              type="submit"
              variant="destructive"
              className="font-bold"
              disabled={drop.isPending || ids.length === 0}
            >
              {drop.isPending
                ? "Guardando…"
                : ids.length === 0
                  ? "Dar de baja"
                  : ids.length === 1
                    ? "Dar de baja 1 materia"
                    : `Dar de baja ${ids.length} materias`}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// Cambio de grupo: same term and plan (another turno, campus or modality). The
// subjects in course move with their captured grades and the charges follow the
// student; graded ones stay where they were taken.
export function ChangeGroupDialog({
  group,
  groups,
  student,
  onClose,
  onDone,
}: {
  group: Group;
  groups: Group[];
  student: GroupStudentSubjects;
  onClose: () => void;
  onDone: () => void;
}) {
  const [toId, setToId] = useState("");
  const [reason, setReason] = useState("");
  const { data: campuses } = useQuery({
    queryKey: ["campuses"],
    queryFn: () => api<Campus[]>("/catalog/campuses"),
  });
  const campusName = (id: string) => campuses?.find((c) => c.id === id)?.name ?? "";
  const options = groups
    .filter(
      (g) =>
        g.id !== group.id &&
        g.plan_version_id === group.plan_version_id &&
        g.term_id === group.term_id &&
        g.is_active,
    )
    .sort((a, b) => a.code.localeCompare(b.code, "es"));
  const target = options.find((g) => g.id === toId);
  const move = useMutation({
    mutationFn: () =>
      api(`/students/${student.student_id}/group-change`, {
        method: "POST",
        body: JSON.stringify({ from_group_id: group.id, to_group_id: toId, reason }),
      }),
    onSuccess: () => {
      onDone();
      toast.success(`${student.name} ahora está en ${target?.code ?? "el nuevo grupo"}`);
      onClose();
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "No se pudo cambiar de grupo", {
        duration: 8000,
      }),
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Cambiar de grupo — {student.name}</DialogTitle>
          <DialogDescription>
            A otro grupo del mismo ciclo y plan (otro turno, plantel o modalidad). Sus
            materias en curso se mueven con las calificaciones capturadas y sus cargos lo
            siguen; las ya calificadas quedan en {group.code}. Para cambiar de carrera o de
            RVOE use «Cambio de RVOE» en el kárdex.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            move.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label>Grupo destino</Label>
            {options.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No hay otro grupo activo de este plan en el ciclo.
              </p>
            ) : (
              <Select value={toId} onValueChange={setToId}>
                <SelectTrigger aria-label="Grupo destino">
                  <SelectValue placeholder="Elija el grupo" />
                </SelectTrigger>
                <SelectContent>
                  {options.map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      {g.code} · {g.period_number}.º
                      {g.campus_id !== group.campus_id ? ` · ${campusName(g.campus_id)}` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
          {target && target.campus_id !== group.campus_id && (
            <p className="text-sm text-muted-foreground">
              El grupo es de otro plantel: el alumno pasa a {campusName(target.campus_id)}.
            </p>
          )}
          <div className="grid gap-2">
            <Label htmlFor="move-reason">Motivo (opcional)</Label>
            <Input
              id="move-reason"
              value={reason}
              maxLength={255}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="submit" className="font-bold" disabled={move.isPending || !toId}>
              {move.isPending ? "Cambiando…" : "Cambiar de grupo"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
