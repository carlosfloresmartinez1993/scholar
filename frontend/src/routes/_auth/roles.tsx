// Roles (Etapa 1): which screens each role may open, and new roles. A check saves at
// once; the server applies it from the next request.
import { Fragment, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { cn } from "@/lib/utils";
import { queryKeys } from "@/api/query-keys";
import type { PermissionItem, RoleItem } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

export const Route = createFileRoute("/_auth/roles")({
  component: RolesPage,
});

const ADMIN = "admin_sistema";
const NONE = "__none__";

type Level = "none" | "view" | "edit";

function levelOf(role: RoleItem, item: PermissionItem): Level {
  if (role.code === ADMIN) return item.edit_code ? "edit" : "view";
  if (item.edit_code && role.permissions.includes(item.edit_code)) return "edit";
  return role.permissions.includes(item.code) ? "view" : "none";
}

const LEVEL_STYLE: Record<Level, string> = {
  none: "text-muted-foreground",
  view: "",
  edit: "font-semibold",
};
const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

function RolesPage() {
  const queryClient = useQueryClient();
  const { data: roles, isLoading } = useQuery({
    queryKey: ["roles"],
    queryFn: () => api<RoleItem[]>("/roles"),
  });
  const { data: catalog } = useQuery({
    queryKey: ["role-permissions"],
    queryFn: () => api<PermissionItem[]>("/roles/permissions"),
  });
  const [editing, setEditing] = useState<RoleItem | "new" | null>(null);

  // a screen: none / ver / ver y editar; an action: on / off
  const toggle = useMutation({
    mutationFn: ({ role, item, level }: { role: RoleItem; item: PermissionItem; level: Level }) => {
      const rest = role.permissions.filter((p) => p !== item.code && p !== item.edit_code);
      const added =
        level === "edit" && item.edit_code
          ? [item.code, item.edit_code]
          : level === "none"
            ? []
            : [item.code];
      return api<RoleItem>(`/roles/${role.id}`, {
        method: "PATCH",
        body: JSON.stringify({ permissions: [...rest, ...added] }),
      });
    },
    onSuccess: (role) => {
      queryClient.invalidateQueries({ queryKey: ["roles"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.me });
      toast.success(`Permisos de «${role.name}» guardados`);
    },
    onError: (e) => toast.error(errorText(e, "No se pudo guardar")),
  });

  const remove = useMutation({
    mutationFn: (role: RoleItem) => api(`/roles/${role.id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["roles"] });
      toast.success("Rol borrado");
    },
    onError: (e) => toast.error(errorText(e, "No se pudo borrar")),
  });

  const sections = [...new Set((catalog ?? []).map((p) => p.section))];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl">Roles</h1>
        <Button className="font-bold" onClick={() => setEditing("new")}>
          <Plus className="size-4" /> Nuevo rol
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        Para cada pantalla elige si el rol no tiene acceso, solo la puede <b>ver</b>, o la puede{" "}
        <b>ver y editar</b>. Las acciones especiales (corregir kárdex, cambio de RVOE, actas…) se
        dan aparte. Se guarda al elegir y aplica desde la siguiente acción del usuario: el servidor
        revisa el permiso en cada consulta, no solo el menú. El administrador de sistema siempre
        tiene todo. Los cambios quedan en Auditoría.
      </p>

      {isLoading || !roles || !catalog ? (
        <Skeleton className="h-64 w-full rounded-md" />
      ) : (
        <div className="overflow-x-auto rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-48">Pantalla o acción</TableHead>
                {roles.map((r) => (
                  <TableHead key={r.id} className="min-w-36 text-center align-top">
                    <div className="flex flex-col items-center gap-1 py-1">
                      <span className="font-bold text-foreground">{r.name}</span>
                      <span className="text-xs font-normal text-muted-foreground">
                        {r.users_count} usuario{r.users_count === 1 ? "" : "s"}
                      </span>
                      <div className="flex flex-wrap justify-center gap-1">
                        {!r.is_active && <Badge variant="destructive">Inactivo</Badge>}
                        {r.own_subjects_only && <Badge variant="secondary">Solo sus materias</Badge>}
                      </div>
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Editar ${r.name}`}
                          onClick={() => setEditing(r)}
                        >
                          <Pencil className="size-4" />
                        </Button>
                        {!r.is_system && (
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Borrar ${r.name}`}
                            disabled={remove.isPending}
                            onClick={() => {
                              if (window.confirm(`¿Borrar el rol «${r.name}»?`)) remove.mutate(r);
                            }}
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        )}
                      </div>
                    </div>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sections.map((section) => (
                <Fragment key={section}>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableCell
                      colSpan={roles.length + 1}
                      className="text-xs font-bold uppercase tracking-wider text-muted-foreground"
                    >
                      {section}
                    </TableCell>
                  </TableRow>
                  {catalog
                    .filter((p) => p.section === section)
                    .map((p) => (
                      <TableRow key={p.code}>
                        <TableCell className="font-semibold">{p.label}</TableCell>
                        {roles.map((r) => (
                          <TableCell key={r.id} className="text-center">
                            {p.edit_code ? (
                              <Select
                                value={levelOf(r, p)}
                                disabled={r.code === ADMIN || toggle.isPending}
                                onValueChange={(v) => toggle.mutate({ role: r, item: p, level: v as Level })}
                              >
                                <SelectTrigger
                                  aria-label={`${p.label} para ${r.name}`}
                                  className={cn("mx-auto h-8 w-32 text-xs", LEVEL_STYLE[levelOf(r, p)])}
                                >
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="none">Sin acceso</SelectItem>
                                  <SelectItem value="view">Ver</SelectItem>
                                  <SelectItem value="edit">Ver y editar</SelectItem>
                                </SelectContent>
                              </Select>
                            ) : (
                              <Checkbox
                                aria-label={`${p.label} para ${r.name}`}
                                checked={levelOf(r, p) !== "none"}
                                disabled={r.code === ADMIN || toggle.isPending}
                                onCheckedChange={(v) =>
                                  toggle.mutate({ role: r, item: p, level: v === true ? "view" : "none" })
                                }
                              />
                            )}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {editing && roles && (
        <RoleDialog
          role={editing === "new" ? null : editing}
          roles={roles}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function RoleDialog({
  role,
  roles,
  onClose,
}: {
  role: RoleItem | null;
  roles: RoleItem[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [own, setOwn] = useState(role?.own_subjects_only ?? false);
  const [active, setActive] = useState(role?.is_active ?? true);
  const [copyFrom, setCopyFrom] = useState(NONE);
  const admin = role?.code === ADMIN;
  const save = useMutation({
    mutationFn: () =>
      role
        ? api<RoleItem>(`/roles/${role.id}`, {
            method: "PATCH",
            body: JSON.stringify({
              name: name.trim(),
              description: description.trim(),
              ...(admin ? {} : { own_subjects_only: own, is_active: active }),
            }),
          })
        : api<RoleItem>("/roles", {
            method: "POST",
            body: JSON.stringify({
              name: name.trim(),
              description: description.trim(),
              own_subjects_only: own,
              permissions:
                copyFrom === NONE ? [] : (roles.find((r) => r.id === copyFrom)?.permissions ?? []),
            }),
          }),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ["roles"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.me });
      toast.success(role ? "Rol actualizado" : `Rol «${r.name}» creado. Marca sus pantallas en la tabla.`);
      onClose();
    },
    onError: (e) => toast.error(errorText(e, "No se pudo guardar")),
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{role ? `Editar «${role.name}»` : "Nuevo rol"}</DialogTitle>
          <DialogDescription>
            {role
              ? "Nombre, descripción y opciones del rol. Sus pantallas se marcan en la tabla."
              : "Un rol nuevo empieza sin pantallas (o con las de otro rol que elijas copiar)."}
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="role-name">Nombre</Label>
            <Input
              id="role-name"
              required
              minLength={2}
              maxLength={128}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Caja"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="role-desc">Descripción (opcional)</Label>
            <Input
              id="role-desc"
              maxLength={512}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          {!role && (
            <div className="grid gap-2">
              <Label>Empezar con las pantallas de</Label>
              <Select value={copyFrom} onValueChange={setCopyFrom}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>Ninguno (vacío)</SelectItem>
                  {roles
                    .filter((r) => r.code !== ADMIN)
                    .map((r) => (
                      <SelectItem key={r.id} value={r.id}>
                        {r.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {!admin && (
            <label className="flex items-start gap-2 text-sm">
              <Checkbox checked={own} onCheckedChange={(v) => setOwn(v === true)} className="mt-0.5" />
              <span>
                <span className="font-medium">Solo sus materias</span>
                <span className="block text-muted-foreground">
                  Como un docente: en Calificaciones y Asistencias solo ve los grupos y materias que
                  tiene asignados, y no entra a datos generales de alumnos.
                </span>
              </span>
            </label>
          )}
          {role && !admin && (
            <label className="flex items-center gap-2 text-sm font-medium">
              <Checkbox checked={active} onCheckedChange={(v) => setActive(v === true)} />
              Rol activo (inactivo: sus usuarios no ven ninguna pantalla)
            </label>
          )}
          <DialogFooter>
            <Button type="submit" className="font-bold" disabled={save.isPending || name.trim().length < 2}>
              {save.isPending ? "Guardando…" : role ? "Guardar" : "Crear rol"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
