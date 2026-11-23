// Historia del alumno (Resumen, al final): where the student is now and what
// happened with them, in order — ingreso, cuatrimestres, bajas, reingresos,
// cambios de RVOE, reconocimientos and corrections.
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRightLeft,
  BadgeCheck,
  CircleDot,
  LogIn,
  PauseCircle,
  PencilLine,
  PlayCircle,
  RefreshCcw,
  Repeat,
  RotateCcw,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "@/api/client";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface HistoryEvent {
  date: string;
  kind: string;
  title: string;
  detail: string;
  term: string | null;
  actor: string | null;
}

interface StudentHistory {
  status: string;
  status_label: string;
  current: {
    period_number: number;
    group_code: string;
    term_name: string;
    term_open: boolean;
    program: string;
  } | null;
  events: HistoryEvent[];
}

const KIND_STYLE: Record<string, { icon: LucideIcon; tone: string }> = {
  ingreso: { icon: LogIn, tone: "text-emerald-600 dark:text-emerald-400" },
  cuatrimestre: { icon: CircleDot, tone: "text-primary" },
  reingreso: { icon: PlayCircle, tone: "text-emerald-600 dark:text-emerald-400" },
  repite: { icon: RotateCcw, tone: "text-amber-600 dark:text-amber-400" },
  recursa: { icon: RotateCcw, tone: "text-muted-foreground" },
  baja: { icon: PauseCircle, tone: "text-red-600 dark:text-red-400" },
  estatus: { icon: RefreshCcw, tone: "text-sky-600 dark:text-sky-400" },
  cambio_grupo: { icon: ArrowRightLeft, tone: "text-muted-foreground" },
  otro_grupo: { icon: Users, tone: "text-muted-foreground" },
  reconocimiento: { icon: BadgeCheck, tone: "text-violet-600 dark:text-violet-400" },
  rvoe: { icon: Repeat, tone: "text-amber-600 dark:text-amber-400" },
  correccion: { icon: PencilLine, tone: "text-muted-foreground" },
};

export function StudentHistorySection({ studentId }: { studentId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["student-history", studentId],
    queryFn: () => api<StudentHistory>(`/students/${studentId}/history`),
  });
  return (
    <Card className="rounded-md">
      <CardContent className="space-y-4 p-6">
        <h2 className="text-lg font-bold">Historia del alumno</h2>
        {isLoading || !data ? (
          <Skeleton className="h-32 w-full" />
        ) : (
          <>
            <div className="rounded-md border bg-muted/30 px-4 py-3 text-sm">
              {data.current ? (
                <>
                  Va en <b>{data.current.period_number}.º cuatrimestre</b> — grupo{" "}
                  <b data-numeric>{data.current.group_code}</b> ({data.current.term_name}) ·{" "}
                  {data.current.program}
                </>
              ) : (
                <>Sin grupo actual</>
              )}
              {" · "}Estatus: <b>{data.status_label || data.status}</b>
            </div>
            {data.events.length === 0 ? (
              <p className="text-sm text-muted-foreground">Sin movimientos registrados.</p>
            ) : (
              <ol className="relative space-y-4 border-l pl-6">
                {data.events.map((e, i) => {
                  const style = KIND_STYLE[e.kind] ?? KIND_STYLE.cuatrimestre;
                  const Icon = style.icon;
                  return (
                    <li key={i} className="relative">
                      <span
                        className={cn(
                          "absolute -left-[33px] flex size-5 items-center justify-center rounded-full bg-background",
                          style.tone,
                        )}
                      >
                        <Icon className="size-4" />
                      </span>
                      <div className="text-xs text-muted-foreground" data-numeric>
                        {e.term ?? formatDate(e.date)}
                      </div>
                      <div className="font-semibold">{e.title}</div>
                      {e.detail && <div className="text-sm text-muted-foreground">{e.detail}</div>}
                      {e.actor && (
                        <div className="text-xs text-muted-foreground">Registró: {e.actor}</div>
                      )}
                    </li>
                  );
                })}
              </ol>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
