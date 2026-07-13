import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Banknote,
  BadgeCheck,
  GraduationCap,
  Users,
  type LucideIcon,
} from "lucide-react";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { AgingRow, Group, Rvoe, Student, Term } from "@/api/types";
import { formatMoney } from "@/lib/format";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/_auth/")({
  component: InicioPage,
});

function InicioPage() {
  const { data: students, isLoading: loadingStudents } = useQuery({
    queryKey: queryKeys.students(),
    queryFn: () => api<Student[]>("/students?limit=1000"),
  });
  const { data: terms } = useQuery({
    queryKey: queryKeys.terms,
    queryFn: () => api<Term[]>("/catalog/terms"),
  });
  const openTerm = terms?.find((t) => t.is_open);
  const { data: groups, isLoading: loadingGroups } = useQuery({
    queryKey: queryKeys.groups(openTerm?.id),
    queryFn: () => api<Group[]>(`/catalog/groups?term_id=${openTerm!.id}`),
    enabled: !!openTerm,
  });
  const { data: rvoes, isLoading: loadingRvoes } = useQuery({
    queryKey: queryKeys.rvoes(),
    queryFn: () => api<Rvoe[]>("/catalog/rvoes"),
  });
  // Requires rol de tesorería — swallow the 403 for other roles.
  const { data: aging, isError: agingError } = useQuery({
    queryKey: queryKeys.aging,
    queryFn: () => api<AgingRow[]>("/treasury/reports/aging"),
  });

  const activeStudents = students?.filter((s) => s.status === "activo").length;
  const vigentes = rvoes?.filter((r) => r.status === "vigente").length;
  const overdue = aging?.reduce((sum, r) => sum + r.balance, 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl">Inicio</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {openTerm
            ? `Ciclo en curso: ${openTerm.name}`
            : "No hay un ciclo abierto — cree uno en «Periodos»."}
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={GraduationCap}
          label="Alumnos activos"
          value={activeStudents}
          loading={loadingStudents}
          to="/alumnos"
          linkLabel="Ver alumnos"
        />
        <StatCard
          icon={Users}
          label={openTerm ? `Grupos de ${openTerm.name}` : "Grupos del ciclo"}
          value={openTerm ? groups?.length : 0}
          loading={!!openTerm && loadingGroups}
          to="/grupos"
          linkLabel="Ver grupos"
        />
        <StatCard
          icon={BadgeCheck}
          label="RVOEs vigentes"
          value={vigentes}
          loading={loadingRvoes}
          to="/programas"
          linkLabel="Ver programas"
        />
        <StatCard
          icon={Banknote}
          label="Cartera vencida"
          value={agingError ? undefined : overdue}
          money
          loading={!aging && !agingError}
          to="/tesoreria"
          linkLabel="Ver tesorería"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <QuickLink
          to="/calificaciones"
          title="Captura de calificaciones"
          description="Registre parciales y ordinarios por grupo y materia, y genere actas con folio."
        />
        <QuickLink
          to="/asistencias"
          title="Pase de lista"
          description="Registre la asistencia por sesión y revise el derecho a examen por materia."
        />
        <QuickLink
          to="/tesoreria"
          title="Cobranza"
          description="Consulte el reporte de cobranza, la cartera vencida y aplique recargos."
        />
      </div>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  loading,
  money,
  to,
  linkLabel,
}: {
  icon: LucideIcon;
  label: string;
  value?: number;
  loading?: boolean;
  money?: boolean;
  to: string;
  linkLabel: string;
}) {
  return (
    <Card className="rounded-2xl">
      <CardContent className="flex flex-col gap-3 p-5">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl bg-primary/15">
            <Icon className="size-5 text-foreground/70" />
          </div>
          <span className="text-sm font-semibold text-muted-foreground">
            {label}
          </span>
        </div>
        {loading ? (
          <Skeleton className="h-9 w-24" />
        ) : (
          <p className="text-3xl font-bold" data-numeric>
            {value == null ? "—" : money ? formatMoney(value) : value}
          </p>
        )}
        <Button variant="outline" size="sm" className="w-fit" asChild>
          <Link to={to}>{linkLabel}</Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function QuickLink({
  to,
  title,
  description,
}: {
  to: string;
  title: string;
  description: string;
}) {
  return (
    <Link
      to={to}
      className="rounded-2xl border bg-card p-5 transition-colors hover:bg-muted/50"
    >
      <h2 className="text-lg font-bold">{title}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{description}</p>
    </Link>
  );
}
