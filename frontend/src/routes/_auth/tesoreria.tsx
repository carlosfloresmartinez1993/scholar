import { useEffect, useMemo, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlarmClock,
  Check,
  Download,
  Plus,
  Printer,
  Receipt,
  Search,
  X,
} from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  AccountStatement,
  AgingRow,
  Charge,
  ChargeConcept,
  ChargeConceptKind,
  CollectionReport,
  FiscalProfile,
  Institution,
  Modality,
  Payment,
  Program,
  Scholarship,
  ScholarshipReport,
  ScholarshipStatus,
  Student,
  Term,
  UserPublic,
} from "@/api/types";
import {
  CONCEPT_KIND_LABELS,
  formatDate,
  formatMoney,
  MODALITY_LABELS,
  PAYMENT_METHOD_LABELS,
  SCHOLARSHIP_STATUS_LABELS,
} from "@/lib/format";
import { usePersistedState } from "@/lib/use-persisted-state";
import {
  paymentToReceiptData,
  printComprobante,
  printReceipt,
  type ReceiptData,
} from "@/lib/receipt";
import {
  DateRangeFilter,
  presetRange,
  type DateRange,
} from "@/components/date-range-filter";
import { PaymentDialog } from "@/components/payment-dialog";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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

// ?studentId= deep-links into Caja with the student preloaded, so "Cobrar"
// anywhere in the app (cartera vencida, ⌘K) is one click away from charging.
export const Route = createFileRoute("/_auth/tesoreria")({
  component: TesoreriaPage,
  validateSearch: (search: Record<string, unknown>): { studentId?: string } =>
    typeof search.studentId === "string" && search.studentId
      ? { studentId: search.studentId }
      : {},
});

