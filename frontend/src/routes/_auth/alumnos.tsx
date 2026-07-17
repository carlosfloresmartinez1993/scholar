import { useState } from "react";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { Campus, Student, StudentStatus, UserPublic } from "@/api/types";
import { formatDate, STUDENT_STATUS_LABELS } from "@/lib/format";
import { StudentAvatar } from "@/components/student-avatar";
import { StudentStatusBadge } from "@/components/student-status-badge";
import { usePersistedState } from "@/lib/use-persisted-state";
import { ALL_CAMPUSES, useCampus } from "@/lib/campus-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

// same gate as the /inscripciones nav item in _auth.tsx
const ENROLL_ROLES: readonly string[] = [
  "admin_sistema",
  "direccion",
  "servicios_escolares",
];

function AlumnosPage() {
  const navigate = useNavigate();
  const { data: me } = useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api<UserPublic>("/auth/me"),
  });
  const canEnroll = !!me && (me.is_superuser || ENROLL_ROLES.includes(me.role));
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");

  const { data: campuses } = useQuery({
    queryKey: queryKeys.campuses,
    queryFn: () => api<Campus[]>("/catalog/campuses"),
  });

  // Global campus filter (header switcher); stale stored ids fall back to all.
  const { campusId } = useCampus();
  const effectiveCampus =
    campusId === ALL_CAMPUSES || !campuses
      ? campusId
      : campuses.some((c) => c.id === campusId)
        ? campusId
        : ALL_CAMPUSES;

  const { data: students, isLoading } = useQuery({
    queryKey: queryKeys.students(search, effectiveCampus),
    queryFn: () =>
      api<Student[]>(
        `/students?limit=200${search ? `&q=${encodeURIComponent(search)}` : ""}${
          effectiveCampus !== ALL_CAMPUSES
            ? `&campus_id=${effectiveCampus}`
            : ""
        }`,
      ),
  });

  // Sticky status filter (persisted, restored on mount). "all" = no filter.
  const [statusFilter, setStatusFilter] = usePersistedState<string>(
    "alumnos-filters-v1:status",
    "all",
    (v) => v === "all" || (typeof v === "string" && v in STUDENT_STATUS_LABELS),
  );
  const filteredStudents = students?.filter(
    (s) => statusFilter === "all" || s.status === statusFilter,
  );

  const campusName = (id: string) =>
    campuses?.find((c) => c.id === id)?.name ?? "—";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl">Alumnos</h1>
        {/* all creation goes through the inscripciones wizard */}
        {canEnroll && (
          <Button className="font-bold" asChild>
            <Link to="/inscripciones">
              <Plus className="size-4" /> Inscribir alumno
            </Link>
          </Button>
        )}
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

      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-14" aria-label="Fotografía" />
              <TableHead>Matrícula</TableHead>
              <TableHead>Nombre</TableHead>
              <TableHead>CURP</TableHead>
              <TableHead>Plantel</TableHead>
              <TableHead>Ingreso</TableHead>
              <TableHead>Estatus</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading &&
              [1, 2, 3, 4].map((i) => (
                <TableRow key={i}>
                  <TableCell colSpan={7}>
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
                <TableCell>
                  <StudentAvatar
                    studentId={s.id}
                    name={s.full_name}
                    hasPhoto={s.has_photo}
                    className="size-8 text-xs"
                  />
                </TableCell>
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
                <TableCell className="text-muted-foreground" data-numeric>
                  {formatDate(s.created_at)}
                </TableCell>
                <TableCell>
                  <StudentStatusBadge status={s.status} />
                </TableCell>
              </TableRow>
            ))}
            {filteredStudents && filteredStudents.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="py-10 text-center text-muted-foreground"
                >
                  {search || effectiveCampus !== "all" || statusFilter !== "all" ? (
                    "Sin resultados"
                  ) : (
                    <div className="flex flex-col items-center gap-3">
                      <span>Sin alumnos registrados</span>
                      {canEnroll && (
                        <Button className="font-bold" asChild>
                          <Link to="/inscripciones">
                            <Plus className="size-4" /> Inscribir alumno
                          </Link>
                        </Button>
                      )}
                    </div>
                  )}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
