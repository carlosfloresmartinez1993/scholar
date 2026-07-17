import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Banknote,
  CalendarRange,
  ClipboardList,
  FileClock,
  FileSignature,
  FileText,
  GraduationCap,
  HandCoins,
  Landmark,
  TrendingDown,
  TrendingUp,
  UserCog,
  UserRoundX,
  Users,
  type LucideIcon,
} from "lucide-react";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  AuditEntry,
  DashboardStats,
  EducationLevel,
  EnrollmentPoint,
  MetricDelta,
} from "@/api/types";
import { formatDate, formatMoney, relativeTime } from "@/lib/format";
import { usePersistedState } from "@/lib/use-persisted-state";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

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

const PERIODS = [
  { days: 1, label: "Día" },
  { days: 7, label: "Semana" },
  { days: 14, label: "Quincena" },
  { days: 30, label: "Mes" },
] as const;

function InicioPage() {
  const [days, setDays] = usePersistedState<number>(
    "dashboard-days",
    30,
    (v): v is number => typeof v === "number" && [1, 7, 14, 30].includes(v),
  );

  const {
    data: stats,
    isLoading,
    isError: statsError,
    refetch: refetchStats,
  } = useQuery({
    queryKey: queryKeys.dashboardStats(days),
    queryFn: () => api<DashboardStats>(`/dashboard/stats?days=${days}`),
  });
  const { data: series, isError: seriesError } = useQuery({
    queryKey: queryKeys.enrollmentsSeries(days),
    queryFn: () =>
      api<EnrollmentPoint[]>(`/dashboard/enrollments-series?days=${days}`),
  });
  const { data: activity, isError: activityError } = useQuery({
    queryKey: queryKeys.dashboardActivity(days),
    queryFn: () => api<AuditEntry[]>(`/dashboard/activity?days=${days}&limit=10`),
  });

  const sumCurrent = (m?: Record<EducationLevel, MetricDelta>) =>
    m ? LEVEL_ORDER.reduce((s, l) => s + (m[l]?.current ?? 0), 0) : 0;
  const sumPrevious = (m?: Record<EducationLevel, MetricDelta>) =>
    m ? LEVEL_ORDER.reduce((s, l) => s + (m[l]?.previous ?? 0), 0) : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
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
        <div
          className="inline-flex rounded-md border bg-muted p-0.5"
          role="group"
          aria-label="Periodo"
        >
          {PERIODS.map((p) => (
            <button
              key={p.days}
              type="button"
              aria-pressed={days === p.days}
              onClick={() => setDays(p.days)}
              className={cn(
                "rounded-sm px-3 py-1.5 text-sm font-semibold transition-colors",
                days === p.days
                  ? "bg-background text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {statsError ? (
        <Card className="rounded-md border">
          <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
            <p className="text-sm text-muted-foreground">
              No se pudieron cargar los indicadores del panel.
            </p>
            <Button variant="outline" onClick={() => refetchStats()}>
              Reintentar
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
      <HeroCollected
        collected={stats?.period.collected}
        days={days}
        loading={isLoading}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          icon={GraduationCap}
          label="Alumnos activos"
          value={sumCurrent(stats?.students)}
          previous={sumPrevious(stats?.students)}
          compareLabel="vs. ciclo anterior"
          loading={isLoading}
        />
        <KpiCard
          icon={Users}
          label="Grupos activos"
          value={sumCurrent(stats?.groups)}
          previous={sumPrevious(stats?.groups)}
          compareLabel="vs. ciclo anterior"
          loading={isLoading}
        />
        <KpiCard
          icon={ClipboardList}
          label="Inscripciones nuevas"
          value={stats?.period.new_enrollments.current ?? 0}
          previous={stats?.period.new_enrollments.previous ?? 0}
          compareLabel="vs. periodo anterior"
          loading={isLoading}
        />
        <KpiCard
          icon={Banknote}
          label="Cartera vencida"
          money
          invertDelta
          value={stats?.cartera_vencida.current ?? 0}
          previous={stats?.cartera_vencida.previous ?? 0}
          compareLabel="vs. ciclo anterior"
          loading={isLoading}
        />
      </div>
        </>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="rounded-md border">
          <CardContent className="space-y-4 p-5">
            <div>
              <h2 className="text-base font-bold">Inscripciones nuevas</h2>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                Por día del periodo
              </p>
            </div>
            {seriesError ? (
              <p className="flex h-44 items-center justify-center text-sm text-muted-foreground">
                No se pudo cargar la gráfica.
              </p>
            ) : (
              <EnrollmentsChart data={series} />
            )}
          </CardContent>
        </Card>
        <Card className="rounded-md border">
          <CardContent className="space-y-3 p-5">
            <div>
              <h2 className="text-base font-bold">Actividad reciente</h2>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                Últimos movimientos del sistema
              </p>
            </div>
            {activityError ? (
              <p className="flex h-44 items-center justify-center text-sm text-muted-foreground">
                No se pudo cargar la actividad.
              </p>
            ) : (
              <ActivityList entries={activity} />
            )}
          </CardContent>
        </Card>
      </div>

      {!statsError && <WorkQueue stats={stats} loading={isLoading} />}
    </div>
  );
}

// --- Hero: cobrado del periodo (the one standout yellow section) --------------

function HeroCollected({
  collected,
  days,
  loading,
}: {
  collected?: MetricDelta;
  days: number;
  loading?: boolean;
}) {
  const pct = collected ? deltaPct(collected.current, collected.previous) : null;
  const up = (pct ?? 0) > 0;
  const flat = pct !== null && Math.abs(pct) < 0.05;
  const periodLabel =
    PERIODS.find((p) => p.days === days)?.label.toLowerCase() ?? "periodo";
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-md bg-primary p-6 text-primary-foreground">
      <div>
        <p className="text-xs font-bold uppercase tracking-wide text-primary-foreground/70">
          Cobrado del periodo ({periodLabel})
        </p>
        {loading || !collected ? (
          <Skeleton className="mt-2 h-10 w-48 bg-black/10" />
        ) : (
          <div className="mt-1 flex flex-wrap items-baseline gap-3">
            <p className="text-4xl font-extrabold tabular-nums">
              {formatMoney(collected.current)}
            </p>
            {pct !== null && !flat && (
              <span
                className={cn(
                  "inline-flex items-center gap-1 text-sm font-bold",
                  up ? "text-emerald-800" : "text-red-800",
                )}
              >
                {up ? (
                  <TrendingUp className="size-4" />
                ) : (
                  <TrendingDown className="size-4" />
                )}
                {up ? "+" : ""}
                {pct.toFixed(1)}%
              </span>
            )}
            <span className="text-xs font-semibold text-primary-foreground/60">
              vs. periodo anterior ({formatMoney(collected.previous)})
            </span>
          </div>
        )}
      </div>
      <Button
        asChild
        className="bg-black font-bold text-white hover:bg-black/85"
      >
        <Link to="/tesoreria">Ir a Caja</Link>
      </Button>
    </div>
  );
}

// --- KPI cards -----------------------------------------------------------------

function deltaPct(current: number, previous: number): number | null {
  if (previous === 0) return current === 0 ? 0 : null; // null = sin base comparable
  return ((current - previous) / previous) * 100;
}

function DeltaChip({
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
    return <span className="text-xs font-semibold text-muted-foreground">nuevo</span>;
  const up = pct > 0;
  const flat = Math.abs(pct) < 0.05;
  // For cartera vencida a drop is good, so invert the color meaning.
  const good = flat ? true : invert ? !up : up;
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs font-bold",
        flat
          ? "bg-muted text-muted-foreground"
          : good
            ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400"
            : "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-400",
      )}
    >
      {!flat && <Icon className="size-3.5" />}
      {up ? "+" : ""}
      {pct.toFixed(1)}%
    </span>
  );
}

function KpiCard({
  icon: Icon,
  label,
  value,
  previous,
  compareLabel,
  loading,
  money,
  invertDelta,
}: {
  icon: LucideIcon;
  label: string;
  value: number;
  previous: number;
  compareLabel: string;
  loading?: boolean;
  money?: boolean;
  invertDelta?: boolean;
}) {
  return (
    <Card className="rounded-md border">
      <CardContent className="flex flex-col gap-3 p-5">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-md bg-muted">
            <Icon className="size-4 text-muted-foreground" />
          </div>
          <span className="text-xs font-bold uppercase tracking-wide text-muted-foreground">
            {label}
          </span>
        </div>
        {loading ? (
          <Skeleton className="h-9 w-24" />
        ) : (
          <>
            <p
              className={cn(
                "text-3xl font-extrabold tabular-nums",
                money &&
                  (invertDelta && value > 0
                    ? "text-red-600 dark:text-red-400"
                    : "text-emerald-600 dark:text-emerald-400"),
              )}
            >
              {money ? formatMoney(value) : value}
            </p>
            <div className="flex items-center gap-2">
              <DeltaChip current={value} previous={previous} invert={invertDelta} />
              <span className="text-xs text-muted-foreground">{compareLabel}</span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// --- Chart: hand-rolled SVG bars (no chart lib) --------------------------------

function EnrollmentsChart({ data }: { data?: EnrollmentPoint[] }) {
  if (!data) return <Skeleton className="h-44 w-full" />;
  const total = data.reduce((s, d) => s + d.count, 0);
  if (total === 0) {
    return (
      <p className="flex h-44 items-center justify-center text-sm text-muted-foreground">
        Sin inscripciones en el periodo
      </p>
    );
  }
  const W = 600;
  const H = 190;
  const padLeft = 30;
  const padBottom = 22;
  const padTop = 8;
  const plotW = W - padLeft - 4;
  const plotH = H - padBottom - padTop;
  const max = Math.max(...data.map((d) => d.count), 1);
  const step = plotW / data.length;
  const barW = Math.min(step * 0.55, 26);
  const y = (v: number) => padTop + plotH - (v / max) * plotH;
  // x labels: first, middle and last day (enough to orient the eye)
  const labelIdx = new Set(
    data.length <= 2
      ? data.map((_, i) => i)
      : [0, Math.floor((data.length - 1) / 2), data.length - 1],
  );
  return (
    <div>
    <svg viewBox={`0 0 ${W} ${H}`} className="h-44 w-full" aria-hidden>
      {/* gridlines: max and half, plus baseline */}
      {[max, max / 2].map((v) => (
        <g key={v}>
          <line
            x1={padLeft}
            x2={W - 4}
            y1={y(v)}
            y2={y(v)}
            className="stroke-border"
            strokeDasharray="3 3"
            strokeWidth={1}
          />
          <text
            x={padLeft - 6}
            y={y(v) + 3.5}
            textAnchor="end"
            className="fill-muted-foreground tabular-nums"
            fontSize={10}
          >
            {Number.isInteger(v) ? v : v.toFixed(1)}
          </text>
        </g>
      ))}
      <line
        x1={padLeft}
        x2={W - 4}
        y1={padTop + plotH}
        y2={padTop + plotH}
        className="stroke-border"
        strokeWidth={1}
      />
      {data.map((d, i) => {
        const x = padLeft + i * step + (step - barW) / 2;
        const barH = Math.max((d.count / max) * plotH, d.count > 0 ? 2 : 0);
        return (
          <g key={d.date}>
            {/* invisible full-height hit area so hover works on short bars */}
            <rect
              x={padLeft + i * step}
              y={padTop}
              width={step}
              height={plotH}
              fill="transparent"
            >
              <title>{`${formatDate(d.date)}: ${d.count}`}</title>
            </rect>
            {d.count > 0 && (
              <rect
                x={x}
                y={padTop + plotH - barH}
                width={barW}
                height={barH}
                rx={1}
                className="fill-foreground/75"
              >
                <title>{`${formatDate(d.date)}: ${d.count}`}</title>
              </rect>
            )}
            {labelIdx.has(i) && (
              <text
                x={padLeft + i * step + step / 2}
                y={H - 6}
                textAnchor="middle"
                className="fill-muted-foreground"
                fontSize={10}
              >
                {formatDate(d.date)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
    {/* accessible representation of the chart for screen readers */}
    <ul className="sr-only" aria-label="Inscripciones nuevas por día">
      {data.map((d) => (
        <li key={d.date}>{`${formatDate(d.date)}: ${d.count}`}</li>
      ))}
    </ul>
    </div>
  );
}

// --- Actividad reciente ---------------------------------------------------------

const ENTITY_LABELS: Record<string, string> = {
  student: "Alumno",
  user: "Usuario",
  group: "Grupo",
  term: "Ciclo",
  payment: "Pago",
  charge: "Cargo",
  charges: "Cargos",
  group_charges: "Cargos de grupo",
  charge_concept: "Concepto de cobro",
  payment_plan: "Plan de pagos",
  scholarship: "Beca",
  program: "Programa",
  campus: "Plantel",
  institution: "Institución",
  rvoe: "RVOE",
  plan_version: "Plan de estudios",
  plan_subject: "Materia",
  group_subject: "Materia de grupo",
  plan_enrollment: "Inscripción a plan",
  group_enrollment: "Inscripción a grupo",
  bulk_intake: "Alta masiva",
  cycle: "Promoción de ciclo",
  acta: "Acta",
  grade: "Calificación",
  attendance: "Asistencia",
  justification: "Justificante",
  document: "Documento",
  doc_requirement: "Requisito",
  student_document: "Documento de alumno",
  teacher_document: "Documento docente",
  teacher_profile: "Expediente docente",
  evaluation_component: "Componente de evaluación",
  regulation: "Reglamento",
  fiscal_profile: "Perfil fiscal",
  degree: "Título",
  late_fees: "Recargos",
};

const VERB_LABELS: Record<string, string> = {
  created: "registrado",
  updated: "actualizado",
  cancelled: "cancelado",
  deleted: "eliminado",
  deactivated: "desactivado",
  registered: "registrado",
  generated: "generado",
  issued: "emitido",
  uploaded: "subido",
  reviewed: "revisado",
  signed: "firmada",
  captured: "capturada",
  imported: "importado",
  synced: "sincronizado",
  authorized: "autorizada",
  rejected: "rechazada",
  requested: "solicitada",
  accepted: "aceptado",
  published: "publicado",
  applied: "aplicados",
  promoted: "ejecutada",
  completed: "completada",
  saved: "guardado",
  recorded: "registrada",
  upserted: "actualizado",
  status_changed: "cambio de estatus",
  prerequisites_set: "seriación actualizada",
  evidence_uploaded: "evidencia subida",
  risk_alerts_sent: "alertas enviadas",
  profile_updated: "perfil actualizado",
  recovery_email_requested: "correo de recuperación solicitado",
  recovery_email_verified: "correo de recuperación verificado",
};

const GOOD_VERBS = new Set([
  "created", "registered", "generated", "issued", "authorized", "signed",
  "published", "completed", "recovery_email_verified",
]);
const BAD_VERBS = new Set(["cancelled", "deleted", "deactivated", "rejected"]);

const ENTITY_ICONS: Record<string, LucideIcon> = {
  student: GraduationCap,
  user: UserCog,
  group: Users,
  term: CalendarRange,
  payment: Banknote,
  charge: Banknote,
  charges: Banknote,
  group_charges: Banknote,
  charge_concept: Banknote,
  payment_plan: Banknote,
  scholarship: HandCoins,
  program: Landmark,
  plan_version: Landmark,
  document: FileText,
  student_document: FileText,
  teacher_document: FileText,
  doc_requirement: FileText,
  acta: FileSignature,
  justification: FileClock,
  plan_enrollment: ClipboardList,
  group_enrollment: ClipboardList,
  bulk_intake: ClipboardList,
};

function actionParts(action: string): { entity: string; verb: string } {
  const dot = action.indexOf(".");
  if (dot === -1) return { entity: action, verb: "" };
  return { entity: action.slice(0, dot), verb: action.slice(dot + 1) };
}

function describeAction(entry: AuditEntry): string {
  const { entity, verb } = actionParts(entry.action);
  const entityLabel = ENTITY_LABELS[entity] ?? entity;
  const verbLabel = VERB_LABELS[verb] ?? verb.replaceAll("_", " ");
  return `${entityLabel} ${verbLabel}`.trim();
}

function ActivityList({ entries }: { entries?: AuditEntry[] }) {
  if (!entries) return <Skeleton className="h-44 w-full" />;
  if (entries.length === 0) {
    return (
      <p className="flex h-44 items-center justify-center text-sm text-muted-foreground">
        Sin actividad en el periodo
      </p>
    );
  }
  return (
    <ul className="divide-y">
      {entries.map((e) => {
        const { entity, verb } = actionParts(e.action);
        const Icon = ENTITY_ICONS[entity] ?? Activity;
        const pill = GOOD_VERBS.has(verb)
          ? "good"
          : BAD_VERBS.has(verb)
            ? "bad"
            : null;
        return (
          <li key={e.id} className="flex items-center gap-3 py-2.5">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted">
              <Icon className="size-4 text-muted-foreground" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">
                {describeAction(e)}
                {e.detail && (
                  <span className="font-normal text-muted-foreground">
                    {" "}
                    · {e.detail}
                  </span>
                )}
              </span>
              <span className="block truncate text-xs text-muted-foreground">
                {e.actor}
              </span>
            </span>
            {pill && (
              <span
                className={cn(
                  "shrink-0 rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase",
                  pill === "good"
                    ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400"
                    : "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-400",
                )}
              >
                {pill === "good" ? "Alta" : "Baja"}
              </span>
            )}
            <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
              {relativeTime(e.created_at)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// --- Pendientes (work queue) ----------------------------------------------------

function WorkQueue({
  stats,
  loading,
}: {
  stats?: DashboardStats;
  loading?: boolean;
}) {
  return (
    <div className="space-y-3">
      <h2 className="text-lg font-bold">Pendientes</h2>
      {loading ? (
        <Skeleton className="h-20 w-full rounded-md" />
      ) : !stats ? (
        <p className="rounded-md border border-destructive/40 bg-card p-5 text-sm text-destructive">
          No se pudieron cargar los pendientes.
        </p>
      ) : (
        (() => {
          const p = stats.pending;
          const items = [
            {
              to: "/asistencias",
              count: p?.justifications_pending ?? 0,
              label: "Justificantes por revisar",
              icon: FileClock,
            },
            {
              to: "/calificaciones",
              count: p?.unsigned_actas ?? 0,
              label: "Actas sin firmar",
              icon: FileSignature,
            },
            {
              to: "/grupos",
              count: p?.groups_without_teacher ?? 0,
              label: "Materias sin docente asignado",
              icon: UserRoundX,
            },
          ].filter((i) => i.count > 0);
          return items.length === 0 ? (
            <p className="rounded-md border bg-card p-5 text-sm text-muted-foreground">
              Todo al día — no hay pendientes.
            </p>
          ) : (
            <div className="grid gap-4 lg:grid-cols-3">
              {items.map((i) => (
                <WorkItem key={i.to} {...i} />
              ))}
            </div>
          );
        })()
      )}
    </div>
  );
}

function WorkItem({
  to,
  count,
  label,
  icon: Icon,
}: {
  to: string;
  count: number;
  label: string;
  icon: LucideIcon;
}) {
  return (
    <Link
      to={to}
      className="flex items-center gap-4 rounded-md border bg-card p-5 transition-colors hover:bg-muted/50"
    >
      <div className="flex size-10 items-center justify-center rounded-md bg-muted">
        <Icon className="size-5 text-muted-foreground" />
      </div>
      <div>
        <p className="text-2xl font-bold" data-numeric>
          {count}
        </p>
        <p className="text-sm text-muted-foreground">{label}</p>
      </div>
    </Link>
  );
}
