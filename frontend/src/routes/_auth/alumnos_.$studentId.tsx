import { useEffect, useMemo, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowLeft,
  BadgeDollarSign,
  CalendarDays,
  Check,
  Eye,
  FilePlus,
  FileText,
  Pencil,
  Plus,
  TriangleAlertIcon,
  Upload,
  X,
} from "lucide-react";
import { api, apiUpload, ApiError, getStudentCalendar } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  AccountStatement,
  Campus,
  Charge,
  ChargeConcept,
  Expediente,
  Institution,
  IssuedDocumentKind,
  Justification,
  Kardex,
  Payment,
  PaymentMethod,
  PlanEnrollment,
  PlanVersion,
  Program,
  Requirement,
  Rvoe,
  Scholarship,
  Student,
  StudentStatus,
  Term,
  UserPublic,
} from "@/api/types";
import { paymentToReceiptData, printReceipt } from "@/lib/receipt";
import {
  ADMISSION_TYPE_LABELS,
  CHARGE_STATUS_LABELS,
  formatDate,
  formatDateTime,
  formatMoney,
  ISSUED_DOC_KIND_LABELS,
  JUSTIFICATION_STATUS_LABELS,
  PAYMENT_METHOD_LABELS,
  PLAN_ENROLLMENT_STATUS_LABELS,
  REVIEW_STATUS_LABELS,
  SCHOLARSHIP_STATUS_LABELS,
  STUDENT_STATUS_LABELS,
  SUBJECT_STATUS_LABELS,
  todayISO,
} from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { SearchableSelect } from "@/components/searchable-select";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
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
  DialogDescription,
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

export const Route = createFileRoute("/_auth/alumnos_/$studentId")({
  component: AlumnoDetailPage,
});

const NONE = "__none__";

function AlumnoDetailPage() {
  const { studentId } = Route.useParams();
  const { data: student, isLoading, error } = useQuery({
    queryKey: queryKeys.student(studentId),
    queryFn: () => api<Student>(`/students/${studentId}`),
  });

  if (error) {
    return (
      <EmptyState
        icon={TriangleAlertIcon}
        title="No se pudo cargar el alumno"
        description={
          error instanceof ApiError ? error.message : "Intenta de nuevo más tarde."
        }
      >
        <Button variant="outline" asChild>
          <Link to="/alumnos">Volver a alumnos</Link>
        </Button>
      </EmptyState>
    );
  }

  if (isLoading || !student) {
    return <Skeleton className="h-96 w-full rounded-2xl" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="icon-sm" asChild aria-label="Volver">
          <Link to="/alumnos">
            <ArrowLeft className="size-4" />
          </Link>
        </Button>
        <h1 className="text-3xl">{student.full_name}</h1>
        <Badge variant="secondary" data-numeric>
          {student.enrollment_number}
        </Badge>
        <Badge
          variant={
            student.status === "activo"
              ? "default"
              : student.status === "baja_definitiva"
                ? "destructive"
                : "outline"
          }
        >
          {STUDENT_STATUS_LABELS[student.status]}
        </Badge>
      </div>

      <Tabs defaultValue="datos">
        <TabsList>
          <TabsTrigger value="datos">Datos</TabsTrigger>
          <TabsTrigger value="expediente">Expediente</TabsTrigger>
          <TabsTrigger value="academico">Académico</TabsTrigger>
          <TabsTrigger value="horario">Horario</TabsTrigger>
          <TabsTrigger value="cuenta">Estado de cuenta</TabsTrigger>
          <TabsTrigger value="justificantes">Justificantes</TabsTrigger>
        </TabsList>
        <TabsContent value="datos" className="mt-4">
          <DatosTab student={student} />
        </TabsContent>
        <TabsContent value="expediente" className="mt-4">
          <ExpedienteTab student={student} />
        </TabsContent>
        <TabsContent value="academico" className="mt-4">
          <AcademicoTab student={student} />
        </TabsContent>
        <TabsContent value="horario" className="mt-4">
          <HorarioTab student={student} />
        </TabsContent>
        <TabsContent value="cuenta" className="mt-4">
          <CuentaTab student={student} />
        </TabsContent>
        <TabsContent value="justificantes" className="mt-4">
          <JustificantesTab student={student} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2 text-sm">
      <span className="w-40 shrink-0 font-semibold text-muted-foreground">
        {label}
      </span>
      <span>{value}</span>
    </div>
  );
}

// --- Datos -----------------------------------------------------------------

