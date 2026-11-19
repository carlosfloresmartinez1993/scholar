// «Cursar materia en otro grupo»: a student of, say, 7th takes a pending subject
// with another group that teaches it. Their group stays the same and nothing is
// billed (for now). From the kárdex (pick the group) or from the group (pick the
// student).
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/api/client";
import type { Group, GroupSubject, Student, StudentKardexRow } from "@/api/types";
import { SearchableSelect } from "@/components/searchable-select";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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

interface OtherGroupOption {
  group_id: string;
  code: string;
  period_number: number;
  term_id: string;
  term_name: string;
  term_open: boolean;
}

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

function takeInOtherGroup(studentId: string, groupId: string, planSubjectIds: string[]) {
  return api(`/students/group-enrollments/other-group`, {
    method: "POST",
    body: JSON.stringify({
      student_id: studentId,
      group_id: groupId,
      plan_subject_ids: planSubjectIds,
    }),
  });
}

function refresh(queryClient: ReturnType<typeof useQueryClient>, studentId: string) {
  queryClient.invalidateQueries({ queryKey: ["kardex", studentId] });
  queryClient.invalidateQueries({ queryKey: ["groups"] });
  queryClient.invalidateQueries({ queryKey: ["grade-grid"] });
  queryClient.invalidateQueries({ queryKey: ["group-students"] });
}

/** From the kárdex: a pending (or failed) subject → the groups that teach it. */
export function TakeInOtherGroupDialog({
  studentId,
  row,
  onClose,
}: {
  studentId: string;
  row: StudentKardexRow;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [groupId, setGroupId] = useState("");
  const { data: options, isLoading, error } = useQuery({
    queryKey: ["other-groups", studentId, row.plan_subject_id],
    queryFn: () =>
      api<OtherGroupOption[]>(
        `/students/${studentId}/other-groups?plan_subject_id=${row.plan_subject_id}`,
      ),
    retry: false,
  });
  const save = useMutation({
    mutationFn: () => takeInOtherGroup(studentId, groupId, [row.plan_subject_id]),
    onSuccess: () => {
      refresh(queryClient, studentId);
      toast.success("Materia inscrita en el otro grupo, sin cargos");
      onClose();
    },
    onError: (e) => toast.error(errorText(e, "No se pudo inscribir"), { duration: 8000 }),
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Cursar en otro grupo</DialogTitle>
          <DialogDescription>
            {row.code} {row.name}. El alumno sigue en su grupo; esta materia la cursa con el
            grupo que elijas y ahí se le captura la calificación. No genera cargos.
          </DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : error ? (
          <p className="text-sm text-destructive">{errorText(error, "No se pudieron cargar los grupos")}</p>
        ) : options && options.length > 0 ? (
          <div className="grid max-h-72 gap-2 overflow-y-auto">
            {options.map((o) => (
              <label
                key={o.group_id}
                className="flex cursor-pointer items-center gap-3 rounded-md border p-3 text-sm has-[:checked]:border-primary"
              >
                <input
                  type="radio"
                  name="other-group"
                  className="accent-primary"
                  checked={groupId === o.group_id}
                  onChange={() => setGroupId(o.group_id)}
                />
                <span className="font-semibold" data-numeric>
                  {o.code}
                </span>
                <span className="text-muted-foreground">
                  {o.period_number}.º cuatrimestre · {o.term_name}
                  {o.term_open ? "" : " (ciclo cerrado)"}
                </span>
              </label>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Ningún grupo activo de su plan y plantel imparte esta materia. Abre el grupo en
            «Grupos» o agrégale la materia a un grupo existente.
          </p>
        )}
        <DialogFooter>
          <Button
            className="font-bold"
            disabled={!groupId || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? "Inscribiendo…" : "Inscribir en ese grupo"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** From the group: a student whose own group is another one takes subjects here. */
export function OtherGroupStudentDialog({
  open,
  onOpenChange,
  group,
  groupSubjects,
  subjectName,
  onDone,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  group: Group;
  groupSubjects: GroupSubject[];
  subjectName: (planSubjectId: string) => string;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [studentId, setStudentId] = useState("");
  const [subjectIds, setSubjectIds] = useState<string[]>([]);
  // same carrera and plantel as the group: the plan's RVOE is what they study
  const { data: students } = useQuery({
    queryKey: ["students", "by-campus", group.campus_id, "carrera", group.plan_version_id],
    queryFn: () =>
      api<Student[]>(
        `/students?limit=1000&campus_id=${group.campus_id}` +
          `&carrera_of_plan_version_id=${group.plan_version_id}`,
      ),
    enabled: open,
  });
  const save = useMutation({
    mutationFn: () => takeInOtherGroup(studentId, group.id, subjectIds),
    onSuccess: () => {
      refresh(queryClient, studentId);
      onDone();
      toast.success("Alumno inscrito en las materias, sin cargos");
      onOpenChange(false);
      setStudentId("");
      setSubjectIds([]);
    },
    onError: (e) => toast.error(errorText(e, "No se pudo inscribir"), { duration: 8000 }),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Alumno de otro grupo en {group.code}</DialogTitle>
          <DialogDescription>
            Para un alumno que va en otro grupo y debe una materia que aquí se imparte. Sigue en
            su grupo, cursa aquí solo las materias que marques y no genera cargos. No se pueden
            adelantar materias: el grupo debe ser de su cuatrimestre o de uno anterior.
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
            <Label>Alumno</Label>
            <SearchableSelect
              value={studentId}
              onChange={setStudentId}
              options={(students ?? []).map((s) => ({
                value: s.id,
                label: s.full_name,
                hint: s.enrollment_number || s.curp,
              }))}
              placeholder="Buscar alumno…"
              searchPlaceholder="Nombre, matrícula o CURP…"
            />
          </div>
          <div className="grid gap-2">
            <Label>Materias que cursará aquí</Label>
            <div className="grid max-h-56 gap-2 overflow-y-auto rounded-md border p-3">
              {groupSubjects.map((gs) => (
                <label key={gs.id} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={subjectIds.includes(gs.plan_subject_id)}
                    onCheckedChange={(v) =>
                      setSubjectIds(
                        v
                          ? [...subjectIds, gs.plan_subject_id]
                          : subjectIds.filter((x) => x !== gs.plan_subject_id),
                      )
                    }
                  />
                  {subjectName(gs.plan_subject_id)}
                </label>
              ))}
            </div>
          </div>
          <DialogFooter>
            <Button
              type="submit"
              className="font-bold"
              disabled={!studentId || subjectIds.length === 0 || save.isPending}
            >
              {save.isPending ? "Inscribiendo…" : "Inscribir en las materias"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
