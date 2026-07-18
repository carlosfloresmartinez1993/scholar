import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, Download } from "lucide-react";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  AgingRow,
  ChargeConceptKind,
  CollectionReport,
  ScholarshipReport,
  Term,
  TermSummaryRow,
} from "@/api/types";
import {
  CONCEPT_KIND_LABELS,
  formatDate,
  formatMoney,
  PAYMENT_METHOD_LABELS,
} from "@/lib/format";
import {
  DateRangeFilter,
  presetRange,
  type DateRange,
} from "@/components/date-range-filter";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
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

export const Route = createFileRoute("/_auth/reportes")({
  component: ReportesPage,
});

function ReportesPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Reportes</h1>
        <p className="text-sm text-muted-foreground">
          Cobranza, cartera vencida, becas y resumen por cuatrimestre.
        </p>
      </div>
      <CobranzaSection />
      <BecasSection />
      <TermSummarySection />
      <CarteraVencidaSection />
      <SepExportSection />
    </div>
  );
}

// --- Cobranza por periodo (con exportación CSV) --------------------------------------

function CobranzaSection() {
  const [range, setRange] = useState<DateRange>(() => presetRange("mes"));
  const { data: collection, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.collectionReport(range.from, range.to),
    queryFn: () =>
      api<CollectionReport>(
        `/treasury/reports/collection?date_from=${range.from}&date_to=${range.to}`,
      ),
  });

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-bold">Cobranza</h2>
        <DateRangeFilter value={range} onChange={setRange} />
      </div>
      {isError ? (
        <div className="flex items-center gap-3 text-sm text-destructive">
          No se pudo cargar el reporte de cobranza.
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            Reintentar
          </Button>
        </div>
      ) : isLoading ? (
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
  );
}

// --- Cartera vencida (detalle por cargo) ---------------------------------------------

function CarteraVencidaSection() {
  const { data: aging, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.aging,
    queryFn: () => api<AgingRow[]>("/treasury/reports/aging"),
  });
  const agingTotal = aging?.reduce((sum, r) => sum + r.balance, 0) ?? 0;

  if (isError) {
    return (
      <section className="space-y-3">
        <h2 className="text-xl font-bold">Cartera vencida</h2>
        <div className="flex items-center gap-3 text-sm text-destructive">
          No se pudo cargar la cartera vencida.
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            Reintentar
          </Button>
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-3">
      <h2 className="text-xl font-bold">
        Cartera vencida{" "}
        <span className="text-muted-foreground" data-numeric>
          · {formatMoney(agingTotal)}
        </span>
      </h2>
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
            {isLoading && (
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
  );
}

// --- Exportación SEP ------------------------------------------------------------------

function SepExportSection() {
  const { data: terms } = useQuery({
    queryKey: queryKeys.terms,
    queryFn: () => api<Term[]>("/catalog/terms"),
  });
  const [sepTermId, setSepTermId] = useState<string>("");
  const effectiveSepTerm = sepTermId || terms?.find((t) => t.is_open)?.id || "";

  return (
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
          {effectiveSepTerm ? (
            <Button variant="outline" asChild>
              <a
                href={`/api/v1/students/exports/sep?term_id=${effectiveSepTerm}`}
                download
              >
                <Download className="size-4" /> Exportar alumnos SEP (CSV)
              </a>
            </Button>
          ) : (
            <Button variant="outline" disabled>
              <Download className="size-4" /> Exportar alumnos SEP (CSV)
            </Button>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

function StatCard({ label, value }: { label: string; value?: number | string }) {
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

function BecasSection() {
  const { data: becas, isError, refetch } = useQuery({
    queryKey: queryKeys.scholarshipReport,
    queryFn: () => api<ScholarshipReport>("/treasury/reports/scholarships"),
  });

  if (isError) {
    return (
      <section className="space-y-3">
        <h2 className="text-xl font-bold">Becas</h2>
        <div className="flex items-center gap-3 text-sm text-destructive">
          No se pudo cargar el reporte de becas.
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            Reintentar
          </Button>
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-3">
      <h2 className="text-xl font-bold">Becas</h2>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard label="Alumnos activos" value={becas?.active_students} />
        <StatCard label="Con beca" value={becas?.students_with_scholarship} />
        <StatCard
          label="% con beca"
          value={becas ? `${becas.pct_with_scholarship}%` : undefined}
        />
        <StatCard
          label="Beca aplicada · mes"
          value={becas ? formatMoney(becas.beca_mes) : undefined}
        />
        <StatCard
          label="Beca aplicada · cuatrimestre"
          value={becas ? formatMoney(becas.beca_cuatrimestre) : undefined}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        Montos acumulados hasta hoy (no proyectados).
      </p>
    </section>
  );
}

function TermSummarySection() {
  const { data: rows, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.termSummary,
    queryFn: () => api<TermSummaryRow[]>("/treasury/reports/term-summary"),
  });

  return (
    <section className="space-y-3">
      <h2 className="text-xl font-bold">Resumen por cuatrimestre</h2>
      {isError ? (
        <div className="flex items-center gap-3 text-sm text-destructive">
          No se pudo cargar el resumen por cuatrimestre.
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            Reintentar
          </Button>
        </div>
      ) : isLoading ? (
        <Skeleton className="h-40 w-full rounded-md" />
      ) : rows && rows.length === 0 ? (
        <EmptyState
          icon={BarChart3}
          title="Sin datos de facturación"
          description="Aún no se han generado cargos por cuatrimestre."
        />
      ) : (
        <div className="rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ciclo</TableHead>
                <TableHead className="text-right">Esperado</TableHead>
                <TableHead className="text-right">Cobrado</TableHead>
                <TableHead className="text-right">Pendiente</TableHead>
                <TableHead className="w-48">% cobrado</TableHead>
                <TableHead>Desglose</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows?.map((r) => {
                const pct = Math.max(0, Math.min(r.collection_pct, 100));
                return (
                  <TableRow key={r.term_id}>
                    <TableCell className="font-semibold">{r.term_name}</TableCell>
                    <TableCell className="text-right" data-numeric>
                      {formatMoney(r.expected)}
                    </TableCell>
                    <TableCell className="text-right" data-numeric>
                      {formatMoney(r.collected)}
                    </TableCell>
                    <TableCell className="text-right" data-numeric>
                      {formatMoney(r.pending)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <div
                          className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted"
                          role="progressbar"
                          aria-valuenow={pct}
                          aria-valuemin={0}
                          aria-valuemax={100}
                        >
                          <div
                            className="h-full rounded-full bg-primary"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span
                          className="w-12 text-right text-xs font-semibold"
                          data-numeric
                        >
                          {r.collection_pct}%
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {Object.entries(r.by_concept).map(([kind, v]) => (
                        <span key={kind} className="mr-3 whitespace-nowrap">
                          {CONCEPT_KIND_LABELS[kind as ChargeConceptKind] ?? kind}
                          :{" "}
                          <span data-numeric className="font-semibold">
                            {formatMoney(v.expected)}
                          </span>{" "}
                          (cobrado{" "}
                          <span data-numeric>{formatMoney(v.collected)}</span>)
                        </span>
                      ))}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}
