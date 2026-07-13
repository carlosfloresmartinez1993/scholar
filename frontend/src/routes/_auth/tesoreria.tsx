import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlarmClock, Download, Plus } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  AgingRow,
  ChargeConcept,
  ChargeConceptKind,
  CollectionReport,
  Institution,
  Modality,
  Program,
  Term,
} from "@/api/types";
import {
  CONCEPT_KIND_LABELS,
  formatDate,
  formatMoney,
  MODALITY_LABELS,
  PAYMENT_METHOD_LABELS,
} from "@/lib/format";
import {
  DateRangeFilter,
  presetRange,
  type DateRange,
} from "@/components/date-range-filter";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
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

export const Route = createFileRoute("/_auth/tesoreria")({
  component: TesoreriaPage,
});

const NONE = "__none__";

function TesoreriaPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl">Tesorería</h1>
      <Tabs defaultValue="conceptos">
        <TabsList>
          <TabsTrigger value="conceptos">Conceptos</TabsTrigger>
          <TabsTrigger value="reportes">Reportes</TabsTrigger>
          <TabsTrigger value="recargos">Recargos</TabsTrigger>
        </TabsList>
        <TabsContent value="conceptos" className="mt-4">
          <ConceptosTab />
        </TabsContent>
        <TabsContent value="reportes" className="mt-4">
          <ReportesTab />
        </TabsContent>
        <TabsContent value="recargos" className="mt-4">
          <RecargosTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// --- Conceptos --------------------------------------------------------------------

