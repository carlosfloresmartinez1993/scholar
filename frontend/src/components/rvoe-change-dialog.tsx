// Cambio de RVOE (desde el kárdex): 1) plan y grupo destino, 2) decisión por cada
// materia del plan nuevo anterior al cuatrimestre del grupo (convalidar, EQ, REV,
// cursar ahora, pendiente) con la propuesta del sistema, 3) aplicar.
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  Group,
  RvoeChangeAction,
  RvoeChangeProposal,
  Student,
  Term,
} from "@/api/types";
import { SearchableSelect } from "@/components/searchable-select";
import { Button } from "@/components/ui/button";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const ACTION_LABELS: Record<RvoeChangeAction, string> = {
  conv: "Convalidar",
  eq: "Equivalencia",
  rev: "Revalidación",
  cursar: "Cursar ahora",
  pendiente: "Pendiente",
};
const RECOGNIZES = (a: RvoeChangeAction) => a === "conv" || a === "eq" || a === "rev";
const NONE = "__none__";

interface Decision {
  action: RvoeChangeAction;
  source: string; // subject_enrollment_id of the old subject, or NONE
  grade: string;
  group_id: string;
}

export function RvoeChangeDialog({
  student,
  fromPlanVersionId,
  planLabels,
  terms,
  onClose,
}: {
  student: Student;
  fromPlanVersionId: string;
  planLabels: Map<string, string>;
  terms: Term[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [planId, setPlanId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [proposal, setProposal] = useState<RvoeChangeProposal | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});

  const { data: groups } = useQuery({
    queryKey: ["groups", "by-plan", planId],
    queryFn: () => api<Group[]>(`/catalog/groups?plan_version_id=${planId}`),
    enabled: !!planId,
  });
  const termName = (id: string) => terms.find((t) => t.id === id)?.name ?? "";
  const targetGroup = groups?.find((g) => g.id === groupId);

  const loadProposal = useMutation({
    mutationFn: () =>
      api<RvoeChangeProposal>(
        `/students/${student.id}/rvoe-change/proposal?from_plan_version_id=${fromPlanVersionId}` +
          `&target_group_id=${groupId}`,
      ),
    onSuccess: (p) => {
      setProposal(p);
      setDecisions(
        Object.fromEntries(
          p.items.map((i) => [
            i.plan_subject_id,
            {
              action: i.action,
              source: i.source_subject_enrollment_id ?? NONE,
              grade: i.grade == null ? "" : String(i.grade),
              group_id: p.target_group_id,
            },
          ]),
        ),
      );
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "No se pudo armar la propuesta"),
  });

  const apply = useMutation({
    mutationFn: () =>
      api<{ summary: Record<RvoeChangeAction, string[]> }>(`/students/${student.id}/rvoe-change`, {
        method: "POST",
        body: JSON.stringify({
          from_plan_version_id: fromPlanVersionId,
          target_group_id: groupId,
          decisions: Object.entries(decisions).map(([plan_subject_id, d]) => ({
            plan_subject_id,
            action: d.action,
            grade: RECOGNIZES(d.action) && d.grade !== "" ? Number(d.grade) : null,
            source_subject_enrollment_id:
              RECOGNIZES(d.action) && d.source !== NONE ? d.source : null,
            group_id: d.action === "cursar" ? d.group_id : null,
          })),
        }),
      }),
    onSuccess: (r) => {
      for (const key of [
        ["kardex", student.id],
        queryKeys.planEnrollments(student.id),
        queryKeys.groupEnrollments(student.id),
        queryKeys.subjectEnrollments(student.id),
      ]) {
        queryClient.invalidateQueries({ queryKey: key });
      }
      const s = r.summary;
      toast.success(
        `Cambio aplicado: ${s.conv.length} convalidadas, ${s.eq.length + s.rev.length} EQ/REV, ` +
          `${s.cursar.length} a cursar, ${s.pendiente.length} pendientes`,
        { duration: 8000 },
      );
      onClose();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "No se pudo aplicar el cambio"),
  });

  const missingGrade = useMemo(
    () =>
      proposal?.items.filter((i) => {
        const d = decisions[i.plan_subject_id];
        return d?.action === "conv" && d.grade === "";
      }) ?? [],
    [proposal, decisions],
  );
  const set = (id: string, patch: Partial<Decision>) =>
    setDecisions((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));

  const planOptions = [...planLabels.entries()]
    .filter(([id]) => id !== fromPlanVersionId)
    .map(([value, label]) => ({ value, label }));

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-[min(96vw,90rem)]">
        <DialogHeader>
          <DialogTitle>Cambio de RVOE — {student.full_name}</DialogTitle>
          <DialogDescription>
            Del plan {planLabels.get(fromPlanVersionId) ?? "actual"}. El plan anterior se cierra
            (no se puede estar en dos RVOE a la vez) y el kárdex conserva un solo historial.
          </DialogDescription>
        </DialogHeader>

        {!proposal ? (
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label>Plan destino (cualquier carrera)</Label>
              <SearchableSelect
                value={planId}
                onChange={(v) => {
                  setPlanId(v);
                  setGroupId("");
                }}
                options={planOptions}
                placeholder="Seleccione el plan"
              />
            </div>
            <div className="grid gap-2">
              <Label>Grupo destino (donde continúa)</Label>
              <Select value={groupId} onValueChange={setGroupId} disabled={!planId}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Seleccione el grupo" />
                </SelectTrigger>
                <SelectContent>
                  {groups?.map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      {g.code} · {g.period_number}.º · {termName(g.term_id)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {groups && groups.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  Ese plan no tiene grupos; créalo primero en «Grupos».
                </p>
              )}
            </div>
            <DialogFooter>
              <Button
                className="font-bold"
                disabled={!groupId || loadProposal.isPending}
                onClick={() => loadProposal.mutate()}
              >
                {loadProposal.isPending ? "Armando propuesta…" : "Ver propuesta"}
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="grid gap-4">
            <p className="text-sm">
              Continúa en <b>{targetGroup?.code}</b> ({proposal.target_period_number}.º). Materias del
              plan nuevo de cuatrimestres anteriores: decide qué pasa con cada una.
              {proposal.items.length === 0 && " No hay materias anteriores: empieza desde ese cuatrimestre."}
            </p>
            <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,5fr)]">
            <div className="space-y-2">
              <p className="text-sm font-bold">
                Plan anterior — <span data-numeric>{proposal.from_rvoe}</span>
              </p>
              <div className="max-h-[60vh] overflow-y-auto rounded-md border text-xs">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Cuatri.</TableHead>
                      <TableHead>Materia</TableHead>
                      <TableHead className="text-right">Calif.</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {proposal.old_subjects.map((o) => (
                      <TableRow
                        key={o.code}
                        className={o.status === "aprobada" ? undefined : "text-muted-foreground"}
                      >
                        <TableCell data-numeric>{o.period_number}</TableCell>
                        <TableCell>
                          <span className="font-semibold" data-numeric>
                            {o.code}
                          </span>{" "}
                          {o.name}
                        </TableCell>
                        <TableCell data-numeric className="text-right">
                          {o.status === "sin_cursar"
                            ? "sin cursar"
                            : o.status === "aprobada"
                              ? (o.grade ?? "")
                              : `${o.grade ?? ""} ${o.status}`}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
            <div className="space-y-2">
            <p className="text-sm font-bold">Plan nuevo — decisiones</p>
            {proposal.items.length > 0 && (
              <div className="overflow-x-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Cuatri.</TableHead>
                      <TableHead>Materia del plan nuevo</TableHead>
                      <TableHead className="w-40">Decisión</TableHead>
                      <TableHead>Viene de (plan anterior)</TableHead>
                      <TableHead className="w-24">Calif.</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {proposal.items.map((item) => {
                      const d = decisions[item.plan_subject_id];
                      if (!d) return null;
                      const groupOptions = [
                        { group_id: proposal.target_group_id, code: `${targetGroup?.code ?? ""} (destino)` },
                        ...item.groups.filter((g) => g.group_id !== proposal.target_group_id),
                      ];
                      return (
                        <TableRow key={item.plan_subject_id}>
                          <TableCell data-numeric>{item.period_number}</TableCell>
                          <TableCell>
                            <span className="font-semibold" data-numeric>
                              {item.code}
                            </span>{" "}
                            {item.name}
                          </TableCell>
                          <TableCell>
                            <Select
                              value={d.action}
                              onValueChange={(v) => set(item.plan_subject_id, { action: v as RvoeChangeAction })}
                            >
                              <SelectTrigger className="h-8 w-full" aria-label={`Decisión para ${item.name}`}>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {(Object.keys(ACTION_LABELS) as RvoeChangeAction[]).map((a) => (
                                  <SelectItem key={a} value={a}>
                                    {ACTION_LABELS[a]}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </TableCell>
                          <TableCell>
                            {RECOGNIZES(d.action) ? (
                              <Select
                                value={d.source}
                                onValueChange={(v) => {
                                  const source = proposal.approved.find((a) => a.subject_enrollment_id === v);
                                  set(item.plan_subject_id, {
                                    source: v,
                                    grade: source?.grade != null ? String(source.grade) : d.grade,
                                  });
                                }}
                              >
                                <SelectTrigger className="h-8 w-full">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value={NONE}>— Sin materia de origen —</SelectItem>
                                  {proposal.approved.map((a) => (
                                    <SelectItem key={a.subject_enrollment_id} value={a.subject_enrollment_id}>
                                      {a.code} {a.name} ({a.grade ?? "—"})
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            ) : d.action === "cursar" ? (
                              <Select
                                value={d.group_id}
                                onValueChange={(v) => set(item.plan_subject_id, { group_id: v })}
                              >
                                <SelectTrigger className="h-8 w-full" aria-label={`Grupo para ${item.name}`}>
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {groupOptions.map((g) => (
                                    <SelectItem key={g.group_id} value={g.group_id}>
                                      Cursar en {g.code}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            ) : (
                              <span className="text-sm text-muted-foreground">Queda debiéndola</span>
                            )}
                          </TableCell>
                          <TableCell>
                            {RECOGNIZES(d.action) && (
                              <Input
                                type="number"
                                min={0}
                                max={10}
                                step="0.1"
                                className="h-8 w-20"
                                placeholder={d.action === "conv" ? "" : "pend."}
                                value={d.grade}
                                aria-label={`Calificación de ${item.name}`}
                                onChange={(e) => set(item.plan_subject_id, { grade: e.target.value })}
                              />
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
            </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Equivalencia o revalidación sin calificación quedan como «EQ/REV pendiente» hasta
              registrar la nota oficial. «Cursar ahora» en otro grupo crea otra inscripción (puede
              generar cargos).
            </p>
            <DialogFooter className="gap-2">
              <Button variant="outline" onClick={() => setProposal(null)}>
                Atrás
              </Button>
              <Button
                className="font-bold"
                disabled={apply.isPending || missingGrade.length > 0}
                title={missingGrade.length > 0 ? "Falta la calificación de alguna convalidación" : undefined}
                onClick={() => apply.mutate()}
              >
                {apply.isPending ? "Aplicando…" : "Aplicar cambio"}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
