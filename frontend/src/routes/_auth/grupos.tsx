import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowUpCircle, CalendarDays, Plus, UserPlus, Users } from "lucide-react";
import {
  api,
  ApiError,
  getCalendarGroups,
  linkGroupToCalendar,
  promoteCycle,
} from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  Campus,
  GradeGrid,
  Group,
  GroupBillingStatus,
  GroupSubject,
  PlanSubject,
  PlanVersion,
  Program,
  PromoteCycleResult,
  Rvoe,
  Student,
  Term,
  UserPublic,
} from "@/api/types";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/empty-state";
import { SearchableSelect } from "@/components/searchable-select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
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
  DialogDescription,
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

export const Route = createFileRoute("/_auth/grupos")({
  component: GruposPage,
});

const NONE = "__none__";

/** plan_version_id -> "Programa · RVOE · Plan" */
function usePlanVersionLabels(): Map<string, string> {
  const { data: planVersions } = useQuery({
    queryKey: queryKeys.planVersions(),
    queryFn: () => api<PlanVersion[]>("/catalog/plan-versions"),
  });
  const { data: rvoes } = useQuery({
    queryKey: queryKeys.rvoes(),
    queryFn: () => api<Rvoe[]>("/catalog/rvoes"),
  });
  const { data: programs } = useQuery({
    queryKey: queryKeys.programs,
    queryFn: () => api<Program[]>("/catalog/programs"),
  });

  return useMemo(() => {
    const map = new Map<string, string>();
    for (const pv of planVersions ?? []) {
      const rvoe = rvoes?.find((r) => r.id === pv.rvoe_id);
      const program = programs?.find((p) => p.id === rvoe?.program_id);
      map.set(
        pv.id,
        `${program?.name ?? "?"} · RVOE ${rvoe?.agreement_number ?? "?"} · Plan ${pv.version_label}`,
      );
    }
    return map;
  }, [planVersions, rvoes, programs]);
}