function ConceptosTab() {
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
    <div className="space-y-4">
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

      <div className="rounded-2xl border bg-card">
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
                  onValueChange={(v) =>
                    setForm({ ...form, kind: v as ChargeConceptKind })
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(
                      Object.keys(CONCEPT_KIND_LABELS) as ChargeConceptKind[]
                    ).map((k) => (
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
                onCheckedChange={(v) =>
                  setForm({ ...form, is_active: v === true })
                }
              />
              Concepto activo
            </label>
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
    </div>
  );
}

// --- Reportes -----------------------------------------------------------------------

function ReportesTab() {
  const [range, setRange] = useState<DateRange>(() => presetRange("mes"));
  const { data: terms } = useQuery({
    queryKey: queryKeys.terms,
    queryFn: () => api<Term[]>("/catalog/terms"),
  });
  const [sepTermId, setSepTermId] = useState<string>("");

  const { data: collection, isLoading: loadingCollection } = useQuery({
    queryKey: queryKeys.collectionReport(range.from, range.to),
    queryFn: () =>
      api<CollectionReport>(
        `/treasury/reports/collection?date_from=${range.from}&date_to=${range.to}`,
      ),
  });
  const { data: aging, isLoading: loadingAging } = useQuery({
    queryKey: queryKeys.aging,
    queryFn: () => api<AgingRow[]>("/treasury/reports/aging"),
  });

  const agingTotal = aging?.reduce((sum, r) => sum + r.balance, 0) ?? 0;
  const effectiveSepTerm = sepTermId || terms?.find((t) => t.is_open)?.id || "";

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-bold">Cobranza</h2>
          <DateRangeFilter value={range} onChange={setRange} />
        </div>
        {loadingCollection ? (
          <Skeleton className="h-32 w-full rounded-2xl" />
        ) : collection ? (
          <Card className="rounded-2xl">
            <CardContent className="flex flex-wrap items-start gap-8 p-6">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Periodo
                </p>
                <p className="font-bold">
                  {formatDate(collection.date_from)} –{" "}
                  {formatDate(collection.date_to)}
                </p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Pagos recibidos
                </p>
                <p className="text-2xl font-bold" data-numeric>
                  {collection.payments_count}
                </p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Total cobrado
                </p>
                <p className="text-2xl font-bold" data-numeric>
                  {formatMoney(collection.total)}
                </p>
              </div>
              <div className="min-w-48">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Por método
                </p>
                {Object.entries(collection.by_method).length === 0 && (
                  <p className="text-sm text-muted-foreground">Sin pagos</p>
                )}
                {Object.entries(collection.by_method).map(([method, total]) => (
                  <p key={method} className="flex justify-between gap-6 text-sm">
                    <span>
                      {PAYMENT_METHOD_LABELS[
                        method as keyof typeof PAYMENT_METHOD_LABELS
                      ] ?? method}
                    </span>
                    <span data-numeric className="font-semibold">
                      {formatMoney(total)}
                    </span>
                  </p>
                ))}
              </div>
              <div className="ml-auto">
                <Button variant="outline" asChild>
                  <a
                    href={`/api/v1/treasury/exports/movements?date_from=${range.from}&date_to=${range.to}`}
                    download
                  >
                    <Download className="size-4" /> Exportar movimientos (CSV)
                  </a>
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : null}
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-bold">
            Cartera vencida{" "}
            <span className="text-muted-foreground" data-numeric>
              · {formatMoney(agingTotal)}
            </span>
          </h2>
        </div>
        <div className="rounded-2xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Matrícula</TableHead>
                <TableHead>Alumno</TableHead>
                <TableHead>Concepto</TableHead>
                <TableHead>Venció</TableHead>
                <TableHead>Días</TableHead>
                <TableHead>Antigüedad</TableHead>
                <TableHead>Saldo</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loadingAging && (
                <TableRow>
                  <TableCell colSpan={7}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              )}
              {aging?.map((r, i) => (
                <TableRow key={`${r.student_id}-${i}`}>
                  <TableCell data-numeric>{r.enrollment_number}</TableCell>
                  <TableCell className="font-semibold">
                    {r.student_name}
                  </TableCell>
                  <TableCell className="max-w-64 truncate">
                    {r.description}
                  </TableCell>
                  <TableCell>{formatDate(r.due_date)}</TableCell>
                  <TableCell data-numeric>{r.days_overdue}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        r.bucket === "1-30"
                          ? "outline"
                          : r.bucket === "31-60"
                            ? "secondary"
                            : "destructive"
                      }
                    >
                      {r.bucket} días
                    </Badge>
                  </TableCell>
                  <TableCell data-numeric className="font-semibold">
                    {formatMoney(r.balance)}
                  </TableCell>
                </TableRow>
              ))}
              {aging && aging.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={7}
                    className="py-8 text-center text-muted-foreground"
                  >
                    No hay cargos vencidos
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-bold">Exportación SEP</h2>
        <Card className="rounded-2xl">
          <CardContent className="flex flex-wrap items-center gap-3 p-6">
            <Label className="text-sm font-semibold">Ciclo</Label>
            <Select value={effectiveSepTerm} onValueChange={setSepTermId}>
              <SelectTrigger className="w-64">
                <SelectValue placeholder="Seleccione un ciclo" />
              </SelectTrigger>
              <SelectContent>
                {terms?.map((t) => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" disabled={!effectiveSepTerm} asChild>
              <a
                href={`/api/v1/students/exports/sep?term_id=${effectiveSepTerm}`}
                download
              >
                <Download className="size-4" /> Exportar alumnos SEP (CSV)
              </a>
            </Button>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

// --- Recargos ------------------------------------------------------------------------

function RecargosTab() {
  const queryClient = useQueryClient();
  const { data: institution } = useQuery({
    queryKey: queryKeys.institution,
    queryFn: () => api<Institution>("/catalog/institution"),
  });

  const run = useMutation({
    mutationFn: () =>
      api<{ created: number }>("/treasury/late-fees/run", { method: "POST" }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.aging });
      toast.success(
        res.created > 0
          ? `Se generaron ${res.created} recargos`
          : "No hay cargos vencidos que generen recargo",
      );
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al aplicar recargos"),
  });

  return (
    <Card className="rounded-2xl">
      <CardContent className="space-y-4 p-6">
        <h2 className="text-lg font-bold">Recargos por mora</h2>
        <p className="max-w-xl text-sm text-muted-foreground">
          Genera cargos de recargo para los adeudos vencidos según la
          configuración institucional
          {institution && (
            <>
              {" "}
              (<span data-numeric>{institution.late_fee_pct}%</span> después de{" "}
              <span data-numeric>{institution.late_fee_grace_days}</span> días
              de gracia)
            </>
          )}
          . Los recargos ya generados no se duplican.
        </p>
        <Button
          className="font-bold"
          disabled={run.isPending}
          onClick={() => run.mutate()}
        >
          <AlarmClock className="size-4" />
          {run.isPending ? "Aplicando…" : "Aplicar recargos"}
        </Button>
      </CardContent>
    </Card>
  );
}
