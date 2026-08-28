import { useState } from "react";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { Campus, Student, StudentStatus, UserPublic } from "@/api/types";
import { formatDate, formatMoney, STUDENT_STATUS_LABELS } from "@/lib/format";
import { StudentAvatar } from "@/components/student-avatar";
import { StudentStatusBadge } from "@/components/student-status-badge";
import { usePersistedState } from "@/lib/use-persisted-state";
import { ALL_CAMPUSES, useCampus } from "@/lib/campus-context";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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

// Mirrors STAFF_FINANCIAL in the backend's deps.py. Asking for ?with_debt as a
// docente is a 403, so the column is not merely hidden — it is never requested.
const DEBT_ROLES: readonly string[] = [
  "admin_sistema",
  "direccion",
  "servicios_escolares",
  "coordinador_academico",
  "tesoreria",
];

function AlumnosPage() {
  const navigate = useNavigate();
  const { data: me } = useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api<UserPublic>("/auth/me"),
  });
  const canEnroll = !!me && (me.is_superuser || ENROLL_ROLES.includes(me.role));
  const canSeeDebt = !!me && (me.is_superuser || DEBT_ROLES.includes(me.role));
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

  // Sticky "solo con adeudo" filter. It is a server-side filter, not a filter on
  // the loaded page: it has to mean "debtors in the institution".
  const [onlyDebtors, setOnlyDebtors] = usePersistedState<boolean>(
    "alumnos-filters-v1:only-debtors",
    false,
    (v) => typeof v === "boolean",
  );

  // The key has to encode the REQUEST, not just the toggle: /asistencias calls
  // queryKeys.students() with no arguments and fetches ?limit=1000 without
  // with_debt. That produced the identical key, so whichever page loaded first
  // won the cache — and rows fetched without with_debt would blank this column.
  const shape = `limit200${canSeeDebt ? "+debt" : ""}${
    onlyDebtors ? "+debtors" : ""
  }`;
  const { data: students, isLoading } = useQuery({
    queryKey: queryKeys.students(search, effectiveCampus, shape),
    queryFn: () =>
      api<Student[]>(
        `/students?limit=200${canSeeDebt ? "&with_debt=true" : ""}${
          onlyDebtors ? "&only_debtors=true" : ""
        }${search ? `&q=${encodeURIComponent(search)}` : ""}${
          effectiveCampus !== ALL_CAMPUSES
            ? `&campus_id=${effectiveCampus}`
            : ""
        }`,
      ),
    // the query is only meaningful once we know whether to ask for the column
    enabled: !!me,
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

  const colCount = canSeeDebt ? 8 : 7;

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

        {canSeeDebt && (
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <Checkbox
              checked={onlyDebtors}
              onCheckedChange={(v) => setOnlyDebtors(v === true)}
            />
            Solo con adeudo
          </label>
        )}
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
              {/* vencido is the number that blocks trámites (RF-T07); the total
                  balance rides underneath it rather than in a column of its own */}
              {canSeeDebt && (
                <TableHead className="text-right">Adeudo</TableHead>
              )}
              <TableHead>Estatus</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading &&
              [1, 2, 3, 4].map((i) => (
                <TableRow key={i}>
                  <TableCell colSpan={colCount}>
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
                {canSeeDebt && (
                  <TableCell className="text-right">
                    <DebtCell
                      overdue={s.overdue_balance}
                      balance={s.balance}
                    />
                  </TableCell>
                )}
                <TableCell>
                  <StudentStatusBadge status={s.status} />
                </TableCell>
              </TableRow>
            ))}
            {filteredStudents && filteredStudents.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={colCount}
                  className="py-10 text-center text-muted-foreground"
                >
                  {search ||
                  effectiveCampus !== "all" ||
                  statusFilter !== "all" ||
                  (canSeeDebt && onlyDebtors) ? (
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

/** Adeudo vencido on top (what RF-T07 blocks documents on), total balance under
 *  it only when the two differ — repeating the same number twice reads as noise.
 *  `undefined` means the list was fetched without ?with_debt: draw nothing
 *  rather than a $0.00 the backend never claimed. */
function DebtCell({
  overdue,
  balance,
}: {
  overdue?: number | null;
  balance?: number | null;
}) {
  if (overdue == null || balance == null) return null;
  if (balance === 0)
    return <span className="text-muted-foreground">—</span>;
  return (
    <div className="leading-tight" data-numeric>
      <span className={overdue > 0 ? "font-bold text-destructive" : ""}>
        {formatMoney(overdue)}
      </span>
      {balance !== overdue && (
        <div className="text-xs text-muted-foreground">
          {formatMoney(balance)} total
        </div>
      )}
    </div>
  );
}
