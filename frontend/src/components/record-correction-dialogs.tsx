// Correcciones del historial académico: el error humano existe. Todo pide un motivo
// y queda en la bitácora.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/api/client";
import type {
  GradeCorrectionForm,
  RecognitionKind,
  RvoeChangeInfo,
  StudentKardexRow,
} from "@/api/types";
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

// everything of this student on screen (kárdex, grupos, plan) plus the group grids
function useRefreshStudent(studentId: string) {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes(studentId) });
    queryClient.invalidateQueries({ queryKey: ["grade-grid"] });
  };
}

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

const toNumber = (text: string) => (text.trim() === "" ? null : Number(text));

function ReasonField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="grid gap-2">
      <Label htmlFor="correction-reason">Motivo de la corrección (obligatorio)</Label>
      <Input
        id="correction-reason"
        value={value}
        maxLength={255}
        placeholder="Ej. Se capturó equivalencia y era convalidación"
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

// The recognition was a mistake: the subject stays in its period of the RVOE, pending.
function UndoRecognitionButton({
  row,
  reason,
  onDone,
}: {
  row: StudentKardexRow;
  reason: string;
  onDone: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const undo = useMutation({
    mutationFn: () =>
      api(`/students/subject-enrollments/${row.subject_enrollment_id}/recognition/undo`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
    onSuccess: () => {
      toast.success(`${row.code} queda pendiente de cursar`);
      onDone();
    },
    onError: (e) => toast.error(errorText(e, "No se pudo corregir"), { duration: 8000 }),
  });
  return (
    <Button
      type="button"
      variant="outline"
      className="mr-auto"
      disabled={undo.isPending || reason.trim().length < 3}
      onClick={() => (confirming ? undo.mutate() : setConfirming(true))}
    >
      {confirming ? "Confirmar: sin reconocimiento" : "No debía reconocerse"}
    </Button>
  );
}

function RecognitionForm({
  row,
  onDone,
}: {
  row: StudentKardexRow;
  onDone: () => void;
}) {
  const [kind, setKind] = useState<RecognitionKind>(row.recognition ?? "eq");
  const [grade, setGrade] = useState(row.final_grade != null ? String(row.final_grade) : "");
  const [origin, setOrigin] = useState(row.origin ?? "");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () =>
      api(`/students/subject-enrollments/${row.subject_enrollment_id}/recognition`, {
        method: "PATCH",
        body: JSON.stringify({ kind, grade: toNumber(grade), origin, reason }),
      }),
    onSuccess: () => {
      toast.success(`${row.code} corregida`);
      onDone();
    },
    onError: (e) => toast.error(errorText(e, "No se pudo corregir"), { duration: 8000 }),
  });
  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="grid grid-cols-2 gap-4">
        <div className="grid gap-2">
          <Label>Tipo</Label>
          <Select value={kind} onValueChange={(v) => setKind(v as RecognitionKind)}>
            <SelectTrigger aria-label="Tipo de reconocimiento">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="eq">Equivalencia</SelectItem>
              <SelectItem value="rev">Revalidación</SelectItem>
              <SelectItem value="conv">Convalidación</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="correction-grade">Calificación</Label>
          <Input
            id="correction-grade"
            type="number"
            min={0}
            max={10}
            step="0.1"
            placeholder="pendiente"
            value={grade}
            onChange={(e) => setGrade(e.target.value)}
          />
        </div>
      </div>
      <div className="grid gap-2">
        <Label htmlFor="correction-origin">Origen (RVOE y materia, escuela o documento)</Label>
        <Input
          id="correction-origin"
          value={origin}
          maxLength={255}
          onChange={(e) => setOrigin(e.target.value)}
        />
      </div>
      <ReasonField value={reason} onChange={setReason} />
      <DialogFooter className="sm:justify-between">
        <UndoRecognitionButton row={row} reason={reason} onDone={onDone} />
        <Button
          type="submit"
          className="font-bold"
          disabled={save.isPending || reason.trim().length < 3}
        >
          {save.isPending ? "Guardando…" : "Guardar corrección"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function GradeForm({
  row,
  onDone,
}: {
  row: StudentKardexRow;
  onDone: () => void;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["grade-correction", row.subject_enrollment_id],
    gcTime: 0,
    queryFn: () =>
      api<GradeCorrectionForm>(`/grades/subject-enrollments/${row.subject_enrollment_id}/correction`),
  });
  const [values, setValues] = useState<Record<string, string>>({});
  const [finalGrade, setFinalGrade] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const componentValue = (id: string, captured: number | null) =>
    values[id] ?? (captured != null ? String(captured) : "");
  const save = useMutation({
    mutationFn: () =>
      api(`/grades/subject-enrollments/${row.subject_enrollment_id}/correct`, {
        method: "POST",
        body: JSON.stringify(
          data?.by_components
            ? {
                reason,
                components: data.components.map((c) => ({
                  component_id: c.id,
                  value: toNumber(componentValue(c.id, c.value)),
                })),
              }
            : {
                reason,
                final_grade: toNumber(finalGrade ?? String(data?.final_grade ?? "")),
              },
        ),
      }),
    onSuccess: () => {
      toast.success(`${row.code} corregida`);
      onDone();
    },
    onError: (e) => toast.error(errorText(e, "No se pudo corregir"), { duration: 8000 }),
  });
  if (isLoading) return <Skeleton className="h-32 w-full" />;
  if (error || !data) {
    return <p className="text-sm text-destructive">{errorText(error, "No se pudo cargar")}</p>;
  }
  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {data.by_components ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {data.components.map((c) => (
            <div key={c.id} className="grid gap-2">
              <Label htmlFor={`component-${c.id}`}>{c.label}</Label>
              <Input
                id={`component-${c.id}`}
                type="number"
                min={0}
                max={10}
                step="0.1"
                placeholder="sin capturar"
                value={componentValue(c.id, c.value)}
                onChange={(e) => setValues((prev) => ({ ...prev, [c.id]: e.target.value }))}
              />
            </div>
          ))}
          <p className="text-xs text-muted-foreground sm:col-span-2">
            La calificación final se vuelve a calcular. No hace falta que la captura del periodo
            esté abierta.
          </p>
        </div>
      ) : (
        <div className="grid gap-2">
          <Label htmlFor="correction-final">Calificación final</Label>
          <Input
            id="correction-final"
            type="number"
            min={0}
            max={10}
            step="0.1"
            placeholder="sin calificación (en curso)"
            value={finalGrade ?? (data.final_grade != null ? String(data.final_grade) : "")}
            onChange={(e) => setFinalGrade(e.target.value)}
          />
        </div>
      )}
      <ReasonField value={reason} onChange={setReason} />
      <DialogFooter>
        <Button
          type="submit"
          className="font-bold"
          disabled={save.isPending || reason.trim().length < 3}
        >
          {save.isPending ? "Guardando…" : "Guardar corrección"}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function CorrectRowDialog({
  studentId,
  row,
  onClose,
}: {
  studentId: string;
  row: StudentKardexRow;
  onClose: () => void;
}) {
  const refresh = useRefreshStudent(studentId);
  const done = () => {
    refresh();
    onClose();
  };
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            Corregir {row.code} — {row.name}
          </DialogTitle>
          <DialogDescription>
            {row.recognition
              ? "Cambia el tipo de reconocimiento, la calificación (vacía = pendiente) o el origen."
              : `Cursada en ${row.group_code ?? ""}${row.term_name ? ` · ${row.term_name}` : ""}. Una calificación vacía se borra.`}{" "}
            La materia sigue en su periodo: eso solo lo define el RVOE. La corrección queda en la
            bitácora.
          </DialogDescription>
        </DialogHeader>
        {row.recognition ? (
          <RecognitionForm row={row} onDone={done} />
        ) : (
          <GradeForm row={row} onDone={done} />
        )}
      </DialogContent>
    </Dialog>
  );
}

