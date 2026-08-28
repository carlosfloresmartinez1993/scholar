import { useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { GraduationCap, Search } from "lucide-react";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  AlumniRow,
  AlumniStats,
  Campus,
  Program,
  Term,
} from "@/api/types";
import { formatDate, LEVEL_LABELS } from "@/lib/format";
import { ALL_CAMPUSES, useCampus } from "@/lib/campus-context";
import { StudentAvatar } from "@/components/student-avatar";
import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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

export const Route = createFileRoute("/_auth/egresados")({
  component: EgresadosPage,
});

const ALL = "all";

function EgresadosPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [termId, setTermId] = useState(ALL);
  const [programId, setProgramId] = useState(ALL);
  const [titulado, setTitulado] = useState(ALL);
  const { campusId } = useCampus();

  const { data: terms } = useQuery({
    queryKey: queryKeys.terms,
    queryFn: () => api<Term[]>("/catalog/terms"),
  });
  const { data: programs } = useQuery({
    queryKey: queryKeys.programs,
    queryFn: () => api<Program[]>("/catalog/programs"),
  });
  const { data: campuses } = useQuery({
    queryKey: queryKeys.campuses,
    queryFn: () => api<Campus[]>("/catalog/campuses"),
  });

  // One query string for both requests: the cards have to describe the table
  // below them, so they can never be filtered differently.
  const params = new URLSearchParams();
  if (search) params.set("q", search);
  if (termId !== ALL) params.set("term_id", termId);
  if (programId !== ALL) params.set("program_id", programId);
  if (titulado !== ALL) params.set("titulado", titulado);
  const qs = params.toString();
  // campusId is not a param: the X-Campus header already scopes every request.
  const key = `${qs}|${campusId ?? ALL_CAMPUSES}`;

  const { data: rows, isLoading } = useQuery({
    queryKey: queryKeys.alumni(key),
    queryFn: () => api<AlumniRow[]>(`/alumni${qs ? `?${qs}` : ""}`),
  });
  const { data: stats } = useQuery({
    queryKey: queryKeys.alumniStats(key),
    queryFn: () => api<AlumniStats>(`/alumni/stats${qs ? `?${qs}` : ""}`),
  });

  const campusName = (id: string) =>
    campuses?.find((c) => c.id === id)?.name ?? "—";
  const filtered = search || termId !== ALL || programId !== ALL || titulado !== ALL;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl">Egresados</h1>
        <p className="text-sm text-muted-foreground">
          Quién egresó, de qué plan y en qué periodo. El periodo se toma del
          último ciclo en que el alumno estuvo inscrito.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Egresados" value={stats?.egresados} />
        <StatCard label="Titulados" value={stats?.titulados} />
        <StatCard
          label="Tasa de titulación"
          value={stats ? `${stats.titulacion_pct}%` : undefined}
        />
      </div>

      {/* Incomplete records are surfaced, not hidden: a graduate with no
          enrollment history still counts, and someone has to go fix them. */}
      {stats && (stats.sin_periodo > 0 || stats.sin_plan > 0) && (
        <p className="text-sm text-muted-foreground">
          {stats.sin_periodo > 0 && (
            <>
              {stats.sin_periodo} sin periodo derivable (nunca tuvieron
              inscripción a grupo)
            </>
          )}
          {stats.sin_periodo > 0 && stats.sin_plan > 0 && " · "}
          {stats.sin_plan > 0 && <>{stats.sin_plan} sin plan de estudios</>}
          .
        </p>
      )}

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(query.trim());
        }}
      >
        <div className="relative w-80">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar por nombre, CURP o matrícula…"
            aria-label="Buscar egresados"
            className="pl-8"
          />
        </div>
        <Button type="submit" variant="outline">
          Buscar
        </Button>

        <Select value={termId} onValueChange={setTermId}>
          <SelectTrigger className="w-48" aria-label="Filtrar por periodo">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos los periodos</SelectItem>
            {terms?.map((t) => (
              <SelectItem key={t.id} value={t.id}>
                {t.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={programId} onValueChange={setProgramId}>
          <SelectTrigger className="w-56" aria-label="Filtrar por programa">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos los programas</SelectItem>
            {programs?.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={titulado} onValueChange={setTitulado}>
          <SelectTrigger className="w-44" aria-label="Filtrar por titulación">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Titulados y pasantes</SelectItem>
            <SelectItem value="true">Solo titulados</SelectItem>
            <SelectItem value="false">Solo pasantes</SelectItem>
          </SelectContent>
        </Select>
      </form>

      {stats && stats.by_term.length > 1 && (
        <PorPeriodo stats={stats} />
      )}

      {isLoading ? (
        <Skeleton className="h-64 w-full rounded-md" />
      ) : rows && rows.length === 0 ? (
        <EmptyState
          icon={GraduationCap}
          title={filtered ? "Sin resultados" : "Todavía no hay egresados"}
          description={
            filtered
              ? "Ningún egresado coincide con los filtros seleccionados."
              : "Un alumno aparece aquí cuando su estatus pasa a Egresado o su inscripción al plan queda como egresado/titulado."
          }
        />
      ) : (
        <div className="rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-14" aria-label="Fotografía" />
                <TableHead>Matrícula</TableHead>
                <TableHead>Nombre</TableHead>
                <TableHead>Programa</TableHead>
                <TableHead>Periodo de egreso</TableHead>
                <TableHead>Plantel</TableHead>
                <TableHead>Titulación</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows?.map((r) => (
                <TableRow
                  key={`${r.student_id}-${r.plan_enrollment_id ?? "sin-plan"}`}
                  className="cursor-pointer"
                  onClick={() =>
                    navigate({
                      to: "/alumnos/$studentId",
                      params: { studentId: r.student_id },
                    })
                  }
                >
                  <TableCell>
                    <StudentAvatar
                      studentId={r.student_id}
                      name={r.full_name}
                      hasPhoto={r.has_photo}
                      className="size-8 text-xs"
                    />
                  </TableCell>
                  <TableCell className="font-semibold" data-numeric>
                    {r.enrollment_number}
                  </TableCell>
                  <TableCell className="font-semibold">{r.full_name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {r.program_name ? (
                      <>
                        {r.program_name}
                        {r.level && (
                          <span className="block text-xs">
                            {LEVEL_LABELS[r.level]}
                            {r.plan_version_label && ` · Plan ${r.plan_version_label}`}
                            {r.rvoe && ` · RVOE ${r.rvoe}`}
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="italic">Sin plan registrado</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground" data-numeric>
                    {r.egreso_term_name ? (
                      <>
                        {r.egreso_term_name}
                        <span className="block text-xs">
                          {formatDate(r.egreso_date)}
                        </span>
                      </>
                    ) : (
                      <span className="italic">Sin periodo</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {campusName(r.campus_id)}
                  </TableCell>
                  <TableCell>
                    {r.titulado ? (
                      <Badge variant="default">
                        Titulado
                        {r.degree && ` · ${r.degree.folio}`}
                      </Badge>
                    ) : (
                      <Badge variant="outline">Pasante</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
}: {
  label: string;
  value?: number | string;
}) {
  return (
    <Card className="rounded-md">
      <CardContent className="p-5">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        {value === undefined ? (
          <Skeleton className="mt-1 h-8 w-20" />
        ) : (
          <p className="text-2xl font-bold" data-numeric>
            {value}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/** Egresados per period, oldest first — the shape of the cohort over time.
 *  Bars are relative to the biggest period, so a single tall period doesn't
 *  flatten every other one into invisibility. */
function PorPeriodo({ stats }: { stats: AlumniStats }) {
  const max = Math.max(...stats.by_term.map((b) => b.egresados), 1);
  return (
    <section className="space-y-2">
      <h2 className="text-xl font-bold">Por periodo</h2>
      <Card className="rounded-md">
        <CardContent className="space-y-2 p-5">
          {stats.by_term.map((b) => (
            <div
              key={b.term_id ?? "sin-periodo"}
              className="flex items-center gap-3 text-sm"
            >
              <span className="w-40 shrink-0 truncate text-muted-foreground">
                {b.term_name}
              </span>
              <div className="h-3 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${(b.egresados / max) * 100}%` }}
                />
              </div>
              <span className="w-28 shrink-0 text-right" data-numeric>
                {b.egresados}
                <span className="text-muted-foreground">
                  {" "}
                  · {b.titulados} tit.
                </span>
              </span>
            </div>
          ))}
        </CardContent>
      </Card>
    </section>
  );
}
