// Grupos: editar o borrar un grupo, e importar los grupos de un ciclo desde el
// calendario (con plan y cuatrimestre confirmados en una vista previa).
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarDays, Pencil, Trash2 } from "lucide-react";
import { api, ApiError } from "@/api/client";
import type { CalendarGroupsPreview, Group } from "@/api/types";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

// --- Editar / borrar ------------------------------------------------------------------

export function GroupAdminButtons({ group, onDeleted }: { group: Group; onDeleted: () => void }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({
    mutationFn: () => api(`/catalog/groups/${group.id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] });
      toast.success(`Grupo ${group.code} eliminado`);
      onDeleted();
    },
    onError: (e) => {
      setConfirming(false);
      toast.error(errorText(e, "No se pudo eliminar"), { duration: 8000 });
    },
  });
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
        <Pencil className="size-4" /> Editar grupo
      </Button>
      <Button
        variant={confirming ? "destructive" : "outline"}
        size="sm"
        disabled={remove.isPending}
        onClick={() => (confirming ? remove.mutate() : setConfirming(true))}
      >
        <Trash2 className="size-4" /> {confirming ? "Confirmar: eliminar grupo" : "Eliminar grupo"}
      </Button>
      {editing && <EditGroupDialog group={group} onClose={() => setEditing(false)} />}
    </div>
  );
}

function EditGroupDialog({ group, onClose }: { group: Group; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [code, setCode] = useState(group.code);
  const [period, setPeriod] = useState(String(group.period_number));
  const [active, setActive] = useState(group.is_active);
  const save = useMutation({
    mutationFn: () =>
      api<Group>(`/catalog/groups/${group.id}`, {
        method: "PATCH",
        body: JSON.stringify({ code: code.trim(), period_number: Number(period), is_active: active }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] });
      queryClient.invalidateQueries({ queryKey: ["group-subjects", group.id] });
      toast.success("Grupo actualizado");
      onClose();
    },
    onError: (e) => toast.error(errorText(e, "No se pudo guardar"), { duration: 8000 }),
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Editar grupo {group.code}</DialogTitle>
          <DialogDescription>
            El cuatrimestre solo cambia mientras el grupo no tenga alumnos; al cambiarlo toma las
            materias de ese cuatrimestre. Un grupo con alumnos se desactiva en lugar de borrarse.
            {group.calendar_group_id ? " Viene del calendario: el calendario no se modifica." : ""}
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
              <Label htmlFor="eg-code">Código</Label>
              <Input
                id="eg-code"
                required
                maxLength={32}
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="eg-period">Cuatrimestre</Label>
              <Input
                id="eg-period"
                type="number"
                min={1}
                max={20}
                required
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm font-medium">
            <Checkbox checked={active} onCheckedChange={(v) => setActive(v === true)} />
            Grupo activo
          </label>
          <DialogFooter>
            <Button type="submit" className="font-bold" disabled={save.isPending || !code.trim()}>
              {save.isPending ? "Guardando…" : "Guardar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// --- Importar del calendario ----------------------------------------------------------

interface Choice {
  selected: boolean;
  code: string;
  plan: string;
  period: string;
}

export function ImportCalendarGroupsButton({ termId }: { termId: string | null }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outline" disabled={!termId} onClick={() => setOpen(true)}>
        <CalendarDays className="size-4" /> Importar del calendario
      </Button>
      {open && termId && <ImportGroupsDialog termId={termId} onClose={() => setOpen(false)} />}
    </>
  );
}

const STATUS_LABEL: Record<string, string> = {
  nuevo: "Nuevo",
  importado: "Ya importado",
  sin_carrera: "Falta la carrera",
  sin_plan: "Falta el plan",
};

function ImportGroupsDialog({ termId, onClose }: { termId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const { data, isLoading, error } = useQuery({
    queryKey: ["calendar-groups-preview", termId],
    queryFn: async () => {
      const preview = await api<CalendarGroupsPreview>(`/catalog/terms/${termId}/calendar-groups/preview`);
      setChoices(
        Object.fromEntries(
          preview.groups
            .filter((g) => g.status === "nuevo")
            .map((g) => [
              g.calendar_group_id,
              {
                selected: true,
                code: g.code,
                plan: g.plans[0]?.plan_version_id ?? "",
                period: g.suggested_period ? String(g.suggested_period) : "",
              },
            ]),
        ),
      );
      return preview;
    },
    gcTime: 0,
    retry: false,
  });
  const set = (id: string, patch: Partial<Choice>) =>
    setChoices((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  const chosen = Object.entries(choices).filter(([, c]) => c.selected);
  const incomplete = chosen.some(([, c]) => !c.plan || !c.period || !c.code.trim());

  const run = useMutation({
    mutationFn: () =>
      api<{ created: string[]; skipped: { code: string; reason: string }[] }>(
        `/catalog/terms/${termId}/calendar-groups/import`,
        {
          method: "POST",
          body: JSON.stringify({
            items: chosen.map(([id, c]) => ({
              calendar_group_id: id,
              plan_version_id: c.plan,
              period_number: Number(c.period),
              code: c.code.trim(),
            })),
          }),
        },
      ),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ["groups"] });
      toast.success(`${r.created.length} grupos importados`);
      for (const s of r.skipped) toast.warning(`${s.code}: ${s.reason}`, { duration: 10000 });
      onClose();
    },
    onError: (e) => toast.error(errorText(e, "No se pudo importar")),
  });

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>Importar grupos del calendario {data ? `· ${data.term_name}` : ""}</DialogTitle>
          <DialogDescription>
            Confirma el plan y el cuatrimestre de cada grupo (el cuatrimestre se sugiere por la
            clave). Al crearse toma las materias de su cuatrimestre. Después cada grupo se puede
            editar o borrar aquí, y el calendario no cambia.
          </DialogDescription>
        </DialogHeader>
        {isLoading && <Skeleton className="h-40 w-full" />}
        {error && (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {error instanceof ApiError && error.status < 500
              ? error.message
              : "Integración con el calendario no disponible"}
          </p>
        )}
        {data && (
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8" />
                  <TableHead>Grupo</TableHead>
                  <TableHead>Carrera</TableHead>
                  <TableHead className="w-80">Plan en Scholar</TableHead>
                  <TableHead className="w-28">Cuatri.</TableHead>
                  <TableHead>Estado</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.groups.map((g) => {
                  const c = choices[g.calendar_group_id];
                  return (
                    <TableRow key={g.calendar_group_id} className={c ? undefined : "text-muted-foreground"}>
                      <TableCell>
                        <Checkbox
                          aria-label={`Importar ${g.code}`}
                          disabled={!c}
                          checked={!!c?.selected}
                          onCheckedChange={(v) => set(g.calendar_group_id, { selected: v === true })}
                        />
                      </TableCell>
                      <TableCell>
                        {c ? (
                          <Input
                            className="h-8 w-28"
                            aria-label={`Código de ${g.code}`}
                            value={c.code}
                            onChange={(e) => set(g.calendar_group_id, { code: e.target.value })}
                          />
                        ) : (
                          <span data-numeric>{g.code}</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {g.program ?? "—"}
                        {g.campus && <span className="block text-xs text-muted-foreground">{g.campus}</span>}
                      </TableCell>
                      <TableCell>
                        {c ? (
                          <Select value={c.plan} onValueChange={(v) => set(g.calendar_group_id, { plan: v })}>
                            <SelectTrigger className="h-8 w-full" aria-label={`Plan de ${g.code}`}>
                              <SelectValue placeholder="Elige el plan" />
                            </SelectTrigger>
                            <SelectContent>
                              {g.plans.map((p) => (
                                <SelectItem key={p.plan_version_id} value={p.plan_version_id}>
                                  {p.label}
                                  {p.operable ? "" : " (RVOE no vigente)"}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        {c ? (
                          <Input
                            className="h-8 w-20"
                            type="number"
                            min={1}
                            max={20}
                            placeholder="?"
                            aria-label={`Cuatrimestre de ${g.code}`}
                            value={c.period}
                            onChange={(e) => set(g.calendar_group_id, { period: e.target.value })}
                          />
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <Badge variant={g.status === "nuevo" ? "default" : "outline"}>
                          {STATUS_LABEL[g.status] ?? g.status}
                        </Badge>
                        {g.reason && <span className="block text-xs">{g.reason}</span>}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
        <DialogFooter>
          {incomplete && (
            <span className="mr-auto self-center text-sm text-destructive">
              Falta el plan o el cuatrimestre en algún grupo marcado
            </span>
          )}
          <Button
            className="font-bold"
            disabled={run.isPending || chosen.length === 0 || incomplete}
            onClick={() => run.mutate()}
          >
            {run.isPending ? "Importando…" : `Importar ${chosen.length} grupos`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
