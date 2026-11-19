// Configuración: the institution's own rules, editable from Scholar (no code, no
// server settings). Académico holds the reglamento; Institución its name.
import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { Institution } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export const Route = createFileRoute("/_auth/configuracion")({
  component: ConfiguracionPage,
});

const errorText = (e: unknown) =>
  e instanceof ApiError ? e.message : "Solo Servicios Escolares o Dirección pueden cambiarlo";

function useInstitution() {
  return useQuery({
    queryKey: queryKeys.institution,
    queryFn: () => api<Institution>("/catalog/institution"),
  });
}

function useSaveInstitution(message: string, onDone?: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Institution>) =>
      api<Institution>("/catalog/institution", { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.institution });
      toast.success(message);
      onDone?.();
    },
    onError: (e) => toast.error(errorText(e)),
  });
}

function ConfiguracionPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl">Configuración</h1>
        <p className="text-sm text-muted-foreground">
          Las reglas de la institución. Lo que cambies aquí aplica de inmediato y queda en la
          bitácora.
        </p>
      </div>
      <Tabs defaultValue="academico">
        <TabsList>
          <TabsTrigger value="academico">Académico</TabsTrigger>
          <TabsTrigger value="institucion">Institución</TabsTrigger>
        </TabsList>
        <TabsContent value="academico" className="mt-4">
          <AcademicoSettings />
        </TabsContent>
        <TabsContent value="institucion" className="mt-4">
          <InstitucionSettings />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function AcademicoSettings() {
  const { data: institution, isLoading } = useInstitution();
  const [value, setValue] = useState<string | null>(null);
  const save = useSaveInstitution("Regla de promoción guardada", () => setValue(null));
  if (isLoading || !institution) return <Skeleton className="h-40 w-full rounded-md" />;
  const current = value ?? String(institution.max_failed_to_promote ?? 0);
  const n = Number(current);
  const valid = current.trim() !== "" && Number.isInteger(n) && n >= 0 && n <= 20;
  return (
    <Card className="rounded-md">
      <CardContent className="space-y-4 p-6">
        <div>
          <h2 className="text-lg font-bold">Promoción al siguiente cuatrimestre</h2>
          <p className="text-sm text-muted-foreground">
            Cuántas materias del cuatrimestre que termina puede tener reprobadas un alumno y aun
            así avanzar al siguiente en la promoción de ciclo.
          </p>
        </div>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate({ max_failed_to_promote: n });
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="max-failed">Materias reprobadas permitidas</Label>
            <Input
              id="max-failed"
              type="number"
              min={0}
              max={20}
              step={1}
              className="w-32"
              value={current}
              onChange={(e) => setValue(e.target.value)}
            />
          </div>
          <Button
            type="submit"
            className="font-bold"
            disabled={!valid || save.isPending || n === institution.max_failed_to_promote}
          >
            {save.isPending ? "Guardando…" : "Guardar"}
          </Button>
        </form>
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>
            <b>0</b>: debe aprobar todas las materias del cuatrimestre para avanzar.
          </li>
          <li>
            Con reprobadas permitidas avanza, y las reprobadas quedan en su kárdex para
            recursarlas («Agregar materias» o «Cursar en otro grupo»).
          </li>
          <li>
            La seriación se sigue respetando: si una materia del siguiente cuatrimestre requiere
            una reprobada, no se le inscribe a esa.
          </li>
          <li>
            Si alguna materia quedó sin calificación (en curso o de baja), no avanza hasta que se
            califique.
          </li>
        </ul>
      </CardContent>
    </Card>
  );
}

function InstitucionSettings() {
  const { data: institution, isLoading } = useInstitution();
  const [form, setForm] = useState<{ name: string; short_name: string } | null>(null);
  const save = useSaveInstitution("Datos de la institución guardados", () => setForm(null));
  if (isLoading || !institution) return <Skeleton className="h-40 w-full rounded-md" />;
  const model = form ?? { name: institution.name, short_name: institution.short_name };
  return (
    <Card className="rounded-md">
      <CardContent className="space-y-4 p-6">
        <div>
          <h2 className="text-lg font-bold">Institución</h2>
          <p className="text-sm text-muted-foreground">
            El nombre sale en el kárdex y en los documentos. Los datos fiscales de los recibos se
            editan en Tesorería → Ajustes.
          </p>
        </div>
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate({ name: model.name.trim(), short_name: model.short_name.trim() });
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="inst-name">Nombre</Label>
            <Input
              id="inst-name"
              required
              maxLength={255}
              value={model.name}
              onChange={(e) => setForm({ ...model, name: e.target.value })}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="inst-short">Nombre corto</Label>
            <Input
              id="inst-short"
              required
              maxLength={64}
              value={model.short_name}
              onChange={(e) => setForm({ ...model, short_name: e.target.value })}
            />
          </div>
          <div className="sm:col-span-2">
            <Button
              type="submit"
              className="font-bold"
              disabled={!form || !model.name.trim() || !model.short_name.trim() || save.isPending}
            >
              {save.isPending ? "Guardando…" : "Guardar"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
