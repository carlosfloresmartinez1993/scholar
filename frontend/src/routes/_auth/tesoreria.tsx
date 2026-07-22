import { useEffect, useMemo, useState } from "react";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Plus,
  Printer,
  Receipt,
  Search,
} from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  AccountStatement,
  AgingRow,
  Campus,
  Charge,
  CollectionReport,
  FiscalProfile,
  FiscalReceptor as FiscalReceptorT,
  GroupEnrollment,
  Group,
  Institution,
  Payment,
  PlanEnrollment,
  PlanVersion,
  Program,
  Rvoe,
  Student,
  UserPublic,
} from "@/api/types";
import { formatDate, formatMoney, PAYMENT_METHOD_LABELS } from "@/lib/format";
import {
  paymentToReceiptData,
  printComprobante,
  printReceipt,
  type ReceiptData,
} from "@/lib/receipt";
import { PaymentDialog } from "@/components/payment-dialog";
import { TesoreriaLayout } from "@/components/tesoreria-nav";
import { StudentAvatar } from "@/components/student-avatar";
import { StudentStatusBadge } from "@/components/student-status-badge";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
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

// ?studentId= deep-links into Caja with the student preloaded, so "Cobrar"
// anywhere in the app (cartera vencida, ⌘K) is one click away from charging.
export const Route = createFileRoute("/_auth/tesoreria")({
  component: TesoreriaPage,
  validateSearch: (search: Record<string, unknown>): { studentId?: string } =>
    typeof search.studentId === "string" && search.studentId
      ? { studentId: search.studentId }
      : {},
});

function useMe() {
  return useQuery({ queryKey: queryKeys.me, queryFn: () => api<UserPublic>("/auth/me") });
}

function useInstitution() {
  return useQuery({
    queryKey: queryKeys.institution,
    queryFn: () => api<Institution>("/catalog/institution"),
  });
}

function TesoreriaPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl">Tesorería</h1>
      <TesoreriaLayout active="caja">
        <CajaBody />
      </TesoreriaLayout>
    </div>
  );
}

// --- Caja: cobrar, recibo, facturar ---------------------------------------------------

function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** The one yellow standout: live "cobrado hoy" for the cashier's shift. */
function CajaHero() {
  const today = todayISO();
  const { data, isError, refetch } = useQuery({
    queryKey: queryKeys.collectionReport(today, today),
    queryFn: () =>
      api<CollectionReport>(
        `/treasury/reports/collection?date_from=${today}&date_to=${today}`,
      ),
  });
  return (
    <div className="w-full max-w-sm rounded-md bg-primary p-6 text-primary-foreground">
      <p className="text-xs font-bold uppercase tracking-wide text-primary-foreground/70">
        Cobrado hoy
      </p>
      {isError ? (
        <div className="mt-1 flex flex-wrap items-center gap-3 text-sm font-semibold">
          No se pudo cargar el total del día.
          <Button
            size="sm"
            className="bg-black text-white hover:bg-black/85"
            onClick={() => refetch()}
          >
            Reintentar
          </Button>
        </div>
      ) : data ? (
        <div className="mt-1 flex flex-wrap items-baseline gap-3">
          <p className="text-4xl font-extrabold tabular-nums">
            {formatMoney(data.total)}
          </p>
          <span className="text-sm font-semibold text-primary-foreground/70" data-numeric>
            {data.payments_count} {data.payments_count === 1 ? "pago" : "pagos"}
          </span>
        </div>
      ) : (
        <Skeleton className="mt-2 h-10 w-48 bg-black/10" />
      )}
    </div>
  );
}

