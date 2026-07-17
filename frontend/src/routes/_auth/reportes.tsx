import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BarChart3 } from "lucide-react";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  ChargeConceptKind,
  ScholarshipReport,
  TermSummaryRow,
} from "@/api/types";
import { CONCEPT_KIND_LABELS, formatMoney } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
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
          Resumen financiero por cuatrimestre y becas.
        </p>
      </div>
      <BecasSection />
      <TermSummarySection />
    </div>
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
