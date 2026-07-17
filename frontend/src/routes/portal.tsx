// Student portal (servo parity): a role=alumno account sees ITS OWN info.
// Minimal read-only layout — dark top bar, tabs, flat cards. Staff accounts
// are redirected to the admin shell; students never see the staff sidebar.
import { useState } from "react";
import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, LogOut } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  AccountStatement,
  Kardex,
  PortalGradeRow,
  PortalMe,
  StudentCalendar,
  UserPublic,
} from "@/api/types";
import {
  CHARGE_STATUS_LABELS,
  formatDate,
  formatDateTime,
  formatMoney,
  PAYMENT_METHOD_LABELS,
  SUBJECT_STATUS_LABELS,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import { StudentAvatar } from "@/components/student-avatar";
import { StudentStatusBadge } from "@/components/student-status-badge";
import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const Route = createFileRoute("/portal")({
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
    // the portal is only for students; staff go to the admin shell
    if (me.role !== "alumno") throw redirect({ to: "/" });
  },
  component: PortalPage,
});

function PortalPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState("resumen");
  const { data: me, isLoading, error: meError, refetch } = useQuery({
    queryKey: ["portal-me"],
    queryFn: () => api<PortalMe>("/portal/me"),
  });

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
    <div className="min-h-svh bg-background">
      <header className="flex h-16 items-center justify-between gap-4 bg-[#111111] px-6 text-white">
        <img src="/logo-inue-light.svg" alt="INUE" className="h-9" />
        <div className="flex items-center gap-4">
          <span className="hidden text-sm font-semibold sm:block">
            {me?.student.full_name ?? ""}
          </span>
          {me && (
            <StudentAvatar
              studentId={me.student.id}
              name={me.student.full_name}
              hasPhoto={me.student.has_photo}
              className="size-9 bg-white/10 text-sm text-white"
            />
          )}
          <button
            type="button"
            onClick={logout}
            title="Cerrar sesión"
            className="flex size-9 items-center justify-center rounded-md text-white/70 transition-colors hover:bg-white/10 hover:text-white"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 p-6">
        {meError ? (
          <Card className="rounded-md border">
            <CardContent className="flex flex-wrap items-center justify-between gap-3 p-6">
              <p className="text-sm text-destructive">
                No se pudo cargar tu información.
              </p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => refetch()}>
                  Reintentar
                </Button>
                <Button variant="outline" size="sm" onClick={logout}>
                  Cerrar sesión
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : isLoading || !me ? (
          <Skeleton className="h-32 w-full rounded-md" />
        ) : (
          <Card className="rounded-md border">
            <CardContent className="flex flex-wrap items-center gap-5 p-6">
              <StudentAvatar
                studentId={me.student.id}
                name={me.student.full_name}
                hasPhoto={me.student.has_photo}
                className="size-20 text-2xl"
              />
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="text-2xl md:text-3xl">
                    {me.student.full_name}
                  </h1>
                  <StudentStatusBadge status={me.student.status} />
                </div>
                <p className="text-sm text-muted-foreground">
                  Matrícula{" "}
                  <span data-numeric className="font-bold text-foreground">
                    {me.student.enrollment_number}
                  </span>
                </p>
                <p className="text-sm text-muted-foreground">
                  {me.plan?.program ?? "Sin plan"}
                  {me.plan?.plan_label && ` · Plan ${me.plan.plan_label}`}
                  {me.group && ` · Grupo ${me.group.code} (${me.group.term})`}
                </p>
              </div>
            </CardContent>
          </Card>
        )}

        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="resumen">Resumen</TabsTrigger>
            <TabsTrigger value="kardex">Kárdex</TabsTrigger>
            <TabsTrigger value="calificaciones">Calificaciones</TabsTrigger>
            <TabsTrigger value="cuenta">Estado de cuenta</TabsTrigger>
            <TabsTrigger value="horario">Horario</TabsTrigger>
          </TabsList>
          <TabsContent value="resumen" className="mt-4">
            {me && <ResumenTab me={me} />}
          </TabsContent>
          <TabsContent value="kardex" className="mt-4">
            <KardexTab />
          </TabsContent>
          <TabsContent value="calificaciones" className="mt-4">
            <CalificacionesTab />
          </TabsContent>
          <TabsContent value="cuenta" className="mt-4">
            <CuentaTab />
          </TabsContent>
          <TabsContent value="horario" className="mt-4">
            <HorarioTab />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2 text-sm">
      <span className="w-44 shrink-0 font-semibold text-muted-foreground">
        {label}
      </span>
      <span>{value}</span>
    </div>
  );
}