const NONE = "__none__";

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
  const { studentId } = Route.useSearch();
  const [tab, setTab] = useState("caja");
  // A deep link always lands on Caja, even if the user was on another tab.
  useEffect(() => {
    if (studentId) setTab("caja");
  }, [studentId]);
  return (
    <div className="space-y-6">
      <h1 className="text-3xl">Tesorería</h1>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="caja">Caja</TabsTrigger>
          <TabsTrigger value="conceptos">Conceptos</TabsTrigger>
          <TabsTrigger value="cartera">Cartera vencida</TabsTrigger>
          <TabsTrigger value="becas">Becas</TabsTrigger>
          <TabsTrigger value="reportes">Reportes</TabsTrigger>
        </TabsList>
        <TabsContent value="caja" className="mt-4">
          <CajaTab />
        </TabsContent>
        <TabsContent value="cartera" className="mt-4">
          <CarteraVencidaTab />
        </TabsContent>
        <TabsContent value="conceptos" className="mt-4">
          <ConceptosTab />
        </TabsContent>
        <TabsContent value="becas" className="mt-4">
          <BecasTab />
        </TabsContent>
        <TabsContent value="reportes" className="mt-4">
          <ReportesTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// --- Caja: cobrar, recibo, facturar ---------------------------------------------------

function CajaTab() {
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

  const { data: results } = useQuery({
    queryKey: queryKeys.students(query),
    queryFn: () => api<Student[]>(`/students?q=${encodeURIComponent(query)}&limit=8`),
    enabled: query.trim().length >= 2 && !student,
  });

  const { data: statement, isLoading: loadingStatement } = useQuery({
    queryKey: queryKeys.statement(student?.id ?? ""),
    queryFn: () => api<AccountStatement>(`/treasury/students/${student!.id}/statement`),
    enabled: !!student,
  });

  const [cobrarCharge, setCobrarCharge] = useState<Charge | null | undefined>(undefined);
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
  const pagos = statement?.payments.filter((p) => !p.cancelled).slice().reverse() ?? [];

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
      {/* Student search */}
      {!student ? (
        <Card className="rounded-md">
          <CardContent className="space-y-3 p-6">
            <h2 className="text-lg font-bold">Cobrar a un alumno</h2>
            <div className="relative max-w-md">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="Buscar por nombre o matrícula…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            {query.trim().length >= 2 && (
              <div className="max-w-md divide-y rounded-md border">
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
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

      {!student && <InstitucionReciboCard />}

      {student && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold">{student.full_name}</h2>
            <p className="text-sm text-muted-foreground">
              Matrícula <span data-numeric>{student.enrollment_number}</span> ·
              Saldo{" "}
              <span data-numeric className="font-semibold">
                {formatMoney(statement?.balance)}
              </span>
            </p>
          </div>
          <div className="flex gap-2">
            <Button className="font-bold" onClick={() => setCobrarCharge(null)}>
              <Plus className="size-4" /> Cobro libre
            </Button>
            <Button variant="outline" onClick={() => pickStudent(null)}>
              Cambiar alumno
            </Button>
          </div>
        </div>
      )}

      {student && (
        <>
          <section className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-muted-foreground">
                Cargos pendientes
              </h3>
              {selectedCharges.length > 0 && (
                <Button size="sm" className="font-bold" onClick={() => setMultiOpen(true)}>
                  Cobrar seleccionados ({selectedCharges.length}) ·{" "}
                  {formatMoney(selectedTotal)}
                </Button>
              )}
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
                    <TableHead>Saldo</TableHead>
                    <TableHead className="text-right">Acción</TableHead>
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
                    <TableRow key={c.id}>
                      <TableCell>
                        <Checkbox
                          aria-label={`Seleccionar ${c.description}`}
                          checked={selectedIds.has(c.id)}
                          onCheckedChange={(v) => toggleCharge(c.id, v === true)}
                        />
                      </TableCell>
                      <TableCell className="font-semibold">{c.description}</TableCell>
                      <TableCell>{formatDate(c.due_date)}</TableCell>
                      <TableCell data-numeric className="font-semibold">
                        {formatMoney(c.balance)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button size="sm" onClick={() => setCobrarCharge(c)}>
                          Cobrar
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
                    <TableHead className="text-right">Recibo</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pagos.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell data-numeric>{p.receipt_folio}</TableCell>
                      <TableCell>{formatDate(p.received_at)}</TableCell>
                      <TableCell>{PAYMENT_METHOD_LABELS[p.method]}</TableCell>
                      <TableCell data-numeric className="font-semibold">
                        {formatMoney(p.amount)}
                      </TableCell>
                      <TableCell className="text-right">
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
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                  {pagos.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={5}
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

function InstitucionReciboCard() {
  const queryClient = useQueryClient();
  const { data: institution } = useInstitution();
  const [form, setForm] = useState<{ rfc: string; fiscal_address: string } | null>(null);
  const model = form ?? {
    rfc: institution?.rfc ?? "",
    fiscal_address: institution?.fiscal_address ?? "",
  };

  const save = useMutation({
    mutationFn: () =>
      api<Institution>("/catalog/institution", {
        method: "PATCH",
        body: JSON.stringify(model),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.institution });
      toast.success("Encabezado de recibos actualizado");
      setForm(null);
    },
    onError: (e) =>
      toast.error(
        e instanceof ApiError ? e.message : "Solo Servicios Escolares o Dirección pueden editarlo",
      ),
  });

  return (
    <Card className="rounded-md border-dashed">
      <CardContent className="space-y-3 p-6">
        <h3 className="text-sm font-semibold text-muted-foreground">
          Encabezado de recibos · datos fiscales de la institución
        </h3>
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label>RFC</Label>
            <Input
              value={model.rfc}
              onChange={(e) => setForm({ ...model, rfc: e.target.value.toUpperCase() })}
              placeholder="IEE070919PCA"
            />
          </div>
          <div className="grid gap-2 sm:row-span-2">
            <Label>Domicilio fiscal (aparece en el recibo)</Label>
            <Textarea
              rows={4}
              value={model.fiscal_address}
              onChange={(e) => setForm({ ...model, fiscal_address: e.target.value })}
              placeholder={"CALLE OCTAVA 1389\nOBRERA\nENSENADA, BAJA CALIFORNIA C.P. 22830"}
            />
          </div>
          <div className="flex items-end">
            <Button
              type="submit"
              variant="outline"
              disabled={save.isPending || form === null}
            >
              {save.isPending ? "Guardando…" : "Guardar encabezado"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

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

// --- Cartera vencida (cobranza) -------------------------------------------------------

type AgingBucket = AgingRow["bucket"];

function CarteraVencidaTab() {
  const navigate = useNavigate();
  const { data: aging, isLoading, isError } = useQuery({
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

  if (isError) {
    return (
      <EmptyState
        icon={Check}
        title="No se pudo cargar la cartera vencida"
        description="Ocurrió un error al consultar los cargos. Intente de nuevo."
      />
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
    <div className="space-y-4">
      <h2 className="text-xl font-bold">
        Cartera vencida{" "}
        <span className="text-muted-foreground" data-numeric>
          · {formatMoney(total)}
        </span>
      </h2>
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
            {rows.map((r) => (
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
      </div>
    </div>
  );
}

// --- Conceptos (incluye recargos como sección) ----------------------------------------

function ConceptosTab() {
  const queryClient = useQueryClient();
  const { data: concepts, isLoading } = useQuery({
    queryKey: queryKeys.concepts,
    queryFn: () => api<ChargeConcept[]>("/treasury/concepts"),
  });
  const { data: programs } = useQuery({
    queryKey: queryKeys.programs,
    queryFn: () => api<Program[]>("/catalog/programs"),
  });

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: "",
    kind: "colegiatura" as ChargeConceptKind,
    amount: "",
    program_id: NONE,
    modality: NONE,
    is_active: true,
  });

  const save = useMutation({
    mutationFn: () =>
      api<ChargeConcept>("/treasury/concepts", {
        method: "POST",
        body: JSON.stringify({
          name: form.name,
          kind: form.kind,
          amount: Number(form.amount),
          program_id: form.program_id === NONE ? null : form.program_id,
          modality: form.modality === NONE ? null : form.modality,
          is_active: form.is_active,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.concepts });
      toast.success("Concepto creado");
      setOpen(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  const programName = (id?: string | null) =>
    id ? (programs?.find((p) => p.id === id)?.name ?? "—") : "Todos";

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <Button
          className="font-bold"
          onClick={() => {
            setForm({
              name: "",
              kind: "colegiatura",
              amount: "",
              program_id: NONE,
              modality: NONE,
              is_active: true,
            });
            setOpen(true);
          }}
        >
          <Plus className="size-4" /> Nuevo concepto
        </Button>
      </div>

      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nombre</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>Importe</TableHead>
              <TableHead>Programa</TableHead>
              <TableHead>Modalidad</TableHead>
              <TableHead>Estado</TableHead>
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
            {concepts?.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="font-semibold">{c.name}</TableCell>
                <TableCell>
                  <Badge variant="secondary">{CONCEPT_KIND_LABELS[c.kind]}</Badge>
                </TableCell>
                <TableCell data-numeric className="font-semibold">
                  {formatMoney(c.amount)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {programName(c.program_id)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {c.modality ? MODALITY_LABELS[c.modality] : "Todas"}
                </TableCell>
                <TableCell>
                  <Badge variant={c.is_active ? "outline" : "destructive"}>
                    {c.is_active ? "Activo" : "Inactivo"}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
            {concepts && concepts.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="py-10 text-center text-muted-foreground"
                >
                  Sin conceptos de cobro
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <RecargosSection />

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuevo concepto de cobro</DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="c-name">Nombre</Label>
              <Input
                id="c-name"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Colegiatura licenciatura 2026"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>Tipo</Label>
                <Select
                  value={form.kind}
                  onValueChange={(v) => setForm({ ...form, kind: v as ChargeConceptKind })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(CONCEPT_KIND_LABELS) as ChargeConceptKind[]).map((k) => (
                      <SelectItem key={k} value={k}>
                        {CONCEPT_KIND_LABELS[k]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="c-amount">Importe</Label>
                <Input
                  id="c-amount"
                  type="number"
                  min={0}
                  step="0.01"
                  required
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>Programa (opcional)</Label>
                <Select
                  value={form.program_id}
                  onValueChange={(v) => setForm({ ...form, program_id: v })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>Todos los programas</SelectItem>
                    {programs?.map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label>Modalidad (opcional)</Label>
                <Select
                  value={form.modality}
                  onValueChange={(v) => setForm({ ...form, modality: v })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>Todas las modalidades</SelectItem>
                    {(Object.keys(MODALITY_LABELS) as Modality[]).map((m) => (
                      <SelectItem key={m} value={m}>
                        {MODALITY_LABELS[m]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm font-medium">
              <Checkbox
                checked={form.is_active}
                onCheckedChange={(v) => setForm({ ...form, is_active: v === true })}
              />
              Concepto activo
            </label>
            <DialogFooter>
              <Button type="submit" className="font-bold" disabled={save.isPending}>
                {save.isPending ? "Guardando…" : "Guardar"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function RecargosSection() {
  const queryClient = useQueryClient();
  const { data: institution } = useInstitution();

  const run = useMutation({
    mutationFn: () =>
      api<{ created: number; scholarships_suspended: number }>(
        "/treasury/late-fees/run",
        { method: "POST" },
      ),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.aging });
      const parts = [
        res.created > 0
          ? `${res.created} recargos generados`
          : "Sin cargos vencidos que generen recargo",
      ];
      if (res.scholarships_suspended > 0)
        parts.push(`${res.scholarships_suspended} becas suspendidas`);
      toast.success(parts.join(" · "));
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al aplicar recargos"),
  });

  return (
    <Card className="rounded-md border-dashed">
      <CardContent className="space-y-3 p-6">
        <div className="flex items-center gap-2">
          <Badge variant="secondary">{CONCEPT_KIND_LABELS.recargo}</Badge>
          <h2 className="text-lg font-bold">Recargos por mora</h2>
        </div>
        <p className="max-w-2xl text-sm text-muted-foreground">
          El recargo es un concepto especial que se genera automáticamente para
          los adeudos vencidos según la configuración institucional
          {institution && (
            <>
              {" "}
              (<span data-numeric>{institution.late_fee_pct}%</span> tras{" "}
              <span data-numeric>{institution.late_fee_grace_days}</span> días de
              gracia)
            </>
          )}
          . Los cargos con beca dentro de su periodo de tolerancia no generan
          recargo; al vencer la tolerancia se pierde la beca. No se duplican.
        </p>
        <Button className="font-bold" disabled={run.isPending} onClick={() => run.mutate()}>
          <AlarmClock className="size-4" />
          {run.isPending ? "Aplicando…" : "Aplicar recargos"}
        </Button>
      </CardContent>
    </Card>
  );
}

// --- Becas (gestión y autorización) ---------------------------------------------------

const BECA_FILTERS: { value: ScholarshipStatus | "all"; label: string }[] = [
  { value: "solicitada", label: "Por autorizar" },
  { value: "activa", label: "Activas" },
  { value: "suspendida", label: "Suspendidas" },
  { value: "all", label: "Todas" },
];

function BecasTab() {
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const canAuthorize =
    me?.is_superuser || me?.role === "admin_sistema" || me?.role === "direccion";
  const [filter, setFilter] = usePersistedState<ScholarshipStatus | "all">(
    "tesoreria-becas-status-v1",
    "solicitada",
    (v) => BECA_FILTERS.some((f) => f.value === v),
  );
  const [students, setStudents] = useState<Record<string, Student>>({});

  const { data: scholarships, isLoading } = useQuery({
    queryKey: queryKeys.scholarshipsByStatus(filter),
    queryFn: async () => {
      const qs = filter === "all" ? "" : `?status=${filter}`;
      const list = await api<Scholarship[]>(`/treasury/scholarships${qs}`);
      // Resolve student names lazily (small pending lists).
      const missing = [...new Set(list.map((s) => s.student_id))].filter(
        (id) => !students[id],
      );
      if (missing.length) {
        const fetched = await Promise.all(
          missing.map((id) =>
            api<Student>(`/students/${id}`).catch(() => null),
          ),
        );
        setStudents((prev) => {
          const next = { ...prev };
          for (const s of fetched) if (s) next[s.id] = s;
          return next;
        });
      }
      return list;
    },
  });

  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "authorize" | "reject" }) =>
      api(`/treasury/scholarships/${id}/${action}`, { method: "POST" }),
    onSuccess: (_d, { action }) => {
      queryClient.invalidateQueries({ queryKey: ["scholarships"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.scholarshipReport });
      toast.success(action === "authorize" ? "Beca autorizada" : "Beca rechazada");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error"),
  });

  const value = (s: Scholarship) =>
    s.pct != null ? `${s.pct}%` : formatMoney(s.fixed_amount);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 rounded-md border p-1">
          {BECA_FILTERS.map((f) => (
            <Button
              key={f.value}
              size="sm"
              variant={filter === f.value ? "default" : "ghost"}
              onClick={() => setFilter(f.value)}
            >
              {f.label}
            </Button>
          ))}
        </div>
        {!canAuthorize && (
          <p className="text-xs text-muted-foreground">
            Solo Dirección o Administración pueden autorizar becas.
          </p>
        )}
      </div>

      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Alumno</TableHead>
              <TableHead>Beca</TableHead>
              <TableHead>Valor</TableHead>
              <TableHead>Tolerancia</TableHead>
              <TableHead>Vigencia</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead className="text-right">Acción</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={7}>
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            )}
            {scholarships?.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="font-semibold">
                  {students[s.student_id]?.full_name ?? "…"}
                  <span className="ml-2 text-xs text-muted-foreground" data-numeric>
                    {students[s.student_id]?.enrollment_number}
                  </span>
                </TableCell>
                <TableCell>{s.name}</TableCell>
                <TableCell data-numeric className="font-semibold">
                  {value(s)}
                </TableCell>
                <TableCell data-numeric>{s.tolerance_days} días</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {formatDate(s.valid_from)}
                  {s.valid_to ? ` – ${formatDate(s.valid_to)}` : ""}
                </TableCell>
                <TableCell>
                  <Badge
                    variant={
                      s.status === "activa"
                        ? "outline"
                        : s.status === "solicitada"
                          ? "secondary"
                          : "destructive"
                    }
                  >
                    {SCHOLARSHIP_STATUS_LABELS[s.status]}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  {s.status === "solicitada" && canAuthorize ? (
                    <div className="flex justify-end gap-2">
                      <Button
                        size="sm"
                        disabled={act.isPending}
                        onClick={() => act.mutate({ id: s.id, action: "authorize" })}
                      >
                        <Check className="size-4" /> Autorizar
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={act.isPending}
                        onClick={() => act.mutate({ id: s.id, action: "reject" })}
                      >
                        <X className="size-4" /> Rechazar
                      </Button>
                    </div>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {scholarships && scholarships.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                  Sin becas en este filtro
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

// --- Reportes -----------------------------------------------------------------------

function ReportesTab() {
  const [range, setRange] = useState<DateRange>(() => presetRange("mes"));
  const { data: terms } = useQuery({
    queryKey: queryKeys.terms,
    queryFn: () => api<Term[]>("/catalog/terms"),
  });
  const [sepTermId, setSepTermId] = useState<string>("");

  const { data: collection, isLoading: loadingCollection } = useQuery({
    queryKey: queryKeys.collectionReport(range.from, range.to),
    queryFn: () =>
      api<CollectionReport>(
        `/treasury/reports/collection?date_from=${range.from}&date_to=${range.to}`,
      ),
  });
  const { data: aging, isLoading: loadingAging } = useQuery({
    queryKey: queryKeys.aging,
    queryFn: () => api<AgingRow[]>("/treasury/reports/aging"),
  });
  const { data: becas } = useQuery({
    queryKey: queryKeys.scholarshipReport,
    queryFn: () => api<ScholarshipReport>("/treasury/reports/scholarships"),
  });

  const agingTotal = aging?.reduce((sum, r) => sum + r.balance, 0) ?? 0;
  const effectiveSepTerm = sepTermId || terms?.find((t) => t.is_open)?.id || "";

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h2 className="text-xl font-bold">Becas</h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Alumnos con beca" value={becas?.students_with_scholarship} />
          <MetricCard
            label="% de becados"
            value={becas ? `${becas.pct_with_scholarship}%` : undefined}
          />
          <MetricCard
            label="Beca aplicada · mes"
            value={becas ? formatMoney(becas.beca_mes) : undefined}
          />
          <MetricCard
            label="Beca aplicada · cuatrimestre"
            value={becas ? formatMoney(becas.beca_cuatrimestre) : undefined}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Montos acumulados hasta hoy (no proyectados). De {becas?.active_students ?? 0}{" "}
          alumnos activos.
        </p>
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-bold">Cobranza</h2>
          <DateRangeFilter value={range} onChange={setRange} />
        </div>
        {loadingCollection ? (
          <Skeleton className="h-32 w-full rounded-md" />
        ) : collection ? (
          <Card className="rounded-md">
            <CardContent className="flex flex-wrap items-start gap-8 p-6">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Periodo
                </p>
                <p className="font-bold">
                  {formatDate(collection.date_from)} – {formatDate(collection.date_to)}
                </p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Pagos recibidos
                </p>
                <p className="text-2xl font-bold" data-numeric>
                  {collection.payments_count}
                </p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Total cobrado
                </p>
                <p className="text-2xl font-bold" data-numeric>
                  {formatMoney(collection.total)}
                </p>
              </div>
              <div className="min-w-48">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Por método
                </p>
                {Object.entries(collection.by_method).length === 0 && (
                  <p className="text-sm text-muted-foreground">Sin pagos</p>
                )}
                {Object.entries(collection.by_method).map(([method, total]) => (
                  <p key={method} className="flex justify-between gap-6 text-sm">
                    <span>
                      {PAYMENT_METHOD_LABELS[
                        method as keyof typeof PAYMENT_METHOD_LABELS
                      ] ?? method}
                    </span>
                    <span data-numeric className="font-semibold">
                      {formatMoney(total)}
                    </span>
                  </p>
                ))}
              </div>
              <div className="ml-auto">
                <Button variant="outline" asChild>
                  <a
                    href={`/api/v1/treasury/exports/movements?date_from=${range.from}&date_to=${range.to}`}
                    download
                  >
                    <Download className="size-4" /> Exportar movimientos (CSV)
                  </a>
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : null}
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-bold">
            Cartera vencida{" "}
            <span className="text-muted-foreground" data-numeric>
              · {formatMoney(agingTotal)}
            </span>
          </h2>
        </div>
        <div className="rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Matrícula</TableHead>
                <TableHead>Alumno</TableHead>
                <TableHead>Concepto</TableHead>
                <TableHead>Venció</TableHead>
                <TableHead>Días</TableHead>
                <TableHead>Antigüedad</TableHead>
                <TableHead>Saldo</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loadingAging && (
                <TableRow>
                  <TableCell colSpan={7}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              )}
              {aging?.map((r, i) => (
                <TableRow key={`${r.student_id}-${i}`}>
                  <TableCell data-numeric>{r.enrollment_number}</TableCell>
                  <TableCell className="font-semibold">{r.student_name}</TableCell>
                  <TableCell className="max-w-64 truncate">{r.description}</TableCell>
                  <TableCell>{formatDate(r.due_date)}</TableCell>
                  <TableCell data-numeric>{r.days_overdue}</TableCell>
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
                      {r.bucket} días
                    </Badge>
                  </TableCell>
                  <TableCell data-numeric className="font-semibold">
                    {formatMoney(r.balance)}
                  </TableCell>
                </TableRow>
              ))}
              {aging && aging.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                    No hay cargos vencidos
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-bold">Exportación SEP</h2>
        <Card className="rounded-md">
          <CardContent className="flex flex-wrap items-center gap-3 p-6">
            <Label className="text-sm font-semibold">Ciclo</Label>
            <Select value={effectiveSepTerm} onValueChange={setSepTermId}>
              <SelectTrigger className="w-64">
                <SelectValue placeholder="Seleccione un ciclo" />
              </SelectTrigger>
              <SelectContent>
                {terms?.map((t) => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" disabled={!effectiveSepTerm} asChild>
              <a
                href={`/api/v1/students/exports/sep?term_id=${effectiveSepTerm}`}
                download
              >
                <Download className="size-4" /> Exportar alumnos SEP (CSV)
              </a>
            </Button>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value?: number | string }) {
  return (
    <Card className="rounded-md">
      <CardContent className="p-5">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        {value == null ? (
          <Skeleton className="mt-2 h-8 w-20" />
        ) : (
          <p className="mt-1 text-3xl font-bold" data-numeric>
            {value}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