export function RevertRvoeDialog({
  studentId,
  change,
  onClose,
}: {
  studentId: string;
  change: RvoeChangeInfo;
  onClose: () => void;
}) {
  const refresh = useRefreshStudent(studentId);
  const [reason, setReason] = useState("");
  const revert = useMutation({
    mutationFn: () =>
      api<{ cancelled_charges: number; paid_charges_kept: number }>(
        `/students/${studentId}/rvoe-change/revert`,
        { method: "POST", body: JSON.stringify({ change_id: change.change_id, reason }) },
      ),
    onSuccess: (r) => {
      toast.success(`Cambio revertido: regresó a ${change.from_rvoe}`);
      if (r.paid_charges_kept > 0) {
        toast.warning(
          `${r.paid_charges_kept} cargos del plan revertido ya tienen pago y siguen en su cuenta: revísalos en Tesorería`,
          { duration: 12000 },
        );
      }
      refresh();
      onClose();
    },
    onError: (e) => toast.error(errorText(e, "No se pudo revertir"), { duration: 12000 }),
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Revertir cambio de RVOE</DialogTitle>
          <DialogDescription>
            El alumno regresa a <b>{change.from_rvoe}</b> ({change.from_program}), a su grupo y a
            las materias que llevaba en curso. Se quita lo que el cambio creó en{" "}
            <b>{change.to_rvoe}</b>: sus EQ/REV/CONV y sus materias. Los cargos sin pago se
            cancelan. No se puede si ya tiene calificaciones capturadas en el plan nuevo: primero
            déjalas vacías con «Corregir».
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            revert.mutate();
          }}
        >
          <ReasonField value={reason} onChange={setReason} />
          <DialogFooter>
            <Button
              type="submit"
              variant="destructive"
              className="font-bold"
              disabled={revert.isPending || reason.trim().length < 3}
            >
              {revert.isPending ? "Revirtiendo…" : "Revertir cambio"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
