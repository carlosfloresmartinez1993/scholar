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
  ClipboardList,
  Landmark,
  CalendarRange,
  ClipboardCheck,
  NotebookPen,
  Banknote,
  UserCog,
  ScrollText,
  Award,
  LogOut,
  Building2,
  Search,
  User,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { CommandPalette } from "@/components/command-palette";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { UserPublic } from "@/api/types";
import { POSITION_LABELS, ROLE_LABELS } from "@/lib/format";
import { ALL_CAMPUSES, CampusProvider, useCampus } from "@/lib/campus-context";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export const Route = createFileRoute("/_auth")({
  beforeLoad: async ({ context }) => {
    let me = context.queryClient.getQueryData<UserPublic>(queryKeys.me);
    if (!me) {
      try {
        me = await context.queryClient.fetchQuery({
          queryKey: queryKeys.me,
          queryFn: () => api<UserPublic>("/auth/me"),
        });
      } catch {
        throw redirect({ to: "/login" });
      }
    }
    if (!me) throw redirect({ to: "/login" });
    // student accounts live in their own portal, never the staff shell
    if (me.role === "alumno") throw redirect({ to: "/portal" });
  },
  component: AppShell,
});

const NAV_GROUPS = [
  {
    label: "Escolar",
    items: [
      { to: "/", label: "Inicio", icon: Home },
      { to: "/alumnos", label: "Alumnos", icon: GraduationCap },
      {
        to: "/inscripciones", label: "Inscripciones", icon: ClipboardList,
        roles: ["admin_sistema", "direccion", "servicios_escolares"],
      },
      { to: "/programas", label: "Programas", icon: Landmark },
      { to: "/grupos", label: "Grupos", icon: Users },
      { to: "/egresados", label: "Egresados", icon: Award },
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

/** Position label shown under the name (falls back to the staff role). */
function positionLabel(me?: UserPublic): string {
  if (!me) return "";
  if (me.position) return POSITION_LABELS[me.position];
  return me.is_superuser ? "Superusuario" : ROLE_LABELS[me.role];
}

/** "María López" -> "ML"; falls back to the email's first letter. */
export function userInitials(me?: UserPublic): string {
  const name = (me?.display_name || me?.full_name || "").trim();
  if (name) {
    const parts = name.split(/\s+/);
    return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase();
  }
  return (me?.email?.[0] ?? "?").toUpperCase();
}

function AppShell() {
  const { data: me } = useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api<UserPublic>("/auth/me"),
  });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("sidebar-collapsed") === "1";
    } catch {
      return false; // private mode / storage unavailable
    }
  });
  const [paletteOpen, setPaletteOpen] = useState(false);
  useEffect(() => {
    try {
      localStorage.setItem("sidebar-collapsed", collapsed ? "1" : "0");
    } catch {
      // persistence is best-effort
    }
  }, [collapsed]);

  const isAdmin = me?.is_superuser || me?.role === "admin_sistema";
  const groups = isAdmin ? [...NAV_GROUPS, NAV_ADMIN] : [...NAV_GROUPS];

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
    <CampusProvider>
      <div className="flex min-h-svh">
        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-20 flex flex-col border-r bg-sidebar transition-[width] duration-200",
            collapsed ? "w-16" : "w-60",
          )}
        >
          <div className="relative flex h-20 items-center justify-center border-b border-sidebar-border px-3">
            <img
              src="/logo-inue-light.svg"
              alt="INUE"
              className={collapsed ? "h-9 max-w-full" : "h-14 max-w-full"}
            />
            {/* Absolutely positioned so the logo stays centered. Icon only. */}
            <button
              type="button"
              onClick={() => setCollapsed((v) => !v)}
              title={collapsed ? "Expandir menú" : "Contraer menú"}
              aria-label={collapsed ? "Expandir menú" : "Contraer menú"}
              className="absolute right-1.5 top-1.5 flex items-center justify-center rounded-md p-1.5 text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
            >
              {collapsed ? (
                <PanelLeftOpen className="size-4 shrink-0" />
              ) : (
                <PanelLeftClose className="size-4 shrink-0" />
              )}
            </button>
          </div>
          <nav className="flex-1 space-y-5 overflow-y-auto p-3">
            {groups.map((group) => (
              <div key={group.label} className="space-y-1">
                {!collapsed && (
                  <p className="px-3 pb-1 text-xs font-bold uppercase tracking-wider text-sidebar-foreground/50">
                    {group.label}
                  </p>
                )}
                {group.items
                  .filter((item) =>
                    !("roles" in item) ||
                    me?.is_superuser ||
                    (me?.role !== undefined &&
                      (item.roles as readonly string[]).includes(me.role)),
                  )
                  .map(({ to, label, icon: Icon }) => (
                  <Link
                    key={to}
                    to={to}
                    activeOptions={{ exact: to === "/" }}
                    title={collapsed ? label : undefined}
                    className={cn(
                      "flex items-center gap-3 rounded-md border-l-2 border-transparent px-3 py-2 text-sm font-semibold text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground data-[status=active]:border-sidebar-primary data-[status=active]:bg-sidebar-accent data-[status=active]:font-bold data-[status=active]:text-sidebar-primary",
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
          <div className="border-t border-sidebar-border p-3">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  title="Mi cuenta"
                  className={cn(
                    "flex w-full items-center gap-3 rounded-md bg-sidebar-accent/50 px-2 py-2 text-left transition-colors hover:bg-sidebar-accent",
                    collapsed && "justify-center bg-transparent",
                  )}
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-sidebar-primary/15 text-sm font-bold text-sidebar-primary">
                    {userInitials(me)}
                  </span>
                  {!collapsed && (
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold text-sidebar-foreground">
                        {me?.display_name || me?.full_name || me?.email || "Usuario"}
                      </span>
                      <span className="block truncate text-xs text-sidebar-foreground/60">
                        {positionLabel(me)}
                      </span>
                    </span>
                  )}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" side="top" className="w-56">
                <DropdownMenuLabel className="truncate">
                  {me?.email}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                  <Link to="/perfil">
                    <User className="size-4" />
                    Mi perfil
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem onClick={logout} variant="destructive">
                  <LogOut className="size-4" />
                  Cerrar sesión
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </aside>

        <div
          className={cn(
            "flex flex-1 flex-col transition-[padding] duration-200",
            collapsed ? "pl-16" : "pl-60",
          )}
        >
          <Header onSearch={() => setPaletteOpen(true)} />
          <main className="flex-1 p-6">
            <Outlet />
          </main>
        </div>
        <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      </div>
    </CampusProvider>
  );
}

function Header({ onSearch }: { onSearch: () => void }) {
  return (
    <header className="sticky top-0 z-10 flex h-16 items-center justify-between gap-4 border-b bg-background/95 px-6 backdrop-blur">
      <button
        type="button"
        onClick={onSearch}
        className="flex h-9 w-64 items-center gap-2 rounded-md border bg-muted/40 px-3 text-sm text-muted-foreground transition-colors hover:bg-muted sm:w-80"
        aria-label="Buscar (⌘K)"
      >
        <Search className="size-4 shrink-0" />
        <span className="flex-1 truncate text-left">Buscar…</span>
        <kbd className="rounded-sm border bg-background px-1.5 py-0.5 font-sans text-[10px] font-semibold text-muted-foreground">
          ⌘K
        </kbd>
      </button>

      <div className="flex items-center gap-4">
        <CampusSwitcher />
        <HeaderClock />
      </div>
    </header>
  );
}

function CampusSwitcher() {
  const { campusId, setCampusId, availableCampuses, canSelectAll, noCampusAccess } =
    useCampus();
  // Zero memberships: say so instead of silently hiding the switcher.
  if (noCampusAccess)
    return (
      <span className="flex items-center gap-2 rounded-md border border-dashed px-3 py-1.5 text-sm text-muted-foreground">
        <Building2 className="size-4 shrink-0" /> Sin planteles asignados
      </span>
    );
  // Nothing to switch between yet (catalog still loading).
  if (availableCampuses.length === 0) return null;
  if (availableCampuses.length === 1 && !canSelectAll) return null;
  return (
    <Select value={campusId} onValueChange={setCampusId}>
      <SelectTrigger
        className="w-52 gap-2"
        aria-label="Filtrar por plantel"
      >
        <Building2 className="size-4 shrink-0 text-muted-foreground" />
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {canSelectAll && (
          <SelectItem value={ALL_CAMPUSES}>Todos los planteles</SelectItem>
        )}
        {availableCampuses.map((c) => (
          <SelectItem key={c.id} value={c.id}>
            {c.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function HeaderClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <time
      dateTime={now.toISOString()}
      className="hidden text-right leading-tight tabular-nums md:block"
    >
      <span className="block text-sm font-semibold">
        {now.toLocaleTimeString("es-MX", { hour12: false })}
      </span>
      <span className="block text-xs text-muted-foreground">
        {now.toLocaleDateString("es-MX", {
          weekday: "short",
          day: "numeric",
          month: "short",
        })}
      </span>
    </time>
  );
}
