// Planteles: la copia de scholar de los campus del calendario, más los que se
// agreguen aquí. Sincronizar trae los que falten; nunca pisa lo editado aquí.
import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarDays, ImageUp, Pencil, Plus, Trash2 } from "lucide-react";
import { api, apiUpload, ApiError } from "@/api/client";
import { campusLogoUrl } from "@/lib/campus-logo";
import { queryKeys } from "@/api/query-keys";
import type { Campus, CampusSyncResult } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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

export const Route = createFileRoute("/_auth/planteles")({
  component: PlantelesPage,
});

const NO_LINK = "__none__";

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

function PlantelesPage() {
  const queryClient = useQueryClient();
  const { data: campuses, isLoading } = useQuery({
    queryKey: queryKeys.campuses,
    queryFn: () => api<Campus[]>("/catalog/campuses"),
  });
  const [editing, setEditing] = useState<Campus | "new" | null>(null);
  const [differences, setDifferences] = useState<CampusSyncResult["different"]>([]);

  const sync = useMutation({
    mutationFn: () => api<CampusSyncResult>("/catalog/campuses/sync-calendar", { method: "POST" }),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.campuses });
      setDifferences(r.different);
      const parts = [
        r.created.length ? `${r.created.length} creados` : "",
        r.linked.length ? `${r.linked.length} vinculados` : "",
      ].filter(Boolean);
      toast.success(parts.length ? `Planteles: ${parts.join(", ")}` : "Planteles al día con el calendario");
    },
    onError: (e) => toast.error(errorText(e, "No se pudo sincronizar")),
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl">Planteles</h1>
        <div className="flex items-center gap-2">
          <Button variant="outline" disabled={sync.isPending} onClick={() => sync.mutate()}>
            <CalendarDays className="size-4" />
            {sync.isPending ? "Sincronizando…" : "Sincronizar con calendario"}
          </Button>
          <Button className="font-bold" onClick={() => setEditing("new")}>
            <Plus className="size-4" /> Nuevo plantel
          </Button>
        </div>
      </div>
      <p className="text-sm text-muted-foreground">
        Los planteles no dependen del periodo. Sincronizar trae los del calendario que falten; lo
        que cambies aquí no se sobrescribe.
      </p>

      {differences.length > 0 && (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-semibold">Nombres distintos en el calendario (aquí no se cambiaron):</p>
          <ul className="mt-1 list-disc pl-5">
            {differences.map((d) => (
              <li key={d.scholar}>
                Aquí «{d.scholar}» · en el calendario «{d.calendar}»
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-24">Logo</TableHead>
              <TableHead>Nombre</TableHead>
              <TableHead>Dirección</TableHead>
              <TableHead>Calendario</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead className="w-16" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={6}>
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            )}
            {campuses?.map((c) => (
              <TableRow key={c.id}>
                <TableCell>
                  {c.logo_updated_at ? (
                    <img
                      src={campusLogoUrl(c.id, c.logo_updated_at)}
                      alt={`Logo de ${c.name}`}
                      className="h-8 max-w-20 object-contain"
                    />
                  ) : (
                    <span className="text-xs text-muted-foreground">Sin logo</span>
                  )}
                </TableCell>
                <TableCell className="font-semibold">{c.name}</TableCell>
                <TableCell className="text-muted-foreground">{c.address || "—"}</TableCell>
                <TableCell>
                  <Badge variant={c.calendar_campus_id ? "secondary" : "outline"}>
                    {c.calendar_campus_id ? "Sincronizado" : "Solo en Scholar"}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge variant={c.is_active ? "outline" : "destructive"}>
                    {c.is_active ? "Activo" : "Inactivo"}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Editar ${c.name}`}
                    onClick={() => setEditing(c)}
                  >
                    <Pencil className="size-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {editing && (
        <CampusDialog campus={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
      )}
    </div>
  );
}

function CampusDialog({ campus, onClose }: { campus: Campus | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(campus?.name ?? "");
  const [address, setAddress] = useState(campus?.address ?? "");
  const [active, setActive] = useState(campus?.is_active ?? true);
  const [link, setLink] = useState(campus?.calendar_campus_id ?? NO_LINK);
  // the calendar's campuses, to link this one by hand (hidden without the integration)
  const { data: calendarCampuses } = useQuery({
    queryKey: ["calendar-campuses"],
    queryFn: () => api<{ id: string; name: string }[]>("/catalog/calendar/campuses"),
    retry: false,
    enabled: !!campus,
  });
  const save = useMutation({
    mutationFn: () =>
      api<Campus>(campus ? `/catalog/campuses/${campus.id}` : "/catalog/campuses", {
        method: campus ? "PATCH" : "POST",
        body: JSON.stringify({
          name: name.trim(),
          address: address.trim(),
          is_active: active,
          ...(campus && calendarCampuses ? { calendar_campus_id: link === NO_LINK ? null : link } : {}),
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.campuses });
      toast.success(campus ? "Plantel actualizado" : "Plantel creado");
      onClose();
    },
    onError: (e) => toast.error(errorText(e, "No se pudo guardar")),
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{campus ? "Editar plantel" : "Nuevo plantel"}</DialogTitle>
          <DialogDescription>
            {campus?.calendar_campus_id
              ? "Viene del calendario. Lo que cambies aquí se queda en Scholar; el calendario no se modifica."
              : "Un plantel que solo existe en Scholar. Si después aparece en el calendario con el mismo nombre, se vincula al sincronizar."}
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="campus-name">Nombre</Label>
            <Input
              id="campus-name"
              required
              maxLength={255}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="campus-address">Dirección (opcional)</Label>
            <Input
              id="campus-address"
              maxLength={512}
              value={address}
              onChange={(e) => setAddress(e.target.value)}
            />
          </div>
          {campus && calendarCampuses && (
            <div className="grid gap-2">
              <Label htmlFor="campus-link">Vínculo con el calendario</Label>
              <Select value={link} onValueChange={setLink}>
                <SelectTrigger id="campus-link" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_LINK}>Sin vincular (solo en Scholar)</SelectItem>
                  {calendarCampuses.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {campus && <CampusLogoField campus={campus} />}
          <label className="flex items-center gap-2 text-sm font-medium">
            <Checkbox checked={active} onCheckedChange={(v) => setActive(v === true)} />
            Plantel activo
          </label>
          <DialogFooter>
            <Button type="submit" className="font-bold" disabled={save.isPending || !name.trim()}>
              {save.isPending ? "Guardando…" : "Guardar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// The logo printed on top of the kárdex of this plantel's students. PNG or JPG
// (what the PDF can embed), up to 2 MB. Saved right away, apart from «Guardar».
function CampusLogoField({ campus }: { campus: Campus }) {
  const queryClient = useQueryClient();
  const [version, setVersion] = useState(campus.logo_updated_at ?? null);
  const done = (c: Campus, message: string) => {
    setVersion(c.logo_updated_at ?? null);
    queryClient.invalidateQueries({ queryKey: queryKeys.campuses });
    toast.success(message);
  };
  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file, file.name);
      return apiUpload<Campus>(`/catalog/campuses/${campus.id}/logo`, form);
    },
    onSuccess: (c) => done(c, "Logo guardado"),
    onError: (e) => toast.error(errorText(e, "No se pudo subir el logo")),
  });
  const remove = useMutation({
    mutationFn: () => api<Campus>(`/catalog/campuses/${campus.id}/logo`, { method: "DELETE" }),
    onSuccess: (c) => done(c, "Logo quitado"),
    onError: (e) => toast.error(errorText(e, "No se pudo quitar el logo")),
  });
  return (
    <div className="grid gap-2">
      <Label>Logo para el kárdex</Label>
      <div className="flex items-center gap-3 rounded-md border p-3">
        <div className="flex h-14 w-28 items-center justify-center rounded bg-muted/50">
          {version ? (
            <img
              src={campusLogoUrl(campus.id, version)}
              alt={`Logo de ${campus.name}`}
              className="max-h-12 max-w-26 object-contain"
            />
          ) : (
            <span className="text-xs text-muted-foreground">Sin logo</span>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" asChild disabled={upload.isPending}>
            <label className="cursor-pointer">
              <ImageUp className="size-4" />
              {upload.isPending ? "Subiendo…" : version ? "Cambiar" : "Subir logo"}
              <input
                type="file"
                accept="image/png,image/jpeg"
                className="sr-only"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file) return;
                  if (file.size > 2 * 1024 * 1024) {
                    toast.error("El logo debe pesar menos de 2 MB");
                    return;
                  }
                  upload.mutate(file);
                }}
              />
            </label>
          </Button>
          {version && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              <Trash2 className="size-4" /> Quitar
            </Button>
          )}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        PNG o JPG, máximo 2 MB. Sale arriba en el kárdex de los alumnos de este plantel; sin logo
        se usa el de INUE.
      </p>
    </div>
  );
}
