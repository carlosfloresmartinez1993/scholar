import { useEffect, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Search } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  AdmissionType,
  Campus,
  Student,
  StudentStatus,
} from "@/api/types";
import {
  ADMISSION_TYPE_LABELS,
  STUDENT_STATUS_LABELS,
} from "@/lib/format";
import { usePersistedState } from "@/lib/use-persisted-state";
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

export const Route = createFileRoute("/_auth/alumnos")({
  component: AlumnosPage,
});

const CURP_RE = /^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d$/;

export function studentStatusVariant(
  status: StudentStatus,
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "activo":
      return "default";
    case "egresado":
      return "secondary";
    case "baja_definitiva":
      return "destructive";
    default:
      return "outline";
  }
}

interface StudentForm {
  curp: string;
  full_name: string;
  email: string;
  phone: string;
  admission_type: AdmissionType;
  status: StudentStatus;
  campus_id: string;
}

const emptyForm: StudentForm = {
  curp: "",
  full_name: "",
  email: "",
  phone: "",
  admission_type: "nuevo_ingreso",
  status: "activo",
  campus_id: "",
};

function AlumnosPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");

  const { data: students, isLoading } = useQuery({
    queryKey: queryKeys.students(search),
    queryFn: () =>
      api<Student[]>(
        `/students?limit=200${search ? `&q=${encodeURIComponent(search)}` : ""}`,
      ),
  });
  const { data: campuses } = useQuery({
    queryKey: queryKeys.campuses,
    queryFn: () => api<Campus[]>("/catalog/campuses"),
  });

  // Sticky table filters (persisted, restored on mount). "all" = no filter.
  const [campusFilter, setCampusFilter] = usePersistedState<string>(
    "alumnos-filters-v1:campus",
    "all",
    (v) => typeof v === "string", // stale campus ids are dropped below
  );
  const [statusFilter, setStatusFilter] = usePersistedState<string>(
    "alumnos-filters-v1:status",
    "all",
    (v) => v === "all" || (typeof v === "string" && v in STUDENT_STATUS_LABELS),
  );
  // Drop a stored campus id that no longer exists in the loaded options.
  const effectiveCampus =
    campusFilter === "all" || !campuses
      ? campusFilter
      : campuses.some((c) => c.id === campusFilter)
        ? campusFilter
        : "all";
  const filteredStudents = students?.filter(
    (s) =>
      (effectiveCampus === "all" || s.campus_id === effectiveCampus) &&
      (statusFilter === "all" || s.status === statusFilter),
  );

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Student | null>(null);
  const [form, setForm] = useState<StudentForm>(emptyForm);

  // Backfill the campus default if the dialog was opened before campuses loaded
  // (with a single campus the picker is hidden, so an empty id would stick).
  useEffect(() => {
    if (campuses?.length && !form.campus_id) {
      setForm((f) => ({ ...f, campus_id: campuses[0].id }));
    }
  }, [campuses, form.campus_id]);

  const curpValue = form.curp.toUpperCase();
  const curpValid = CURP_RE.test(curpValue);

  const save = useMutation({
    mutationFn: () => {
      if (editing) {
        return api<Student>(`/students/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            full_name: form.full_name,
            email: form.email,
            phone: form.phone,
            status: form.status,
            campus_id: form.campus_id,
          }),
        });
      }
      return api<Student>("/students", {
        method: "POST",
        body: JSON.stringify({
          curp: curpValue,
          full_name: form.full_name,
          email: form.email,
          phone: form.phone,
          admission_type: form.admission_type,
          campus_id: form.campus_id,
        }),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["students"] });
      toast.success(editing ? "Alumno actualizado" : "Alumno registrado");
      setOpen(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  const campusName = (id: string) =>
    campuses?.find((c) => c.id === id)?.name ?? "—";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl">Alumnos</h1>
        <Button
          className="font-bold"
          onClick={() => {
            setEditing(null);
            setForm({ ...emptyForm, campus_id: campuses?.[0]?.id ?? "" });
            setOpen(true);
          }}
        >
          <Plus className="size-4" /> Nuevo alumno
        </Button>
      </div>

      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(query.trim());
        }}
      >
        <div className="relative w-96">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar por nombre, CURP o matrícula…"
            aria-label="Buscar alumnos"
            className="pl-8"
          />
        </div>
        <Button type="submit" variant="outline">
          Buscar
        </Button>

        {campuses && campuses.length > 1 && (
          <Select value={effectiveCampus} onValueChange={setCampusFilter}>
            <SelectTrigger className="w-48" aria-label="Filtrar por campus">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todos los campus</SelectItem>
              {campuses.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-44" aria-label="Filtrar por estatus">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todos los estatus</SelectItem>
            {(Object.keys(STUDENT_STATUS_LABELS) as StudentStatus[]).map((s) => (
              <SelectItem key={s} value={s}>
                {STUDENT_STATUS_LABELS[s]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </form>

      <div className="rounded-2xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Matrícula</TableHead>
              <TableHead>Nombre</TableHead>
              <TableHead>CURP</TableHead>
              <TableHead>Campus</TableHead>
              <TableHead>Ingreso</TableHead>
              <TableHead>Estatus</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading &&
              [1, 2, 3, 4].map((i) => (
                <TableRow key={i}>
                  <TableCell colSpan={6}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {filteredStudents?.map((s) => (
              <TableRow
                key={s.id}
                className="cursor-pointer"
                onClick={() =>
                  navigate({
                    to: "/alumnos/$studentId",
                    params: { studentId: s.id },
                  })
                }
              >
                <TableCell className="font-semibold" data-numeric>
                  {s.enrollment_number}
                </TableCell>
                <TableCell className="font-semibold">{s.full_name}</TableCell>
                <TableCell data-numeric className="text-muted-foreground">
                  {s.curp}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {campusName(s.campus_id)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {ADMISSION_TYPE_LABELS[s.admission_type]}
                </TableCell>
                <TableCell>
                  <Badge variant={studentStatusVariant(s.status)}>
                    {STUDENT_STATUS_LABELS[s.status]}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
            {filteredStudents && filteredStudents.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="py-10 text-center text-muted-foreground"
                >
                  {search || effectiveCampus !== "all" || statusFilter !== "all"
                    ? "Sin resultados"
                    : "Sin alumnos registrados"}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editing ? "Editar alumno" : "Nuevo alumno"}
            </DialogTitle>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (!editing && !curpValid) {
                toast.error("La CURP no tiene un formato válido");
                return;
              }
              save.mutate();
            }}
          >
            {!editing && (
              <div className="grid gap-2">
                <Label htmlFor="curp">CURP</Label>
                <Input
                  id="curp"
                  required
                  maxLength={18}
                  value={form.curp}
                  onChange={(e) =>
                    setForm({ ...form, curp: e.target.value.toUpperCase() })
                  }
                  placeholder="GOMC010203HBCNRL09"
                  className="font-mono uppercase"
                  aria-invalid={form.curp.length > 0 && !curpValid}
                />
                <p
                  className={
                    form.curp.length === 0
                      ? "text-xs text-muted-foreground"
                      : curpValid
                        ? "text-xs font-semibold text-green-600"
                        : "text-xs font-semibold text-destructive"
                  }
                >
                  {form.curp.length === 0
                    ? "18 caracteres, como aparece en el documento oficial."
                    : curpValid
                      ? "Formato de CURP válido"
                      : `Formato de CURP inválido (${form.curp.length}/18 caracteres)`}
                </p>
              </div>
            )}
            <div className="grid gap-2">
              <Label htmlFor="full_name">Nombre completo</Label>
              <Input
                id="full_name"
                required
                value={form.full_name}
                onChange={(e) =>
                  setForm({ ...form, full_name: e.target.value })
                }
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="phone">Teléfono</Label>
                <Input
                  id="phone"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </div>
            </div>
            {campuses && campuses.length > 1 && (
              <div className="grid gap-2">
                <Label>Campus</Label>
                <Select
                  value={form.campus_id}
                  onValueChange={(v) => setForm({ ...form, campus_id: v })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Seleccione un campus" />
                  </SelectTrigger>
                  <SelectContent>
                    {campuses.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            {!editing ? (
              <div className="grid gap-2">
                <Label>Tipo de ingreso</Label>
                <Select
                  value={form.admission_type}
                  onValueChange={(v) =>
                    setForm({ ...form, admission_type: v as AdmissionType })
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(
                      Object.keys(ADMISSION_TYPE_LABELS) as AdmissionType[]
                    ).map((a) => (
                      <SelectItem key={a} value={a}>
                        {ADMISSION_TYPE_LABELS[a]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : (
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
            )}
            <DialogFooter>
              <Button
                type="submit"
                className="font-bold"
                disabled={save.isPending || !form.campus_id}
              >
                {save.isPending ? "Guardando…" : "Guardar"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