function ResumenTab({ me }: { me: PortalMe }) {
  const s = me.student;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card className="rounded-md border">
        <CardContent className="space-y-3 p-6">
          <h2 className="text-lg font-bold">Datos personales</h2>
          <Row label="CURP" value={s.curp} />
          <Row label="Email" value={s.email || "—"} />
          <Row label="Teléfono" value={s.phone || "—"} />
          <Row label="Ingreso" value={formatDate(s.created_at)} />
        </CardContent>
      </Card>
      <Card className="rounded-md border">
        <CardContent className="space-y-3 p-6">
          <h2 className="text-lg font-bold">Inscripción</h2>
          <Row label="Programa" value={me.plan?.program ?? "—"} />
          <Row label="Plan de estudios" value={me.plan?.plan_label ?? "—"} />
          <Row label="RVOE" value={me.plan?.rvoe ?? "—"} />
          <Row
            label="Grupo"
            value={
              me.group
                ? `${me.group.code} · ${me.group.term} · Periodo ${me.group.period_number}`
                : "Sin grupo activo"
            }
          />
        </CardContent>
      </Card>
    </div>
  );
}

function KardexTab() {
  const { data: kardex, isLoading, error } = useQuery({
    queryKey: ["portal-kardex"],
    queryFn: () => api<Kardex>("/portal/kardex"),
    retry: false,
  });
  if (isLoading) return <Skeleton className="h-64 w-full rounded-md" />;
  if (error || !kardex) {
    return (
      <p className="rounded-md border bg-card p-5 text-sm text-muted-foreground">
        {error instanceof ApiError && error.status === 404
          ? "Aún no tienes un plan de estudios asignado."
          : "No se pudo cargar el kárdex."}
      </p>
    );
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-8 gap-y-2 rounded-md border bg-card p-4 text-sm">
        <span>
          <span className="font-semibold text-muted-foreground">Créditos: </span>
          <span data-numeric>
            {kardex.progress.earned_credits} / {kardex.progress.total_credits}
          </span>
        </span>
        <span>
          <span className="font-semibold text-muted-foreground">
            Materias aprobadas:{" "}
          </span>
          <span data-numeric>
            {kardex.progress.passed_subjects} / {kardex.progress.total_subjects}
          </span>
        </span>
        <span>
          <span className="font-semibold text-muted-foreground">Promedio: </span>
          <span data-numeric>{kardex.progress.gpa ?? "—"}</span>
        </span>
        <span>
          <span className="font-semibold text-muted-foreground">Avance: </span>
          <span data-numeric>{kardex.progress.credit_progress_pct}%</span>
        </span>
      </div>
      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Periodo</TableHead>
              <TableHead>Clave</TableHead>
              <TableHead>Materia</TableHead>
              <TableHead>Créditos</TableHead>
              <TableHead>Calificación</TableHead>
              <TableHead>Estatus</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {kardex.rows.map((r) => (
              <TableRow key={r.subject_enrollment_id}>
                <TableCell data-numeric>{r.period_number}</TableCell>
                <TableCell data-numeric>{r.code}</TableCell>
                <TableCell className="font-semibold">{r.name}</TableCell>
                <TableCell data-numeric>{r.credits}</TableCell>
                <TableCell data-numeric className="font-semibold">
                  {r.final_grade ?? "—"}
                </TableCell>
                <TableCell>
                  <Badge
                    variant={
                      r.status === "aprobada"
                        ? "default"
                        : r.status === "reprobada"
                          ? "destructive"
                          : "outline"
                    }
                  >
                    {SUBJECT_STATUS_LABELS[r.status]}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
            {kardex.rows.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="py-8 text-center text-muted-foreground"
                >
                  Sin historial académico
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function PortalTabError() {
  return (
    <p className="rounded-md border bg-card py-8 text-center text-sm text-muted-foreground">
      No se pudo cargar la información. Intenta de nuevo más tarde.
    </p>
  );
}

function CalificacionesTab() {
  const { data: rows, isLoading, error } = useQuery({
    queryKey: ["portal-grades"],
    queryFn: () => api<PortalGradeRow[]>("/portal/grades"),
  });
  if (isLoading) return <Skeleton className="h-48 w-full rounded-md" />;
  if (error) return <PortalTabError />;
  return (
    <div className="rounded-md border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Clave</TableHead>
            <TableHead>Materia</TableHead>
            <TableHead>Grupo</TableHead>
            <TableHead>Intento</TableHead>
            <TableHead>Calificación</TableHead>
            <TableHead>Estatus</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows?.map((r, i) => (
            <TableRow key={`${r.code}-${i}`}>
              <TableCell data-numeric>{r.code}</TableCell>
              <TableCell className="font-semibold">{r.subject}</TableCell>
              <TableCell data-numeric>{r.group_code}</TableCell>
              <TableCell data-numeric>{r.attempt_number}</TableCell>
              <TableCell data-numeric className="font-semibold">
                {r.final_grade ?? "—"}
              </TableCell>
              <TableCell>{SUBJECT_STATUS_LABELS[r.status]}</TableCell>
            </TableRow>
          ))}
          {rows && rows.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={6}
                className="py-8 text-center text-muted-foreground"
              >
                Sin materias en curso
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}

function CuentaTab() {
  const { data: statement, isLoading, error } = useQuery({
    queryKey: ["portal-statement"],
    queryFn: () => api<AccountStatement>("/portal/statement"),
  });
  if (error) return <PortalTabError />;
  if (isLoading || !statement)
    return <Skeleton className="h-64 w-full rounded-md" />;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-3">
        {[
          { label: "Cargado", value: formatMoney(statement.total_charged) },
          { label: "Pagado", value: formatMoney(statement.total_paid) },
          {
            label: "Saldo",
            value: formatMoney(statement.balance),
            tone: statement.balance > 0 ? "bad" : "ok",
          },
          {
            label: "Vencido",
            value: formatMoney(statement.overdue_balance),
            tone: statement.overdue_balance > 0 ? "bad" : "ok",
          },
        ].map((chip) => (
          <div
            key={chip.label}
            className={cn(
              "rounded-md border bg-card px-4 py-2",
              chip.tone === "bad" && "border-red-200 text-red-700 dark:border-red-900 dark:text-red-400",
              chip.tone === "ok" &&
                "border-emerald-200 text-emerald-700 dark:border-emerald-900 dark:text-emerald-400",
            )}
          >
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {chip.label}
            </p>
            <p className="font-bold" data-numeric>
              {chip.value}
            </p>
          </div>
        ))}
      </div>

      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Concepto</TableHead>
              <TableHead>Vence</TableHead>
              <TableHead>Importe</TableHead>
              <TableHead>Pagado</TableHead>
              <TableHead>Saldo</TableHead>
              <TableHead>Estatus</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {statement.charges.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="font-semibold">{c.description}</TableCell>
                <TableCell data-numeric>{formatDate(c.due_date)}</TableCell>
                <TableCell data-numeric>{formatMoney(c.amount)}</TableCell>
                <TableCell data-numeric>{formatMoney(c.paid_amount)}</TableCell>
                <TableCell data-numeric className="font-semibold">
                  {formatMoney(c.balance)}
                </TableCell>
                <TableCell>{CHARGE_STATUS_LABELS[c.status]}</TableCell>
              </TableRow>
            ))}
            {statement.charges.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="py-8 text-center text-muted-foreground"
                >
                  Sin cargos registrados
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Folio</TableHead>
              <TableHead>Fecha</TableHead>
              <TableHead>Método</TableHead>
              <TableHead>Importe</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {statement.payments
              .filter((p) => !p.cancelled)
              .map((p) => (
                <TableRow key={p.id}>
                  <TableCell data-numeric className="font-semibold">
                    {p.receipt_folio}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(p.received_at)}
                  </TableCell>
                  <TableCell>{PAYMENT_METHOD_LABELS[p.method]}</TableCell>
                  <TableCell data-numeric className="font-semibold">
                    {formatMoney(p.amount)}
                  </TableCell>
                </TableRow>
              ))}
            {statement.payments.filter((p) => !p.cancelled).length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={4}
                  className="py-8 text-center text-muted-foreground"
                >
                  Sin pagos registrados
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

const WEEKDAY_LABELS = [
  "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo",
];
const formatTime = (t: string) => t.slice(0, 5);

function HorarioTab() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["portal-schedule"],
    queryFn: () => api<StudentCalendar>("/portal/schedule"),
    retry: false,
  });
  if (isLoading) return <Skeleton className="h-64 w-full rounded-md" />;
  if (error || !data || !data.linked || data.items.length === 0) {
    return (
      <EmptyState
        icon={CalendarDays}
        title="Horario no disponible"
        description="Tu grupo aún no tiene horario publicado en el calendario."
      />
    );
  }
  const rows = data.items
    .flatMap((item) => item.meetings.map((meeting) => ({ item, meeting })))
    .sort(
      (a, b) =>
        a.meeting.weekday - b.meeting.weekday ||
        a.meeting.start_time.localeCompare(b.meeting.start_time),
    );
  return (
    <div className="rounded-md border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Día</TableHead>
            <TableHead>Horario</TableHead>
            <TableHead>Materia</TableHead>
            <TableHead>Profesor</TableHead>
            <TableHead>Aula</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(({ item, meeting }, i) => (
            <TableRow key={`${item.id}-${meeting.weekday}-${i}`}>
              <TableCell className="font-semibold">
                {WEEKDAY_LABELS[meeting.weekday] ?? "—"}
              </TableCell>
              <TableCell data-numeric className="whitespace-nowrap">
                {formatTime(meeting.start_time)} – {formatTime(meeting.end_time)}
              </TableCell>
              <TableCell className="font-semibold">{item.subject}</TableCell>
              <TableCell
                className={item.professor ? "" : "text-muted-foreground"}
              >
                {item.professor ?? "Sin asignar"}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {item.classroom ?? (item.classroom_is_virtual ? "Virtual" : "—")}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
