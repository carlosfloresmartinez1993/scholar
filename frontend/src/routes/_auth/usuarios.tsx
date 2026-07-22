import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Pencil } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { Campus, UserPublic, UserRole } from "@/api/types";
import { formatDateTime, ROLE_LABELS } from "@/lib/format";
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

export const Route = createFileRoute("/_auth/usuarios")({
  component: UsuariosPage,
});

interface UserForm {
  email: string;
  full_name: string;
  password: string;
  role: UserRole;
  is_active: boolean;
  is_superuser: boolean;
  campuses: string[];
}

const emptyForm: UserForm = {
  email: "",
  full_name: "",
  password: "",
  role: "docente",
  is_active: true,
  is_superuser: false,
  campuses: [],
};

/** admin_sistema and superusers implicitly see every campus — no membership. */
function isAllCampusForm(form: UserForm): boolean {
  return form.is_superuser || form.role === "admin_sistema";
}

function UsuariosPage() {
  const queryClient = useQueryClient();
  const { data: users, isLoading } = useQuery({
    queryKey: queryKeys.users(),
    queryFn: () => api<UserPublic[]>("/users"),
  });
  const { data: campuses } = useQuery({
    queryKey: queryKeys.campuses,
    queryFn: () => api<Campus[]>("/catalog/campuses"),
  });

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<UserPublic | null>(null);
  const [form, setForm] = useState<UserForm>(emptyForm);

  // A campus-scoped role with zero planteles would be a self-inflicted lockout.
  const campusSelectionInvalid =
    !isAllCampusForm(form) && form.campuses.length === 0;

  const save = useMutation({
    mutationFn: () => {
      // all-campus roles carry no membership rows; everyone else gets their set
      const campuses = isAllCampusForm(form) ? [] : form.campuses;
      if (editing) {
        const body = JSON.stringify({
          email: form.email,
          full_name: form.full_name,
          role: form.role,
          is_active: form.is_active,
          campuses,
          ...(form.password ? { password: form.password } : {}),
        });
        return api<UserPublic>(`/users/${editing.id}`, {
          method: "PATCH",
          body,
        });
      }
      const body = JSON.stringify({
        email: form.email,
        full_name: form.full_name,
        password: form.password,
        role: form.role,
        is_active: form.is_active,
        is_superuser: form.is_superuser,
        campuses,
      });
      return api<UserPublic>("/users", { method: "POST", body });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      toast.success(editing ? "Usuario actualizado" : "Usuario creado");
      setOpen(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl">Usuarios</h1>
        <Button
          className="font-bold"
          onClick={() => {
            setEditing(null);
            setForm(emptyForm);
            setOpen(true);
          }}
        >
          <Plus className="size-4" /> Nuevo usuario
        </Button>
      </div>

      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nombre</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Rol</TableHead>
              <TableHead>Activo</TableHead>
              <TableHead>Creado</TableHead>
              <TableHead className="w-16" />
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
            {users?.map((u) => (
              <TableRow key={u.id}>
                <TableCell className="font-semibold">{u.full_name}</TableCell>
                <TableCell>{u.email}</TableCell>
                <TableCell>
                  <Badge variant={u.is_superuser ? "default" : "secondary"}>
                    {u.is_superuser ? "Superusuario" : ROLE_LABELS[u.role]}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge variant={u.is_active ? "outline" : "destructive"}>
                    {u.is_active ? "Activo" : "Inactivo"}
                  </Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(u.created_at)}
                </TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Editar"
                    onClick={() => {
                      setEditing(u);
                      setForm({
                        email: u.email,
                        full_name: u.full_name,
                        password: "",
                        role: u.role,
                        is_active: u.is_active,
                        is_superuser: u.is_superuser,
                        campuses: u.all_campuses ? [] : (u.campuses ?? []),
                      });
                      setOpen(true);
                    }}
                  >
                    <Pencil className="size-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editing ? "Editar usuario" : "Nuevo usuario"}
            </DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (campusSelectionInvalid) {
                toast.error("Selecciona al menos un plantel");
                return;
              }
              save.mutate();
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="full_name">Nombre completo</Label>
              <Input
                id="full_name"
                required
                value={form.full_name}
                onChange={(e) =>
                  setForm({ ...form, full_name: e.target.value })
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                required
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="role">Rol</Label>
              <Select
                value={form.role}
                onValueChange={(v) => setForm({ ...form, role: v as UserRole })}
              >
                <SelectTrigger id="role" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(ROLE_LABELS) as UserRole[]).map((r) => (
                    <SelectItem key={r} value={r}>
                      {ROLE_LABELS[r]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="password">
                {editing ? "Nueva contraseña (opcional)" : "Contraseña"}
              </Label>
              <Input
                id="password"
                type="password"
                required={!editing}
                minLength={8}
                value={form.password}
                onChange={(e) =>
                  setForm({ ...form, password: e.target.value })
                }
              />
            </div>
            {!isAllCampusForm(form) && (
              <div className="grid gap-2">
                <Label>Planteles</Label>
                <p className="text-xs text-muted-foreground">
                  Planteles a los que el usuario tendrá acceso.
                </p>
                <div className="grid gap-1.5 rounded-md border p-3">
                  {campuses?.length ? (
                    campuses.map((c) => (
                      <label
                        key={c.id}
                        className="flex items-center gap-2 text-sm font-medium"
                      >
                        <Checkbox
                          checked={form.campuses.includes(c.id)}
                          onCheckedChange={(v) =>
                            setForm({
                              ...form,
                              campuses:
                                v === true
                                  ? [...form.campuses, c.id]
                                  : form.campuses.filter((id) => id !== c.id),
                            })
                          }
                        />
                        {c.name}
                      </label>
                    ))
                  ) : (
                    <span className="text-sm text-muted-foreground">
                      Sin planteles
                    </span>
                  )}
                </div>
              </div>
            )}
            <label className="flex items-center gap-2 text-sm font-medium">
              <Checkbox
                checked={form.is_active}
                onCheckedChange={(v) =>
                  setForm({ ...form, is_active: v === true })
                }
              />
              Usuario activo
            </label>
            {!editing && (
              <label className="flex items-center gap-2 text-sm font-medium">
                <Checkbox
                  checked={form.is_superuser}
                  onCheckedChange={(v) =>
                    setForm({ ...form, is_superuser: v === true })
                  }
                />
                Superusuario
              </label>
            )}
            <DialogFooter>
              <Button
                type="submit"
                className="font-bold"
                disabled={save.isPending || campusSelectionInvalid}
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
