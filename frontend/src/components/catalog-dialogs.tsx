// Edición del catálogo desde Programas: niveles educativos, carreras y planes.
// Todo se puede editar en Scholar, con o sin el sistema de calendario.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { GraduationCap, Pencil, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { EducationLevelItem, PeriodType, PlanVersion, Program } from "@/api/types";
import { PERIOD_TYPE_LABELS } from "@/lib/format";
import { useEducationLevels } from "@/lib/levels";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
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

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

// --- Niveles educativos ------------------------------------------------------------

export function EducationLevelsButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        <GraduationCap className="size-4" /> Niveles educativos
      </Button>
      {open && <EducationLevelsDialog onClose={() => setOpen(false)} />}
    </>
  );
}

function EducationLevelsDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const { data: levels, isLoading } = useEducationLevels(true);
  const [draft, setDraft] = useState({ code: "", name: "", sort_order: "" });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["education-levels"] });

  const create = useMutation({
    mutationFn: () =>
      api("/catalog/education-levels", {
        method: "POST",
        body: JSON.stringify({
          code: draft.code.trim() || draft.name.trim(),
          name: draft.name.trim(),
          sort_order: Number(draft.sort_order || 0),
        }),
      }),
    onSuccess: () => {
      refresh();
      setDraft({ code: "", name: "", sort_order: "" });
      toast.success("Nivel agregado");
    },
    onError: (e) => toast.error(errorText(e, "No se pudo agregar")),
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<EducationLevelItem> }) =>
      api(`/catalog/education-levels/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: refresh,
    onError: (e) => toast.error(errorText(e, "No se pudo guardar")),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/catalog/education-levels/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      refresh();
      toast.success("Nivel eliminado");
    },
    onError: (e) => toast.error(errorText(e, "No se pudo eliminar"), { duration: 8000 }),
  });

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Niveles educativos</DialogTitle>
          <DialogDescription>
            Los niveles que ofrece la institución. El nombre y el orden se pueden cambiar; uno que
            ya usan carreras no se borra, se desactiva.
          </DialogDescription>
        </DialogHeader>
        {isLoading && <Skeleton className="h-40 w-full" />}
        <div className="divide-y rounded-md border">
          {levels?.map((l) => (
            <LevelRow
              key={l.id}
              level={l}
              onSave={(body) => update.mutate({ id: l.id, body })}
              onDelete={() => remove.mutate(l.id)}
            />
          ))}
        </div>
        <form
          className="grid gap-2 rounded-md border bg-muted/30 p-3 sm:grid-cols-[1fr_1fr_6rem_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <div className="grid gap-1">
            <Label htmlFor="lv-name">Nuevo nivel</Label>
            <Input
              id="lv-name"
              required
              maxLength={64}
              placeholder="Ej. Diplomado"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="lv-code">Clave (opcional)</Label>
            <Input
              id="lv-code"
              maxLength={32}
              placeholder="se toma del nombre"
              value={draft.code}
              onChange={(e) => setDraft({ ...draft, code: e.target.value })}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="lv-order">Orden</Label>
            <Input
              id="lv-order"
              type="number"
              min={0}
              value={draft.sort_order}
              onChange={(e) => setDraft({ ...draft, sort_order: e.target.value })}
            />
          </div>
          <Button type="submit" disabled={create.isPending || !draft.name.trim()}>
            <Plus className="size-4" /> Agregar
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function LevelRow({
  level,
  onSave,
  onDelete,
}: {
  level: EducationLevelItem;
  onSave: (body: Partial<EducationLevelItem>) => void;
  onDelete: () => void;
}) {
  const [name, setName] = useState(level.name);
  const [order, setOrder] = useState(String(level.sort_order));
  const dirty = name.trim() !== level.name || Number(order) !== level.sort_order;
  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
      <Input
        className="h-8 w-48"
        aria-label={`Nombre de ${level.code}`}
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <Input
        className="h-8 w-20"
        type="number"
        min={0}
        aria-label={`Orden de ${level.code}`}
        value={order}
        onChange={(e) => setOrder(e.target.value)}
      />
      <span className="text-xs text-muted-foreground" data-numeric>
        {level.code}
      </span>
      <label className="ml-auto flex items-center gap-1 text-xs">
        <Checkbox
          checked={level.is_active}
          onCheckedChange={(v) => onSave({ is_active: v === true })}
        />
        Activo
      </label>
      <Button
        size="sm"
        variant="outline"
        className="h-8"
        disabled={!dirty || !name.trim()}
        onClick={() => onSave({ name: name.trim(), sort_order: Number(order || 0) })}
      >
        Guardar
      </Button>
      <Button
        size="icon-sm"
        variant="ghost"
        aria-label={`Eliminar ${level.name}`}
        onClick={onDelete}
      >
        <Trash2 className="size-4" />
      </Button>
    </div>
  );
}

// --- Carreras ----------------------------------------------------------------------

export function EditProgramButton({ program }: { program: Program }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={`Editar ${program.name}`}
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
      >
        <Pencil className="size-4" />
      </Button>
      {open && <EditProgramDialog program={program} onClose={() => setOpen(false)} />}
    </>
  );
}

function EditProgramDialog({ program, onClose }: { program: Program; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { data: levels } = useEducationLevels();
  const [form, setForm] = useState({
    code: program.code,
    name: program.name,
    level: program.level,
    is_active: program.is_active,
  });
  const save = useMutation({
    mutationFn: () =>
      api<Program>(`/catalog/programs/${program.id}`, {
        method: "PATCH",
        body: JSON.stringify({ ...form, code: form.code.trim(), name: form.name.trim() }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.programs });
      toast.success("Carrera actualizada");
      onClose();
    },
    onError: (e) => toast.error(errorText(e, "No se pudo guardar")),
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent onClick={(e) => e.stopPropagation()}>
        <DialogHeader>
          <DialogTitle>Editar carrera</DialogTitle>
          <DialogDescription>
            {program.calendar_program_id
              ? "Viene del calendario. Lo que cambies aquí se queda en Scholar; el calendario no se modifica."
              : "Carrera capturada en Scholar."}
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-2 sm:grid-cols-[10rem_1fr] sm:gap-4">
            <div className="grid gap-2">
              <Label htmlFor="ep-code">Clave</Label>
              <Input
                id="ep-code"
                required
                maxLength={32}
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="ep-name">Nombre</Label>
              <Input
                id="ep-name"
                required
                maxLength={255}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="ep-level">Nivel</Label>
            <Select value={form.level} onValueChange={(v) => setForm({ ...form, level: v })}>
              <SelectTrigger id="ep-level" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {levels?.map((l) => (
                  <SelectItem key={l.code} value={l.code}>
                    {l.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <label className="flex items-center gap-2 text-sm font-medium">
            <Checkbox
              checked={form.is_active}
              onCheckedChange={(v) => setForm({ ...form, is_active: v === true })}
            />
            Carrera activa
          </label>
          <DialogFooter>
            <Button
              type="submit"
              className="font-bold"
              disabled={save.isPending || !form.code.trim() || !form.name.trim()}
            >
              {save.isPending ? "Guardando…" : "Guardar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// --- Planes de estudio --------------------------------------------------------------

export function EditPlanButton({ plan }: { plan: PlanVersion }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={`Editar plan ${plan.version_label}`}
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
      >
        <Pencil className="size-4" />
      </Button>
      {open && <EditPlanDialog plan={plan} onClose={() => setOpen(false)} />}
    </>
  );
}

function EditPlanDialog({ plan, onClose }: { plan: PlanVersion; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    version_label: plan.version_label,
    period_type: plan.period_type,
    periods_count: String(plan.periods_count),
    min_attendance_pct: String(plan.min_attendance_pct),
    is_active: plan.is_active,
  });
  const save = useMutation({
    mutationFn: () =>
      api<PlanVersion>(`/catalog/plan-versions/${plan.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          version_label: form.version_label.trim(),
          period_type: form.period_type,
          periods_count: Number(form.periods_count),
          min_attendance_pct: Number(form.min_attendance_pct),
          is_active: form.is_active,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plan-versions"] });
      toast.success("Plan actualizado");
      onClose();
    },
    onError: (e) => toast.error(errorText(e, "No se pudo guardar"), { duration: 8000 }),
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent onClick={(e) => e.stopPropagation()}>
        <DialogHeader>
          <DialogTitle>Editar plan de estudios</DialogTitle>
          <DialogDescription>
            El número de periodos no puede ser menor que el periodo más alto de sus materias.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="pl-label">Etiqueta de versión</Label>
              <Input
                id="pl-label"
                required
                maxLength={32}
                value={form.version_label}
                onChange={(e) => setForm({ ...form, version_label: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="pl-type">Tipo de periodo</Label>
              <Select
                value={form.period_type}
                onValueChange={(v) => setForm({ ...form, period_type: v as PeriodType })}
              >
                <SelectTrigger id="pl-type" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(PERIOD_TYPE_LABELS) as PeriodType[]).map((t) => (
                    <SelectItem key={t} value={t}>
                      {PERIOD_TYPE_LABELS[t]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="pl-count">Número de periodos</Label>
              <Input
                id="pl-count"
                type="number"
                min={1}
                max={20}
                required
                value={form.periods_count}
                onChange={(e) => setForm({ ...form, periods_count: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="pl-att">Asistencia mínima (%)</Label>
              <Input
                id="pl-att"
                type="number"
                min={0}
                max={100}
                required
                value={form.min_attendance_pct}
                onChange={(e) => setForm({ ...form, min_attendance_pct: e.target.value })}
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm font-medium">
            <Checkbox
              checked={form.is_active}
              onCheckedChange={(v) => setForm({ ...form, is_active: v === true })}
            />
            Plan activo
          </label>
          <DialogFooter>
            <Button
              type="submit"
              className="font-bold"
              disabled={save.isPending || !form.version_label.trim()}
            >
              {save.isPending ? "Guardando…" : "Guardar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ActiveBadge({ active }: { active: boolean }) {
  return (
    <Badge variant={active ? "outline" : "destructive"}>{active ? "Activo" : "Inactivo"}</Badge>
  );
}
