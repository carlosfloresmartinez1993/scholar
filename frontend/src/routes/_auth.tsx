import { useEffect, useState } from "react";
import {
  createFileRoute,
  Link,
  Outlet,
  redirect,
  useNavigate,
} from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Home,
  BarChart3,
  GraduationCap,
  Users,
  Landmark,
  CalendarRange,
  ClipboardCheck,
  NotebookPen,
  Banknote,
  UserCog,
  ScrollText,
  LogOut,
  ChevronDown,
  KeyRound,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { CommandPalette } from "@/components/command-palette";
import { ApiError } from "@/api/client";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { UserPublic } from "@/api/types";
import { ROLE_LABELS } from "@/lib/format";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/_auth")({
  beforeLoad: async ({ context }) => {
    const cached = context.queryClient.getQueryData(queryKeys.me);
    if (cached) return;
    try {
      await context.queryClient.fetchQuery({
        queryKey: queryKeys.me,
        queryFn: () => api<UserPublic>("/auth/me"),
      });
    } catch {
      throw redirect({ to: "/login" });
    }
  },
  component: AppShell,
});

const NAV_GROUPS = [
  {
    label: "Escolar",
    items: [
      { to: "/", label: "Inicio", icon: Home },
      { to: "/alumnos", label: "Alumnos", icon: GraduationCap },
      { to: "/programas", label: "Programas", icon: Landmark },
      { to: "/grupos", label: "Grupos", icon: Users },
    ],
  },
  {
    label: "Académico",
    items: [
      { to: "/calificaciones", label: "Calificaciones", icon: NotebookPen },
      { to: "/asistencias", label: "Asistencias", icon: ClipboardCheck },
    ],
  },
  {
    label: "Gestión",
    items: [
      { to: "/tesoreria", label: "Tesorería", icon: Banknote },
      {
        to: "/reportes",
        label: "Reportes",
        icon: BarChart3,
        roles: ["admin_sistema", "direccion", "tesoreria"],
      },
      { to: "/periodos", label: "Periodos", icon: CalendarRange },
    ],
  },
] as const;

const NAV_ADMIN = {
  label: "Administración",
  items: [
    { to: "/usuarios", label: "Usuarios", icon: UserCog },
    { to: "/auditoria", label: "Auditoría", icon: ScrollText },
  ],
} as const;

function AppShell() {
  const { data: me } = useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api<UserPublic>("/auth/me"),
  });
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("sidebar-collapsed") === "1",
  );
  useEffect(() => {
    localStorage.setItem("sidebar-collapsed", collapsed ? "1" : "0");
  }, [collapsed]);

  const isAdmin = me?.is_superuser || me?.role === "admin_sistema";
  const groups = isAdmin ? [...NAV_GROUPS, NAV_ADMIN] : [...NAV_GROUPS];

  return (
    <div className="flex min-h-svh">
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-20 flex flex-col border-r bg-sidebar transition-[width] duration-200",
          collapsed ? "w-16" : "w-60",
        )}
      >
        <div className="flex h-20 flex-col items-center justify-center gap-1 border-b px-3">
          <img
            src="/logo-inue.svg"
            alt="INUE"
            className={collapsed ? "h-8 max-w-full" : "h-10 max-w-full"}
          />
          {!collapsed && (
            <span className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
              INUE Escolar
            </span>
          )}
        </div>
        <nav className="flex-1 space-y-5 overflow-y-auto p-3">
          {groups.map((group) => (
            <div key={group.label} className="space-y-1">
              {!collapsed && (
                <p className="px-3 pb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground/70">
                  {group.label}
                </p>
              )}
              {group.items
                .filter(
                  (item) =>
                    !("roles" in item) ||
                    me?.is_superuser ||
                    (me?.role &&
                      (item.roles as readonly string[]).includes(me.role)),
                )
                .map(({ to, label, icon: Icon }) => (
                <Link
                  key={to}
                  to={to}
                  activeOptions={{ exact: to === "/" }}
                  title={collapsed ? label : undefined}
                  className={cn(
                    "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-semibold text-muted-foreground transition-colors hover:bg-muted hover:text-foreground data-[status=active]:bg-primary data-[status=active]:font-bold data-[status=active]:text-primary-foreground data-[status=active]:hover:bg-primary",
                    collapsed && "justify-center px-2",
                  )}
                >
                  <Icon className="size-4 shrink-0" />
                  {!collapsed && label}
                </Link>
              ))}
            </div>
          ))}
        </nav>
        <div className="border-t p-3">
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            title={collapsed ? "Expandir menú" : "Contraer menú"}
            className={cn(
              "flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm font-semibold text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
              collapsed && "justify-center px-2",
            )}
          >
            {collapsed ? (
              <PanelLeftOpen className="size-4 shrink-0" />
            ) : (
              <>
                <PanelLeftClose className="size-4 shrink-0" /> Contraer
              </>
            )}
          </button>
        </div>
      </aside>

      <div
        className={cn(
          "flex flex-1 flex-col transition-[padding] duration-200",
          collapsed ? "pl-16" : "pl-60",
        )}
      >
        <Header me={me} />
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
      <CommandPalette />
    </div>
  );
}

function Header({ me }: { me?: UserPublic }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [passwordOpen, setPasswordOpen] = useState(false);

  async function logout() {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {
      // ignore
    }
    queryClient.clear();
    navigate({ to: "/login" });
  }

  return (
    <header className="sticky top-0 z-10 flex h-16 items-center justify-between gap-4 border-b bg-background/95 px-6 backdrop-blur">
      <span className="text-sm font-semibold text-muted-foreground">
        Sistema de administración escolar
      </span>

      <div className="flex items-center gap-4">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="gap-2 font-semibold">
              {me?.full_name || me?.email || "Usuario"}
              <ChevronDown className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel className="truncate">
              {me?.email}
              {me && (
                <span className="block text-xs font-normal text-muted-foreground">
                  {me.is_superuser ? "Superusuario" : ROLE_LABELS[me.role]}
                </span>
              )}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => setPasswordOpen(true)}>
              <KeyRound className="size-4" />
              Cambiar contraseña
            </DropdownMenuItem>
            <DropdownMenuItem onClick={logout} variant="destructive">
              <LogOut className="size-4" />
              Cerrar sesión
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <PasswordDialog open={passwordOpen} onOpenChange={setPasswordOpen} />
    </header>
  );
}

function PasswordDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== confirm) {
      toast.error("La nueva contraseña y su confirmación no coinciden");
      return;
    }
    setSaving(true);
    try {
      await api("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      toast.success("Contraseña actualizada");
      setCurrent("");
      setNext("");
      setConfirm("");
      onOpenChange(false);
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.message : "Error al cambiar la contraseña",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Cambiar contraseña</DialogTitle>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={submit}>
          <div className="grid gap-2">
            <Label htmlFor="pw-current">Contraseña actual</Label>
            <Input
              id="pw-current"
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="pw-new">Nueva contraseña</Label>
            <Input
              id="pw-new"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="pw-confirm">Confirmar nueva contraseña</Label>
            <Input
              id="pw-confirm"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="submit" className="font-bold" disabled={saving}>
              {saving ? "Guardando…" : "Guardar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

