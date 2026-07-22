import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, Plus, Search, X } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  ChargeConcept,
  Scholarship,
  ScholarshipStatus,
  Student,
  UserPublic,
} from "@/api/types";
import {
  formatDate,
  formatMoney,
  SCHOLARSHIP_STATUS_LABELS,
} from "@/lib/format";
import { usePersistedState } from "@/lib/use-persisted-state";
import { TesoreriaLayout } from "@/components/tesoreria-nav";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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

export const Route = createFileRoute("/_auth/tesoreria_/becas")({
  component: BecasPage,
});

const COLEGIATURA = "__colegiatura__";

function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function BecasPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl">Tesorería</h1>
      <TesoreriaLayout active="becas">
        <BecasSection />
      </TesoreriaLayout>
    </div>
  );
}

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
  const [createOpen, setCreateOpen] = useState(false);

  const { data: concepts } = useQuery({
    queryKey: queryKeys.concepts,
    queryFn: () => api<ChargeConcept[]>("/treasury/concepts"),
  });

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
          missing.map((id) => api<Student>(`/students/${id}`).catch(() => null)),
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
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Error"),
  });

  const value = (s: Scholarship) =>
    s.pct != null ? `${s.pct}%` : formatMoney(s.fixed_amount);
  const appliesTo = (s: Scholarship) =>
    s.concept_id
      ? (concepts?.find((c) => c.id === s.concept_id)?.name ?? "Concepto")
      : "Colegiatura";

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
        <div className="flex items-center gap-3">
          {!canAuthorize && (
            <p className="text-xs text-muted-foreground">
              Tus becas se envían como solicitud; Dirección o Administración las
              autorizan.
            </p>
          )}
          <Button className="font-bold" onClick={() => setCreateOpen(true)}>
            <Plus className="size-4" /> Crear beca
          </Button>
        </div>
      </div>

      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Alumno</TableHead>
              <TableHead>Beca</TableHead>
              <TableHead>Valor</TableHead>
              <TableHead>Aplica a</TableHead>
              <TableHead>Tolerancia</TableHead>
              <TableHead>Vigencia</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead className="text-right">Acción</TableHead>
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
                <TableCell className="text-muted-foreground">{appliesTo(s)}</TableCell>
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
                <TableCell colSpan={8} className="py-10 text-center text-muted-foreground">
                  Sin becas en este filtro
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {createOpen && (
        <BecaCreateDialog
          concepts={concepts ?? []}
          direct={!!canAuthorize}
          onClose={() => setCreateOpen(false)}
          onDone={() => {
            queryClient.invalidateQueries({ queryKey: ["scholarships"] });
            queryClient.invalidateQueries({ queryKey: queryKeys.scholarshipReport });
          }}
        />
      )}
    </div>
  );
}

// --- Crear beca -----------------------------------------------------------------------

