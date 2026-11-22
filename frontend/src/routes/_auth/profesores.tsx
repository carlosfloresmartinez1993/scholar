// Profesores: create a docente (account + expediente, access sent by email), keep
// their expediente, and see their classes. They are assigned to a materia in Grupos.
import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { FileUp, Pencil, Plus } from "lucide-react";
import { api, apiUpload, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
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

export const Route = createFileRoute("/_auth/profesores")({
  component: ProfesoresPage,
});

interface Teacher {
  id: string;
  full_name: string;
  email: string;
  is_active: boolean;
  campuses: { id: string; name: string }[];
  profile_id: string | null;
  cedula_profesional: string;
  max_degree: string;
  cv_summary: string;
  classes_now: number;
}

interface TeacherDetail extends Teacher {
  classes: {
    group_subject_id: string;
    group_code: string;
    subject: string;
    period_number: number;
    term_name: string;
    term_open: boolean;
    campus: string;
    schedule: string;
  }[];
  documents: { id: string; title: string; filename: string; uploaded_at: string }[];
}

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

function ProfesoresPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<Teacher | "new" | null>(null);
  const [search, setSearch] = useState("");
  const { data: teachers, isLoading } = useQuery({
    queryKey: ["teachers"],
    queryFn: () => api<Teacher[]>("/teachers"),
  });
  const term = search.trim().toLowerCase();
  const shown = (teachers ?? []).filter(
    (t) => !term || t.full_name.toLowerCase().includes(term) || t.email.toLowerCase().includes(term),
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl">Profesores</h1>
        <Button className="font-bold" onClick={() => setEditing("new")}>
          <Plus className="size-4" /> Nuevo profesor
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        Aquí se dan de alta los profesores (su acceso les llega por correo) y se lleva su
        expediente. Un profesor puede dar clase en cualquier plantel: se le asigna cada materia
        en Grupos, y con eso ve esos grupos.
      </p>
      <Input
        className="max-w-sm"
        placeholder="Buscar por nombre o correo…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nombre</TableHead>
              <TableHead>Correo</TableHead>
              <TableHead>Grado máximo</TableHead>
              <TableHead>Cédula</TableHead>
              <TableHead>Da clase en</TableHead>
              <TableHead className="text-right">Materias en curso</TableHead>
              <TableHead>Estado</TableHead>
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
            {shown.map((t) => (
              <TableRow
                key={t.id}
                className={cn("cursor-pointer", t.id === selected && "bg-muted/60")}
                onClick={() => setSelected(t.id === selected ? null : t.id)}
              >
                <TableCell className="font-semibold">{t.full_name}</TableCell>
                <TableCell className="text-muted-foreground">{t.email}</TableCell>
                <TableCell>{t.max_degree || "—"}</TableCell>
                <TableCell data-numeric>{t.cedula_profesional || "—"}</TableCell>
                <TableCell className="text-muted-foreground">
                  {t.campuses.map((c) => c.name).join(", ") || "—"}
                </TableCell>
                <TableCell data-numeric className="text-right">
                  {t.classes_now}
                </TableCell>
                <TableCell>
                  <Badge variant={t.is_active ? "outline" : "destructive"}>
                    {t.is_active ? "Activo" : "Inactivo"}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
            {teachers && shown.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                  {teachers.length === 0 ? "Sin profesores registrados" : "Ningún profesor coincide"}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {selected && <TeacherFicha teacherId={selected} onEdit={setEditing} />}
      {editing && (
        <TeacherDialog
          teacher={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onCreated={(t) => setSelected(t.id)}
        />
      )}
    </div>
  );
}

function TeacherFicha({
  teacherId,
  onEdit,
}: {
  teacherId: string;
  onEdit: (t: Teacher) => void;
}) {
  const queryClient = useQueryClient();
  const { data: t, isLoading } = useQuery({
    queryKey: ["teacher", teacherId],
    queryFn: () => api<TeacherDetail>(`/teachers/${teacherId}`),
  });
  const [docTitle, setDocTitle] = useState("");
  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file, file.name);
      return apiUpload(
        `/documents/teachers/${t!.profile_id}/documents?title=${encodeURIComponent(docTitle.trim())}`,
        form,
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", teacherId] });
      toast.success("Documento agregado al expediente");
      setDocTitle("");
    },
    onError: (e) => toast.error(errorText(e, "No se pudo subir el documento")),
  });
  if (isLoading || !t) return <Skeleton className="h-48 w-full rounded-md" />;
  const now = t.classes.filter((c) => c.term_open);
  const past = t.classes.filter((c) => !c.term_open);
  return (
    <section className="space-y-5 rounded-md border bg-card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">{t.full_name}</h2>
          <p className="text-sm text-muted-foreground">
            {t.email} · {t.max_degree || "Sin grado registrado"}
            {t.cedula_profesional ? ` · Cédula ${t.cedula_profesional}` : ""}
          </p>
        </div>
        <Button variant="outline" onClick={() => onEdit(t)}>
          <Pencil className="size-4" /> Editar
        </Button>
      </div>
      {t.cv_summary && <p className="whitespace-pre-line text-sm">{t.cv_summary}</p>}

      <div className="space-y-2">
        <h3 className="font-bold">Materias en ciclos abiertos</h3>
        <ClassesTable rows={now} empty="Sin materias asignadas en los ciclos abiertos. Se asignan en Grupos." />
      </div>
      {past.length > 0 && (
        <div className="space-y-2">
          <h3 className="font-bold">Ciclos anteriores</h3>
          <ClassesTable rows={past} empty="" />
        </div>
      )}

      <div className="space-y-2">
        <h3 className="font-bold">Expediente</h3>
        {t.documents.length > 0 ? (
          <ul className="space-y-1 text-sm">
            {t.documents.map((d) => (
              <li key={d.id}>
                <a
                  className="font-semibold underline-offset-2 hover:underline"
                  href={`/api/v1/teachers/documents/${d.id}/file`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {d.title}
                </a>{" "}
                <span className="text-muted-foreground">
                  · {d.filename} · {formatDate(d.uploaded_at)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Sin documentos.</p>
        )}
        {t.profile_id && (
          <div className="flex flex-wrap items-end gap-2">
            <div className="grid gap-1">
              <Label htmlFor="doc-title" className="text-xs">
                Documento (cédula, título, CV…)
              </Label>
              <Input
                id="doc-title"
                className="w-64"
                value={docTitle}
                onChange={(e) => setDocTitle(e.target.value)}
                placeholder="Cédula profesional"
              />
            </div>
            <Button
              asChild
              variant="outline"
              disabled={docTitle.trim().length < 2 || upload.isPending}
            >
              <label
                className={cn(
                  "cursor-pointer",
                  (docTitle.trim().length < 2 || upload.isPending) && "pointer-events-none opacity-50",
                )}
              >
                <FileUp className="size-4" />
                {upload.isPending ? "Subiendo…" : "Subir archivo"}
                <input
                  type="file"
                  accept="application/pdf,image/png,image/jpeg,image/webp"
                  className="sr-only"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = "";
                    if (file) upload.mutate(file);
                  }}
                />
              </label>
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}

function ClassesTable({ rows, empty }: { rows: TeacherDetail["classes"]; empty: string }) {
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Ciclo</TableHead>
            <TableHead>Grupo</TableHead>
            <TableHead>Materia</TableHead>
            <TableHead>Plantel</TableHead>
            <TableHead>Horario</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((c) => (
            <TableRow key={c.group_subject_id}>
              <TableCell data-numeric>{c.term_name}</TableCell>
              <TableCell className="font-semibold" data-numeric>
                {c.group_code}
              </TableCell>
              <TableCell>{c.subject}</TableCell>
              <TableCell className="text-muted-foreground">{c.campus}</TableCell>
              <TableCell className="text-muted-foreground">{c.schedule || "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function TeacherDialog({
  teacher,
  onClose,
  onCreated,
}: {
  teacher: Teacher | null;
  onClose: () => void;
  onCreated: (t: Teacher) => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    full_name: teacher?.full_name ?? "",
    email: teacher?.email ?? "",
    cedula_profesional: teacher?.cedula_profesional ?? "",
    max_degree: teacher?.max_degree ?? "",
    cv_summary: teacher?.cv_summary ?? "",
    is_active: teacher?.is_active ?? true,
  });
  const save = useMutation({
    mutationFn: () =>
      teacher
        ? api<Teacher>(`/teachers/${teacher.id}`, { method: "PATCH", body: JSON.stringify(form) })
        : api<Teacher>("/teachers", {
            method: "POST",
            body: JSON.stringify({ ...form, is_active: undefined }),
          }),
    onSuccess: (t) => {
      queryClient.invalidateQueries({ queryKey: ["teachers"] });
      queryClient.invalidateQueries({ queryKey: ["teacher", t.id] });
      queryClient.invalidateQueries({ queryKey: queryKeys.users("docente") });
      toast.success(teacher ? "Profesor actualizado" : `Profesor creado. Su acceso se envió a ${t.email}`);
      if (!teacher) onCreated(t);
      onClose();
    },
    onError: (e) => toast.error(errorText(e, "No se pudo guardar")),
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{teacher ? "Editar profesor" : "Nuevo profesor"}</DialogTitle>
          <DialogDescription>
            {teacher
              ? "Datos de acceso y expediente del profesor."
              : "Se crea su cuenta de docente y le llega por correo su usuario y contraseña."}
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
            <Label htmlFor="t-name">Nombre completo</Label>
            <Input
              id="t-name"
              required
              minLength={3}
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="t-email">Correo (su usuario)</Label>
            <Input
              id="t-email"
              type="email"
              required
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="t-degree">Grado máximo</Label>
              <Input
                id="t-degree"
                placeholder="Maestría en…"
                value={form.max_degree}
                onChange={(e) => setForm({ ...form, max_degree: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="t-cedula">Cédula profesional</Label>
              <Input
                id="t-cedula"
                value={form.cedula_profesional}
                onChange={(e) => setForm({ ...form, cedula_profesional: e.target.value })}
              />
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="t-cv">Resumen de CV (opcional)</Label>
            <Textarea
              id="t-cv"
              rows={3}
              value={form.cv_summary}
              onChange={(e) => setForm({ ...form, cv_summary: e.target.value })}
            />
          </div>
          {teacher && (
            <label className="flex items-center gap-2 text-sm font-medium">
              <Checkbox
                checked={form.is_active}
                onCheckedChange={(v) => setForm({ ...form, is_active: v === true })}
              />
              Activo (puede entrar al sistema)
            </label>
          )}
          <DialogFooter>
            <Button
              type="submit"
              className="font-bold"
              disabled={save.isPending || form.full_name.trim().length < 3 || !form.email.trim()}
            >
              {save.isPending ? "Guardando…" : teacher ? "Guardar" : "Crear profesor"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
