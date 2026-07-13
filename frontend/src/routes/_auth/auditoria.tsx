import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { AuditEntry } from "@/api/types";
import { formatDateTime } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const Route = createFileRoute("/_auth/auditoria")({
  component: AuditoriaPage,
});

function AuditoriaPage() {
  const { data: entries, isLoading } = useQuery({
    queryKey: queryKeys.audit,
    queryFn: () => api<AuditEntry[]>("/audit?limit=500"),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-3xl">Auditoría</h1>

      <div className="rounded-2xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Fecha</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Acción</TableHead>
              <TableHead>Entidad</TableHead>
              <TableHead>Detalle</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading &&
              [1, 2, 3, 4, 5].map((i) => (
                <TableRow key={i}>
                  <TableCell colSpan={5}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {entries?.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="whitespace-nowrap text-muted-foreground">
                  {formatDateTime(e.created_at)}
                </TableCell>
                <TableCell className="font-semibold">{e.actor}</TableCell>
                <TableCell>
                  <Badge variant="outline">{e.action}</Badge>
                </TableCell>
                <TableCell>
                  {e.entity ? `${e.entity}${e.entity_id ? ` · ${e.entity_id.slice(0, 8)}` : ""}` : "—"}
                </TableCell>
                <TableCell className="max-w-md truncate text-muted-foreground">
                  {e.detail || "—"}
                </TableCell>
              </TableRow>
            ))}
            {entries && entries.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className="py-10 text-center text-muted-foreground"
                >
                  Sin registros de auditoría
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