function BecaCreateDialog({
  concepts,
  direct,
  onClose,
  onDone,
}: {
  concepts: ChargeConcept[];
  direct: boolean; // admin/superuser: the beca activates immediately
  onClose: () => void;
  onDone: () => void;
}) {
  const [query, setQuery] = useState("");
  const [student, setStudent] = useState<Student | null>(null);
  const [form, setForm] = useState({
    name: "",
    pct: "",
    concept_id: COLEGIATURA,
    valid_from: todayISO(),
    valid_to: "",
    tolerance_days: "0",
  });

  const { data: results } = useQuery({
    queryKey: queryKeys.students(query),
    queryFn: () => api<Student[]>(`/students?q=${encodeURIComponent(query)}&limit=8`),
    enabled: query.trim().length >= 2 && !student,
  });

  // Concept-scoped becas target the inscripción tabulador; "Colegiatura" keeps
  // the classic career-wide colegiatura beca.
  const inscripcionConcepts = concepts.filter(
    (c) => c.is_active && (c.kind === "inscripcion" || c.kind === "reinscripcion"),
  );

  const save = useMutation({
    mutationFn: () =>
      api<Scholarship>("/treasury/scholarships", {
        method: "POST",
        body: JSON.stringify({
          student_id: student!.id,
          name: form.name,
          pct: Number(form.pct),
          concept_id: form.concept_id === COLEGIATURA ? null : form.concept_id,
          valid_from: form.valid_from,
          valid_to: form.valid_to || null,
          tolerance_days: Number(form.tolerance_days) || 0,
        }),
      }),
    onSuccess: () => {
      toast.success(
        direct
          ? "Beca creada y aplicada a los cargos pendientes"
          : "Solicitud de beca enviada — requiere autorización",
      );
      onDone();
      onClose();
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  const pct = Number(form.pct);
  const pctInvalid = form.pct !== "" && (pct <= 0 || pct > 100);

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Crear beca</DialogTitle>
          <DialogDescription>
            {direct
              ? "La beca se activa de inmediato y se aplica a los cargos pendientes del concepto."
              : "La beca queda como solicitud hasta que Dirección o Administración la autorice."}
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!student || pctInvalid) return;
            save.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label>Alumno</Label>
            {student ? (
              <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm">
                <span className="font-semibold">{student.full_name}</span>
                <span className="flex items-center gap-2 text-muted-foreground">
                  <span data-numeric>{student.enrollment_number}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setStudent(null)}
                  >
                    Cambiar
                  </Button>
                </span>
              </div>
            ) : (
              <div className="relative">
                <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="pl-9"
                  placeholder="Buscar por nombre o matrícula…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
                {query.trim().length >= 2 && (
                  <div className="absolute inset-x-0 top-full z-20 mt-1 divide-y overflow-hidden rounded-md border bg-popover shadow-lg">
                    {results?.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-muted/50"
                        onClick={() => {
                          setStudent(s);
                          setQuery("");
                        }}
                      >
                        <span className="font-semibold">{s.full_name}</span>
                        <span data-numeric className="text-muted-foreground">
                          {s.enrollment_number}
                        </span>
                      </button>
                    ))}
                    {results && results.length === 0 && (
                      <p className="px-3 py-3 text-sm text-muted-foreground">
                        Sin resultados
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="grid gap-2">
            <Label htmlFor="nb-name">Nombre de la beca</Label>
            <Input
              id="nb-name"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Beca convenio 2026"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="nb-pct">Porcentaje (%)</Label>
              <Input
                id="nb-pct"
                type="number"
                required
                min={0.1}
                max={100}
                step="0.1"
                value={form.pct}
                onChange={(e) => setForm({ ...form, pct: e.target.value })}
              />
              {pctInvalid && (
                <p className="text-xs text-destructive">
                  El porcentaje debe ser mayor a 0 y no exceder 100%.
                </p>
              )}
            </div>
            <div className="grid gap-2">
              <Label>Concepto al que aplica</Label>
              <Select
                value={form.concept_id}
                onValueChange={(v) => setForm({ ...form, concept_id: v })}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={COLEGIATURA}>
                    Colegiatura (toda la carrera)
                  </SelectItem>
                  {inscripcionConcepts.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name} · {formatMoney(c.amount)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="nb-from">Vigente desde</Label>
              <Input
                id="nb-from"
                type="date"
                required
                value={form.valid_from}
                onChange={(e) => setForm({ ...form, valid_from: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="nb-to">Hasta (opcional)</Label>
              <Input
                id="nb-to"
                type="date"
                value={form.valid_to}
                onChange={(e) => setForm({ ...form, valid_to: e.target.value })}
              />
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="nb-tol">Tolerancia de pago (días)</Label>
            <Input
              id="nb-tol"
              type="number"
              min={0}
              value={form.tolerance_days}
              onChange={(e) => setForm({ ...form, tolerance_days: e.target.value })}
            />
            <p className="text-xs text-muted-foreground">
              Días tras el vencimiento para pagar sin generar recargo.
            </p>
          </div>
          <DialogFooter>
            <Button
              type="submit"
              className="font-bold"
              disabled={save.isPending || !student || pctInvalid}
            >
              {save.isPending
                ? "Guardando…"
                : direct
                  ? "Crear y aplicar"
                  : "Enviar solicitud"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
