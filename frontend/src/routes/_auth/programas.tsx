import { useEffect, useRef, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarDays, Plus, Pencil, SlidersHorizontal, Trash2 } from "lucide-react";
import {
  api,
  ApiError,
  getCalendarPrograms,
  linkProgramToCalendar,
} from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  Campus,
  EducationLevel,
  EvaluationComponent,
  EvaluationKind,
  Modality,
  PeriodType,
  PlanSubject,
  PlanVersion,
  Program,
  Rvoe,
  RvoeAuthority,
  RvoeStatus,
} from "@/api/types";
import {
  EVALUATION_KIND_LABELS,
  formatDate,
  LEVEL_LABELS,
  MODALITY_LABELS,
  PERIOD_TYPE_LABELS,
  RVOE_STATUS_LABELS,
} from "@/lib/format";
import { cn } from "@/lib/utils";
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

export const Route = createFileRoute("/_auth/programas")({
  component: ProgramasPage,
});

function rvoeBadgeVariant(
  status: RvoeStatus,
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "vigente":
      return "default";
    case "en_tramite_modificacion":
      return "secondary";
    case "cancelado":
      return "destructive";
    default:
      return "outline";
  }
}

function ProgramasPage() {
  const [programId, setProgramId] = useState<string | null>(null);
  const [rvoeId, setRvoeId] = useState<string | null>(null);
  const [planVersionId, setPlanVersionId] = useState<string | null>(null);
  const [wizardStep, setWizardStep] = useState<null | "rvoe" | "plan">(null);

  const { data: programs, isLoading } = useQuery({
    queryKey: queryKeys.programs,
    queryFn: () => api<Program[]>("/catalog/programs"),
  });

  const program = programs?.find((p) => p.id === programId) ?? null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl">Programas académicos</h1>
        <ProgramDialogButton
          onCreated={(p) => {
            setProgramId(p.id);
            setRvoeId(null);
            setPlanVersionId(null);
            setWizardStep("rvoe");
          }}
        />
      </div>

      <div className="rounded-2xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Clave</TableHead>
              <TableHead>Nombre</TableHead>
              <TableHead>Nivel</TableHead>
              <TableHead>Estado</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading &&
              [1, 2, 3].map((i) => (
                <TableRow key={i}>
                  <TableCell colSpan={4}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {programs?.map((p) => (
              <TableRow
                key={p.id}
                className={cn(
                  "cursor-pointer",
                  p.id === programId && "bg-muted/60",
                )}
                onClick={() => {
                  setProgramId(p.id === programId ? null : p.id);
                  setRvoeId(null);
                  setPlanVersionId(null);
                }}
              >
                <TableCell className="font-semibold" data-numeric>
                  {p.code}
                </TableCell>
                <TableCell className="font-semibold">{p.name}</TableCell>
                <TableCell className="text-muted-foreground">
                  {LEVEL_LABELS[p.level]}
                </TableCell>
                <TableCell>
                  <Badge variant={p.is_active ? "outline" : "destructive"}>
                    {p.is_active ? "Activo" : "Inactivo"}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
            {programs && programs.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={4}
                  className="py-10 text-center text-muted-foreground"
                >
                  Sin programas registrados
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {program && <ProgramCalendarLink program={program} />}
      {program && (
        <RvoeSection
          program={program}
          rvoeId={rvoeId}
          onSelectRvoe={(id) => {
            setRvoeId(id);
            setPlanVersionId(null);
          }}
          autoOpen={wizardStep === "rvoe"}
          onCreated={(r) => {
            setRvoeId(r.id);
            setPlanVersionId(null);
            setWizardStep("plan");
          }}
          onDismiss={() => setWizardStep((s) => (s === "rvoe" ? null : s))}
        />
      )}
      {program && rvoeId && (
        <PlanVersionSection
          rvoeId={rvoeId}
          planVersionId={planVersionId}
          onSelectPlan={setPlanVersionId}
          autoOpen={wizardStep === "plan"}
          onCreated={(pv) => {
            setPlanVersionId(pv.id);
            setWizardStep(null);
          }}
          onDismiss={() => setWizardStep((s) => (s === "plan" ? null : s))}
        />
      )}
      {planVersionId && <SubjectsSection planVersionId={planVersionId} />}
    </div>
  );
}

// --- Calendar link (calendar.inue.online) ---------------------------------------

const NONE = "__none__";

function ProgramCalendarLink({ program }: { program: Program }) {
  const queryClient = useQueryClient();
  const { data: calendarPrograms, isError } = useQuery({
    queryKey: queryKeys.calendarPrograms,
    queryFn: getCalendarPrograms,
    retry: false,
  });

  const link = useMutation({
    mutationFn: (calendarProgramId: string | null) =>
      linkProgramToCalendar(program.id, calendarProgramId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.programs });
      toast.success("Vinculación con el calendario actualizada");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al vincular"),
  });

  const linked = calendarPrograms?.find(
    (cp) => cp.id === program.calendar_program_id,
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
          {program.calendar_program_id ? (
            <Badge variant="secondary">
              {linked?.name ?? program.calendar_program_id}
            </Badge>
          ) : (
            <span className="text-sm text-muted-foreground">Sin vincular</span>
          )}
          <div className="ml-auto w-72">
            <Select
              value={program.calendar_program_id ?? NONE}
              onValueChange={(v) => link.mutate(v === NONE ? null : v)}
              disabled={link.isPending}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Vincular programa del calendario" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Sin vincular</SelectItem>
                {calendarPrograms?.map((cp) => (
                  <SelectItem key={cp.id} value={cp.id}>
                    {cp.name}
                    {cp.rvoe ? ` · RVOE ${cp.rvoe}` : ""}
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

// --- Programs -----------------------------------------------------------------

function ProgramDialogButton({
  onCreated,
}: {
  onCreated?: (program: Program) => void;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    code: "",
    name: "",
    level: "licenciatura" as EducationLevel,
  });

  const save = useMutation({
    mutationFn: () =>
      api<Program>("/catalog/programs", {
        method: "POST",
        body: JSON.stringify(form),
      }),
    onSuccess: (program) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.programs });
      toast.success("Programa creado");
      setOpen(false);
      onCreated?.(program);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  return (
    <>
      <Button
        className="font-bold"
        onClick={() => {
          setForm({ code: "", name: "", level: "licenciatura" });
          setOpen(true);
        }}
      >
        <Plus className="size-4" /> Nuevo programa
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuevo programa</DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="p-code">Clave</Label>
              <Input
                id="p-code"
                required
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
                placeholder="LIC-DER"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="p-name">Nombre</Label>
              <Input
                id="p-name"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Licenciatura en Derecho"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="p-level">Nivel</Label>
              <Select
                value={form.level}
                onValueChange={(v) =>
                  setForm({ ...form, level: v as EducationLevel })
                }
              >
                <SelectTrigger id="p-level" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(LEVEL_LABELS) as EducationLevel[]).map((l) => (
                    <SelectItem key={l} value={l}>
                      {LEVEL_LABELS[l]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button
                type="submit"
                className="font-bold"
                disabled={save.isPending}
              >
                {save.isPending ? "Guardando…" : "Guardar"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}

// --- RVOEs ---------------------------------------------------------------------

interface RvoeForm {
  agreement_number: string;
  authority: RvoeAuthority;
  modality: Modality;
  issue_date: string;
  valid_until: string;
  status: RvoeStatus;
  notes: string;
  campus_id: string;
}

const emptyRvoeForm: RvoeForm = {
  agreement_number: "",
  authority: "estatal",
  modality: "escolarizada",
  issue_date: "",
  valid_until: "",
  status: "vigente",
  notes: "",
  campus_id: "",
};

function RvoeSection({
  program,
  rvoeId,
  onSelectRvoe,
  autoOpen,
  onCreated,
  onDismiss,
}: {
  program: Program;
  rvoeId: string | null;
  onSelectRvoe: (id: string | null) => void;
  autoOpen?: boolean;
  onCreated?: (rvoe: Rvoe) => void;
  onDismiss?: () => void;
}) {
  const queryClient = useQueryClient();
  const { data: rvoes, isLoading } = useQuery({
    queryKey: queryKeys.rvoes(program.id),
    queryFn: () => api<Rvoe[]>(`/catalog/rvoes?program_id=${program.id}`),
  });
  const { data: campuses } = useQuery({
    queryKey: queryKeys.campuses,
    queryFn: () => api<Campus[]>("/catalog/campuses"),
  });

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Rvoe | null>(null);
  const [form, setForm] = useState<RvoeForm>(emptyRvoeForm);
  const openedByWizardRef = useRef(false);

  useEffect(() => {
    if (autoOpen && !open) {
      setEditing(null);
      setForm({ ...emptyRvoeForm, campus_id: campuses?.[0]?.id ?? "" });
      openedByWizardRef.current = true;
      setOpen(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoOpen]);

  const save = useMutation({
    mutationFn: () => {
      if (editing) {
        return api<Rvoe>(`/catalog/rvoes/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            agreement_number: form.agreement_number,
            authority: form.authority,
            issue_date: form.issue_date,
            valid_until: form.valid_until || null,
            status: form.status,
            notes: form.notes,
          }),
        });
      }
      return api<Rvoe>("/catalog/rvoes", {
        method: "POST",
        body: JSON.stringify({
          agreement_number: form.agreement_number,
          authority: form.authority,
          modality: form.modality,
          issue_date: form.issue_date,
          valid_until: form.valid_until || null,
          status: form.status,
          notes: form.notes,
          program_id: program.id,
          campus_id: form.campus_id,
        }),
      });
    },
    onSuccess: (rvoe) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.rvoes(program.id) });
      toast.success(editing ? "RVOE actualizado" : "RVOE registrado");
      setOpen(false);
      if (!editing && openedByWizardRef.current) onCreated?.(rvoe);
      openedByWizardRef.current = false;
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  const campusName = (id: string) =>
    campuses?.find((c) => c.id === id)?.name ?? "—";

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">RVOEs de {program.name}</h2>
        <Button
          variant="outline"
          onClick={() => {
            setEditing(null);
            setForm({ ...emptyRvoeForm, campus_id: campuses?.[0]?.id ?? "" });
            setOpen(true);
          }}
        >
          <Plus className="size-4" /> Nuevo RVOE
        </Button>
      </div>

      <div className="rounded-2xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Acuerdo</TableHead>
              <TableHead>Autoridad</TableHead>
              <TableHead>Modalidad</TableHead>
              <TableHead>Campus</TableHead>
              <TableHead>Expedición</TableHead>
              <TableHead>Vigencia</TableHead>
              <TableHead>Estatus</TableHead>
              <TableHead className="w-16" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={8}>
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            )}
            {rvoes?.map((r) => (
              <TableRow
                key={r.id}
                className={cn("cursor-pointer", r.id === rvoeId && "bg-muted/60")}
                onClick={() => onSelectRvoe(r.id === rvoeId ? null : r.id)}
              >
                <TableCell className="font-semibold" data-numeric>
                  {r.agreement_number}
                </TableCell>
                <TableCell className="capitalize text-muted-foreground">
                  {r.authority}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {MODALITY_LABELS[r.modality]}
                </TableCell>
                <TableCell>{campusName(r.campus_id)}</TableCell>
                <TableCell>{formatDate(r.issue_date)}</TableCell>
                <TableCell>
                  {r.valid_until ? formatDate(r.valid_until) : "Indefinida"}
                </TableCell>
                <TableCell>
                  <Badge variant={rvoeBadgeVariant(r.status)}>
                    {RVOE_STATUS_LABELS[r.status]}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Editar"
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditing(r);
                      setForm({
                        agreement_number: r.agreement_number,
                        authority: r.authority,
                        modality: r.modality,
                        issue_date: r.issue_date,
                        valid_until: r.valid_until ?? "",
                        status: r.status,
                        notes: r.notes,
                        campus_id: r.campus_id,
                      });
                      setOpen(true);
                    }}
                  >
                    <Pencil className="size-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {rvoes && rvoes.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={8}
                  className="py-8 text-center text-muted-foreground"
                >
                  Este programa aún no tiene RVOE registrado
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog
        open={open}
        onOpenChange={(v) => {
          setOpen(v);
          if (!v) {
            onDismiss?.();
            openedByWizardRef.current = false;
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? "Editar RVOE" : "Nuevo RVOE"}</DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="r-num">Número de acuerdo</Label>
              <Input
                id="r-num"
                required
                value={form.agreement_number}
                onChange={(e) =>
                  setForm({ ...form, agreement_number: e.target.value })
                }
                placeholder="20230123"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>Autoridad</Label>
                <Select
                  value={form.authority}
                  onValueChange={(v) =>
                    setForm({ ...form, authority: v as RvoeAuthority })
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="estatal">Estatal</SelectItem>
                    <SelectItem value="federal">Federal</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label>Modalidad</Label>
                <Select
                  value={form.modality}
                  onValueChange={(v) =>
                    setForm({ ...form, modality: v as Modality })
                  }
                  disabled={!!editing}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(MODALITY_LABELS) as Modality[]).map((m) => (
                      <SelectItem key={m} value={m}>
                        {MODALITY_LABELS[m]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            {!editing && (
              <div className="grid gap-2">
                <Label>Campus</Label>
                <Select
                  value={form.campus_id}
                  onValueChange={(v) => setForm({ ...form, campus_id: v })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Seleccione un campus" />
                  </SelectTrigger>
                  <SelectContent>
                    {campuses?.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label htmlFor="r-issue">Fecha de expedición</Label>
                <Input
                  id="r-issue"
                  type="date"
                  required
                  value={form.issue_date}
                  onChange={(e) =>
                    setForm({ ...form, issue_date: e.target.value })
                  }
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="r-until">Vigente hasta (opcional)</Label>
                <Input
                  id="r-until"
                  type="date"
                  value={form.valid_until}
                  onChange={(e) =>
                    setForm({ ...form, valid_until: e.target.value })
                  }
                />
              </div>
            </div>
            <div className="grid gap-2">
              <Label>Estatus</Label>
              <Select
                value={form.status}
                onValueChange={(v) =>
                  setForm({ ...form, status: v as RvoeStatus })
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(RVOE_STATUS_LABELS) as RvoeStatus[]).map(
                    (s) => (
                      <SelectItem key={s} value={s}>
                        {RVOE_STATUS_LABELS[s]}
                      </SelectItem>
                    ),
                  )}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="r-notes">Notas</Label>
              <Input
                id="r-notes"
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
              />
            </div>
            <DialogFooter>
              <Button
                type="submit"
                className="font-bold"
                disabled={save.isPending || (!editing && !form.campus_id)}
              >
                {save.isPending ? "Guardando…" : "Guardar"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}

// --- Plan versions -----------------------------------------------------------

function PlanVersionSection({
  rvoeId,
  planVersionId,
  onSelectPlan,
  autoOpen,
  onCreated,
  onDismiss,
}: {
  rvoeId: string;
  planVersionId: string | null;
  onSelectPlan: (id: string | null) => void;
  autoOpen?: boolean;
  onCreated?: (plan: PlanVersion) => void;
  onDismiss?: () => void;
}) {
  const queryClient = useQueryClient();
  const { data: plans, isLoading } = useQuery({
    queryKey: queryKeys.planVersions(rvoeId),
    queryFn: () => api<PlanVersion[]>(`/catalog/plan-versions?rvoe_id=${rvoeId}`),
  });

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    version_label: "",
    period_type: "cuatrimestral" as PeriodType,
    periods_count: 9,
    min_attendance_pct: 80,
  });
  const openedByWizardRef = useRef(false);

  useEffect(() => {
    if (autoOpen && !open) {
      setForm({
        version_label: "",
        period_type: "cuatrimestral",
        periods_count: 9,
        min_attendance_pct: 80,
      });
      openedByWizardRef.current = true;
      setOpen(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoOpen]);

  const save = useMutation({
    mutationFn: () =>
      api<PlanVersion>("/catalog/plan-versions", {
        method: "POST",
        body: JSON.stringify({ ...form, rvoe_id: rvoeId }),
      }),
    onSuccess: (plan) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.planVersions(rvoeId) });
      toast.success("Versión de plan creada");
      setOpen(false);
      if (openedByWizardRef.current) onCreated?.(plan);
      openedByWizardRef.current = false;
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Versiones del plan de estudios</h2>
        <Button
          variant="outline"
          onClick={() => {
            setForm({
              version_label: "",
              period_type: "cuatrimestral",
              periods_count: 9,
              min_attendance_pct: 80,
            });
            setOpen(true);
          }}
        >
          <Plus className="size-4" /> Nueva versión
        </Button>
      </div>

      <div className="rounded-2xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Versión</TableHead>
              <TableHead>Tipo de periodo</TableHead>
              <TableHead>Periodos</TableHead>
              <TableHead>Asistencia mínima</TableHead>
              <TableHead>Estado</TableHead>
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
            {plans?.map((p) => (
              <TableRow
                key={p.id}
                className={cn(
                  "cursor-pointer",
                  p.id === planVersionId && "bg-muted/60",
                )}
                onClick={() => onSelectPlan(p.id === planVersionId ? null : p.id)}
              >
                <TableCell className="font-semibold">{p.version_label}</TableCell>
                <TableCell className="text-muted-foreground">
                  {PERIOD_TYPE_LABELS[p.period_type]}
                </TableCell>
                <TableCell data-numeric>{p.periods_count}</TableCell>
                <TableCell data-numeric>{p.min_attendance_pct}%</TableCell>
                <TableCell>
                  <Badge variant={p.is_active ? "outline" : "destructive"}>
                    {p.is_active ? "Activa" : "Inactiva"}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
            {plans && plans.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className="py-8 text-center text-muted-foreground"
                >
                  Este RVOE aún no tiene versiones de plan
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog
        open={open}
        onOpenChange={(v) => {
          setOpen(v);
          if (!v) {
            onDismiss?.();
            openedByWizardRef.current = false;
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nueva versión de plan</DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="v-label">Etiqueta de versión</Label>
              <Input
                id="v-label"
                required
                value={form.version_label}
                onChange={(e) =>
                  setForm({ ...form, version_label: e.target.value })
                }
                placeholder="2023"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>Tipo de periodo</Label>
                <Select
                  value={form.period_type}
                  onValueChange={(v) =>
                    setForm({ ...form, period_type: v as PeriodType })
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(PERIOD_TYPE_LABELS) as PeriodType[]).map(
                      (p) => (
                        <SelectItem key={p} value={p}>
                          {PERIOD_TYPE_LABELS[p]}
                        </SelectItem>
                      ),
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="v-count">Número de periodos</Label>
                <Input
                  id="v-count"
                  type="number"
                  min={1}
                  max={20}
                  required
                  value={form.periods_count}
                  onChange={(e) =>
                    setForm({ ...form, periods_count: Number(e.target.value) })
                  }
                />
              </div>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="v-att">Asistencia mínima (%)</Label>
              <Input
                id="v-att"
                type="number"
                min={0}
                max={100}
                required
                value={form.min_attendance_pct}
                onChange={(e) =>
                  setForm({
                    ...form,
                    min_attendance_pct: Number(e.target.value),
                  })
                }
              />
            </div>
            <DialogFooter>
              <Button
                type="submit"
                className="font-bold"
                disabled={save.isPending}
              >
                {save.isPending ? "Guardando…" : "Guardar"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}

// --- Plan subjects ------------------------------------------------------------

interface SubjectForm {
  code: string;
  name: string;
  period_number: number;
  credits: number;
  theory_hours: number;
  practice_hours: number;
  prerequisite_ids: string[];
}

const emptySubjectForm: SubjectForm = {
  code: "",
  name: "",
  period_number: 1,
  credits: 6,
  theory_hours: 0,
  practice_hours: 0,
  prerequisite_ids: [],
};

function SubjectsSection({ planVersionId }: { planVersionId: string }) {
  const queryClient = useQueryClient();
  const { data: subjects, isLoading } = useQuery({
    queryKey: queryKeys.planSubjects(planVersionId),
    queryFn: () =>
      api<PlanSubject[]>(`/catalog/plan-versions/${planVersionId}/subjects`),
  });

  const [open, setOpen] = useState(false);
  const [editingPrereqs, setEditingPrereqs] = useState<PlanSubject | null>(null);
  const [form, setForm] = useState<SubjectForm>(emptySubjectForm);
  const [componentsFor, setComponentsFor] = useState<PlanSubject | null>(null);

  const save = useMutation({
    mutationFn: () => {
      if (editingPrereqs) {
        return api<PlanSubject>(
          `/catalog/plan-subjects/${editingPrereqs.id}/prerequisites`,
          { method: "PUT", body: JSON.stringify(form.prerequisite_ids) },
        );
      }
      return api<PlanSubject>("/catalog/plan-subjects", {
        method: "POST",
        body: JSON.stringify({ ...form, plan_version_id: planVersionId }),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.planSubjects(planVersionId),
      });
      toast.success(
        editingPrereqs ? "Seriación actualizada" : "Materia creada",
      );
      setOpen(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  const nameOf = (id: string) =>
    subjects?.find((s) => s.id === id)?.code ?? "?";

  const prereqCandidates = (subjects ?? []).filter(
    (s) =>
      (!editingPrereqs || s.id !== editingPrereqs.id) &&
      (editingPrereqs
        ? s.period_number < editingPrereqs.period_number
        : s.period_number < form.period_number),
  );

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Materias del plan</h2>
        <Button
          variant="outline"
          onClick={() => {
            setEditingPrereqs(null);
            setForm(emptySubjectForm);
            setOpen(true);
          }}
        >
          <Plus className="size-4" /> Nueva materia
        </Button>
      </div>

      <div className="rounded-2xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Periodo</TableHead>
              <TableHead>Clave</TableHead>
              <TableHead>Nombre</TableHead>
              <TableHead>Créditos</TableHead>
              <TableHead>Seriación (requiere)</TableHead>
              <TableHead className="w-28" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={6}>
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            )}
            {subjects?.map((s) => (
              <TableRow key={s.id}>
                <TableCell data-numeric>{s.period_number}</TableCell>
                <TableCell className="font-semibold" data-numeric>
                  {s.code}
                </TableCell>
                <TableCell className="font-semibold">{s.name}</TableCell>
                <TableCell data-numeric>{s.credits}</TableCell>
                <TableCell className="text-muted-foreground">
                  {(s.prerequisite_ids ?? []).length > 0
                    ? (s.prerequisite_ids ?? []).map(nameOf).join(", ")
                    : "—"}
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Editar seriación"
                    title="Editar seriación"
                    onClick={() => {
                      setEditingPrereqs(s);
                      setForm({
                        code: s.code,
                        name: s.name,
                        period_number: s.period_number,
                        credits: s.credits,
                        theory_hours: s.theory_hours,
                        practice_hours: s.practice_hours,
                        prerequisite_ids: s.prerequisite_ids ?? [],
                      });
                      setOpen(true);
                    }}
                  >
                    <Pencil className="size-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Componentes de evaluación"
                    title="Componentes de evaluación"
                    onClick={() => setComponentsFor(s)}
                  >
                    <SlidersHorizontal className="size-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {subjects && subjects.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="py-8 text-center text-muted-foreground"
                >
                  Esta versión del plan aún no tiene materias
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingPrereqs
                ? `Seriación de ${editingPrereqs.name}`
                : "Nueva materia"}
            </DialogTitle>
            {editingPrereqs && (
              <DialogDescription>
                Materias que el alumno debe aprobar antes de cursarla.
              </DialogDescription>
            )}
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            {!editingPrereqs && (
              <>
                <div className="grid grid-cols-2 gap-4">
                  <div className="grid gap-2">
                    <Label htmlFor="s-code">Clave</Label>
                    <Input
                      id="s-code"
                      required
                      value={form.code}
                      onChange={(e) =>
                        setForm({ ...form, code: e.target.value })
                      }
                      placeholder="DER-101"
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="s-period">Periodo</Label>
                    <Input
                      id="s-period"
                      type="number"
                      min={1}
                      max={20}
                      required
                      value={form.period_number}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          period_number: Number(e.target.value),
                        })
                      }
                    />
                  </div>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="s-name">Nombre</Label>
                  <Input
                    id="s-name"
                    required
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                  />
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div className="grid gap-2">
                    <Label htmlFor="s-credits">Créditos</Label>
                    <Input
                      id="s-credits"
                      type="number"
                      min={0}
                      step="0.5"
                      required
                      value={form.credits}
                      onChange={(e) =>
                        setForm({ ...form, credits: Number(e.target.value) })
                      }
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="s-theory">Hrs. teoría</Label>
                    <Input
                      id="s-theory"
                      type="number"
                      min={0}
                      value={form.theory_hours}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          theory_hours: Number(e.target.value),
                        })
                      }
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="s-practice">Hrs. práctica</Label>
                    <Input
                      id="s-practice"
                      type="number"
                      min={0}
                      value={form.practice_hours}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          practice_hours: Number(e.target.value),
                        })
                      }
                    />
                  </div>
                </div>
              </>
            )}
            <div className="grid gap-2">
              <Label>Seriación (materias prerequisito)</Label>
              {prereqCandidates.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No hay materias de periodos anteriores para seriar.
                </p>
              ) : (
                <div className="max-h-48 space-y-1 overflow-y-auto rounded-xl border p-2">
                  {prereqCandidates.map((s) => (
                    <label
                      key={s.id}
                      className="flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-muted"
                    >
                      <Checkbox
                        checked={form.prerequisite_ids.includes(s.id)}
                        onCheckedChange={(v) =>
                          setForm({
                            ...form,
                            prerequisite_ids:
                              v === true
                                ? [...form.prerequisite_ids, s.id]
                                : form.prerequisite_ids.filter(
                                    (id) => id !== s.id,
                                  ),
                          })
                        }
                      />
                      <span className="font-semibold">{s.code}</span>
                      <span className="truncate">{s.name}</span>
                      <span className="ml-auto text-xs text-muted-foreground">
                        Periodo {s.period_number}
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>
            <DialogFooter>
              <Button
                type="submit"
                className="font-bold"
                disabled={save.isPending}
              >
                {save.isPending ? "Guardando…" : "Guardar"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {componentsFor && (
        <ComponentsDialog
          subject={componentsFor}
          onClose={() => setComponentsFor(null)}
        />
      )}
    </section>
  );
}

// --- Evaluation components ------------------------------------------------------

function ComponentsDialog({
  subject,
  onClose,
}: {
  subject: PlanSubject;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { data: components, isLoading } = useQuery({
    queryKey: queryKeys.evaluationComponents(subject.id),
    queryFn: () =>
      api<EvaluationComponent[]>(
        `/catalog/plan-subjects/${subject.id}/evaluation-components`,
      ),
  });

  const [form, setForm] = useState({
    kind: "parcial" as EvaluationKind,
    label: "",
    weight_pct: 25,
    sequence: 1,
    counts_towards_final: true,
  });

  const add = useMutation({
    mutationFn: () =>
      api<EvaluationComponent>("/catalog/evaluation-components", {
        method: "POST",
        body: JSON.stringify({ ...form, plan_subject_id: subject.id }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.evaluationComponents(subject.id),
      });
      toast.success("Componente agregado");
      setForm((f) => ({ ...f, label: "", sequence: f.sequence + 1 }));
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  const remove = useMutation({
    mutationFn: (id: string) =>
      api(`/catalog/evaluation-components/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.evaluationComponents(subject.id),
      });
      toast.success("Componente eliminado");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al eliminar"),
  });

  const countingWeight = (components ?? [])
    .filter((c) => c.counts_towards_final)
    .reduce((sum, c) => sum + c.weight_pct, 0);

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Evaluación de {subject.name}</DialogTitle>
          <DialogDescription>
            Los componentes que cuentan para la calificación final deben sumar
            100%.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          {isLoading && <Skeleton className="h-6 w-full" />}
          {components?.map((c) => (
            <div
              key={c.id}
              className="flex items-center gap-3 rounded-xl border px-3 py-2 text-sm"
            >
              <Badge variant="secondary">{EVALUATION_KIND_LABELS[c.kind]}</Badge>
              <span className="font-semibold">{c.label}</span>
              <span className="ml-auto" data-numeric>
                {c.weight_pct}%
              </span>
              {!c.counts_towards_final && (
                <span className="text-xs text-muted-foreground">
                  no cuenta
                </span>
              )}
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Eliminar"
                disabled={remove.isPending}
                onClick={() => remove.mutate(c.id)}
              >
                <Trash2 className="size-4 text-destructive" />
              </Button>
            </div>
          ))}
          {components && components.length === 0 && (
            <p className="py-4 text-center text-sm text-muted-foreground">
              Sin componentes de evaluación
            </p>
          )}
          {components && components.length > 0 && (
            <p
              className={cn(
                "text-right text-sm font-semibold",
                Math.abs(countingWeight - 100) > 0.01
                  ? "text-destructive"
                  : "text-muted-foreground",
              )}
              data-numeric
            >
              Suma ponderada: {countingWeight}%
              {Math.abs(countingWeight - 100) > 0.01 && " (debe ser 100%)"}
            </p>
          )}
        </div>

        <form
          className="grid gap-3 border-t pt-4"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-2">
              <Label>Tipo</Label>
              <Select
                value={form.kind}
                onValueChange={(v) =>
                  setForm({ ...form, kind: v as EvaluationKind })
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(
                    Object.keys(EVALUATION_KIND_LABELS) as EvaluationKind[]
                  ).map((k) => (
                    <SelectItem key={k} value={k}>
                      {EVALUATION_KIND_LABELS[k]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="c-label">Etiqueta</Label>
              <Input
                id="c-label"
                required
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                placeholder="Parcial 1"
              />
            </div>
          </div>
          <div className="grid grid-cols-3 items-end gap-3">
            <div className="grid gap-2">
              <Label htmlFor="c-weight">Peso (%)</Label>
              <Input
                id="c-weight"
                type="number"
                min={0}
                max={100}
                step="0.1"
                required
                value={form.weight_pct}
                onChange={(e) =>
                  setForm({ ...form, weight_pct: Number(e.target.value) })
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="c-seq">Orden</Label>
              <Input
                id="c-seq"
                type="number"
                min={1}
                required
                value={form.sequence}
                onChange={(e) =>
                  setForm({ ...form, sequence: Number(e.target.value) })
                }
              />
            </div>
            <label className="flex items-center gap-2 pb-2 text-sm font-medium">
              <Checkbox
                checked={form.counts_towards_final}
                onCheckedChange={(v) =>
                  setForm({ ...form, counts_towards_final: v === true })
                }
              />
              Cuenta para final
            </label>
          </div>
          <DialogFooter>
            <Button type="submit" className="font-bold" disabled={add.isPending}>
              <Plus className="size-4" />
              {add.isPending ? "Agregando…" : "Agregar componente"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
