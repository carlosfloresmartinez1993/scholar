import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Banknote,
  GraduationCap,
  HandCoins,
  TrendingDown,
  TrendingUp,
  Users,
  type LucideIcon,
} from "lucide-react";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { DashboardStats, EducationLevel, MetricDelta } from "@/api/types";
import { formatMoney, LEVEL_LABELS } from "@/lib/format";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/_auth/")({
  component: InicioPage,
});

const LEVEL_ORDER: EducationLevel[] = [
  "tsu",
  "licenciatura",
  "especialidad",
  "maestria",
  "doctorado",
];

function InicioPage() {
  const { data: stats, isLoading } = useQuery({
    queryKey: queryKeys.dashboardStats,
    queryFn: () => api<DashboardStats>("/dashboard/stats"),
  });

  const sumCurrent = (m?: Record<EducationLevel, MetricDelta>) =>
    m ? LEVEL_ORDER.reduce((s, l) => s + (m[l]?.current ?? 0), 0) : 0;
  const sumPrevious = (m?: Record<EducationLevel, MetricDelta>) =>
    m ? LEVEL_ORDER.reduce((s, l) => s + (m[l]?.previous ?? 0), 0) : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl">Inicio</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {stats?.term
            ? `Ciclo en curso: ${stats.term.name}`
            : "No hay un ciclo abierto — cree uno en «Periodos»."}
          {stats?.prev_term && (
            <span> · comparado con {stats.prev_term.name}</span>
          )}
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <LevelStatCard
          icon={GraduationCap}
          label="Alumnos activos"
          metric={stats?.students}
          total={sumCurrent(stats?.students)}
          previous={sumPrevious(stats?.students)}
          loading={isLoading}
          to="/alumnos"
          linkLabel="Ver alumnos"
        />
        <LevelStatCard
          icon={Users}
          label="Grupos activos"
          metric={stats?.groups}
          total={sumCurrent(stats?.groups)}
          previous={sumPrevious(stats?.groups)}
          loading={isLoading}
          to="/grupos"
          linkLabel="Ver grupos"
        />
        <LevelStatCard
          icon={HandCoins}
          label="Alumnos becados"
          metric={stats?.scholars}
          total={sumCurrent(stats?.scholars)}
          previous={sumPrevious(stats?.scholars)}
          loading={isLoading}
          to="/tesoreria"
          linkLabel="Ver becas"
        />
        <LevelStatCard
          icon={Banknote}
          label="Cartera vencida"
          money
          invertDelta
          total={stats?.cartera_vencida.current ?? 0}
          previous={stats?.cartera_vencida.previous ?? 0}
          loading={isLoading}
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
          title="Caja y cobranza"
          description="Cobre a los alumnos, imprima recibos, facture y revise la cartera vencida."
        />
      </div>
    </div>
  );
}

function deltaPct(current: number, previous: number): number | null {
  if (previous === 0) return current === 0 ? 0 : null; // null = sin base comparable
  return ((current - previous) / previous) * 100;
}

function DeltaBadge({
  current,
  previous,
  invert,
}: {
  current: number;
  previous: number;
  invert?: boolean;
}) {
  const pct = deltaPct(current, previous);
  if (pct === null)
    return <span className="text-xs text-muted-foreground">nuevo</span>;
  const up = pct > 0;
  const flat = Math.abs(pct) < 0.05;
  // For cartera vencida a drop is good, so invert the color meaning.
  const good = flat ? true : invert ? !up : up;
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-semibold ${
        flat
          ? "text-muted-foreground"
          : good
            ? "text-emerald-600 dark:text-emerald-400"
            : "text-red-600 dark:text-red-400"
      }`}
    >
      {!flat && <Icon className="size-3.5" />}
      {up ? "+" : ""}
      {pct.toFixed(1)}%
    </span>
  );
}

function LevelStatCard({
  icon: Icon,
  label,
  metric,
  total,
  previous,
  loading,
  money,
  invertDelta,
  to,
  linkLabel,
}: {
  icon: LucideIcon;
  label: string;
  metric?: Record<EducationLevel, MetricDelta>;
  total: number;
  previous: number;
  loading?: boolean;
  money?: boolean;
  invertDelta?: boolean;
  to: string;
  linkLabel: string;
}) {
  const levelRows = metric
    ? LEVEL_ORDER.filter(
        (l) => (metric[l]?.current ?? 0) > 0 || (metric[l]?.previous ?? 0) > 0,
      )
    : [];
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
          <div className="flex items-end justify-between gap-2">
            <p className="text-3xl font-bold" data-numeric>
              {money ? formatMoney(total) : total}
            </p>
            <DeltaBadge current={total} previous={previous} invert={invertDelta} />
          </div>
        )}
        {!loading && !money && (
          <div className="space-y-0.5">
            {levelRows.map((l) => (
              <div
                key={l}
                className="flex justify-between text-xs text-muted-foreground"
              >
                <span>{LEVEL_LABELS[l]}</span>
                <span data-numeric className="font-semibold">
                  {metric![l].current}
                </span>
              </div>
            ))}
            {levelRows.length === 0 && (
              <p className="text-xs text-muted-foreground">Sin datos del ciclo</p>
            )}
          </div>
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