function DatosTab({ student }: { student: Student }) {
  const queryClient = useQueryClient();
  const { data: campuses } = useQuery({
    queryKey: queryKeys.campuses,
    queryFn: () => api<Campus[]>("/catalog/campuses"),
  });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    full_name: student.full_name,
    email: student.email,
    phone: student.phone,
    status: student.status as StudentStatus,
    campus_id: student.campus_id,
  });

  const save = useMutation({
    mutationFn: () =>
      api<Student>(`/students/${student.id}`, {
        method: "PATCH",
        body: JSON.stringify(form),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.student(student.id) });
      queryClient.invalidateQueries({ queryKey: ["students"] });
      toast.success("Alumno actualizado");
      setOpen(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  const campusName =
    campuses?.find((c) => c.id === student.campus_id)?.name ?? "—";

  return (
    <Card className="rounded-2xl">
      <CardContent className="space-y-3 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold">Datos generales</h2>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setForm({
                full_name: student.full_name,
                email: student.email,
                phone: student.phone,
                status: student.status,
                campus_id: student.campus_id,
              });
              setOpen(true);
            }}
          >
            <Pencil className="size-4" /> Editar
          </Button>
        </div>
        <DetailRow label="CURP" value={student.curp} />
        <DetailRow label="Matrícula" value={student.enrollment_number} />
        <DetailRow label="Email" value={student.email || "—"} />
        <DetailRow label="Teléfono" value={student.phone || "—"} />
        <DetailRow label="Campus" value={campusName} />
        <DetailRow
          label="Tipo de ingreso"
          value={ADMISSION_TYPE_LABELS[student.admission_type]}
        />
        <DetailRow
          label="Registrado"
          value={formatDateTime(student.created_at)}
        />

        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Editar alumno</DialogTitle>
            </DialogHeader>
            <form
              className="grid gap-4"
              onSubmit={(e) => {
                e.preventDefault();
                save.mutate();
              }}
            >
              <div className="grid gap-2">
                <Label htmlFor="d-name">Nombre completo</Label>
                <Input
                  id="d-name"
                  required
                  value={form.full_name}
                  onChange={(e) =>
                    setForm({ ...form, full_name: e.target.value })
                  }
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="d-email">Email</Label>
                  <Input
                    id="d-email"
                    type="email"
                    value={form.email}
                    onChange={(e) =>
                      setForm({ ...form, email: e.target.value })
                    }
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="d-phone">Teléfono</Label>
                  <Input
                    id="d-phone"
                    value={form.phone}
                    onChange={(e) =>
                      setForm({ ...form, phone: e.target.value })
                    }
                  />
                </div>
              </div>
              <div className="grid gap-2">
                <Label>Campus</Label>
                <Select
                  value={form.campus_id}
                  onValueChange={(v) => setForm({ ...form, campus_id: v })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {campuses?.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label>Estatus</Label>
                <Select
                  value={form.status}
                  onValueChange={(v) =>
                    setForm({ ...form, status: v as StudentStatus })
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(
                      Object.keys(STUDENT_STATUS_LABELS) as StudentStatus[]
                    ).map((s) => (
                      <SelectItem key={s} value={s}>
                        {STUDENT_STATUS_LABELS[s]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <DialogFooter>
                <Button
                  type="submit"
                  className="font-bold"
                  disabled={save.isPending}
                >
                  {save.isPending ? "Guardando…" : "Guardar"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}

// --- Expediente --------------------------------------------------------------

function ExpedienteTab({ student }: { student: Student }) {
  const queryClient = useQueryClient();
  const { data: expediente, isLoading, error } = useQuery({
    queryKey: queryKeys.expediente(student.id),
    queryFn: () => api<Expediente>(`/documents/students/${student.id}/expediente`),
  });
  const { data: requirements } = useQuery({
    queryKey: queryKeys.requirements,
    queryFn: () => api<Requirement[]>("/documents/requirements"),
  });

  const [uploadOpen, setUploadOpen] = useState(false);
  const [issueOpen, setIssueOpen] = useState(false);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");

  const review = useMutation({
    mutationFn: ({
      documentId,
      status,
      reason,
    }: {
      documentId: string;
      status: "aceptado" | "rechazado";
      reason?: string;
    }) =>
      api(`/documents/student-documents/${documentId}/review`, {
        method: "POST",
        body: JSON.stringify({ status, reject_reason: reason ?? "" }),
      }),
    onSuccess: (_, { status }) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.expediente(student.id),
      });
      toast.success(
        status === "aceptado" ? "Documento aceptado" : "Documento rechazado",
      );
      setRejecting(null);
      setRejectReason("");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al revisar"),
  });

  if (error) {
    return (
      <EmptyState
        icon={TriangleAlertIcon}
        title="No se pudo cargar el expediente"
        description={
          error instanceof ApiError ? error.message : "Intenta de nuevo más tarde."
        }
      />
    );
  }
  if (isLoading || !expediente) {
    return <Skeleton className="h-64 w-full rounded-2xl" />;
  }

  return (
    <div className="space-y-6">
      {expediente.overdue_balance > 0 && (
        <p className="rounded-xl border border-destructive/40 bg-red-50 px-4 py-3 text-sm font-semibold text-destructive dark:bg-destructive/10">
          El alumno tiene adeudo vencido por{" "}
          {formatMoney(expediente.overdue_balance)}. La emisión de documentos
          oficiales puede estar bloqueada.
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="rounded-2xl">
          <CardContent className="space-y-3 p-6">
            <h2 className="text-lg font-bold">Checklist de requisitos</h2>
            {expediente.checklist.length === 0 && (
              <p className="text-sm text-muted-foreground">
                No hay requisitos configurados.
              </p>
            )}
            {expediente.checklist.map((item) => (
              <div
                key={item.requirement_id}
                className="flex items-center gap-3 text-sm"
              >
                {item.delivered ? (
                  <Check className="size-4 text-green-600" />
                ) : (
                  <X className="size-4 text-destructive" />
                )}
                <span className="font-semibold">{item.name}</span>
                <span className="ml-auto flex gap-2">
                  {item.required && <Badge variant="outline">Obligatorio</Badge>}
                  <Badge variant={item.delivered ? "secondary" : "destructive"}>
                    {item.delivered ? "Entregado" : "Pendiente"}
                  </Badge>
                </span>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="rounded-2xl">
          <CardContent className="space-y-3 p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold">Documentos emitidos</h2>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setIssueOpen(true)}
              >
                <FilePlus className="size-4" /> Emitir documento
              </Button>
            </div>
            {expediente.issued_documents.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Sin documentos emitidos.
              </p>
            )}
            {expediente.issued_documents.map((d) => (
              <div key={d.id} className="flex items-center gap-3 text-sm">
                <FileText className="size-4 text-muted-foreground" />
                <span className="font-semibold">
                  {ISSUED_DOC_KIND_LABELS[d.kind]}
                </span>
                <span className="ml-auto text-muted-foreground" data-numeric>
                  {d.folio}
                </span>
                <span className="text-muted-foreground">
                  {formatDate(d.issued_at)}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold">Documentos entregados</h2>
          <Button variant="outline" onClick={() => setUploadOpen(true)}>
            <Upload className="size-4" /> Subir documento
          </Button>
        </div>
        <div className="rounded-2xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Documento</TableHead>
                <TableHead>Archivo</TableHead>
                <TableHead>Versión</TableHead>
                <TableHead>Subido</TableHead>
                <TableHead>Revisión</TableHead>
                <TableHead className="w-40" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {expediente.documents.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="font-semibold">{d.title}</TableCell>
                  <TableCell className="max-w-52 truncate text-muted-foreground">
                    {d.filename}
                  </TableCell>
                  <TableCell data-numeric>v{d.version}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(d.uploaded_at)}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        d.status === "aceptado"
                          ? "default"
                          : d.status === "rechazado"
                            ? "destructive"
                            : "outline"
                      }
                      title={d.reject_reason || undefined}
                    >
                      {REVIEW_STATUS_LABELS[d.status]}
                    </Badge>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    <Button variant="ghost" size="sm" asChild>
                      <a
                        href={`/api/v1/documents/files/${d.id}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <Eye className="size-4" /> Ver
                      </a>
                    </Button>
                    {d.status === "pendiente" && (
                      <>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={review.isPending}
                          onClick={() =>
                            review.mutate({
                              documentId: d.id,
                              status: "aceptado",
                            })
                          }
                        >
                          <Check className="size-4 text-green-600" /> Aceptar
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={review.isPending}
                          onClick={() => setRejecting(d.id)}
                        >
                          <X className="size-4 text-destructive" /> Rechazar
                        </Button>
                      </>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {expediente.documents.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="py-8 text-center text-muted-foreground"
                  >
                    Sin documentos entregados
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </section>

      <UploadDocumentDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        student={student}
        requirements={requirements ?? []}
      />
      <IssueDocumentDialog
        open={issueOpen}
        onOpenChange={setIssueOpen}
        student={student}
      />

      <Dialog
        open={!!rejecting}
        onOpenChange={(v) => {
          if (!v) setRejecting(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rechazar documento</DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (rejecting)
                review.mutate({
                  documentId: rejecting,
                  status: "rechazado",
                  reason: rejectReason,
                });
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="reject-reason">Motivo de rechazo</Label>
              <Textarea
                id="reject-reason"
                required
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
              />
            </div>
            <DialogFooter>
              <Button
                type="submit"
                variant="destructive"
                className="font-bold"
                disabled={review.isPending}
              >
                {review.isPending ? "Rechazando…" : "Rechazar"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function UploadDocumentDialog({
  open,
  onOpenChange,
  student,
  requirements,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  student: Student;
  requirements: Requirement[];
}) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [requirementId, setRequirementId] = useState(NONE);
  const [file, setFile] = useState<File | null>(null);

  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("file", file!);
      const params = new URLSearchParams({ title });
      if (requirementId !== NONE) params.set("requirement_id", requirementId);
      return apiUpload(
        `/documents/students/${student.id}/documents?${params}`,
        form,
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.expediente(student.id),
      });
      toast.success("Documento subido");
      setTitle("");
      setRequirementId(NONE);
      setFile(null);
      onOpenChange(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al subir"),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Subir documento</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!file) {
              toast.error("Seleccione un archivo");
              return;
            }
            upload.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="u-title">Título</Label>
            <Input
              id="u-title"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Acta de nacimiento"
            />
          </div>
          <div className="grid gap-2">
            <Label>Requisito (opcional)</Label>
            <Select
              value={requirementId}
              onValueChange={(v) => {
                setRequirementId(v);
                // default the title to the requirement name (unless already typed)
                const r = requirements.find((x) => x.id === v);
                if (r && !title.trim()) setTitle(r.name);
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Sin requisito asociado</SelectItem>
                {requirements.map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    {r.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="u-file">Archivo</Label>
            <Input
              id="u-file"
              type="file"
              required
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <DialogFooter>
            <Button
              type="submit"
              className="font-bold"
              disabled={upload.isPending}
            >
              {upload.isPending ? "Subiendo…" : "Subir"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function IssueDocumentDialog({
  open,
  onOpenChange,
  student,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  student: Student;
}) {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<IssuedDocumentKind>("constancia_estudios");
  const [planVersionId, setPlanVersionId] = useState(NONE);
  const [notes, setNotes] = useState("");

  const { data: enrollments } = useQuery({
    queryKey: queryKeys.planEnrollments(student.id),
    queryFn: () =>
      api<PlanEnrollment[]>(`/students/${student.id}/plan-enrollments`),
    enabled: open,
  });
  // a student usually has one plan — default to it instead of "sin plan"
  useEffect(() => {
    if (planVersionId === NONE && enrollments?.length === 1) {
      setPlanVersionId(enrollments[0].plan_version_id);
    }
  }, [enrollments, planVersionId]);
  const planVersionLabels = usePlanVersionLabels();

  const issue = useMutation({
    mutationFn: () =>
      api(`/documents/issue`, {
        method: "POST",
        body: JSON.stringify({
          student_id: student.id,
          kind,
          plan_version_id: planVersionId === NONE ? null : planVersionId,
          notes,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.expediente(student.id),
      });
      toast.success("Documento emitido con folio");
      onOpenChange(false);
    },
    onError: (e) =>
      toast.error(
        e instanceof ApiError && e.status === 409
          ? `Emisión bloqueada: ${e.message}`
          : e instanceof ApiError
            ? e.message
            : "Error al emitir",
      ),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Emitir documento oficial</DialogTitle>
          <DialogDescription>
            Se asignará un folio consecutivo. Si el alumno tiene adeudo vencido
            la emisión será rechazada.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            issue.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label>Tipo de documento</Label>
            <Select
              value={kind}
              onValueChange={(v) => setKind(v as IssuedDocumentKind)}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(
                  Object.keys(ISSUED_DOC_KIND_LABELS) as IssuedDocumentKind[]
                ).map((k) => (
                  <SelectItem key={k} value={k}>
                    {ISSUED_DOC_KIND_LABELS[k]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label>Plan de estudios (para kárdex y certificados)</Label>
            <Select value={planVersionId} onValueChange={setPlanVersionId}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Sin plan específico</SelectItem>
                {enrollments?.map((en) => (
                  <SelectItem key={en.id} value={en.plan_version_id}>
                    {planVersionLabels.get(en.plan_version_id) ??
                      en.plan_version_id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="i-notes">Notas</Label>
            <Input
              id="i-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              type="submit"
              className="font-bold"
              disabled={issue.isPending}
            >
              {issue.isPending ? "Emitiendo…" : "Emitir"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// --- Académico -----------------------------------------------------------------

/** plan_version_id -> "Programa · RVOE · Plan" */
function usePlanVersionLabels(): Map<string, string> {
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

  return useMemo(() => {
    const map = new Map<string, string>();
    for (const pv of planVersions ?? []) {
      const rvoe = rvoes?.find((r) => r.id === pv.rvoe_id);
      const program = programs?.find((p) => p.id === rvoe?.program_id);
      map.set(
        pv.id,
        `${program?.name ?? "?"} · RVOE ${rvoe?.agreement_number ?? "?"} · Plan ${pv.version_label}`,
      );
    }
    return map;
  }, [planVersions, rvoes, programs]);
}

function AcademicoTab({ student }: { student: Student }) {
  const queryClient = useQueryClient();
  const planVersionLabels = usePlanVersionLabels();

  const { data: enrollments, isLoading } = useQuery({
    queryKey: queryKeys.planEnrollments(student.id),
    queryFn: () =>
      api<PlanEnrollment[]>(`/students/${student.id}/plan-enrollments`),
  });
  const { data: terms } = useQuery({
    queryKey: queryKeys.terms,
    queryFn: () => api<Term[]>("/catalog/terms"),
  });

  const [selectedPlan, setSelectedPlan] = useState<string | null>(null);
  const planVersionId = selectedPlan ?? enrollments?.[0]?.plan_version_id ?? null;

  const { data: kardex, isLoading: loadingKardex } = useQuery({
    queryKey: queryKeys.kardex(student.id, planVersionId ?? ""),
    queryFn: () =>
      api<Kardex>(
        `/grades/students/${student.id}/kardex?plan_version_id=${planVersionId}`,
      ),
    enabled: !!planVersionId,
  });

  // Inscribir a plan
  const [open, setOpen] = useState(false);
  const [newPlanId, setNewPlanId] = useState("");
  const [startTermId, setStartTermId] = useState("");

  const enroll = useMutation({
    mutationFn: () =>
      api(`/students/plan-enrollments`, {
        method: "POST",
        body: JSON.stringify({
          student_id: student.id,
          plan_version_id: newPlanId,
          start_term_id: startTermId,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.planEnrollments(student.id),
      });
      toast.success("Alumno inscrito al plan");
      setOpen(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al inscribir"),
  });

  const termName = (id: string) => terms?.find((t) => t.id === id)?.name ?? "—";
  const planOptions = [...planVersionLabels.entries()].map(([value, label]) => ({
    value,
    label,
  }));

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold">Planes de estudio</h2>
          <Button
            variant="outline"
            onClick={() => {
              setNewPlanId("");
              setStartTermId(terms?.find((t) => t.is_open)?.id ?? "");
              setOpen(true);
            }}
          >
            <Plus className="size-4" /> Inscribir a plan
          </Button>
        </div>
        <div className="rounded-2xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Plan</TableHead>
                <TableHead>Ciclo de inicio</TableHead>
                <TableHead>Estatus</TableHead>
                <TableHead>Inscrito</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && (
                <TableRow>
                  <TableCell colSpan={4}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              )}
              {enrollments?.map((en) => (
                <TableRow
                  key={en.id}
                  className={
                    en.plan_version_id === planVersionId
                      ? "bg-muted/60"
                      : "cursor-pointer"
                  }
                  onClick={() => setSelectedPlan(en.plan_version_id)}
                >
                  <TableCell className="font-semibold">
                    {planVersionLabels.get(en.plan_version_id) ??
                      en.plan_version_id}
                  </TableCell>
                  <TableCell>{termName(en.start_term_id)}</TableCell>
                  <TableCell>
                    <Badge
                      variant={en.status === "inscrito" ? "default" : "outline"}
                    >
                      {PLAN_ENROLLMENT_STATUS_LABELS[en.status]}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(en.created_at)}
                  </TableCell>
                </TableRow>
              ))}
              {enrollments && enrollments.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="py-8 text-center text-muted-foreground"
                  >
                    El alumno no está inscrito a ningún plan
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </section>

      {planVersionId && (
        <section className="space-y-3">
          <h2 className="text-xl font-bold">Kárdex</h2>
          {loadingKardex && <Skeleton className="h-40 w-full rounded-2xl" />}
          {kardex && (
            <>
              <Card className="rounded-2xl">
                <CardContent className="space-y-3 p-6">
                  <div className="flex flex-wrap items-center gap-x-8 gap-y-2 text-sm">
                    <span>
                      <span className="font-semibold text-muted-foreground">
                        Créditos:{" "}
                      </span>
                      <span data-numeric>
                        {kardex.progress.earned_credits} /{" "}
                        {kardex.progress.total_credits}
                      </span>
                    </span>
                    <span>
                      <span className="font-semibold text-muted-foreground">
                        Materias aprobadas:{" "}
                      </span>
                      <span data-numeric>
                        {kardex.progress.passed_subjects} /{" "}
                        {kardex.progress.total_subjects}
                      </span>
                    </span>
                    <span>
                      <span className="font-semibold text-muted-foreground">
                        Promedio:{" "}
                      </span>
                      <span data-numeric>{kardex.progress.gpa ?? "—"}</span>
                    </span>
                    {kardex.progress.eligible_for_degree && (
                      <Badge variant="default">Elegible para titulación</Badge>
                    )}
                  </div>
                  <div>
                    <div className="mb-1 flex justify-between text-xs font-semibold text-muted-foreground">
                      <span>Avance curricular</span>
                      <span data-numeric>
                        {kardex.progress.credit_progress_pct}%
                      </span>
                    </div>
                    <div
                      className="h-3 w-full overflow-hidden rounded-full bg-muted"
                      role="progressbar"
                      aria-valuenow={kardex.progress.credit_progress_pct}
                      aria-valuemin={0}
                      aria-valuemax={100}
                    >
                      <div
                        className="h-full rounded-full bg-primary transition-[width]"
                        style={{
                          width: `${Math.min(kardex.progress.credit_progress_pct, 100)}%`,
                        }}
                      />
                    </div>
                  </div>
                </CardContent>
              </Card>

              <div className="rounded-2xl border bg-card">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Periodo</TableHead>
                      <TableHead>Clave</TableHead>
                      <TableHead>Materia</TableHead>
                      <TableHead>Créditos</TableHead>
                      <TableHead>Grupo</TableHead>
                      <TableHead>Intento</TableHead>
                      <TableHead>Calificación</TableHead>
                      <TableHead>Estatus</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {kardex.rows.map((r) => (
                      <TableRow key={r.subject_enrollment_id}>
                        <TableCell data-numeric>{r.period_number}</TableCell>
                        <TableCell data-numeric>{r.code}</TableCell>
                        <TableCell className="font-semibold">
                          {r.name}
                        </TableCell>
                        <TableCell data-numeric>{r.credits}</TableCell>
                        <TableCell data-numeric>{r.group_code}</TableCell>
                        <TableCell data-numeric>{r.attempt_number}</TableCell>
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
                          colSpan={8}
                          className="py-8 text-center text-muted-foreground"
                        >
                          Sin historial académico en este plan
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </>
          )}
        </section>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Inscribir a plan de estudios</DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              enroll.mutate();
            }}
          >
            <div className="grid gap-2">
              <Label>Plan de estudios</Label>
              <SearchableSelect
                value={newPlanId}
                onChange={setNewPlanId}
                options={planOptions}
                placeholder="Seleccione un plan"
              />
            </div>
            <div className="grid gap-2">
              <Label>Ciclo de inicio</Label>
              <Select value={startTermId} onValueChange={setStartTermId}>
                <SelectTrigger className="w-full">
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
            </div>
            <DialogFooter>
              <Button
                type="submit"
                className="font-bold"
                disabled={enroll.isPending || !newPlanId || !startTermId}
              >
                {enroll.isPending ? "Inscribiendo…" : "Inscribir"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// --- Estado de cuenta -------------------------------------------------------------

function CuentaTab({ student }: { student: Student }) {
  const queryClient = useQueryClient();
  const { data: statement, isLoading, error } = useQuery({
    queryKey: queryKeys.statement(student.id),
    queryFn: () =>
      api<AccountStatement>(`/treasury/students/${student.id}/statement`),
  });
  const { data: scholarships } = useQuery({
    queryKey: queryKeys.scholarships(student.id),
    queryFn: () =>
      api<Scholarship[]>(`/treasury/scholarships?student_id=${student.id}`),
  });
  const { data: concepts } = useQuery({
    queryKey: queryKeys.concepts,
    queryFn: () => api<ChargeConcept[]>("/treasury/concepts"),
  });
  const { data: institution } = useQuery({
    queryKey: queryKeys.institution,
    queryFn: () => api<Institution>("/catalog/institution"),
  });
  const { data: me } = useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api<UserPublic>("/auth/me"),
  });
  const reprint = (payment: Payment) => {
    if (!institution) return;
    printReceipt(
      paymentToReceiptData(payment, {
        institution,
        student,
        charges: statement?.charges ?? [],
        cajero: me?.full_name ?? "",
      }),
    );
  };

  const [paymentOpen, setPaymentOpen] = useState(false);
  const [chargeOpen, setChargeOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [becaOpen, setBecaOpen] = useState(false);
  const [cancellingPayment, setCancellingPayment] = useState<string | null>(
    null,
  );
  const [cancelReason, setCancelReason] = useState("");

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: queryKeys.statement(student.id) });
    queryClient.invalidateQueries({
      queryKey: queryKeys.scholarships(student.id),
    });
  }

  const cancelCharge = useMutation({
    mutationFn: (chargeId: string) =>
      api(`/treasury/charges/${chargeId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      invalidate();
      toast.success("Cargo cancelado");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al cancelar"),
  });

  const cancelPayment = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api(
        `/treasury/payments/${id}/cancel?reason=${encodeURIComponent(reason)}`,
        { method: "POST" },
      ),
    onSuccess: () => {
      invalidate();
      toast.success("Pago cancelado");
      setCancellingPayment(null);
      setCancelReason("");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al cancelar"),
  });

  if (error) {
    return (
      <EmptyState
        icon={TriangleAlertIcon}
        title="No se pudo cargar el estado de cuenta"
        description={
          error instanceof ApiError ? error.message : "Intenta de nuevo más tarde."
        }
      />
    );
  }
  if (isLoading || !statement) {
    return <Skeleton className="h-64 w-full rounded-2xl" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <SummaryChip label="Cargado" value={formatMoney(statement.total_charged)} />
        <SummaryChip label="Pagado" value={formatMoney(statement.total_paid)} />
        <SummaryChip
          label="Saldo"
          value={formatMoney(statement.balance)}
          tone={statement.balance > 0 ? "warn" : "ok"}
        />
        <SummaryChip
          label="Vencido"
          value={formatMoney(statement.overdue_balance)}
          tone={statement.overdue_balance > 0 ? "bad" : "ok"}
        />
        {statement.next_due_date && (
          <SummaryChip
            label="Próximo vencimiento"
            value={formatDate(statement.next_due_date)}
          />
        )}
        <div className="ml-auto flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setChargeOpen(true)}>
            <Plus className="size-4" /> Nuevo cargo
          </Button>
          <Button variant="outline" onClick={() => setPlanOpen(true)}>
            <BadgeDollarSign className="size-4" /> Plan de pagos
          </Button>
          <Button className="font-bold" onClick={() => setPaymentOpen(true)}>
            <Plus className="size-4" /> Registrar pago
          </Button>
        </div>
      </div>

      <section className="space-y-3">
        <h2 className="text-xl font-bold">Cargos</h2>
        <div className="rounded-2xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Descripción</TableHead>
                <TableHead>Vence</TableHead>
                <TableHead>Importe</TableHead>
                <TableHead>Beca</TableHead>
                <TableHead>Pagado</TableHead>
                <TableHead>Saldo</TableHead>
                <TableHead>Estatus</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {statement.charges.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-semibold">
                    {c.description}
                    {c.is_late_fee && (
                      <Badge variant="outline" className="ml-2">
                        Recargo
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>{formatDate(c.due_date)}</TableCell>
                  <TableCell data-numeric>{formatMoney(c.amount)}</TableCell>
                  <TableCell data-numeric>
                    {c.scholarship_discount > 0
                      ? `-${formatMoney(c.scholarship_discount)}`
                      : "—"}
                  </TableCell>
                  <TableCell data-numeric>
                    {formatMoney(c.paid_amount)}
                  </TableCell>
                  <TableCell data-numeric className="font-semibold">
                    {formatMoney(c.balance)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={chargeStatusVariant(c)}>
                      {CHARGE_STATUS_LABELS[c.status]}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {c.status !== "cancelado" && c.status !== "pagado" && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-destructive"
                        disabled={cancelCharge.isPending}
                        onClick={() => cancelCharge.mutate(c.id)}
                      >
                        Cancelar
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {statement.charges.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={8}
                    className="py-8 text-center text-muted-foreground"
                  >
                    Sin cargos registrados
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-bold">Pagos</h2>
        <div className="rounded-2xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Folio</TableHead>
                <TableHead>Fecha</TableHead>
                <TableHead>Método</TableHead>
                <TableHead>Referencia</TableHead>
                <TableHead>Importe</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {statement.payments.map((p) => (
                <TableRow key={p.id}>
                  <TableCell className="font-semibold" data-numeric>
                    {p.receipt_folio}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(p.received_at)}
                  </TableCell>
                  <TableCell>{PAYMENT_METHOD_LABELS[p.method]}</TableCell>
                  <TableCell data-numeric className="text-muted-foreground">
                    {p.bank_reference || "—"}
                  </TableCell>
                  <TableCell data-numeric className="font-semibold">
                    {formatMoney(p.amount)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={p.cancelled ? "destructive" : "outline"}>
                      {p.cancelled ? "Cancelado" : "Vigente"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {!p.cancelled && (
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => reprint(p)}
                        >
                          Recibo
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive"
                          onClick={() => setCancellingPayment(p.id)}
                        >
                          Cancelar
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {statement.payments.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={7}
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

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold">Becas</h2>
          <Button variant="outline" onClick={() => setBecaOpen(true)}>
            <Plus className="size-4" /> Nueva beca
          </Button>
        </div>
        <div className="rounded-2xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nombre</TableHead>
                <TableHead>Descuento</TableHead>
                <TableHead>Vigencia</TableHead>
                <TableHead>Estatus</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {scholarships?.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-semibold">{s.name}</TableCell>
                  <TableCell data-numeric>
                    {s.pct != null
                      ? `${s.pct}%`
                      : s.fixed_amount != null
                        ? formatMoney(s.fixed_amount)
                        : "—"}
                  </TableCell>
                  <TableCell>
                    {formatDate(s.valid_from)} –{" "}
                    {s.valid_to ? formatDate(s.valid_to) : "indefinida"}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        s.status === "activa"
                          ? "default"
                          : s.status === "suspendida" || s.status === "cancelada"
                            ? "destructive"
                            : "outline"
                      }
                    >
                      {SCHOLARSHIP_STATUS_LABELS[s.status]}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
              {scholarships && scholarships.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="py-8 text-center text-muted-foreground"
                  >
                    Sin becas asignadas
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </section>

      <PaymentDialog
        open={paymentOpen}
        onOpenChange={setPaymentOpen}
        student={student}
        charges={statement.charges}
        onDone={invalidate}
      />
      <ChargeDialog
        open={chargeOpen}
        onOpenChange={setChargeOpen}
        student={student}
        concepts={concepts ?? []}
        onDone={invalidate}
      />
      <PaymentPlanDialog
        open={planOpen}
        onOpenChange={setPlanOpen}
        student={student}
        concepts={concepts ?? []}
        onDone={invalidate}
      />
      <ScholarshipDialog
        open={becaOpen}
        onOpenChange={setBecaOpen}
        student={student}
        onDone={invalidate}
      />

      <Dialog
        open={!!cancellingPayment}
        onOpenChange={(v) => {
          if (!v) setCancellingPayment(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancelar pago</DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (cancellingPayment)
                cancelPayment.mutate({
                  id: cancellingPayment,
                  reason: cancelReason,
                });
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="cp-reason">Motivo de cancelación</Label>
              <Textarea
                id="cp-reason"
                required
                value={cancelReason}
                onChange={(e) => setCancelReason(e.target.value)}
              />
            </div>
            <DialogFooter>
              <Button
                type="submit"
                variant="destructive"
                className="font-bold"
                disabled={cancelPayment.isPending}
              >
                {cancelPayment.isPending ? "Cancelando…" : "Cancelar pago"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function chargeStatusVariant(
  c: Charge,
): "default" | "secondary" | "destructive" | "outline" {
  if (c.status === "pagado") return "default";
  if (c.status === "cancelado") return "outline";
  if (c.status === "parcial") return "secondary";
  return "destructive";
}

function SummaryChip({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "ok" | "warn" | "bad";
}) {
  const toneClass =
    tone === "bad"
      ? "border-destructive/40 text-destructive"
      : tone === "warn"
        ? "border-amber-400/60 text-amber-700 dark:text-amber-400"
        : tone === "ok"
          ? "border-green-500/40 text-green-700 dark:text-green-400"
          : "";
  return (
    <div className={`rounded-xl border bg-card px-4 py-2 ${toneClass}`}>
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="font-bold" data-numeric>
        {value}
      </p>
    </div>
  );
}

function PaymentDialog({
  open,
  onOpenChange,
  student,
  charges,
  onDone,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  student: Student;
  charges: Charge[];
  onDone: () => void;
}) {
  const [form, setForm] = useState({
    charge_id: NONE,
    amount: "",
    method: "efectivo" as PaymentMethod,
    bank_reference: "",
    notes: "",
  });
  // for the printed receipt (parity with Caja)
  const { data: institution } = useQuery({
    queryKey: queryKeys.institution,
    queryFn: () => api<Institution>("/catalog/institution"),
  });
  const { data: me } = useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api<UserPublic>("/auth/me"),
  });

  const save = useMutation({
    mutationFn: () =>
      api<Payment>(`/treasury/payments`, {
        method: "POST",
        body: JSON.stringify({
          student_id: student.id,
          charge_id: form.charge_id === NONE ? null : form.charge_id,
          amount: Number(form.amount),
          method: form.method,
          bank_reference: form.bank_reference,
          notes: form.notes,
        }),
      }),
    onSuccess: (payment) => {
      onDone();
      toast.success("Pago registrado");
      if (institution) {
        printReceipt(
          paymentToReceiptData(payment, {
            institution,
            student,
            charges,
            cajero: me?.full_name ?? "",
          }),
        );
      }
      onOpenChange(false);
      setForm({
        charge_id: NONE,
        amount: "",
        method: "efectivo",
        bank_reference: "",
        notes: "",
      });
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al registrar"),
  });

  const openCharges = charges.filter(
    (c) => c.status === "pendiente" || c.status === "parcial",
  );
  const oldestOpen = openCharges.length
    ? [...openCharges].sort((a, b) => a.due_date.localeCompare(b.due_date))[0]
    : null;
  // default to settling the oldest open charge instead of "sin cargo"
  useEffect(() => {
    if (open && oldestOpen && form.charge_id === NONE && form.amount === "") {
      setForm((f) => ({
        ...f,
        charge_id: oldestOpen.id,
        amount: String(oldestOpen.balance),
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, oldestOpen?.id]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Registrar pago</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label>Cargo (opcional)</Label>
            <Select
              value={form.charge_id}
              onValueChange={(v) => {
                const charge = openCharges.find((c) => c.id === v);
                setForm({
                  ...form,
                  charge_id: v,
                  amount:
                    v !== NONE && charge ? String(charge.balance) : form.amount,
                });
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Pago a cuenta (sin cargo)</SelectItem>
                {openCharges.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.description} · saldo {formatMoney(c.balance)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="pay-amount">Importe</Label>
              <Input
                id="pay-amount"
                type="number"
                min="0.01"
                step="0.01"
                required
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label>Método</Label>
              <Select
                value={form.method}
                onValueChange={(v) =>
                  setForm({ ...form, method: v as PaymentMethod })
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(
                    Object.keys(PAYMENT_METHOD_LABELS) as PaymentMethod[]
                  ).map((m) => (
                    <SelectItem key={m} value={m}>
                      {PAYMENT_METHOD_LABELS[m]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="pay-ref">Referencia bancaria</Label>
            <Input
              id="pay-ref"
              value={form.bank_reference}
              onChange={(e) =>
                setForm({ ...form, bank_reference: e.target.value })
              }
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="pay-notes">Notas</Label>
            <Input
              id="pay-notes"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
          </div>
          <DialogFooter>
            <Button type="submit" className="font-bold" disabled={save.isPending}>
              {save.isPending ? "Registrando…" : "Registrar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ChargeDialog({
  open,
  onOpenChange,
  student,
  concepts,
  onDone,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  student: Student;
  concepts: ChargeConcept[];
  onDone: () => void;
}) {
  const [form, setForm] = useState({
    concept_id: NONE,
    description: "",
    amount: "",
    due_date: todayISO(),
  });

  const save = useMutation({
    mutationFn: () =>
      api(`/treasury/charges`, {
        method: "POST",
        body: JSON.stringify({
          student_id: student.id,
          concept_id: form.concept_id === NONE ? null : form.concept_id,
          description: form.description,
          amount: Number(form.amount),
          due_date: form.due_date,
        }),
      }),
    onSuccess: () => {
      onDone();
      toast.success("Cargo creado");
      onOpenChange(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al crear cargo"),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nuevo cargo</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label>Concepto (opcional)</Label>
            <Select
              value={form.concept_id}
              onValueChange={(v) => {
                const concept = concepts.find((c) => c.id === v);
                setForm({
                  ...form,
                  concept_id: v,
                  description: concept?.name ?? form.description,
                  amount: concept ? String(concept.amount) : form.amount,
                });
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Sin concepto</SelectItem>
                {concepts
                  .filter((c) => c.is_active)
                  .map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name} · {formatMoney(c.amount)}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="ch-desc">Descripción</Label>
            <Input
              id="ch-desc"
              required
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="ch-amount">Importe</Label>
              <Input
                id="ch-amount"
                type="number"
                min="0"
                step="0.01"
                required
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="ch-due">Fecha de vencimiento</Label>
              <Input
                id="ch-due"
                type="date"
                required
                value={form.due_date}
                onChange={(e) => setForm({ ...form, due_date: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="submit" className="font-bold" disabled={save.isPending}>
              {save.isPending ? "Guardando…" : "Guardar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function PaymentPlanDialog({
  open,
  onOpenChange,
  student,
  concepts,
  onDone,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  student: Student;
  concepts: ChargeConcept[];
  onDone: () => void;
}) {
  const [form, setForm] = useState({
    concept_id: "",
    installments: 4,
    first_due_date: todayISO(),
    day_interval: "",
  });

  const save = useMutation({
    mutationFn: () =>
      api(`/treasury/payment-plans`, {
        method: "POST",
        body: JSON.stringify({
          student_id: student.id,
          concept_id: form.concept_id,
          installments: form.installments,
          first_due_date: form.first_due_date,
          day_interval: form.day_interval ? Number(form.day_interval) : null,
        }),
      }),
    onSuccess: () => {
      onDone();
      toast.success("Plan de pagos generado");
      onOpenChange(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al generar"),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Generar plan de pagos</DialogTitle>
          <DialogDescription>
            Genera N mensualidades del concepto seleccionado para el alumno.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label>Concepto</Label>
            <Select
              value={form.concept_id}
              onValueChange={(v) => setForm({ ...form, concept_id: v })}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Seleccione un concepto" />
              </SelectTrigger>
              <SelectContent>
                {concepts
                  .filter((c) => c.is_active)
                  .map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name} · {formatMoney(c.amount)}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="pp-n">Parcialidades</Label>
              <Input
                id="pp-n"
                type="number"
                min={1}
                max={48}
                required
                value={form.installments}
                onChange={(e) =>
                  setForm({ ...form, installments: Number(e.target.value) })
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="pp-first">Primer vencimiento</Label>
              <Input
                id="pp-first"
                type="date"
                required
                value={form.first_due_date}
                onChange={(e) =>
                  setForm({ ...form, first_due_date: e.target.value })
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="pp-interval">Intervalo (días)</Label>
              <Input
                id="pp-interval"
                type="number"
                min={1}
                placeholder="Mensual"
                value={form.day_interval}
                onChange={(e) =>
                  setForm({ ...form, day_interval: e.target.value })
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              type="submit"
              className="font-bold"
              disabled={save.isPending || !form.concept_id}
            >
              {save.isPending ? "Generando…" : "Generar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ScholarshipDialog({
  open,
  onOpenChange,
  student,
  onDone,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  student: Student;
  onDone: () => void;
}) {
  const [form, setForm] = useState({
    name: "",
    pct: "",
    fixed_amount: "",
    valid_from: todayISO(),
    valid_to: "",
    tolerance_days: "0",
  });

  const save = useMutation({
    mutationFn: () =>
      api(`/treasury/scholarships`, {
        method: "POST",
        body: JSON.stringify({
          student_id: student.id,
          name: form.name,
          pct: form.pct ? Number(form.pct) : null,
          fixed_amount: form.fixed_amount ? Number(form.fixed_amount) : null,
          valid_from: form.valid_from,
          valid_to: form.valid_to || null,
          tolerance_days: Number(form.tolerance_days) || 0,
        }),
      }),
    onSuccess: () => {
      onDone();
      toast.success("Beca solicitada — requiere autorización de un administrador");
      onOpenChange(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al registrar"),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Solicitar beca</DialogTitle>
          <DialogDescription>
            Indique porcentaje o monto fijo (uno de los dos). La beca queda como{" "}
            <b>solicitada</b> y no aplica descuentos hasta que un administrador la
            autorice.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!form.pct && !form.fixed_amount) {
              toast.error("Indique porcentaje o monto fijo");
              return;
            }
            save.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="b-name">Nombre</Label>
            <Input
              id="b-name"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Beca académica 2026"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="b-pct">Porcentaje (%)</Label>
              <Input
                id="b-pct"
                type="number"
                min={0}
                max={100}
                step="0.1"
                value={form.pct}
                onChange={(e) =>
                  setForm({ ...form, pct: e.target.value, fixed_amount: "" })
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="b-fixed">Monto fijo</Label>
              <Input
                id="b-fixed"
                type="number"
                min={0}
                step="0.01"
                value={form.fixed_amount}
                onChange={(e) =>
                  setForm({ ...form, fixed_amount: e.target.value, pct: "" })
                }
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="b-from">Vigente desde</Label>
              <Input
                id="b-from"
                type="date"
                required
                value={form.valid_from}
                onChange={(e) =>
                  setForm({ ...form, valid_from: e.target.value })
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="b-to">Vigente hasta (opcional)</Label>
              <Input
                id="b-to"
                type="date"
                value={form.valid_to}
                onChange={(e) => setForm({ ...form, valid_to: e.target.value })}
              />
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="b-tol">Tolerancia de pago (días)</Label>
            <Input
              id="b-tol"
              type="number"
              min={0}
              value={form.tolerance_days}
              onChange={(e) =>
                setForm({ ...form, tolerance_days: e.target.value })
              }
            />
            <p className="text-xs text-muted-foreground">
              Días tras el vencimiento para pagar sin perder la beca ni generar
              recargo.
            </p>
          </div>
          <DialogFooter>
            <Button type="submit" className="font-bold" disabled={save.isPending}>
              {save.isPending ? "Guardando…" : "Guardar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// --- Horario (calendar.inue.online) ---------------------------------------------------

const WEEKDAY_LABELS = [
  "Lunes",
  "Martes",
  "Miércoles",
  "Jueves",
  "Viernes",
  "Sábado",
  "Domingo",
];

/** "HH:MM:SS" -> "HH:MM" */
const formatTime = (t: string) => t.slice(0, 5);

function HorarioTab({ student }: { student: Student }) {
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.studentCalendar(student.id),
    queryFn: () => getStudentCalendar(student.id),
    retry: false,
  });

  if (isLoading) {
    return <Skeleton className="h-64 w-full rounded-2xl" />;
  }

  if (error || !data) {
    return (
      <EmptyState
        icon={CalendarDays}
        title="Horario no disponible"
        description={
          error instanceof ApiError
            ? error.message
            : "No se pudo consultar el sistema de calendario."
        }
      />
    );
  }

  if (!data.linked) {
    return (
      <EmptyState
        icon={CalendarDays}
        title="Grupo sin vincular al calendario"
        description="Los grupos del alumno no están vinculados al sistema de calendario. Vincúlelos en la sección «Grupos» para consultar su horario."
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

  if (rows.length === 0) {
    return (
      <EmptyState
        icon={CalendarDays}
        title="Sin clases programadas"
        description="El calendario aún no tiene bloques publicados para los grupos del alumno."
      />
    );
  }

  return (
    <div className="rounded-2xl border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Día</TableHead>
            <TableHead>Horario</TableHead>
            <TableHead>Materia</TableHead>
            <TableHead>Profesor</TableHead>
            <TableHead>Aula</TableHead>
            <TableHead>Grupo</TableHead>
            <TableHead>Vigencia</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(({ item, meeting }, i) => (
            <TableRow key={`${item.id}-${meeting.weekday}-${meeting.start_time}-${i}`}>
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
                {item.classroom && item.classroom_is_virtual && (
                  <Badge variant="outline" className="ml-2">
                    Virtual
                  </Badge>
                )}
              </TableCell>
              <TableCell data-numeric>{item.group_code}</TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {formatDate(item.start_date)} – {formatDate(item.end_date)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// --- Justificantes ------------------------------------------------------------------

function JustificantesTab({ student }: { student: Student }) {
  const queryClient = useQueryClient();
  const { data: justifications, isLoading } = useQuery({
    queryKey: queryKeys.justifications(`student:${student.id}`),
    queryFn: () =>
      api<Justification[]>(`/attendance/justifications?student_id=${student.id}`),
  });

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    reason: "",
    date_from: todayISO(),
    date_to: todayISO(),
  });

  const create = useMutation({
    mutationFn: () =>
      api<Justification>(`/attendance/justifications`, {
        method: "POST",
        body: JSON.stringify({ ...form, student_id: student.id }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["justifications"] });
      toast.success("Justificante registrado");
      setOpen(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al registrar"),
  });

  const uploadEvidence = useMutation({
    mutationFn: ({ id, file }: { id: string; file: File }) => {
      const fd = new FormData();
      fd.append("file", file);
      return apiUpload(`/attendance/justifications/${id}/evidence`, fd);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["justifications"] });
      toast.success("Evidencia adjuntada");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al subir"),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Justificantes de inasistencia</h2>
        <Button
          variant="outline"
          onClick={() => {
            setForm({ reason: "", date_from: todayISO(), date_to: todayISO() });
            setOpen(true);
          }}
        >
          <Plus className="size-4" /> Nuevo justificante
        </Button>
      </div>

      <div className="rounded-2xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Motivo</TableHead>
              <TableHead>Periodo</TableHead>
              <TableHead>Evidencia</TableHead>
              <TableHead>Estatus</TableHead>
              <TableHead>Notas de revisión</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={5}>
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            )}
            {justifications?.map((j) => (
              <TableRow key={j.id}>
                <TableCell className="max-w-64 truncate font-semibold">
                  {j.reason}
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  {formatDate(j.date_from)} – {formatDate(j.date_to)}
                </TableCell>
                <TableCell>
                  {j.evidence_filename ? (
                    <span className="text-sm text-muted-foreground">
                      {j.evidence_filename}
                    </span>
                  ) : (
                    <label className="cursor-pointer text-sm font-semibold text-primary hover:underline">
                      Adjuntar
                      <input
                        type="file"
                        className="hidden"
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file)
                            uploadEvidence.mutate({ id: j.id, file });
                        }}
                      />
                    </label>
                  )}
                </TableCell>
                <TableCell>
                  <Badge
                    variant={
                      j.status === "aprobado"
                        ? "default"
                        : j.status === "rechazado"
                          ? "destructive"
                          : "outline"
                    }
                  >
                    {JUSTIFICATION_STATUS_LABELS[j.status]}
                  </Badge>
                </TableCell>
                <TableCell className="max-w-52 truncate text-muted-foreground">
                  {j.review_notes || "—"}
                </TableCell>
              </TableRow>
            ))}
            {justifications && justifications.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className="py-8 text-center text-muted-foreground"
                >
                  Sin justificantes registrados
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuevo justificante</DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="j-reason">Motivo</Label>
              <Textarea
                id="j-reason"
                required
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label htmlFor="j-from">Desde</Label>
                <Input
                  id="j-from"
                  type="date"
                  required
                  value={form.date_from}
                  onChange={(e) =>
                    setForm({ ...form, date_from: e.target.value })
                  }
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="j-to">Hasta</Label>
                <Input
                  id="j-to"
                  type="date"
                  required
                  min={form.date_from}
                  value={form.date_to}
                  onChange={(e) => setForm({ ...form, date_to: e.target.value })}
                />
              </div>
            </div>
            <DialogFooter>
              <Button
                type="submit"
                className="font-bold"
                disabled={create.isPending}
              >
                {create.isPending ? "Guardando…" : "Guardar"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
