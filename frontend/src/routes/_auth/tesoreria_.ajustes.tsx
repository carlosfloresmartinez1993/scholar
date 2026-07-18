import { useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlarmClock, ArrowLeft, Check, Plus, X } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  ChargeConcept,
  ChargeConceptKind,
  Institution,
  Modality,
  Program,
  Scholarship,
  ScholarshipStatus,
  Student,
  UserPublic,
} from "@/api/types";
import {
  CONCEPT_KIND_LABELS,
  formatDate,
  formatMoney,
  MODALITY_LABELS,
  SCHOLARSHIP_STATUS_LABELS,
} from "@/lib/format";
import { usePersistedState } from "@/lib/use-persisted-state";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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

export const Route = createFileRoute("/_auth/tesoreria_/ajustes")({
  component: AjustesPage,
});

const NONE = "__none__";

function AjustesPage() {
  // Pending-approval count surfaces on the Becas tab without opening it.
  const { data: pendientes } = useQuery({
    queryKey: queryKeys.scholarshipsByStatus("solicitada"),
    queryFn: () => api<Scholarship[]>("/treasury/scholarships?status=solicitada"),
  });
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="icon" asChild aria-label="Volver a Caja">
          <Link to="/tesoreria">
            <ArrowLeft className="size-4" />
          </Link>
        </Button>
        <div>
          <h1 className="text-3xl">Ajustes de tesorería</h1>
          <p className="text-sm text-muted-foreground">
            Conceptos de cobro, recargos y becas.
          </p>
        </div>
      </div>
      <Tabs defaultValue="conceptos">
        <TabsList>
          <TabsTrigger value="conceptos">Conceptos y recargos</TabsTrigger>
          <TabsTrigger value="becas">
            Becas
            {pendientes && pendientes.length > 0 && (
              <Badge variant="destructive" className="ml-1" data-numeric>
                {pendientes.length}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="conceptos" className="mt-4">
          <ConceptosSection />
        </TabsContent>
        <TabsContent value="becas" className="mt-4">
          <BecasSection />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// --- Conceptos (incluye recargos como sección) ----------------------------------------

function ConceptosSection() {
  const queryClient = useQueryClient();
  const { data: concepts, isLoading } = useQuery({
    queryKey: queryKeys.concepts,
    queryFn: () => api<ChargeConcept[]>("/treasury/concepts"),
  });
  const { data: programs } = useQuery({
    queryKey: queryKeys.programs,
    queryFn: () => api<Program[]>("/catalog/programs"),
  });

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: "",
    kind: "colegiatura" as ChargeConceptKind,
    amount: "",
    program_id: NONE,
    modality: NONE,
    is_active: true,
  });

  const save = useMutation({
    mutationFn: () =>
      api<ChargeConcept>("/treasury/concepts", {
        method: "POST",
        body: JSON.stringify({
          name: form.name,
          kind: form.kind,
          amount: Number(form.amount),
          program_id: form.program_id === NONE ? null : form.program_id,
          modality: form.modality === NONE ? null : form.modality,
          is_active: form.is_active,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.concepts });
      toast.success("Concepto creado");
      setOpen(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  const programName = (id?: string | null) =>
    id ? (programs?.find((p) => p.id === id)?.name ?? "—") : "Todos";

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <Button
          className="font-bold"
          onClick={() => {
            setForm({
              name: "",
              kind: "colegiatura",
              amount: "",
              program_id: NONE,
              modality: NONE,
              is_active: true,
            });
            setOpen(true);
          }}
        >
          <Plus className="size-4" /> Nuevo concepto
        </Button>
      </div>

      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nombre</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>Importe</TableHead>
              <TableHead>Programa</TableHead>
              <TableHead>Modalidad</TableHead>
              <TableHead>Estado</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading &&
              [1, 2, 3].map((i) => (
                <TableRow key={i}>
                  <TableCell colSpan={6}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {concepts?.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="font-semibold">{c.name}</TableCell>
                <TableCell>
                  <Badge variant="secondary">{CONCEPT_KIND_LABELS[c.kind]}</Badge>
                </TableCell>
                <TableCell data-numeric className="font-semibold">
                  {formatMoney(c.amount)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {programName(c.program_id)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {c.modality ? MODALITY_LABELS[c.modality] : "Todas"}
                </TableCell>
                <TableCell>
                  <Badge variant={c.is_active ? "outline" : "destructive"}>
                    {c.is_active ? "Activo" : "Inactivo"}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
            {concepts && concepts.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="py-10 text-center text-muted-foreground"
                >
                  Sin conceptos de cobro
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <RecargosSection />
      <InstitucionReciboCard />

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuevo concepto de cobro</DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="c-name">Nombre</Label>
              <Input
                id="c-name"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Colegiatura licenciatura 2026"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>Tipo</Label>
                <Select
                  value={form.kind}
                  onValueChange={(v) => setForm({ ...form, kind: v as ChargeConceptKind })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(CONCEPT_KIND_LABELS) as ChargeConceptKind[]).map((k) => (
                      <SelectItem key={k} value={k}>
                        {CONCEPT_KIND_LABELS[k]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="c-amount">Importe</Label>
                <Input
                  id="c-amount"
                  type="number"
                  min={0}
                  step="0.01"
                  required
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>Programa (opcional)</Label>
                <Select
                  value={form.program_id}
                  onValueChange={(v) => setForm({ ...form, program_id: v })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>Todos los programas</SelectItem>
                    {programs?.map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label>Modalidad (opcional)</Label>
                <Select
                  value={form.modality}
                  onValueChange={(v) => setForm({ ...form, modality: v })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>Todas las modalidades</SelectItem>
                    {(Object.keys(MODALITY_LABELS) as Modality[]).map((m) => (
                      <SelectItem key={m} value={m}>
                        {MODALITY_LABELS[m]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm font-medium">
              <Checkbox
                checked={form.is_active}
                onCheckedChange={(v) => setForm({ ...form, is_active: v === true })}
              />
              Concepto activo
            </label>
            <DialogFooter>
              <Button type="submit" className="font-bold" disabled={save.isPending}>
                {save.isPending ? "Guardando…" : "Guardar"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function RecargosSection() {
  const queryClient = useQueryClient();
  const { data: institution } = useQuery({
    queryKey: queryKeys.institution,
    queryFn: () => api<Institution>("/catalog/institution"),
  });

  const run = useMutation({
    mutationFn: () =>
      api<{ created: number; scholarships_suspended: number }>(
        "/treasury/late-fees/run",
        { method: "POST" },
      ),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.aging });
      const parts = [
        res.created > 0
          ? `${res.created} recargos generados`
          : "Sin cargos vencidos que generen recargo",
      ];
      if (res.scholarships_suspended > 0)
        parts.push(`${res.scholarships_suspended} becas suspendidas`);
      toast.success(parts.join(" · "));
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al aplicar recargos"),
  });

  return (
    <Card className="rounded-md border-dashed">
      <CardContent className="space-y-3 p-6">
        <div className="flex items-center gap-2">
          <Badge variant="secondary">{CONCEPT_KIND_LABELS.recargo}</Badge>
          <h2 className="text-lg font-bold">Recargos por mora</h2>
        </div>
        <p className="max-w-2xl text-sm text-muted-foreground">
          El recargo es un concepto especial que se genera automáticamente para
          los adeudos vencidos según la configuración institucional
          {institution && (
            <>
              {" "}
              (<span data-numeric>{institution.late_fee_pct}%</span> tras{" "}
              <span data-numeric>{institution.late_fee_grace_days}</span> días de
              gracia)
            </>
          )}
          . Los cargos con beca dentro de su periodo de tolerancia no generan
          recargo; al vencer la tolerancia se pierde la beca. No se duplican.
        </p>
        <Button className="font-bold" disabled={run.isPending} onClick={() => run.mutate()}>
          <AlarmClock className="size-4" />
          {run.isPending ? "Aplicando…" : "Aplicar recargos"}
        </Button>
      </CardContent>
    </Card>
  );
}

function InstitucionReciboCard() {
  const queryClient = useQueryClient();
  const { data: institution } = useQuery({
    queryKey: queryKeys.institution,
    queryFn: () => api<Institution>("/catalog/institution"),
  });
  const [form, setForm] = useState<{ rfc: string; fiscal_address: string } | null>(null);
  const model = form ?? {
    rfc: institution?.rfc ?? "",
    fiscal_address: institution?.fiscal_address ?? "",
  };

  const save = useMutation({
    mutationFn: () =>
      api<Institution>("/catalog/institution", {
        method: "PATCH",
        body: JSON.stringify(model),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.institution });
      toast.success("Encabezado de recibos actualizado");
      setForm(null);
    },
    onError: (e) =>
      toast.error(
        e instanceof ApiError ? e.message : "Solo Servicios Escolares o Dirección pueden editarlo",
      ),
  });

  return (
    <Card className="rounded-md border-dashed">
      <CardContent className="space-y-3 p-6">
        <h3 className="text-sm font-semibold text-muted-foreground">
          Encabezado de recibos · datos fiscales de la institución
        </h3>
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label>RFC</Label>
            <Input
              disabled={!institution}
              value={model.rfc}
              onChange={(e) => setForm({ ...model, rfc: e.target.value.toUpperCase() })}
              placeholder="IEE070919PCA"
            />
          </div>
          <div className="grid gap-2 sm:row-span-2">
            <Label>Domicilio fiscal (aparece en el recibo)</Label>
            <Textarea
              rows={4}
              disabled={!institution}
              value={model.fiscal_address}
              onChange={(e) => setForm({ ...model, fiscal_address: e.target.value })}
              placeholder={"CALLE OCTAVA 1389\nOBRERA\nENSENADA, BAJA CALIFORNIA C.P. 22830"}
            />
          </div>
          <div className="flex items-end">
            <Button
              type="submit"
              variant="outline"
              disabled={save.isPending || form === null}
            >
              {save.isPending ? "Guardando…" : "Guardar encabezado"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

// --- Becas: bandeja de autorización ---------------------------------------------------

const BECA_FILTERS: { value: ScholarshipStatus | "all"; label: string }[] = [
  { value: "solicitada", label: "Por autorizar" },
  { value: "activa", label: "Activas" },
  { value: "suspendida", label: "Suspendidas" },
  { value: "all", label: "Todas" },
];

function BecasSection() {
  const queryClient = useQueryClient();
  const { data: me } = useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api<UserPublic>("/auth/me"),
  });
  const canAuthorize =
    me?.is_superuser || me?.role === "admin_sistema" || me?.role === "direccion";
  const [filter, setFilter] = usePersistedState<ScholarshipStatus | "all">(
    "tesoreria-becas-status-v1",
    "solicitada",
    (v) => BECA_FILTERS.some((f) => f.value === v),
  );
  const [students, setStudents] = useState<Record<string, Student>>({});

  const { data: scholarships, isLoading } = useQuery({
    queryKey: queryKeys.scholarshipsByStatus(filter),
    queryFn: async () => {
      const qs = filter === "all" ? "" : `?status=${filter}`;
      const list = await api<Scholarship[]>(`/treasury/scholarships${qs}`);
      // Resolve student names lazily (small pending lists).
      const missing = [...new Set(list.map((s) => s.student_id))].filter(
        (id) => !students[id],
      );
      if (missing.length) {
        const fetched = await Promise.all(
          missing.map((id) =>
            api<Student>(`/students/${id}`).catch(() => null),
          ),
        );
        setStudents((prev) => {
          const next = { ...prev };
          for (const s of fetched) if (s) next[s.id] = s;
          return next;
        });
      }
      return list;
    },
  });

  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "authorize" | "reject" }) =>
      api(`/treasury/scholarships/${id}/${action}`, { method: "POST" }),
    onSuccess: (_d, { action }) => {
      queryClient.invalidateQueries({ queryKey: ["scholarships"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.scholarshipReport });
      toast.success(action === "authorize" ? "Beca autorizada" : "Beca rechazada");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error"),
  });

  const value = (s: Scholarship) =>
    s.pct != null ? `${s.pct}%` : formatMoney(s.fixed_amount);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 rounded-md border p-1">
          {BECA_FILTERS.map((f) => (
            <Button
              key={f.value}
              size="sm"
              variant={filter === f.value ? "default" : "ghost"}
              onClick={() => setFilter(f.value)}
            >
              {f.label}
            </Button>
          ))}
        </div>
        {!canAuthorize && (
          <p className="text-xs text-muted-foreground">
            Solo Dirección o Administración pueden autorizar becas.
          </p>
        )}
      </div>

      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Alumno</TableHead>
              <TableHead>Beca</TableHead>
              <TableHead>Valor</TableHead>
              <TableHead>Tolerancia</TableHead>
              <TableHead>Vigencia</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead className="text-right">Acción</TableHead>
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
            {scholarships?.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="font-semibold">
                  {students[s.student_id]?.full_name ?? "…"}
                  <span className="ml-2 text-xs text-muted-foreground" data-numeric>
                    {students[s.student_id]?.enrollment_number}
                  </span>
                </TableCell>
                <TableCell>{s.name}</TableCell>
                <TableCell data-numeric className="font-semibold">
                  {value(s)}
                </TableCell>
                <TableCell data-numeric>{s.tolerance_days} días</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {formatDate(s.valid_from)}
                  {s.valid_to ? ` – ${formatDate(s.valid_to)}` : ""}
                </TableCell>
                <TableCell>
                  <Badge
                    variant={
                      s.status === "activa"
                        ? "outline"
                        : s.status === "solicitada"
                          ? "secondary"
                          : "destructive"
                    }
                  >
                    {SCHOLARSHIP_STATUS_LABELS[s.status]}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  {s.status === "solicitada" && canAuthorize ? (
                    <div className="flex justify-end gap-2">
                      <Button
                        size="sm"
                        disabled={act.isPending}
                        onClick={() => act.mutate({ id: s.id, action: "authorize" })}
                      >
                        <Check className="size-4" /> Autorizar
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={act.isPending}
                        onClick={() => act.mutate({ id: s.id, action: "reject" })}
                      >
                        <X className="size-4" /> Rechazar
                      </Button>
                    </div>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {scholarships && scholarships.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                  Sin becas en este filtro
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