function CajaBody() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { studentId: deepStudentId } = Route.useSearch();
  const { data: me } = useMe();
  const { data: institution } = useInstitution();
  const [query, setQuery] = useState("");
  const [student, setStudent] = useState<Student | null>(null);

  // Deep link (?studentId=): preload the student straight into Caja.
  const { data: deepStudent, error: deepStudentError } = useQuery({
    queryKey: queryKeys.student(deepStudentId ?? ""),
    queryFn: () => api<Student>(`/students/${deepStudentId}`),
    enabled: !!deepStudentId,
  });
  useEffect(() => {
    if (deepStudent) {
      setStudent(deepStudent);
      setSelectedIds(new Set());
    }
  }, [deepStudent]);
  useEffect(() => {
    if (deepStudentError) toast.error("No se pudo cargar el alumno del enlace");
  }, [deepStudentError]);

  const {
    data: results,
    isError: searchError,
    refetch: refetchSearch,
  } = useQuery({
    queryKey: queryKeys.students(query),
    queryFn: () => api<Student[]>(`/students?q=${encodeURIComponent(query)}&limit=8`),
    enabled: query.trim().length >= 2 && !student,
  });

  const {
    data: statement,
    isLoading: loadingStatement,
    isError: statementError,
    refetch: refetchStatement,
  } = useQuery({
    queryKey: queryKeys.statement(student?.id ?? ""),
    queryFn: () => api<AccountStatement>(`/treasury/students/${student!.id}/statement`),
    enabled: !!student,
  });

  const [cobrarCharge, setCobrarCharge] = useState<Charge | null | undefined>(undefined);
  const [condonarCharge, setCondonarCharge] = useState<Charge | null>(null);
  const [cancelPayment, setCancelPayment] = useState<Payment | null>(null);
  const [facturarPayment, setFacturarPayment] = useState<Payment | null>(null);
  // Multi-cobro: charges ticked for a single combined payment.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [multiOpen, setMultiOpen] = useState(false);

  const pickStudent = (s: Student | null) => {
    setStudent(s);
    setSelectedIds(new Set());
    setMultiOpen(false);
    // Drop a consumed deep link so "Cambiar alumno" doesn't re-select it.
    if (deepStudentId) {
      navigate({ to: "/tesoreria", search: {}, replace: true });
    }
  };

  const receiptFor = (payment: Payment): ReceiptData | null => {
    if (!institution || !student) return null;
    return paymentToReceiptData(payment, {
      institution,
      student,
      charges: statement?.charges ?? [],
      cajero: me?.full_name ?? "",
    });
  };

  const printPaymentReceipt = (payment: Payment) => {
    const data = receiptFor(payment);
    if (data) printReceipt(data);
  };

  const pendientes =
    statement?.charges.filter((c) => c.status !== "cancelado" && c.balance > 0) ?? [];
  const pagos = statement?.payments.slice().reverse() ?? [];

  const selectedCharges = pendientes.filter((c) => selectedIds.has(c.id));
  const selectedTotal =
    Math.round(selectedCharges.reduce((sum, c) => sum + c.balance, 0) * 100) / 100;
  const allSelected = pendientes.length > 0 && selectedCharges.length === pendientes.length;

  const toggleCharge = (id: string, on: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  return (
    <div className="space-y-6">
      {!student && (
        <>
          {/* Borderless search: results overlay the page (absolute) — no layout shift. */}
          <div className="relative max-w-xl">
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                refetchSearch();
              }}
            >
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  autoFocus
                  className="pl-9"
                  placeholder="Cobrar a un alumno — nombre o matrícula…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </div>
              <Button type="submit" aria-label="Buscar alumno">
                <Search className="size-4" /> Buscar
              </Button>
            </form>
            {query.trim().length >= 2 && (
              <div className="absolute inset-x-0 top-full z-20 mt-1 divide-y overflow-hidden rounded-md border bg-popover shadow-lg">
                {searchError ? (
                  <div className="flex items-center gap-3 px-3 py-3 text-sm text-destructive">
                    No se pudo buscar alumnos.
                    <Button size="sm" variant="outline" onClick={() => refetchSearch()}>
                      Reintentar
                    </Button>
                  </div>
                ) : (
                  <>
                    {results?.map((s) => (
                      <button
                        key={s.id}
                        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-muted/50"
                        onClick={() => {
                          pickStudent(s);
                          setQuery("");
                        }}
                      >
                        <span className="font-semibold">{s.full_name}</span>
                        <span data-numeric className="text-muted-foreground">
                          {s.enrollment_number}
                        </span>
                      </button>
                    ))}
                    {results && results.length === 0 && (
                      <p className="px-3 py-3 text-sm text-muted-foreground">
                        Sin resultados
                      </p>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
          <CarteraVencidaSection />
          <div className="flex justify-end">
            <CajaHero />
          </div>
        </>
      )}

      {student && (
        <StudentStrip
          student={student}
          balance={statement?.balance}
          onChange={() => pickStudent(null)}
        />
      )}

      {student && statementError && (
        <div className="flex items-center gap-3 rounded-md border p-4 text-sm text-destructive">
          No se pudo cargar el estado de cuenta.
          <Button size="sm" variant="outline" onClick={() => refetchStatement()}>
            Reintentar
          </Button>
        </div>
      )}

      {student && !statementError && (
        <>
          <section className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-muted-foreground">
                Cargos pendientes
              </h3>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => setCobrarCharge(null)}>
                  <Plus className="size-4" /> Cobro libre
                </Button>
                <Button
                  size="sm"
                  className="font-bold"
                  disabled={selectedCharges.length === 0}
                  onClick={() => setMultiOpen(true)}
                >
                  Cobrar
                  {selectedCharges.length > 0 && (
                    <span data-numeric>
                      {" "}
                      ({selectedCharges.length}) · {formatMoney(selectedTotal)}
                    </span>
                  )}
                </Button>
              </div>
            </div>
            <div className="rounded-md border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10">
                      <Checkbox
                        aria-label="Seleccionar todos"
                        checked={allSelected}
                        onCheckedChange={(v) =>
                          setSelectedIds(
                            v === true
                              ? new Set(pendientes.map((c) => c.id))
                              : new Set(),
                          )
                        }
                      />
                    </TableHead>
                    <TableHead>Concepto</TableHead>
                    <TableHead>Vence</TableHead>
                    <TableHead className="text-right">Saldo</TableHead>
                    <TableHead className="w-28" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {loadingStatement && (
                    <TableRow>
                      <TableCell colSpan={5}>
                        <Skeleton className="h-6 w-full" />
                      </TableCell>
                    </TableRow>
                  )}
                  {pendientes.map((c) => (
                    <TableRow
                      key={c.id}
                      className="cursor-pointer"
                      onClick={() => toggleCharge(c.id, !selectedIds.has(c.id))}
                    >
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <Checkbox
                          aria-label={`Seleccionar ${c.description}`}
                          checked={selectedIds.has(c.id)}
                          onCheckedChange={(v) => toggleCharge(c.id, v === true)}
                        />
                      </TableCell>
                      <TableCell className="font-semibold">
                        {c.description}
                        {c.is_late_fee && (
                          <Badge variant="destructive" className="ml-2">
                            Recargo
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>{formatDate(c.due_date)}</TableCell>
                      <TableCell data-numeric className="text-right font-semibold">
                        {formatMoney(c.balance)}
                        {c.condoned_amount > 0 && (
                          <span className="ml-2 text-xs font-normal text-muted-foreground">
                            (cond. {formatMoney(c.condoned_amount)})
                          </span>
                        )}
                      </TableCell>
                      <TableCell
                        className="text-right"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-muted-foreground"
                          onClick={() => setCondonarCharge(c)}
                        >
                          Condonar
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!loadingStatement && pendientes.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={5}
                        className="py-8 text-center text-muted-foreground"
                      >
                        Sin cargos pendientes
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-semibold text-muted-foreground">
              Pagos recientes
            </h3>
            <div className="rounded-md border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Folio</TableHead>
                    <TableHead>Fecha</TableHead>
                    <TableHead>Método</TableHead>
                    <TableHead>Monto</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Recibo</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pagos.map((p) => (
                    <TableRow key={p.id} className={p.cancelled ? "opacity-60" : ""}>
                      <TableCell data-numeric>{p.receipt_folio}</TableCell>
                      <TableCell>{formatDate(p.received_at)}</TableCell>
                      <TableCell>{PAYMENT_METHOD_LABELS[p.method]}</TableCell>
                      <TableCell data-numeric className="font-semibold">
                        {formatMoney(p.amount)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={p.cancelled ? "destructive" : "outline"}>
                          {p.cancelled ? "Cancelado" : "Vigente"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        {!p.cancelled && (
                          <div className="flex justify-end gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => printPaymentReceipt(p)}
                            >
                              <Printer className="size-4" /> Recibo
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setFacturarPayment(p)}
                            >
                              <Receipt className="size-4" /> Facturar
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="text-destructive"
                              onClick={() => setCancelPayment(p)}
                            >
                              Cancelar
                            </Button>
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                  {pagos.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={6}
                        className="py-8 text-center text-muted-foreground"
                      >
                        Sin pagos registrados
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          </section>
        </>
      )}

      {student && cobrarCharge !== undefined && (
        <PaymentDialog
          student={student}
          charge={cobrarCharge}
          open
          onOpenChange={(o) => !o && setCobrarCharge(undefined)}
          onPaid={(payment) => {
            queryClient.invalidateQueries({ queryKey: queryKeys.statement(student.id) });
            printPaymentReceipt(payment);
          }}
        />
      )}

      {student && multiOpen && (
        <PaymentDialog
          student={student}
          multiCharges={selectedCharges}
          open
          onOpenChange={(o) => !o && setMultiOpen(false)}
          onPaid={(payment) => {
            queryClient.invalidateQueries({ queryKey: queryKeys.statement(student.id) });
            setSelectedIds(new Set());
            printPaymentReceipt(payment);
          }}
        />
      )}

      {student && condonarCharge && (
        <CondonarDialog
          charge={condonarCharge}
          onClose={() => setCondonarCharge(null)}
          onDone={() =>
            queryClient.invalidateQueries({ queryKey: queryKeys.statement(student.id) })
          }
        />
      )}

      {student && cancelPayment && (
        <CancelPaymentDialog
          payment={cancelPayment}
          onClose={() => setCancelPayment(null)}
          onDone={() =>
            queryClient.invalidateQueries({ queryKey: queryKeys.statement(student.id) })
          }
        />
      )}

      {student && facturarPayment && (
        <FacturarDialog
          student={student}
          payment={facturarPayment}
          receiptFor={receiptFor}
          onClose={() => setFacturarPayment(null)}
        />
      )}
    </div>
  );
}

// --- Condonación: forgive part/all of a charge's open balance -------------------------

function CondonarDialog({
  charge,
  onClose,
  onDone,
}: {
  charge: Charge;
  onClose: () => void;
  onDone: () => void;
}) {
  const [amount, setAmount] = useState(String(charge.balance));
  const [reason, setReason] = useState("");

  const condone = useMutation({
    mutationFn: () =>
      api<Charge>(`/treasury/charges/${charge.id}/condone`, {
        method: "POST",
        body: JSON.stringify({ amount: Number(amount), reason }),
      }),
    onSuccess: () => {
      toast.success("Condonación aplicada");
      onDone();
      onClose();
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al condonar"),
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Condonar: {charge.description}</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            condone.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="cond-amount">Importe a condonar</Label>
            <Input
              id="cond-amount"
              type="number"
              min={0.01}
              max={charge.balance}
              step="0.01"
              required
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Saldo del cargo: {formatMoney(charge.balance)}. La condonación queda
              en auditoría y no borra los pagos ya aplicados.
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="cond-reason">Motivo</Label>
            <Input
              id="cond-reason"
              required
              minLength={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Autorizado por dirección…"
            />
          </div>
          <DialogFooter>
            <Button type="submit" className="font-bold" disabled={condone.isPending}>
              {condone.isPending ? "Aplicando…" : "Condonar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// --- Cancelar recibo (pago) -----------------------------------------------------------

function CancelPaymentDialog({
  payment,
  onClose,
  onDone,
}: {
  payment: Payment;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");

  const cancel = useMutation({
    mutationFn: () =>
      api<Payment>(
        `/treasury/payments/${payment.id}/cancel?reason=${encodeURIComponent(reason)}`,
        { method: "POST" },
      ),
    onSuccess: () => {
      toast.success(`Recibo ${payment.receipt_folio} cancelado`);
      onDone();
      onClose();
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al cancelar"),
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Cancelar recibo · {payment.receipt_folio}</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            cancel.mutate();
          }}
        >
          <p className="text-sm text-muted-foreground">
            El pago de <b data-numeric>{formatMoney(payment.amount)}</b> dejará de
            contar en el estado de cuenta y los cargos que cubría se reabren.
          </p>
          <div className="grid gap-2">
            <Label htmlFor="cp-reason">Motivo</Label>
            <Input
              id="cp-reason"
              required
              minLength={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Error de captura, devolución…"
            />
          </div>
          <DialogFooter>
            <Button
              type="submit"
              variant="destructive"
              className="font-bold"
              disabled={cancel.isPending}
            >
              {cancel.isPending ? "Cancelando…" : "Cancelar recibo"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// --- Identity strip (compact version of the alumnos/$id header) ----------------------

function StudentStrip({
  student,
  balance,
  onChange,
}: {
  student: Student;
  balance?: number;
  onChange: () => void;
}) {
  const { data: campuses } = useQuery({
    queryKey: queryKeys.campuses,
    queryFn: () => api<Campus[]>("/catalog/campuses"),
  });
  const { data: enrollments } = useQuery({
    queryKey: queryKeys.planEnrollments(student.id),
    queryFn: () => api<PlanEnrollment[]>(`/students/${student.id}/plan-enrollments`),
  });
  const { data: groupEnrollments } = useQuery({
    queryKey: queryKeys.groupEnrollments(student.id),
    queryFn: () => api<GroupEnrollment[]>(`/students/${student.id}/group-enrollments`),
  });
  const { data: planVersions } = useQuery({
    queryKey: queryKeys.planVersions(),
    queryFn: () => api<PlanVersion[]>("/catalog/plan-versions"),
  });
  const { data: rvoes } = useQuery({
    queryKey: queryKeys.rvoes(),
    queryFn: () => api<Rvoe[]>("/catalog/rvoes"),
  });
  const { data: programs } = useQuery({
    queryKey: queryKeys.programs,
    queryFn: () => api<Program[]>("/catalog/programs"),
  });
  const activeGroupEnrollment = groupEnrollments
    ?.filter((e) => e.status === "activa")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const { data: currentGroup } = useQuery({
    queryKey: ["group", activeGroupEnrollment?.group_id ?? "none"],
    queryFn: () => api<Group>(`/catalog/groups/${activeGroupEnrollment!.group_id}`),
    enabled: !!activeGroupEnrollment,
  });

  const campusName = campuses?.find((c) => c.id === student.campus_id)?.name;
  const activePlan =
    enrollments?.find((e) => e.status === "inscrito") ?? enrollments?.[0];
  const programName = useMemo(() => {
    if (!activePlan) return null;
    const pv = planVersions?.find((v) => v.id === activePlan.plan_version_id);
    const rvoe = rvoes?.find((r) => r.id === pv?.rvoe_id);
    return programs?.find((p) => p.id === rvoe?.program_id)?.name ?? null;
  }, [activePlan, planVersions, rvoes, programs]);

  const facts = [
    campusName,
    programName ?? "Sin plan",
    currentGroup ? `Grupo ${currentGroup.code}` : "Sin grupo",
  ].filter(Boolean) as string[];

  return (
    <Card className="rounded-md">
      <CardContent className="flex flex-wrap items-center gap-5 p-5">
        <StudentAvatar
          studentId={student.id}
          name={student.full_name}
          hasPhoto={student.has_photo}
          className="size-16 text-xl"
        />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to="/alumnos/$studentId"
              params={{ studentId: student.id }}
              className="text-xl font-bold hover:underline"
            >
              {student.full_name}
            </Link>
            <StudentStatusBadge status={student.status} />
          </div>
          <p className="flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
            <span data-numeric className="font-semibold text-foreground">
              {student.enrollment_number}
            </span>
            {facts.map((f) => (
              <span key={f} className="flex items-center gap-x-2">
                <span aria-hidden>·</span>
                {f}
              </span>
            ))}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Saldo
          </p>
          <p
            data-numeric
            className={
              "text-2xl font-bold " +
              (balance != null && balance > 0 ? "text-red-600" : "text-emerald-600")
            }
          >
            {formatMoney(balance)}
          </p>
        </div>
        <Button variant="outline" onClick={onChange}>
          Cambiar alumno
        </Button>
      </CardContent>
    </Card>
  );
}

// --- Cartera vencida: the cashier's work queue ----------------------------------------

type AgingBucket = AgingRow["bucket"];

const CARTERA_PAGE_SIZE = 5;

function CarteraVencidaSection() {
  const navigate = useNavigate();
  const [page, setPage] = useState(0);
  const { data: aging, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.aging,
    queryFn: () => api<AgingRow[]>("/treasury/reports/aging"),
  });

  // Aggregate one row per student across all their overdue charges.
  const rows = useMemo(() => {
    const byStudent = new Map<
      string,
      {
        student_id: string;
        student_name: string;
        enrollment_number: string;
        total: number;
        max_days: number;
        bucket: AgingBucket;
        count: number;
      }
    >();
    for (const r of aging ?? []) {
      const cur = byStudent.get(r.student_id);
      if (cur) {
        cur.total += r.balance;
        cur.count += 1;
        if (r.days_overdue > cur.max_days) {
          cur.max_days = r.days_overdue;
          cur.bucket = r.bucket;
        }
      } else {
        byStudent.set(r.student_id, {
          student_id: r.student_id,
          student_name: r.student_name,
          enrollment_number: r.enrollment_number,
          total: r.balance,
          max_days: r.days_overdue,
          bucket: r.bucket,
          count: 1,
        });
      }
    }
    return [...byStudent.values()].sort((a, b) => b.total - a.total);
  }, [aging]);

  const total = rows.reduce((sum, r) => sum + r.total, 0);
  // 5 per page, biggest debt first; clamp so a shrinking list never strands the page.
  const pages = Math.max(1, Math.ceil(rows.length / CARTERA_PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const start = current * CARTERA_PAGE_SIZE;
  const pageRows = rows.slice(start, start + CARTERA_PAGE_SIZE);

  if (isError) {
    return (
      <EmptyState
        icon={Check}
        title="No se pudo cargar la cartera vencida"
        description="Ocurrió un error al consultar los cargos. Intente de nuevo."
      >
        <Button variant="outline" onClick={() => refetch()}>
          Reintentar
        </Button>
      </EmptyState>
    );
  }
  // empty state only for a SUCCESSFUL empty response (not a failed/loading one)
  if (!isLoading && !isError && rows.length === 0) {
    return (
      <EmptyState
        icon={Check}
        title="Sin cartera vencida"
        description="Ningún alumno tiene cargos vencidos por cobrar."
      />
    );
  }

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-muted-foreground">
        Cartera vencida{" "}
        <span data-numeric>· {formatMoney(total)}</span>
      </h3>
      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Matrícula</TableHead>
              <TableHead>Alumno</TableHead>
              <TableHead># cargos</TableHead>
              <TableHead>Días</TableHead>
              <TableHead>Total vencido</TableHead>
              <TableHead className="text-right">Acción</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={6}>
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            )}
            {pageRows.map((r) => (
              <TableRow key={r.student_id}>
                <TableCell data-numeric>{r.enrollment_number}</TableCell>
                <TableCell className="font-semibold">{r.student_name}</TableCell>
                <TableCell data-numeric>{r.count}</TableCell>
                <TableCell>
                  <Badge
                    variant={
                      r.bucket === "1-30"
                        ? "outline"
                        : r.bucket === "31-60"
                          ? "secondary"
                          : "destructive"
                    }
                  >
                    {r.max_days} días
                  </Badge>
                </TableCell>
                <TableCell data-numeric className="font-semibold">
                  {formatMoney(r.total)}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    size="sm"
                    onClick={() =>
                      navigate({
                        to: "/tesoreria",
                        search: { studentId: r.student_id },
                      })
                    }
                  >
                    Cobrar
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {pages > 1 && (
          <div className="flex items-center justify-between border-t px-3 py-2 text-sm text-muted-foreground">
            <span data-numeric>
              {start + 1}–{Math.min(start + CARTERA_PAGE_SIZE, rows.length)} de{" "}
              {rows.length} alumnos
            </span>
            <div className="flex gap-1">
              <Button
                variant="ghost"
                size="sm"
                aria-label="Página anterior"
                disabled={current === 0}
                onClick={() => setPage(current - 1)}
              >
                <ChevronLeft className="size-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label="Página siguiente"
                disabled={current >= pages - 1}
                onClick={() => setPage(current + 1)}
              >
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// --- Facturar (comprobante sin validez fiscal) ----------------------------------------

function FacturarDialog({
  student,
  payment,
  receiptFor,
  onClose,
}: {
  student: Student;
  payment: Payment;
  receiptFor: (p: Payment) => ReceiptData | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { data: profile, isLoading } = useQuery({
    queryKey: queryKeys.fiscalProfile(student.id),
    queryFn: () => api<FiscalProfile | null>(`/treasury/students/${student.id}/fiscal`),
  });

  const empty = {
    rfc: "",
    razon_social: "",
    regimen_fiscal: "",
    uso_cfdi: "G03",
    email: "",
    cp: "",
    calle: "",
    no_ext: "",
    no_int: "",
    colonia: "",
    municipio: "",
    estado: "",
    pais: "México",
  };
  const [form, setForm] = useState<typeof empty | null>(null);
  const model = form ?? profile ?? empty;
  const editing = form !== null || !profile;

  // Registered receptors (one per RFC): recurrent clients fill the form in one
  // click instead of being recaptured.
  const [receptorQuery, setReceptorQuery] = useState("");
  const { data: receptors } = useQuery({
    queryKey: queryKeys.fiscalReceptors(receptorQuery),
    queryFn: () =>
      api<FiscalReceptorT[]>(
        `/treasury/fiscal-receptors?q=${encodeURIComponent(receptorQuery)}`,
      ),
    enabled: editing && receptorQuery.trim().length >= 2,
  });
  const pickReceptor = (r: FiscalReceptorT) => {
    const { id: _id, ...fields } = r;
    setForm(fields);
    setReceptorQuery("");
  };

  const save = useMutation({
    mutationFn: () =>
      api<FiscalProfile>(`/treasury/students/${student.id}/fiscal`, {
        method: "PUT",
        body: JSON.stringify(model),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.fiscalProfile(student.id) });
      toast.success("Datos fiscales guardados");
      setForm(null);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  const facturar = (f: FiscalProfile) => {
    const data = receiptFor(payment);
    if (!data) return;
    const domicilio = [
      [f.calle, f.no_ext, f.no_int && `Int. ${f.no_int}`].filter(Boolean).join(" "),
      f.colonia,
      [f.municipio, f.estado].filter(Boolean).join(", "),
    ]
      .filter(Boolean)
      .join(" · ");
    printComprobante(data, {
      rfc: f.rfc,
      razonSocial: f.razon_social,
      regimenFiscal: f.regimen_fiscal,
      usoCfdi: f.uso_cfdi,
      cp: f.cp,
      domicilio,
    });
    onClose();
  };

  const set = (k: keyof typeof empty, v: string) =>
    setForm({ ...(form ?? profile ?? empty), [k]: v });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Facturar · {payment.receipt_folio}</DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <div className="space-y-4">
            <p className="text-xs text-muted-foreground">
              Comprobante sin validez fiscal. El timbrado CFDI ante el SAT se
              habilitará al conectar un PAC.
            </p>
            {!editing && profile ? (
              <div className="space-y-1 rounded-md border p-4 text-sm">
                <p className="font-bold">{profile.razon_social}</p>
                <p className="text-muted-foreground">RFC: {profile.rfc}</p>
                {profile.regimen_fiscal && (
                  <p className="text-muted-foreground">
                    Régimen: {profile.regimen_fiscal} · Uso CFDI: {profile.uso_cfdi}
                  </p>
                )}
                <div className="flex gap-2 pt-2">
                  <Button className="font-bold" onClick={() => facturar(profile)}>
                    <Printer className="size-4" /> Generar comprobante
                  </Button>
                  <Button variant="outline" onClick={() => setForm({ ...profile })}>
                    Editar datos
                  </Button>
                </div>
              </div>
            ) : (
              <form
                className="grid gap-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  save.mutate();
                }}
              >
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    className="pl-9"
                    placeholder="Buscar receptor registrado (RFC o razón social)…"
                    value={receptorQuery}
                    onChange={(e) => setReceptorQuery(e.target.value)}
                  />
                  {receptorQuery.trim().length >= 2 && (
                    <div className="absolute inset-x-0 top-full z-20 mt-1 divide-y overflow-hidden rounded-md border bg-popover shadow-lg">
                      {receptors?.map((r) => (
                        <button
                          key={r.id}
                          type="button"
                          className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-muted/50"
                          onClick={() => pickReceptor(r)}
                        >
                          <span className="font-semibold">{r.razon_social}</span>
                          <span data-numeric className="text-muted-foreground">
                            {r.rfc}
                          </span>
                        </button>
                      ))}
                      {receptors && receptors.length === 0 && (
                        <p className="px-3 py-3 text-sm text-muted-foreground">
                          Sin receptores registrados con ese dato
                        </p>
                      )}
                    </div>
                  )}
                </div>
                <div className="grid gap-2">
                  <Label>Razón social</Label>
                  <Input
                    required
                    value={model.razon_social}
                    onChange={(e) => set("razon_social", e.target.value)}
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="grid gap-2">
                    <Label>RFC</Label>
                    <Input
                      required
                      value={model.rfc}
                      onChange={(e) => set("rfc", e.target.value.toUpperCase())}
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label>Código postal</Label>
                    <Input value={model.cp} onChange={(e) => set("cp", e.target.value)} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="grid gap-2">
                    <Label>Régimen fiscal (clave SAT)</Label>
                    <Input
                      value={model.regimen_fiscal}
                      onChange={(e) => set("regimen_fiscal", e.target.value)}
                      placeholder="p. ej. 612, 605"
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label>Uso CFDI</Label>
                    <Input
                      value={model.uso_cfdi}
                      onChange={(e) => set("uso_cfdi", e.target.value)}
                      placeholder="G03"
                    />
                  </div>
                </div>
                <div className="grid gap-2">
                  <Label>Correo</Label>
                  <Input
                    type="email"
                    value={model.email}
                    onChange={(e) => set("email", e.target.value)}
                  />
                </div>
                <div className="grid grid-cols-[1fr_auto_auto] gap-4">
                  <div className="grid gap-2">
                    <Label>Calle</Label>
                    <Input value={model.calle} onChange={(e) => set("calle", e.target.value)} />
                  </div>
                  <div className="grid gap-2">
                    <Label>No. Ext</Label>
                    <Input
                      className="w-24"
                      value={model.no_ext}
                      onChange={(e) => set("no_ext", e.target.value)}
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label>No. Int</Label>
                    <Input
                      className="w-24"
                      value={model.no_int}
                      onChange={(e) => set("no_int", e.target.value)}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div className="grid gap-2">
                    <Label>Colonia</Label>
                    <Input value={model.colonia} onChange={(e) => set("colonia", e.target.value)} />
                  </div>
                  <div className="grid gap-2">
                    <Label>Municipio</Label>
                    <Input
                      value={model.municipio}
                      onChange={(e) => set("municipio", e.target.value)}
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label>Estado</Label>
                    <Input value={model.estado} onChange={(e) => set("estado", e.target.value)} />
                  </div>
                </div>
                <DialogFooter>
                  {profile && (
                    <Button type="button" variant="outline" onClick={() => setForm(null)}>
                      Cancelar
                    </Button>
                  )}
                  <Button type="submit" className="font-bold" disabled={save.isPending}>
                    {save.isPending ? "Guardando…" : "Guardar datos fiscales"}
                  </Button>
                </DialogFooter>
              </form>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
