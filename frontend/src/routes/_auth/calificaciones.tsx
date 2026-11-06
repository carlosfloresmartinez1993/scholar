import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Eye, FileSignature, FileText, NotebookPen } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import { useAcademicSelector } from "@/components/academic-selector";
import {
  canCaptureReplacement,
  ordinaryGrade,
  replacesFinal,
  weighsInFinal,
} from "@/lib/evaluation";
import type {
  ActaKind,
  GradeActa,
  GradeGrid,
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
  const { term, groupSubjectId, selector } = useAcademicSelector();

  return (
    <div className="space-y-6">
      <h1 className="text-3xl">Calificaciones</h1>

      <div className="flex flex-wrap items-center gap-3">
        {selector}
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

  // edited-but-unsaved cells, keyed `${subjectEnrollmentId}:${componentId}`
  const [edits, setEdits] = useState<Record<string, string>>({});
  const editCount = Object.keys(edits).length;

  const saveBatch = useMutation({
    mutationFn: (
      items: { subject_enrollment_id: string; component_id: string; value: number }[],
    ) =>
      api(`/grades/capture-batch`, {
        method: "POST",
        body: JSON.stringify(items),
      }),
    // Optimistically write the saved values into the grid cache so clearing the
    // local `edits` doesn't flash the old server values before the refetch lands.
    onMutate: async (items) => {
      const queryKey = queryKeys.gradeGrid(groupSubjectId);
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<GradeGrid>(queryKey);
      if (previous) {
        const byRow = new Map<string, Record<string, number>>();
        for (const it of items) {
          const updates = byRow.get(it.subject_enrollment_id) ?? {};
          updates[it.component_id] = it.value;
          byRow.set(it.subject_enrollment_id, updates);
        }
        queryClient.setQueryData<GradeGrid>(queryKey, {
          ...previous,
          rows: previous.rows.map((r) => {
            const updates = byRow.get(r.subject_enrollment_id);
            return updates ? { ...r, grades: { ...r.grades, ...updates } } : r;
          }),
        });
      }
      return { previous };
    },
    onSuccess: (_data, items) => {
      setEdits({});
      toast.success(`${items.length} calificaciones guardadas`);
    },
    onError: (e, _items, context) => {
      if (context?.previous) {
        queryClient.setQueryData(
          queryKeys.gradeGrid(groupSubjectId),
          context.previous,
        );
      }
      toast.error(e instanceof ApiError ? e.message : "Error al capturar");
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.gradeGrid(groupSubjectId),
      });
    },
  });

  // the row's values with unsaved edits applied, to know its ordinario live
  const rowValues = (row: GradeGrid["rows"][number]) =>
    Object.fromEntries(
      (grid?.components ?? []).map((c) => {
        const key = `${row.subject_enrollment_id}:${c.id}`;
        const raw = key in edits ? edits[key] : null;
        return [c.id, raw == null ? row.grades[c.id] : raw === "" ? null : Number(raw)];
      }),
    );
  const rowOrdinary = (row: GradeGrid["rows"][number]) =>
    ordinaryGrade(grid?.components ?? [], rowValues(row));

  const save = () => {
    const items: { subject_enrollment_id: string; component_id: string; value: number }[] = [];
    let hadEmpty = false;
    let droppedExtra = false;
    for (const [key, raw] of Object.entries(edits)) {
      if (raw === "") {
        hadEmpty = true; // no delete-grade endpoint: an emptied cell can't be saved
        continue;
      }
      const value = Number(raw);
      if (Number.isNaN(value) || value < 0 || value > 10) {
        toast.error("Cada calificación debe estar entre 0 y 10");
        return;
      }
      const [subject_enrollment_id, component_id] = key.split(":");
      const component = grid?.components.find((c) => c.id === component_id);
      const row = grid?.rows.find((r) => r.subject_enrollment_id === subject_enrollment_id);
      if (component && row && replacesFinal(component) && !canCaptureReplacement(rowOrdinary(row))) {
        droppedExtra = true; // the ordinario was fixed up to a pass: no extraordinario
        continue;
      }
      items.push({ subject_enrollment_id, component_id, value });
    }
    if (droppedExtra) {
      toast.warning("Se omitieron extraordinarios de alumnos que aprobaron el ordinario");
    }
    if (!items.length) {
      toast.error("No hay calificaciones para guardar");
      return;
    }
    if (hadEmpty) {
      toast.warning(
        "Las celdas vacías se ignoran: no es posible borrar una calificación ya guardada",
      );
    }
    saveBatch.mutate(items);
  };

  if (isLoading || !grid) {
    return <Skeleton className="h-64 w-full rounded-md" />;
  }

  if (grid.components.length === 0) {
    return (
      <p className="rounded-md border border-amber-400/60 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
        La materia no tiene componentes de evaluación configurados. Defínalos en
        «Programas» para poder capturar.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end gap-3">
        {editCount > 0 && (
          <span className="text-sm text-muted-foreground">
            {editCount} sin guardar
          </span>
        )}
        <Button
          className="font-bold"
          disabled={saveBatch.isPending || editCount === 0}
          onClick={save}
        >
          {saveBatch.isPending ? "Guardando…" : "Guardar calificaciones"}
        </Button>
      </div>
      <div className="overflow-x-auto rounded-md border bg-card">
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
                    {replacesFinal(c)
                      ? "solo si reprobó"
                      : `${c.weight_pct}%${weighsInFinal(c) ? "" : " · no cuenta"}`}
                  </span>
                </span>
              </TableHead>
            ))}
            <TableHead className="text-center">Final</TableHead>
            <TableHead>Estatus</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {grid.rows.map((row) => {
            const ordinary = rowOrdinary(row);
            const extraOpen = canCaptureReplacement(ordinary);
            return (
            <TableRow key={row.subject_enrollment_id}>
              <TableCell data-numeric>{row.enrollment_number}</TableCell>
              <TableCell className="font-semibold">
                {row.student_name}
                {row.attempt_number > 1 && (
                  <Badge variant="outline" className="ml-2">
                    Recursamiento
                  </Badge>
                )}
              </TableCell>
              {grid.components.map((c) => {
                const current = row.grades[c.id];
                const key = `${row.subject_enrollment_id}:${c.id}`;
                const edited = key in edits;
                const locked = replacesFinal(c) && !extraOpen;
                return (
                  <TableCell key={c.id} className="text-center">
                    <Input
                      type="number"
                      min={0}
                      max={10}
                      step="0.1"
                      value={edited ? edits[key] : (current ?? "")}
                      aria-label={`${c.label} de ${row.student_name}`}
                      title={
                        locked
                          ? ordinary == null
                            ? "Captura primero las calificaciones ordinarias"
                            : `Aprobó el ordinario (${ordinary}); no aplica`
                          : undefined
                      }
                      className={`mx-auto h-8 w-20 text-center ${
                        edited ? "ring-2 ring-primary/40" : ""
                      }`}
                      disabled={saveBatch.isPending || locked}
                      onChange={(e) =>
                        setEdits((prev) => ({ ...prev, [key]: e.target.value }))
                      }
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
            );
          })}
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

      <div className="rounded-md border bg-card">
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
                      disabled={!me}
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
      <div className="rounded-md border">
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
