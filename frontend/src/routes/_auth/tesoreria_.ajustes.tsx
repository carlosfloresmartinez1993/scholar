import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlarmClock, Pencil, Plus, X } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  ChargeConcept,
  ChargeConceptKind,
  Institution,
  Modality,
  Program,
} from "@/api/types";
import {
  CONCEPT_KIND_LABELS,
  formatMoney,
  MODALITY_LABELS,
} from "@/lib/format";
import { TesoreriaLayout } from "@/components/tesoreria-nav";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
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
  return (
    <div className="space-y-6">
      <h1 className="text-3xl">Tesorería</h1>
      <TesoreriaLayout active="ajustes">
        <ConceptosSection />
      </TesoreriaLayout>
    </div>
  );
}

// --- Conceptos (incluye recargos como sección) ----------------------------------------

const EMPTY_FORM = {
  name: "",
  kind: "colegiatura" as ChargeConceptKind,
  amount: "",
  program_id: NONE,
  modality: NONE,
  is_active: true,
};

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
  const [editing, setEditing] = useState<ChargeConcept | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);

  const startCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setOpen(true);
  };
  const startEdit = (c: ChargeConcept) => {
    setEditing(c);
    setForm({
      name: c.name,
      kind: c.kind,
      amount: String(c.amount),
      program_id: c.program_id ?? NONE,
      modality: c.modality ?? NONE,
      is_active: c.is_active,
    });
    setOpen(true);
  };

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: form.name,
        amount: Number(form.amount),
        program_id: form.program_id === NONE ? null : form.program_id,
        modality: form.modality === NONE ? null : form.modality,
        is_active: form.is_active,
      };
      return editing
        ? api<ChargeConcept>(`/treasury/concepts/${editing.id}`, {
            method: "PATCH",
            body: JSON.stringify(payload),
          })
        : api<ChargeConcept>("/treasury/concepts", {
            method: "POST",
            body: JSON.stringify({ ...payload, kind: form.kind }),
          });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.concepts });
      toast.success(editing ? "Concepto actualizado" : "Concepto creado");
      setOpen(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  const programName = (id?: string | null) =>
    id ? (programs?.find((p) => p.id === id)?.name ?? "—") : "Todos";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-xl text-sm text-muted-foreground">
          Cada cargo congela su importe al generarse: cambiar el precio de un
          concepto solo afecta cargos futuros, los adeudos existentes no se
          mueven. Edita el concepto en lugar de crear uno nuevo por ciclo.
        </p>
        <Button className="font-bold" onClick={startCreate}>
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
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading &&
              [1, 2, 3].map((i) => (
                <TableRow key={i}>
                  <TableCell colSpan={7}>
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
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Editar ${c.name}`}
                    onClick={() => startEdit(c)}
                  >
                    <Pencil className="size-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {concepts && concepts.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={7}
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
      <BecaPctsCard />
      <InstitucionReciboCard />

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editing ? `Editar: ${editing.name}` : "Nuevo concepto de cobro"}
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
              <Label htmlFor="c-name">Nombre</Label>
              <Input
                id="c-name"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Colegiatura licenciatura"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>Tipo</Label>
                <Select
                  value={form.kind}
                  disabled={!!editing}
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
                {editing && (
                  <p className="text-xs text-muted-foreground">
                    El nuevo importe aplica solo a cargos futuros.
                  </p>
                )}
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

/** Beca percentages Dirección pre-authorizes: caja grants these instantly,
 * anything else goes through the solicitud→autorización flow. */
function BecaPctsCard() {
  const queryClient = useQueryClient();
  const { data: institution } = useQuery({
    queryKey: queryKeys.institution,
    queryFn: () => api<Institution>("/catalog/institution"),
  });
  const [newPct, setNewPct] = useState("");
  const pcts = institution?.scholarship_pcts ?? [];

  const save = useMutation({
    mutationFn: (next: number[]) =>
      api<number[]>("/treasury/scholarship-pcts", {
        method: "PUT",
        body: JSON.stringify(next),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.institution });
      setNewPct("");
      toast.success("Porcentajes preautorizados actualizados");
    },
    onError: (e) =>
      toast.error(
        e instanceof ApiError
          ? e.message
          : "Solo Dirección o Administración pueden editarlos",
      ),
  });

  const add = () => {
    const p = Number(newPct);
    if (!(p > 0) || p > 100) {
      toast.error("El porcentaje debe ser mayor a 0 y no exceder 100%");
      return;
    }
    save.mutate([...pcts, p]);
  };

  return (
    <Card className="rounded-md border-dashed">
      <CardContent className="space-y-3 p-6">
        <h2 className="text-lg font-bold">Porcentajes de beca preautorizados</h2>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Las becas con estos porcentajes se aplican al momento en caja, sin
          esperar autorización. Cualquier otro porcentaje se captura como
          solicitud y requiere el visto bueno de Dirección o Administración.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {pcts.map((p) => (
            <Badge key={p} variant="secondary" className="gap-1 text-sm" data-numeric>
              {p}%
              <button
                type="button"
                aria-label={`Quitar ${p}%`}
                className="ml-1 hover:text-destructive"
                disabled={save.isPending}
                onClick={() => save.mutate(pcts.filter((x) => x !== p))}
              >
                <X className="size-3" />
              </button>
            </Badge>
          ))}
          {pcts.length === 0 && (
            <span className="text-sm text-muted-foreground">
              Sin porcentajes preautorizados — toda beca requiere autorización.
            </span>
          )}
        </div>
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            add();
          }}
        >
          <Input
            type="number"
            min={0.1}
            max={100}
            step="0.1"
            placeholder="25"
            className="w-28"
            value={newPct}
            onChange={(e) => setNewPct(e.target.value)}
          />
          <Button type="submit" variant="outline" disabled={save.isPending || !newPct}>
            <Plus className="size-4" /> Agregar
          </Button>
        </form>
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
