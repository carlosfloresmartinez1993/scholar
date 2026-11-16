// «Importar del calendario» en Programas: vista previa de las carreras del
// calendario y qué pasaría con cada una; se copian (o vinculan) las elegidas.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarDays } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { CalendarProgramPreview, CalendarProgramsImportResult } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
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

const STATUS: Record<CalendarProgramPreview["status"], { label: string; variant: "default" | "secondary" | "outline" | "destructive" }> = {
  nueva: { label: "Nueva", variant: "default" },
  vincular: { label: "Ya existe: se vincula", variant: "secondary" },
  sincronizada: { label: "Sincronizada", variant: "outline" },
  diferente: { label: "Sincronizada · nombre distinto", variant: "outline" },
  no_importable: { label: "No se puede traer", variant: "destructive" },
};

const importable = (r: CalendarProgramPreview) => r.status === "nueva" || r.status === "vincular";

export function CalendarProgramsImportButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        <CalendarDays className="size-4" /> Importar del calendario
      </Button>
      {open && <ImportDialog onClose={() => setOpen(false)} />}
    </>
  );
}

function ImportDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["calendar-programs-preview"],
    queryFn: () => api<CalendarProgramPreview[]>("/catalog/calendar/programs/preview"),
    gcTime: 0,
    retry: false,
  });
  const [unchecked, setUnchecked] = useState<Set<string>>(new Set());
  const chosen = (data ?? []).filter((r) => importable(r) && !unchecked.has(r.calendar_program_id));

  const run = useMutation({
    mutationFn: () =>
      api<CalendarProgramsImportResult>("/catalog/programs/import-calendar", {
        method: "POST",
        body: JSON.stringify({ calendar_program_ids: chosen.map((r) => r.calendar_program_id) }),
      }),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.programs });
      queryClient.invalidateQueries({ queryKey: queryKeys.calendarPrograms });
      toast.success(`Carreras: ${r.created.length} creadas, ${r.linked.length} vinculadas`);
      onClose();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "No se pudo importar"),
  });

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Importar carreras del calendario</DialogTitle>
          <DialogDescription>
            Se copia la carrera con su nombre y nivel. El RVOE no se crea solo: el calendario solo
            tiene su número, así que al capturarlo aquí ese número ya viene sugerido y tú pones la
            fecha y la autoridad. Lo que ya esté en Scholar no se sobrescribe.
          </DialogDescription>
        </DialogHeader>
        {isLoading && <Skeleton className="h-40 w-full" />}
        {error && (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {error instanceof ApiError && error.status < 500
              ? error.message
              : "Integración con el calendario no disponible"}
          </p>
        )}
        {data && (
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8" />
                  <TableHead>Carrera en el calendario</TableHead>
                  <TableHead>RVOE</TableHead>
                  <TableHead>Plantel</TableHead>
                  <TableHead>Qué pasa</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((r) => (
                  <TableRow key={r.calendar_program_id} className={importable(r) ? undefined : "text-muted-foreground"}>
                    <TableCell>
                      <Checkbox
                        aria-label={`Traer ${r.name}`}
                        disabled={!importable(r)}
                        checked={importable(r) && !unchecked.has(r.calendar_program_id)}
                        onCheckedChange={(v) =>
                          setUnchecked((prev) => {
                            const next = new Set(prev);
                            if (v === true) next.delete(r.calendar_program_id);
                            else next.add(r.calendar_program_id);
                            return next;
                          })
                        }
                      />
                    </TableCell>
                    <TableCell>
                      <span className="font-semibold">{r.name}</span>
                      {r.scholar_name && r.scholar_name !== r.name && (
                        <span className="block text-xs text-muted-foreground">
                          En Scholar: {r.scholar_name}
                        </span>
                      )}
                    </TableCell>
                    <TableCell data-numeric className="text-xs">
                      {r.rvoe ?? "Sin RVOE en el calendario"}
                      {r.rvoe && (
                        <span className="block text-muted-foreground">
                          {r.has_rvoe ? "ya capturado aquí" : "por capturar aquí"}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>{r.campus ?? "—"}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS[r.status].variant}>{STATUS[r.status].label}</Badge>
                      {r.problems.map((p) => (
                        <span key={p} className="block text-xs text-destructive">
                          {p}
                        </span>
                      ))}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        <DialogFooter>
          <Button
            className="font-bold"
            disabled={run.isPending || chosen.length === 0}
            onClick={() => run.mutate()}
          >
            {run.isPending
              ? "Importando…"
              : chosen.length === 0
                ? "Nada por traer"
                : `Traer ${chosen.length} ${chosen.length === 1 ? "carrera" : "carreras"}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
