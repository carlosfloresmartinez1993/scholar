import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Eye, FileSignature, FileText, NotebookPen } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  ActaKind,
  GradeActa,
  GradeGrid,
  Group,
  GroupSubject,
  PlanSubject,
  Term,
  UserPublic,
} from "@/api/types";
import {
  EVALUATION_KIND_LABELS,
  formatDateTime,
  SUBJECT_STATUS_LABELS,
} from "@/lib/format";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
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

export const Route = createFileRoute("/_auth/calificaciones")({
  component: CalificacionesPage,
});

function CalificacionesPage() {
  const { data: terms } = useQuery({
    queryKey: queryKeys.terms,
    queryFn: () => api<Term[]>("/catalog/terms"),
  });
  const [selectedTerm, setSelectedTerm] = useState<string | null>(null);
  const termId = selectedTerm ?? terms?.find((t) => t.is_open)?.id ?? null;
  const term = terms?.find((t) => t.id === termId);

  const [groupId, setGroupId] = useState<string | null>(null);
  const [groupSubjectId, setGroupSubjectId] = useState<string | null>(null);

  const { data: groups } = useQuery({
    queryKey: queryKeys.groups(termId ?? undefined),
    queryFn: () => api<Group[]>(`/catalog/groups?term_id=${termId}`),
    enabled: !!termId,
  });
  const group = groups?.find((g) => g.id === groupId);

  const { data: groupSubjects } = useQuery({
    queryKey: queryKeys.groupSubjects(groupId ?? ""),
    queryFn: () => api<GroupSubject[]>(`/catalog/groups/${groupId}/subjects`),
    enabled: !!groupId,
  });
  const { data: planSubjects } = useQuery({
    queryKey: queryKeys.planSubjects(group?.plan_version_id ?? ""),
    queryFn: () =>
      api<PlanSubject[]>(
        `/catalog/plan-versions/${group!.plan_version_id}/subjects`,
      ),
    enabled: !!group,
  });
  const subjectName = (planSubjectId: string) => {
    const s = planSubjects?.find((ps) => ps.id === planSubjectId);
    return s ? `${s.code} — ${s.name}` : "Materia";
  };

  return (
    <div className="space-y-6">
      <h1 className="text-3xl">Calificaciones</h1>

      <div className="flex flex-wrap items-center gap-3">
        <Select
          value={termId ?? ""}
          onValueChange={(v) => {
            setSelectedTerm(v);
            setGroupId(null);
            setGroupSubjectId(null);
          }}
        >
          <SelectTrigger className="w-56">
            <SelectValue placeholder="Ciclo" />
          </SelectTrigger>
          <SelectContent>
            {terms?.map((t) => (
              <SelectItem key={t.id} value={t.id}>
                {t.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={groupId ?? ""}
          onValueChange={(v) => {
            setGroupId(v);
            setGroupSubjectId(null);
          }}
          disabled={!termId}
        >
          <SelectTrigger className="w-56">
            <SelectValue placeholder="Grupo" />
          </SelectTrigger>
          <SelectContent>
            {groups?.map((g) => (
              <SelectItem key={g.id} value={g.id}>
                {g.code}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={groupSubjectId ?? ""}
          onValueChange={setGroupSubjectId}
          disabled={!groupId}
        >
          <SelectTrigger className="w-80">
            <SelectValue placeholder="Materia" />
          </SelectTrigger>
          <SelectContent>
            {groupSubjects?.map((gs) => (
              <SelectItem key={gs.id} value={gs.id}>
                {subjectName(gs.plan_subject_id)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {term && !term.grade_capture_open && (
          <Badge variant="destructive">Captura cerrada en este ciclo</Badge>
        )}
      </div>

      {!groupSubjectId ? (
        <EmptyState
          icon={NotebookPen}
          title="Seleccione ciclo, grupo y materia"
          description="Elija la materia para capturar calificaciones por componente de evaluación y generar el acta."
        />
      ) : (
        <>
          <GradeGridSection groupSubjectId={groupSubjectId} />
          <ActasSection groupSubjectId={groupSubjectId} />
        </>
      )}
    </div>
  );
}

// --- Grade grid ------------------------------------------------------------------

function GradeGridSection({ groupSubjectId }: { groupSubjectId: string }) {
  const queryClient = useQueryClient();
  const { data: grid, isLoading } = useQuery({
    queryKey: queryKeys.gradeGrid(groupSubjectId),
    queryFn: () => api<GradeGrid>(`/grades/group-subjects/${groupSubjectId}/grid`),
  });

  const capture = useMutation({
    mutationFn: ({
      subjectEnrollmentId,
      componentId,
      value,
    }: {
      subjectEnrollmentId: string;
      componentId: string;
      value: number;
    }) =>
      api(`/grades/capture`, {
        method: "POST",
        body: JSON.stringify({
          subject_enrollment_id: subjectEnrollmentId,
          component_id: componentId,
          value,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.gradeGrid(groupSubjectId),
      });
      toast.success("Calificación guardada");
    },
    onError: (e) => {
      toast.error(e instanceof ApiError ? e.message : "Error al capturar");
      queryClient.invalidateQueries({
        queryKey: queryKeys.gradeGrid(groupSubjectId),
      });
    },
  });

  if (isLoading || !grid) {
    return <Skeleton className="h-64 w-full rounded-2xl" />;
  }

  if (grid.components.length === 0) {
    return (
      <p className="rounded-xl border border-amber-400/60 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
        La materia no tiene componentes de evaluación configurados. Defínalos en
        «Programas» para poder capturar.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-2xl border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Matrícula</TableHead>
            <TableHead>Alumno</TableHead>
            {grid.components.map((c) => (
              <TableHead key={c.id} className="text-center">
                <span title={EVALUATION_KIND_LABELS[c.kind]}>
                  {c.label}
                  <span className="block text-xs font-normal text-muted-foreground">
                    {c.weight_pct}%
                    {!c.counts_towards_final && " · no cuenta"}
                  </span>
                </span>
              </TableHead>
            ))}
            <TableHead className="text-center">Final</TableHead>
            <TableHead>Estatus</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {grid.rows.map((row) => (
            <TableRow key={row.subject_enrollment_id}>
              <TableCell data-numeric>{row.enrollment_number}</TableCell>
              <TableCell className="font-semibold">
                {row.student_name}
              </TableCell>
              {grid.components.map((c) => {
                const current = row.grades[c.id];
                return (
                  <TableCell key={c.id} className="text-center">
                    <Input
                      key={`${row.subject_enrollment_id}-${c.id}-${current ?? ""}`}
                      type="number"
                      min={0}
                      max={10}
                      step="0.1"
                      defaultValue={current ?? ""}
                      aria-label={`${c.label} de ${row.student_name}`}
                      className="mx-auto h-8 w-20 text-center"
                      disabled={capture.isPending}
                      onBlur={(e) => {
                        const raw = e.target.value;
                        if (raw === "") return;
                        const value = Number(raw);
                        if (Number.isNaN(value) || value < 0 || value > 10) {
                          toast.error("La calificación debe estar entre 0 y 10");
                          e.target.value = current == null ? "" : String(current);
                          return;
                        }
                        if (current != null && value === current) return;
                        capture.mutate({
                          subjectEnrollmentId: row.subject_enrollment_id,
                          componentId: c.id,
                          value,
                        });
                      }}
                    />
                  </TableCell>
                );
              })}
              <TableCell className="text-center font-bold" data-numeric>
                {row.final_grade ?? "—"}
              </TableCell>
              <TableCell>
                <Badge
                  variant={
                    row.status === "aprobada"
                      ? "default"
                      : row.status === "reprobada"
                        ? "destructive"
                        : "outline"
                  }
                >
                  {SUBJECT_STATUS_LABELS[row.status]}
                </Badge>
              </TableCell>
            </TableRow>
          ))}
          {grid.rows.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={grid.components.length + 4}
                className="py-10 text-center text-muted-foreground"
              >
                No hay alumnos inscritos en esta materia
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}

// --- Actas -----------------------------------------------------------------------

function ActasSection({ groupSubjectId }: { groupSubjectId: string }) {
  const queryClient = useQueryClient();
  const { data: actas } = useQuery({
    queryKey: queryKeys.actas(groupSubjectId),
    queryFn: () =>
      api<GradeActa[]>(`/grades/group-subjects/${groupSubjectId}/actas`),
  });
  const { data: me } = useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api<UserPublic>("/auth/me"),
  });

  const [kind, setKind] = useState<ActaKind>("ordinaria");
  const [signing, setSigning] = useState<GradeActa | null>(null);
  const [signName, setSignName] = useState("");
  const [viewing, setViewing] = useState<GradeActa | null>(null);

  const generate = useMutation({
    mutationFn: () =>
      api<GradeActa>(
        `/grades/group-subjects/${groupSubjectId}/actas?kind=${kind}`,
        { method: "POST" },
      ),
    onSuccess: (acta) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.actas(groupSubjectId) });
      toast.success(`Acta generada con folio ${acta.folio}`);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al generar acta"),
  });

  const sign = useMutation({
    mutationFn: ({ actaId, name }: { actaId: string; name: string }) =>
      api<GradeActa>(
        `/grades/actas/${actaId}/sign?signed_by_name=${encodeURIComponent(name)}`,
        { method: "POST" },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.actas(groupSubjectId) });
      toast.success("Acta firmada");
      setSigning(null);
      setSignName("");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al firmar"),
  });

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-bold">Actas de calificaciones</h2>
        <div className="flex items-center gap-2">
          <Select value={kind} onValueChange={(v) => setKind(v as ActaKind)}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ordinaria">Ordinaria</SelectItem>
              <SelectItem value="extraordinaria">Extraordinaria</SelectItem>
            </SelectContent>
          </Select>
          <Button
            className="font-bold"
            disabled={generate.isPending}
            onClick={() => generate.mutate()}
          >
            <FileText className="size-4" />
            {generate.isPending ? "Generando…" : "Generar acta"}
          </Button>
        </div>
      </div>

      <div className="rounded-2xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Folio</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>Generada</TableHead>
              <TableHead>Firma</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {actas?.map((a) => (
              <TableRow key={a.id}>
                <TableCell className="font-semibold" data-numeric>
                  {a.folio}
                </TableCell>
                <TableCell className="capitalize">{a.kind}</TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(a.generated_at)}
                </TableCell>
                <TableCell>
                  {a.signed_at ? (
                    <span className="text-sm">
                      {a.signed_by_name}
                      <span className="text-muted-foreground">
                        {" "}
                        · {formatDateTime(a.signed_at)}
                      </span>
                    </span>
                  ) : (
                    <Badge variant="outline">Sin firmar</Badge>
                  )}
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <Button variant="ghost" size="sm" onClick={() => setViewing(a)}>
                    <Eye className="size-4" /> Ver
                  </Button>
                  {!a.signed_at && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setSignName(me?.full_name ?? "");
                        setSigning(a);
                      }}
                    >
                      <FileSignature className="size-4" /> Firmar
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {actas && actas.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className="py-8 text-center text-muted-foreground"
                >
                  Sin actas generadas para esta materia
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog
        open={!!signing}
        onOpenChange={(v) => {
          if (!v) setSigning(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Firmar acta {signing?.folio}</DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (signing) sign.mutate({ actaId: signing.id, name: signName });
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="sign-name">Nombre de quien firma</Label>
              <Input
                id="sign-name"
                required
                value={signName}
                onChange={(e) => setSignName(e.target.value)}
                placeholder="Mtra. Nombre Apellido"
              />
            </div>
            <DialogFooter>
              <Button type="submit" className="font-bold" disabled={sign.isPending}>
                {sign.isPending ? "Firmando…" : "Firmar"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!viewing}
        onOpenChange={(v) => {
          if (!v) setViewing(null);
        }}
      >
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              Acta {viewing?.folio}
              <span className="ml-2 font-normal capitalize text-muted-foreground">
                {viewing?.kind}
              </span>
            </DialogTitle>
          </DialogHeader>
          {viewing && <ActaSnapshot acta={viewing} />}
        </DialogContent>
      </Dialog>
    </section>
  );
}

interface ActaSnapshotRow {
  matricula: string;
  curp: string;
  nombre: string;
  calificacion: number | null;
  estatus: keyof typeof SUBJECT_STATUS_LABELS;
}

function ActaSnapshot({ acta }: { acta: GradeActa }) {
  let rows: ActaSnapshotRow[] = [];
  try {
    rows = JSON.parse(acta.snapshot);
  } catch {
    return <p className="text-sm text-destructive">Acta ilegible</p>;
  }
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Generada el {formatDateTime(acta.generated_at)}
        {acta.signed_at &&
          ` · Firmada por ${acta.signed_by_name} el ${formatDateTime(acta.signed_at)}`}
      </p>
      <div className="rounded-xl border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Matrícula</TableHead>
              <TableHead>Alumno</TableHead>
              <TableHead>Calificación</TableHead>
              <TableHead>Estatus</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.matricula}>
                <TableCell data-numeric>{r.matricula}</TableCell>
                <TableCell className="font-semibold">{r.nombre}</TableCell>
                <TableCell data-numeric>{r.calificacion ?? "—"}</TableCell>
                <TableCell>
                  {SUBJECT_STATUS_LABELS[r.estatus] ?? r.estatus}
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={4}
                  className="py-6 text-center text-muted-foreground"
                >
                  Sin alumnos en el acta
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
