import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { HandCoins, Landmark, Settings } from "lucide-react";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { Scholarship, UserPublic } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const AJUSTES_ROLES = ["admin_sistema", "direccion", "tesoreria"];

const ITEMS = [
  { key: "caja", label: "Caja", to: "/tesoreria", icon: Landmark },
  { key: "becas", label: "Becas", to: "/tesoreria/becas", icon: HandCoins },
  { key: "ajustes", label: "Ajustes", to: "/tesoreria/ajustes", icon: Settings },
] as const;

export type TesoreriaSection = (typeof ITEMS)[number]["key"];

/** Shared shell for /tesoreria: left sidebar (Caja · Becas · Ajustes) + content. */
export function TesoreriaLayout({
  active,
  children,
}: {
  active: TesoreriaSection;
  children: ReactNode;
}) {
  const { data: me } = useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api<UserPublic>("/auth/me"),
  });
  const canManage =
    me?.is_superuser || (me?.role !== undefined && AJUSTES_ROLES.includes(me.role));
  const { data: pendientes } = useQuery({
    queryKey: queryKeys.scholarshipsByStatus("solicitada"),
    queryFn: () => api<Scholarship[]>("/treasury/scholarships?status=solicitada"),
    enabled: !!canManage,
  });

  const items = canManage ? ITEMS : ITEMS.filter((i) => i.key === "caja");
  return (
    <div className="flex flex-col gap-6 md:flex-row">
      <nav className="flex shrink-0 gap-1 md:w-44 md:flex-col">
        {items.map(({ key, label, to, icon: Icon }) => (
          <Link
            key={key}
            to={to}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition-colors",
              key === active
                ? "bg-primary/15 text-foreground"
                : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
            )}
          >
            <Icon className="size-4" /> {label}
            {key === "becas" && pendientes && pendientes.length > 0 && (
              <Badge variant="destructive" className="ml-auto" data-numeric>
                {pendientes.length}
              </Badge>
            )}
          </Link>
        ))}
      </nav>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