function GruposPage() {
  const { data: terms } = useQuery({
    queryKey: queryKeys.terms,
    queryFn: () => api<Term[]>("/catalog/terms"),
  });
  const [selectedTerm, setSelectedTerm] = useState<string | null>(null);
  const termId = selectedTerm ?? terms?.find((t) => t.is_open)?.id ?? null;

  const { data: groups, isLoading } = useQuery({
    queryKey: queryKeys.groups(termId ?? undefined),
    queryFn: () => api<Group[]>(`/catalog/groups?term_id=${termId}`),
    enabled: !!termId,
  });
  const { data: campuses } = useQuery({
    queryKey: queryKeys.campuses,
    queryFn: () => api<Campus[]>("/catalog/campuses"),
  });
  const planVersionLabels = usePlanVersionLabels();

  const [groupId, setGroupId] = useState<string | null>(null);
  const group = groups?.find((g) => g.id === groupId) ?? null;
  const [createOpen, setCreateOpen] = useState(false);
  const [promoteOpen, setPromoteOpen] = useState(false);

  const campusName = (id: string) =>
    campuses?.find((c) => c.id === id)?.name ?? "—";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl">Grupos</h1>
        <div className="flex items-center gap-2">
          <Select
            value={termId ?? ""}
            onValueChange={(v) => {
              setSelectedTerm(v);
              setGroupId(null);
            }}
          >
            <SelectTrigger className="w-64">
              <SelectValue placeholder="Seleccione un ciclo" />
            </SelectTrigger>
            <SelectContent>
              {terms?.map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {t.name}
                  {t.is_open ? " · abierto" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => setPromoteOpen(true)}>
            <ArrowUpCircle className="size-4" /> Promoción de ciclo
          </Button>
          <Button
            className="font-bold"
            disabled={!termId}
            onClick={() => setCreateOpen(true)}
          >
            <Plus className="size-4" /> Nuevo grupo
          </Button>
        </div>
      </div>

      {!termId ? (
        <EmptyState
          icon={Users}
          title="Seleccione un ciclo"
          description="Cree un ciclo en «Periodos» y selecciónelo para administrar sus grupos."
        />
      ) : (
        <div className="rounded-2xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Código</TableHead>
                <TableHead>Plan de estudios</TableHead>
                <TableHead>Campus</TableHead>
                <TableHead>Periodo</TableHead>
                <TableHead>Estado</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading &&
                [1, 2, 3].map((i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={5}>
                      <Skeleton className="h-6 w-full" />
                    </TableCell>
                  </TableRow>
                ))}
              {groups?.map((g) => (
                <TableRow
                  key={g.id}
                  className={cn(
                    "cursor-pointer",
                    g.id === groupId && "bg-muted/60",
                  )}
                  onClick={() => setGroupId(g.id === groupId ? null : g.id)}
                >
                  <TableCell className="font-semibold" data-numeric>
                    {g.code}
                  </TableCell>
                  <TableCell>
                    {planVersionLabels.get(g.plan_version_id) ?? "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {campusName(g.campus_id)}
                  </TableCell>
                  <TableCell data-numeric>{g.period_number}</TableCell>
                  <TableCell>
                    <Badge variant={g.is_active ? "outline" : "destructive"}>
                      {g.is_active ? "Activo" : "Inactivo"}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
              {groups && groups.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="py-10 text-center text-muted-foreground"
                  >
                    Este ciclo no tiene grupos
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {group && <GroupDetail group={group} groups={groups ?? []} />}

      {termId && (
        <CreateGroupDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          termId={termId}
          planVersionLabels={planVersionLabels}
        />
      )}

      <PromoteCycleDialog open={promoteOpen} onOpenChange={setPromoteOpen} />
    </div>
  );
}

// --- Cycle promotion (reinscripción) -----------------------------------------

function PromoteCycleDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const preview = useQuery({
    queryKey: queryKeys.promoteCyclePreview,
    queryFn: () => promoteCycle(true),
    enabled: open,
    staleTime: 0,
  });

  const run = useMutation({
    mutationFn: () => promoteCycle(false),
    onSuccess: (r: PromoteCycleResult) => {
      toast.success(
        `${r.promoted_count} promovidos, ${r.skipped_count} omitidos`,
      );
      queryClient.invalidateQueries({ queryKey: ["groups"] });
      preview.refetch();
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al promover"),
  });

  const data = preview.data;
  const isEmpty =
    data && data.promoted_count === 0 && data.skipped_count === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Promoción de ciclo</DialogTitle>
          <DialogDescription>
            Mueve a los alumnos que acreditaron y continúan al grupo del siguiente
            cuatrimestre y genera su reinscripción. Normalmente se ejecuta de forma
            automática antes de cada cuatrimestre; esta es una vista previa y
            ejecución manual.
          </DialogDescription>
        </DialogHeader>

        {preview.isLoading && <Skeleton className="h-24 w-full" />}
        {preview.isError && (
          <p className="text-sm text-destructive">
            No se pudo cargar la vista previa.
          </p>
        )}

        {data && (
          <div className="space-y-4">
            {isEmpty ? (
              <p className="py-6 text-center text-muted-foreground">
                No hay alumnos por promover en este momento.
              </p>
            ) : (
              <>
                <p className="text-sm">
                  <span className="font-semibold" data-numeric>
                    {data.promoted_count}
                  </span>{" "}
                  alumnos se promoverán ·{" "}
                  <span className="font-semibold" data-numeric>
                    {data.skipped_count}
                  </span>{" "}
                  omitidos
                </p>

                {data.promoted.length > 0 && (
                  <div className="rounded-2xl border bg-card">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Alumno</TableHead>
                          <TableHead>Matrícula</TableHead>
                          <TableHead>Grupo destino</TableHead>
                          <TableHead>Ciclo</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {data.promoted.map((p, i) => (
                          <TableRow key={`p-${i}`}>
                            <TableCell className="font-semibold">
                              {p.student}
                            </TableCell>
                            <TableCell data-numeric>{p.matricula}</TableCell>
                            <TableCell data-numeric>{p.target_group}</TableCell>
                            <TableCell>{p.term ?? "—"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}

                {data.skipped.length > 0 && (
                  <div className="rounded-2xl border bg-card">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Alumno</TableHead>
                          <TableHead>Matrícula</TableHead>
                          <TableHead>Motivo</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {data.skipped.map((p, i) => (
                          <TableRow key={`s-${i}`}>
                            <TableCell className="font-semibold">
                              {p.student}
                            </TableCell>
                            <TableCell data-numeric>{p.matricula}</TableCell>
                            <TableCell className="text-muted-foreground">
                              {p.reason ?? "—"}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        <DialogFooter>
          <Button
            className="font-bold"
            disabled={
              run.isPending ||
              preview.isFetching ||
              preview.isError ||
              !data ||
              isEmpty
            }
            onClick={() => run.mutate()}
          >
            {run.isPending ? "Promoviendo…" : "Promover y facturar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CreateGroupDialog({
  open,
  onOpenChange,
  termId,
  planVersionLabels,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  termId: string;
  planVersionLabels: Map<string, string>;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    code: "",
    period_number: 1,
    plan_version_id: "",
    promotes_from_group_id: NONE,
  });

  const save = useMutation({
    mutationFn: () =>
      api<Group>("/catalog/groups", {
        method: "POST",
        body: JSON.stringify({
          code: form.code,
          period_number: form.period_number,
          plan_version_id: form.plan_version_id,
          promotes_from_group_id:
            form.promotes_from_group_id === NONE
              ? null
              : form.promotes_from_group_id,
          term_id: termId,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] });
      toast.success("Grupo creado");
      onOpenChange(false);
      setForm({
        code: "",
        period_number: 1,
        plan_version_id: "",
        promotes_from_group_id: NONE,
      });
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  // Candidate source groups: same plan version, from a different (previous) term.
  const { data: planGroups } = useQuery({
    queryKey: queryKeys.groups(`plan-${form.plan_version_id}`),
    queryFn: () =>
      api<Group[]>(`/catalog/groups?plan_version_id=${form.plan_version_id}`),
    enabled: open && !!form.plan_version_id,
  });
  // valid predecessors only: same plan, the immediately previous period, and a
  // different (earlier) term — mirrors the backend lineage check.
  const sourceOptions = (planGroups ?? []).filter(
    (g) => g.term_id !== termId && g.period_number === form.period_number - 1,
  );

  const planOptions = [...planVersionLabels.entries()].map(([value, label]) => ({
    value,
    label,
  }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nuevo grupo</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="g-code">Código</Label>
              <Input
                id="g-code"
                required
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
                placeholder="LDER-1A"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="g-period">Periodo (cuatrimestre)</Label>
              <Input
                id="g-period"
                type="number"
                min={1}
                max={20}
                required
                value={form.period_number}
                onChange={(e) =>
                  setForm({
                    ...form,
                    period_number: Number(e.target.value),
                    promotes_from_group_id: NONE, // predecessors depend on the period
                  })
                }
              />
            </div>
          </div>
          <div className="grid gap-2">
            <Label>Plan de estudios</Label>
            <SearchableSelect
              value={form.plan_version_id}
              onChange={(v) =>
                setForm({ ...form, plan_version_id: v, promotes_from_group_id: NONE })
              }
              options={planOptions}
              placeholder="Seleccione un plan"
            />
          </div>
          <div className="grid gap-2">
            <Label>Proviene del grupo anterior (opcional)</Label>
            <Select
              value={form.promotes_from_group_id}
              onValueChange={(v) =>
                setForm({ ...form, promotes_from_group_id: v })
              }
              disabled={!form.plan_version_id}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Ninguno" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Ninguno</SelectItem>
                {sourceOptions.map((g) => (
                  <SelectItem key={g.id} value={g.id}>
                    {g.code} · Periodo {g.period_number}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Al promover el ciclo, los alumnos que acrediten en ese grupo pasarán
              a este.
            </p>
          </div>
          <p className="text-sm text-muted-foreground">
            El campus se toma del RVOE del plan seleccionado.
          </p>
          <DialogFooter>
            <Button
              type="submit"
              className="font-bold"
              disabled={save.isPending || !form.plan_version_id}
            >
              {save.isPending ? "Guardando…" : "Guardar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// --- Calendar link (calendar.inue.online) --------------------------------------

function GroupCalendarLink({ group }: { group: Group }) {
  const queryClient = useQueryClient();
  const { data: planVersions } = useQuery({
    queryKey: queryKeys.planVersions(),
    queryFn: () => api<PlanVersion[]>("/catalog/plan-versions"),
  });
  const { data: rvoes } = useQuery({
    queryKey: queryKeys.rvoes(),
    queryFn: () => api<Rvoe[]>("/catalog/rvoes"),
  });
  const { data: programs } = useQuery({
    queryKey: queryKeys.programs,
    queryFn: () => api<Program[]>("/catalog/programs"),
  });

  const planVersion = planVersions?.find((pv) => pv.id === group.plan_version_id);
  const rvoe = rvoes?.find((r) => r.id === planVersion?.rvoe_id);
  const program = programs?.find((p) => p.id === rvoe?.program_id);
  const calendarProgramId = program?.calendar_program_id ?? undefined;

  const { data: calendarGroups, isError } = useQuery({
    queryKey: queryKeys.calendarGroups(calendarProgramId),
    queryFn: () =>
      getCalendarGroups(
        calendarProgramId ? { program_id: calendarProgramId } : undefined,
      ),
    retry: false,
  });

  const link = useMutation({
    mutationFn: (calendarGroupId: string | null) =>
      linkGroupToCalendar(group.id, calendarGroupId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] });
      toast.success("Vinculación con el calendario actualizada");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al vincular"),
  });

  const linked = calendarGroups?.find(
    (cg) => cg.id === group.calendar_group_id,
  );

  return (
    <section className="flex flex-wrap items-center gap-3 rounded-2xl border bg-card px-4 py-3">
      <CalendarDays className="size-4 text-muted-foreground" />
      <span className="text-sm font-semibold">Calendario</span>
      {isError ? (
        <span className="text-sm text-muted-foreground">
          Integración con el calendario no disponible
        </span>
      ) : (
        <>
          {group.calendar_group_id ? (
            <Badge variant="secondary">
              {linked?.code ?? group.calendar_group_id}
            </Badge>
          ) : (
            <span className="text-sm text-muted-foreground">Sin vincular</span>
          )}
          <div className="ml-auto w-72">
            <Select
              value={group.calendar_group_id ?? NONE}
              onValueChange={(v) => link.mutate(v === NONE ? null : v)}
              disabled={link.isPending}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Vincular grupo del calendario" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Sin vincular</SelectItem>
                {calendarGroups?.map((cg) => (
                  <SelectItem key={cg.id} value={cg.id}>
                    {cg.code}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </>
      )}
    </section>
  );
}

// --- Group detail ------------------------------------------------------------

function GroupDetail({ group, groups }: { group: Group; groups: Group[] }) {
  const queryClient = useQueryClient();
  // the source group is in a previous term, so it isn't in `groups` (current term)
  // — fetch it by id to show its real code.
  const { data: sourceGroup } = useQuery({
    queryKey: ["group", group.promotes_from_group_id],
    queryFn: () => api<Group>(`/catalog/groups/${group.promotes_from_group_id}`),
    enabled: !!group.promotes_from_group_id,
  });
  const promotesFrom = group.promotes_from_group_id
    ? (groups.find((g) => g.id === group.promotes_from_group_id)?.code ??
      sourceGroup?.code ??
      "…")
    : null;
  const { data: groupSubjects, isLoading } = useQuery({
    queryKey: queryKeys.groupSubjects(group.id),
    queryFn: () => api<GroupSubject[]>(`/catalog/groups/${group.id}/subjects`),
  });
  const { data: planSubjects } = useQuery({
    queryKey: queryKeys.planSubjects(group.plan_version_id),
    queryFn: () =>
      api<PlanSubject[]>(
        `/catalog/plan-versions/${group.plan_version_id}/subjects`,
      ),
  });
  const { data: teachers } = useQuery({
    queryKey: queryKeys.users("docente"),
    queryFn: () => api<UserPublic[]>("/users?role=docente"),
  });
  const { data: billing } = useQuery({
    queryKey: queryKeys.groupBillingStatus(group.id),
    queryFn: () =>
      api<GroupBillingStatus[]>(
        `/treasury/groups/${group.id}/billing-status`,
      ),
    enabled: !!group,
  });
  const billedCount = (billing ?? []).filter((b) => b.billed).length;

  const [subjectDialogOpen, setSubjectDialogOpen] = useState(false);
  const [editingSubject, setEditingSubject] = useState<GroupSubject | null>(
    null,
  );
  const [enrollOpen, setEnrollOpen] = useState(false);

  const subjectName = (planSubjectId: string) => {
    const s = planSubjects?.find((ps) => ps.id === planSubjectId);
    return s ? `${s.code} — ${s.name}` : "—";
  };

  // Enrolled students = union of the grade grids of every materia in the group.
  const gridQueries = useQueries({
    queries: (groupSubjects ?? []).map((gs) => ({
      queryKey: queryKeys.gradeGrid(gs.id),
      queryFn: () => api<GradeGrid>(`/grades/group-subjects/${gs.id}/grid`),
    })),
  });
  const enrolled = useMemo(() => {
    const byId = new Map<
      string,
      { student_id: string; name: string; enrollment_number: string; subjects: number }
    >();
    for (const q of gridQueries) {
      for (const row of q.data?.rows ?? []) {
        const existing = byId.get(row.student_id);
        if (existing) existing.subjects += 1;
        else
          byId.set(row.student_id, {
            student_id: row.student_id,
            name: row.student_name,
            enrollment_number: row.enrollment_number,
            subjects: 1,
          });
      }
    }
    return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name, "es"));
  }, [gridQueries]);

  function invalidateGrids() {
    for (const gs of groupSubjects ?? []) {
      queryClient.invalidateQueries({ queryKey: queryKeys.gradeGrid(gs.id) });
    }
  }

  const generateCharges = useMutation({
    mutationFn: () =>
      api<{ students_billed: number; charges_created: number }>(
        `/treasury/groups/${group.id}/generate-charges`,
        { method: "POST" },
      ),
    onSuccess: (r) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.groupBillingStatus(group.id),
      });
      if (r.students_billed === 0 && r.charges_created === 0) {
        toast.info("No se generaron cargos nuevos");
      } else {
        toast.success(
          `Cargos generados: ${r.students_billed} alumnos, ${r.charges_created} cargos`,
        );
      }
    },
    onError: (e) =>
      toast.error(
        e instanceof ApiError ? e.message : "Error al generar cargos",
      ),
  });

  return (
    <div className="space-y-6">
      {promotesFrom && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <ArrowUpCircle className="size-4" />
          Proviene de: <Badge variant="secondary">{promotesFrom}</Badge>
        </div>
      )}
      <GroupCalendarLink group={group} />

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold">Materias del grupo {group.code}</h2>
          <Button
            variant="outline"
            onClick={() => {
              setEditingSubject(null);
              setSubjectDialogOpen(true);
            }}
          >
            <Plus className="size-4" /> Agregar materia
          </Button>
        </div>
        <div className="rounded-2xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Materia</TableHead>
                <TableHead className="w-56">Docente</TableHead>
                <TableHead className="w-72">Horario</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && (
                <TableRow>
                  <TableCell colSpan={3}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              )}
              {groupSubjects?.map((gs) => (
                <GroupSubjectRow
                  key={gs.id}
                  gs={gs}
                  group={group}
                  teachers={teachers ?? []}
                  subjectLabel={subjectName(gs.plan_subject_id)}
                />
              ))}
              {groupSubjects && groupSubjects.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={3}
                    className="py-8 text-center text-muted-foreground"
                  >
                    Este grupo aún no tiene materias asignadas
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold">Alumnos inscritos</h2>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              disabled={generateCharges.isPending}
              onClick={() => generateCharges.mutate()}
            >
              {generateCharges.isPending
                ? "Generando…"
                : "Generar cargos del grupo"}
            </Button>
            <Button
              className="font-bold"
              disabled={(groupSubjects ?? []).length === 0}
              title={
                (groupSubjects ?? []).length === 0
                  ? "Agregue materias al grupo antes de inscribir alumnos"
                  : undefined
              }
              onClick={() => setEnrollOpen(true)}
            >
              <UserPlus className="size-4" /> Inscribir alumno
            </Button>
          </div>
        </div>
        <div className="rounded-2xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Matrícula</TableHead>
                <TableHead>Nombre</TableHead>
                <TableHead>Materias inscritas</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {enrolled.map((s) => (
                <TableRow key={s.student_id}>
                  <TableCell className="font-semibold" data-numeric>
                    {s.enrollment_number}
                  </TableCell>
                  <TableCell className="font-semibold">{s.name}</TableCell>
                  <TableCell data-numeric>
                    {s.subjects} / {(groupSubjects ?? []).length}
                  </TableCell>
                </TableRow>
              ))}
              {enrolled.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={3}
                    className="py-8 text-center text-muted-foreground"
                  >
                    Sin alumnos inscritos
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>

        {billing && billing.length > 0 && (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              Facturación:{" "}
              <span className="font-semibold text-foreground" data-numeric>
                {billedCount} de {billing.length}
              </span>{" "}
              alumnos facturados. Usa «Generar cargos del grupo» para completar
              los faltantes.
            </p>
            <div className="rounded-2xl border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Alumno</TableHead>
                    <TableHead>Matrícula</TableHead>
                    <TableHead>Cargos</TableHead>
                    <TableHead>Facturación</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {billing.map((b) => (
                    <TableRow key={b.student_id}>
                      <TableCell className="font-semibold">
                        {b.student_name}
                      </TableCell>
                      <TableCell data-numeric>{b.enrollment_number}</TableCell>
                      <TableCell data-numeric>{b.charges_count}</TableCell>
                      <TableCell>
                        <Badge variant={b.billed ? "outline" : "destructive"}>
                          {b.billed ? "Facturado" : "Sin cargos"}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
      </section>

      <GroupSubjectDialog
        key={`${group.id}-${editingSubject?.id ?? "new"}`}
        open={subjectDialogOpen}
        onOpenChange={setSubjectDialogOpen}
        group={group}
        editing={editingSubject}
        planSubjects={planSubjects ?? []}
        teachers={teachers ?? []}
      />

      <EnrollDialog
        key={group.id}
        open={enrollOpen}
        onOpenChange={setEnrollOpen}
        group={group}
        groupSubjects={groupSubjects ?? []}
        subjectName={subjectName}
        onDone={() => {
          invalidateGrids();
          // the new student + its auto-generated charges change the billing roster
          queryClient.invalidateQueries({
            queryKey: queryKeys.groupBillingStatus(group.id),
          });
        }}
      />
    </div>
  );
}

// Inline row: teacher (Select, saves on change) and schedule (Input, saves on
// blur/Enter). Both persist via the group-subjects upsert (POST is idempotent by
// group_id + plan_subject_id) — no dialog, no extra backend endpoint.
function GroupSubjectRow({
  gs,
  group,
  teachers,
  subjectLabel,
}: {
  gs: GroupSubject;
  group: Group;
  teachers: UserPublic[];
  subjectLabel: string;
}) {
  const queryClient = useQueryClient();
  const [schedule, setSchedule] = useState(gs.schedule_text ?? "");

  const save = useMutation({
    mutationFn: (patch: {
      teacher_user_id?: string | null;
      schedule_text?: string;
    }) =>
      api<GroupSubject>("/catalog/group-subjects", {
        method: "POST",
        body: JSON.stringify({
          group_id: group.id,
          plan_subject_id: gs.plan_subject_id,
          teacher_user_id: gs.teacher_user_id,
          schedule_text: gs.schedule_text,
          ...patch,
        }),
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: queryKeys.groupSubjects(group.id),
      }),
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  function commitSchedule() {
    if (save.isPending) return; // don't overlap with an in-flight teacher save
    const next = schedule.trim();
    if (next !== (gs.schedule_text ?? "")) save.mutate({ schedule_text: next });
  }

  return (
    <TableRow>
      <TableCell className="font-semibold">{subjectLabel}</TableCell>
      <TableCell>
        <Select
          value={gs.teacher_user_id ?? NONE}
          onValueChange={(v) =>
            save.mutate({ teacher_user_id: v === NONE ? null : v })
          }
          disabled={save.isPending}
        >
          <SelectTrigger className="w-full" aria-label="Docente">
            <SelectValue placeholder="Sin asignar" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>Sin asignar</SelectItem>
            {teachers.map((t) => (
              <SelectItem key={t.id} value={t.id}>
                {t.full_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </TableCell>
      <TableCell>
        <Input
          value={schedule}
          disabled={save.isPending}
          onChange={(e) => setSchedule(e.target.value)}
          onBlur={commitSchedule}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              e.currentTarget.blur();
            }
          }}
          placeholder="Lun y Mié 18:00–20:00"
          aria-label="Horario"
        />
      </TableCell>
    </TableRow>
  );
}

function GroupSubjectDialog({
  open,
  onOpenChange,
  group,
  editing,
  planSubjects,
  teachers,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  group: Group;
  editing: GroupSubject | null;
  planSubjects: PlanSubject[];
  teachers: UserPublic[];
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    plan_subject_id: editing?.plan_subject_id ?? "",
    teacher_user_id: editing?.teacher_user_id ?? NONE,
    schedule_text: editing?.schedule_text ?? "",
  });

  const save = useMutation({
    mutationFn: () => {
      const body = JSON.stringify({
        group_id: group.id,
        plan_subject_id: form.plan_subject_id,
        teacher_user_id:
          form.teacher_user_id === NONE ? null : form.teacher_user_id,
        schedule_text: form.schedule_text,
      });
      return editing
        ? api<GroupSubject>(`/catalog/group-subjects/${editing.id}`, {
            method: "PATCH",
            body,
          })
        : api<GroupSubject>("/catalog/group-subjects", {
            method: "POST",
            body,
          });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.groupSubjects(group.id),
      });
      toast.success(editing ? "Materia actualizada" : "Materia agregada");
      onOpenChange(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  const subjectOptions = planSubjects.map((s) => ({
    value: s.id,
    label: `${s.code} — ${s.name}`,
    hint: `Periodo ${s.period_number}`,
  }));
  const teacherOptions = [
    { value: NONE, label: "Sin asignar" },
    ...teachers.map((t) => ({ value: t.id, label: t.full_name, hint: t.email })),
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {editing ? "Editar materia del grupo" : "Agregar materia al grupo"}
          </DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label>Materia del plan</Label>
            <SearchableSelect
              value={form.plan_subject_id}
              onChange={(v) => setForm({ ...form, plan_subject_id: v })}
              options={subjectOptions}
              placeholder="Seleccione una materia"
            />
          </div>
          <div className="grid gap-2">
            <Label>Docente</Label>
            <SearchableSelect
              value={form.teacher_user_id ?? NONE}
              onChange={(v) => setForm({ ...form, teacher_user_id: v })}
              options={teacherOptions}
              placeholder="Sin asignar"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="gs-schedule">Horario (texto)</Label>
            <Input
              id="gs-schedule"
              value={form.schedule_text}
              onChange={(e) =>
                setForm({ ...form, schedule_text: e.target.value })
              }
              placeholder="Lun y Mié 18:00–20:00"
            />
          </div>
          <DialogFooter>
            <Button
              type="submit"
              className="font-bold"
              disabled={save.isPending || !form.plan_subject_id}
            >
              {save.isPending ? "Guardando…" : "Guardar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EnrollDialog({
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
  const [studentId, setStudentId] = useState("");
  const [subjectIds, setSubjectIds] = useState<string[]>([]);
  const [override, setOverride] = useState(false);
  const [waiveEnrollmentFee, setWaiveEnrollmentFee] = useState(false);

  // only students of the group's campus can enroll (Servo Plantel key)
  const { data: students } = useQuery({
    queryKey: ["students", "by-campus", group.campus_id],
    queryFn: () =>
      api<Student[]>(`/students?limit=1000&campus_id=${group.campus_id}`),
    enabled: open,
  });

  const enroll = useMutation({
    mutationFn: () =>
      api(`/students/group-enrollments`, {
        method: "POST",
        body: JSON.stringify({
          student_id: studentId,
          group_id: group.id,
          plan_subject_ids: subjectIds,
          override_prerequisites: override,
          waive_enrollment_fee: waiveEnrollmentFee,
        }),
      }),
    onSuccess: () => {
      onDone();
      toast.success("Alumno inscrito. Verifica los cargos en su estado de cuenta");
      onOpenChange(false);
      setStudentId("");
      setSubjectIds([]);
      setOverride(false);
      setWaiveEnrollmentFee(false);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) {
        toast.error(`No se pudo inscribir: ${e.message}`, { duration: 8000 });
      } else {
        toast.error(e instanceof ApiError ? e.message : "Error al inscribir");
      }
    },
  });

  const studentOptions = (students ?? []).map((s) => ({
    value: s.id,
    label: s.full_name,
    hint: s.enrollment_number || s.curp,
  }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Inscribir alumno a {group.code}</DialogTitle>
          <DialogDescription>
            Se validará la seriación y que el RVOE del plan esté vigente. Si no
            selecciona materias se inscribirá a todas.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            enroll.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label>Alumno</Label>
            <SearchableSelect
              value={studentId}
              onChange={setStudentId}
              options={studentOptions}
              placeholder="Buscar alumno…"
              searchPlaceholder="Nombre, matrícula o CURP…"
            />
          </div>
          <div className="grid gap-2">
            <Label>Materias (opcional — vacío inscribe todas)</Label>
            <div className="max-h-44 space-y-1 overflow-y-auto rounded-xl border p-2">
              {groupSubjects.map((gs) => (
                <label
                  key={gs.id}
                  className="flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-muted"
                >
                  <Checkbox
                    checked={subjectIds.includes(gs.plan_subject_id)}
                    onCheckedChange={(v) =>
                      setSubjectIds(
                        v === true
                          ? [...subjectIds, gs.plan_subject_id]
                          : subjectIds.filter(
                              (id) => id !== gs.plan_subject_id,
                            ),
                      )
                    }
                  />
                  <span className="truncate">
                    {subjectName(gs.plan_subject_id)}
                  </span>
                </label>
              ))}
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm font-medium">
            <Checkbox
              checked={waiveEnrollmentFee}
              onCheckedChange={(v) => setWaiveEnrollmentFee(v === true)}
            />
            Condonar inscripción (no cobrar)
          </label>
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground">
              Opciones avanzadas
            </summary>
            <label className="mt-2 flex items-center gap-2 font-medium">
              <Checkbox
                checked={override}
                onCheckedChange={(v) => setOverride(v === true)}
              />
              Omitir validación de seriación (autorización especial)
            </label>
          </details>
          <DialogFooter>
            <Button
              type="submit"
              className="font-bold"
              disabled={enroll.isPending || !studentId}
            >
              {enroll.isPending ? "Inscribiendo…" : "Inscribir"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
