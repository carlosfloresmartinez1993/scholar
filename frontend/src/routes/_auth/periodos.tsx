import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Pencil, CalendarDays, RefreshCw } from "lucide-react";
import {
  api,
  ApiError,
  getCalendarTerms,
  importCalendarTerm,
  syncTermCalendar,
} from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { CalendarTerm, PeriodType, Term } from "@/api/types";
import { formatDate, PERIOD_TYPE_LABELS } from "@/lib/format";
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

export const Route = createFileRoute("/_auth/periodos")({
  component: PeriodosPage,
});

interface TermForm {
  name: string;
  period_type: PeriodType;
  start_date: string;
  end_date: string;
  is_open: boolean;
  grade_capture_open: boolean;
}

const emptyForm: TermForm = {
  name: "",
  period_type: "cuatrimestral",
  start_date: "",
  end_date: "",
  is_open: true,
  grade_capture_open: false,
};

function PeriodosPage() {
  const queryClient = useQueryClient();
  const { data: terms, isLoading } = useQuery({
    queryKey: queryKeys.terms,
    queryFn: () => api<Term[]>("/catalog/terms"),
  });

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Term | null>(null);
  const [form, setForm] = useState<TermForm>(emptyForm);

  const save = useMutation({
    mutationFn: (payload: TermForm) => {
      const body = JSON.stringify(payload);
      return editing
        ? api<Term>(`/catalog/terms/${editing.id}`, { method: "PATCH", body })
        : api<Term>("/catalog/terms", { method: "POST", body });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.terms });
      toast.success(editing ? "Ciclo actualizado" : "Ciclo creado");
      setOpen(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  const toggle = useMutation({
    mutationFn: ({
      term,
      field,
      value,
    }: {
      term: Term;
      field: "is_open" | "grade_capture_open";
      value: boolean;
    }) =>
      api<Term>(`/catalog/terms/${term.id}`, {
        method: "PATCH",
        body: JSON.stringify({ [field]: value }),
      }),
    onSuccess: (_, { field, value }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.terms });
      toast.success(
        field === "is_open"
          ? value
            ? "Ciclo abierto"
            : "Ciclo cerrado"
          : value
            ? "Captura de calificaciones abierta"
            : "Captura de calificaciones cerrada",
      );
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al actualizar"),
  });

  const sync = useMutation({
    mutationFn: (term: Term) => syncTermCalendar(term.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.terms });
      toast.success("Fechas sincronizadas con el calendario");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al sincronizar"),
  });

  function openCreate() {
    setEditing(null);
    setForm(emptyForm);
    setOpen(true);
  }

  function openEdit(t: Term) {
    setEditing(t);
    setForm({
      name: t.name,
      period_type: t.period_type,
      start_date: t.start_date,
      end_date: t.end_date,
      is_open: t.is_open,
      grade_capture_open: t.grade_capture_open,
    });
    setOpen(true);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl">Periodos</h1>
        <div className="flex items-center gap-2">
          <ImportTermsButton />
          <Button onClick={openCreate} className="font-bold">
            <Plus className="size-4" /> Nuevo ciclo
          </Button>
        </div>
      </div>

      <div className="rounded-2xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nombre</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>Inicio</TableHead>
              <TableHead>Fin</TableHead>
              <TableHead>Abierto</TableHead>
              <TableHead>Captura de calificaciones</TableHead>
              <TableHead className="w-24" />
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
            {terms?.map((t) => (
              <TableRow key={t.id}>
                <TableCell className="font-semibold">
                  <span className="flex items-center gap-2">
                    {t.name}
                    {t.calendar_term_id && (
                      <Badge variant="secondary" className="gap-1">
                        <CalendarDays className="size-3" /> Calendario
                      </Badge>
                    )}
                  </span>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {PERIOD_TYPE_LABELS[t.period_type]}
                </TableCell>
                <TableCell>{formatDate(t.start_date)}</TableCell>
                <TableCell>{formatDate(t.end_date)}</TableCell>
                <TableCell>
                  <label className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={t.is_open}
                      disabled={toggle.isPending}
                      onCheckedChange={(v) =>
                        toggle.mutate({
                          term: t,
                          field: "is_open",
                          value: v === true,
                        })
                      }
                    />
                    {t.is_open ? "Abierto" : "Cerrado"}
                  </label>
                </TableCell>
                <TableCell>
                  <label className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={t.grade_capture_open}
                      disabled={toggle.isPending}
                      onCheckedChange={(v) =>
                        toggle.mutate({
                          term: t,
                          field: "grade_capture_open",
                          value: v === true,
                        })
                      }
                    />
                    {t.grade_capture_open ? "Abierta" : "Cerrada"}
                  </label>
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  {t.calendar_term_id && (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => sync.mutate(t)}
                      disabled={sync.isPending}
                      aria-label="Sincronizar fechas"
                      title="Sincronizar fechas con el calendario"
                    >
                      <RefreshCw className="size-4" />
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => openEdit(t)}
                    aria-label="Editar"
                  >
                    <Pencil className="size-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {terms && terms.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="py-10 text-center text-muted-foreground"
                >
                  <div className="flex flex-col items-center gap-3">
                    <span>Sin ciclos registrados</span>
                    <Button onClick={openCreate} className="font-bold">
                      <Plus className="size-4" /> Nuevo ciclo
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? "Editar ciclo" : "Nuevo ciclo"}</DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(form);
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="name">Nombre</Label>
              <Input
                id="name"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="2026-1 Enero – Abril"
              />
            </div>
            {!editing && (
              <div className="grid gap-2">
                <Label htmlFor="period_type">Tipo de periodo</Label>
                <Select
                  value={form.period_type}
                  onValueChange={(v) =>
                    setForm({ ...form, period_type: v as PeriodType })
                  }
                >
                  <SelectTrigger id="period_type" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(
                      Object.keys(PERIOD_TYPE_LABELS) as PeriodType[]
                    ).map((p) => (
                      <SelectItem key={p} value={p}>
                        {PERIOD_TYPE_LABELS[p]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label htmlFor="start">Fecha de inicio</Label>
                <Input
                  id="start"
                  type="date"
                  required
                  value={form.start_date}
                  onChange={(e) =>
                    setForm({ ...form, start_date: e.target.value })
                  }
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="end">Fecha de fin</Label>
                <Input
                  id="end"
                  type="date"
                  required
                  value={form.end_date}
                  onChange={(e) =>
                    setForm({ ...form, end_date: e.target.value })
                  }
                />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm font-medium">
              <Checkbox
                checked={form.is_open}
                onCheckedChange={(v) => setForm({ ...form, is_open: v === true })}
              />
              Ciclo abierto (permite inscripciones)
            </label>
            <label className="flex items-center gap-2 text-sm font-medium">
              <Checkbox
                checked={form.grade_capture_open}
                onCheckedChange={(v) =>
                  setForm({ ...form, grade_capture_open: v === true })
                }
              />
              Captura de calificaciones abierta
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

// --- Import terms from the calendar (calendar.inue.online) -------------------

function ImportTermsButton() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const {
    data: calendarTerms,
    isError,
    isLoading,
  } = useQuery({
    queryKey: queryKeys.calendarTerms,
    queryFn: getCalendarTerms,
    retry: false,
    enabled: open,
  });

  const importTerm = useMutation({
    mutationFn: (ct: CalendarTerm) => importCalendarTerm(ct.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.terms });
      queryClient.invalidateQueries({ queryKey: queryKeys.calendarTerms });
      toast.success("Periodo importado del calendario");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al importar"),
  });

  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        <CalendarDays className="size-4" /> Importar del calendario
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Importar del calendario</DialogTitle>
            <DialogDescription>
              El calendario es la fuente de las fechas del periodo; de ellas se
              calculan las fechas de colegiatura.
            </DialogDescription>
          </DialogHeader>
          {isError ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Integración con el calendario no disponible
            </p>
          ) : (
            <div className="space-y-2">
              {isLoading && <Skeleton className="h-16 w-full" />}
              {calendarTerms?.map((ct) => {
                const undated = !ct.start_date || !ct.end_date;
                return (
                  <div
                    key={ct.id}
                    className="flex items-center gap-3 rounded-xl border px-3 py-2 text-sm"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 font-semibold">
                        {ct.name}
                        <span className="text-xs font-normal text-muted-foreground">
                          {ct.code}
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {undated
                          ? "sin fechas en el calendario"
                          : `${formatDate(ct.start_date)} – ${formatDate(ct.end_date)}`}
                      </div>
                    </div>
                    <div className="ml-auto">
                      {ct.imported ? (
                        <Badge variant="secondary">Ya importado</Badge>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={undated || importTerm.isPending}
                          onClick={() => importTerm.mutate(ct)}
                        >
                          Importar
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
              {calendarTerms && calendarTerms.length === 0 && (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  El calendario no tiene periodos disponibles
                </p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
