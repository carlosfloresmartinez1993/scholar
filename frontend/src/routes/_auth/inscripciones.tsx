import { useMemo, useRef, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ClipboardList } from "lucide-react";
import { api, bulkIntake } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { BulkIntakeResult, BulkIntakeRow, Group, Term } from "@/api/types";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const Route = createFileRoute("/_auth/inscripciones")({
  component: InscripcionesPage,
});

const PREVIEW_CAP = 50;
const MAX_ROWS = 1000; // mirrors the backend cap on bulk-intake rows

// ponytail: names containing a comma break comma-separated parsing
// (curp,nombre,email). Paste from Excel (tab-separated) to avoid it.
function parseRows(text: string): BulkIntakeRow[] {
  const lines = text
    .replace(/^\uFEFF/, "") // strip a UTF-8 BOM (Excel .csv) before parsing
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  const rows: BulkIntakeRow[] = [];
  lines.forEach((line, i) => {
    const cells = (line.includes("\t") ? line.split("\t") : line.split(",")).map(
      (c) => c.trim(),
    );
    // only skip an EXPLICIT header row — a real (even invalid) CURP is kept and
    // reported by the backend, never silently dropped
    if (i === 0 && cells[0].toUpperCase() === "CURP") return;
    rows.push({
      curp: cells[0] ?? "",
      full_name: cells[1] ?? "",
      email: cells[2] ?? "",
    });
  });
  return rows;
}

function InscripcionesPage() {
  const { data: terms } = useQuery({
    queryKey: queryKeys.terms,
    queryFn: () => api<Term[]>("/catalog/terms"),
  });
  const [selectedTerm, setSelectedTerm] = useState<string | null>(null);
  const termId = selectedTerm ?? terms?.find((t) => t.is_open)?.id ?? null;

  const { data: groups } = useQuery({
    queryKey: queryKeys.groups(termId ?? undefined),
    queryFn: () => api<Group[]>(`/catalog/groups?term_id=${termId}`),
    enabled: !!termId,
  });

  const [groupId, setGroupId] = useState<string | null>(null);
  const group = groups?.find((g) => g.id === groupId) ?? null;

  // shared options (apply to both modes)
  const [waiveEnrollmentFee, setWaiveEnrollmentFee] = useState(false);
  const [override, setOverride] = useState(false);
  const options = {
    waive_enrollment_fee: waiveEnrollmentFee,
    override_prerequisites: override,
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl">Inscripciones</h1>
        <div className="flex items-center gap-2">
          <Select
            value={termId ?? ""}
            onValueChange={(v) => {
              setSelectedTerm(v);
              setGroupId(null);
            }}
          >
            <SelectTrigger className="w-56">
              <SelectValue placeholder="Seleccione un ciclo" />
            </SelectTrigger>
            <SelectContent>
              {terms?.map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {t.name}
                  {t.is_open ? " · abierto" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={groupId ?? ""}
            onValueChange={setGroupId}
            disabled={!termId}
          >
            <SelectTrigger className="w-56">
              <SelectValue placeholder="Seleccione un grupo" />
            </SelectTrigger>
            <SelectContent>
              {groups?.map((g) => (
                <SelectItem key={g.id} value={g.id}>
                  {g.code} · P{g.period_number}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {!group ? (
        <EmptyState
          icon={ClipboardList}
          title="Seleccione un grupo"
          description="Elija el ciclo y el grupo al que inscribirá a los alumnos. El campus se toma del grupo."
        />
      ) : (
        <>
          <Card>
            <CardContent className="flex flex-wrap gap-6 py-4">
              <label className="flex items-center gap-2 text-sm font-medium">
                <Checkbox
                  checked={waiveEnrollmentFee}
                  onCheckedChange={(v) => setWaiveEnrollmentFee(v === true)}
                />
                Condonar inscripción (no cobrar)
              </label>
              <details className="text-sm">
                <summary className="cursor-pointer text-muted-foreground">
                  Opciones avanzadas
                </summary>
                <label className="mt-2 flex items-center gap-2 font-medium">
                  <Checkbox
                    checked={override}
                    onCheckedChange={(v) => setOverride(v === true)}
                  />
                  Omitir seriación (autorización especial)
                </label>
              </details>
            </CardContent>
          </Card>

          <Tabs defaultValue="single">
            <TabsList>
              <TabsTrigger value="single">Alumno nuevo</TabsTrigger>
              <TabsTrigger value="bulk">Carga masiva</TabsTrigger>
            </TabsList>
            <TabsContent value="single">
              <SingleIntake group={group} options={options} />
            </TabsContent>
            <TabsContent value="bulk">
              <BulkIntake group={group} options={options} />
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}

type SharedOptions = {
  waive_enrollment_fee: boolean;
  override_prerequisites: boolean;
};

function SingleIntake({
  group,
  options,
}: {
  group: Group;
  options: SharedOptions;
}) {
  const [form, setForm] = useState({ curp: "", full_name: "", email: "" });

  const submit = useMutation({
    mutationFn: () =>
      bulkIntake({ group_id: group.id, rows: [form], ...options }),
    onSuccess: (r: BulkIntakeResult) => {
      if (r.enrolled === 1) {
        toast.success("Alumno inscrito");
        setForm({ curp: "", full_name: "", email: "" });
      } else {
        toast.error(r.errors[0]?.detail ?? "No se pudo inscribir al alumno");
      }
    },
    onError: () => toast.error("Error al inscribir"),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Alumno nuevo</CardTitle>
        <CardDescription>
          Se creará el alumno y se inscribirá al grupo {group.code}. Si el
          tabulador está configurado, se generan los cargos del cuatrimestre.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="grid max-w-lg gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            submit.mutate();
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="s-curp">CURP</Label>
            <Input
              id="s-curp"
              required
              value={form.curp}
              onChange={(e) =>
                setForm({ ...form, curp: e.target.value.toUpperCase() })
              }
              placeholder="XAXX010101HDFXXX01"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="s-name">Nombre completo</Label>
            <Input
              id="s-name"
              required
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              placeholder="Juan Pérez López"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="s-email">Email (opcional)</Label>
            <Input
              id="s-email"
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              placeholder="alumno@correo.com"
            />
          </div>
          <div>
            <Button
              type="submit"
              className="font-bold"
              disabled={submit.isPending}
            >
              {submit.isPending ? "Inscribiendo…" : "Inscribir alumno"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function BulkIntake({
  group,
  options,
}: {
  group: Group;
  options: SharedOptions;
}) {
  const [raw, setRaw] = useState("");
  const [result, setResult] = useState<BulkIntakeResult | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const rows = useMemo(() => parseRows(raw), [raw]);

  const submit = useMutation({
    mutationFn: () => bulkIntake({ group_id: group.id, rows, ...options }),
    onSuccess: (r: BulkIntakeResult) => {
      setResult(r);
      if (r.errors.length === 0) {
        toast.success(`${r.enrolled} alumnos inscritos`);
        setRaw(""); // all done — clear the editor
      } else {
        toast.warning(`${r.enrolled} inscritos · ${r.errors.length} con error`);
        // keep ONLY the failed rows so a resubmit doesn't re-send the ones that
        // already succeeded (which would come back as "ya existe")
        const failed = r.errors
          .map((e) => rows[e.row - 1])
          .filter((row): row is BulkIntakeRow => Boolean(row))
          .map((row) => [row.curp, row.full_name, row.email].join("\t"));
        setRaw(failed.join("\n"));
      }
    },
    onError: () => toast.error("Error en la carga masiva"),
  });

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setRaw(await file.text());
    if (fileRef.current) fileRef.current.value = "";
  }

  const truncated = rows.length > PREVIEW_CAP;
  if (truncated) {
    console.log(
      `Vista previa limitada a ${PREVIEW_CAP} de ${rows.length} filas; se enviarán todas.`,
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Carga masiva</CardTitle>
        <CardDescription>
          Un alumno por línea: <code>CURP, Nombre, Email</code> (email opcional).
          Acepta separación por tabulador o coma. Pegue desde Excel o cargue un
          archivo .csv. Se omiten líneas vacías y una fila de encabezado «CURP».
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            onChange={onFile}
            className="text-sm file:mr-3 file:rounded-md file:border file:bg-muted file:px-3 file:py-1.5 file:text-sm file:font-semibold"
          />
        </div>
        <Textarea
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          rows={8}
          placeholder={
            "XAXX010101HDFXXX01\tJuan Pérez López\tjuan@correo.com\nXEXX020202MDFXXX02\tMaría Ruiz"
          }
          className="font-mono text-sm"
        />

        {rows.length > 0 && (
          <div className="space-y-2">
            <p className="text-sm font-semibold">
              {rows.length} alumnos a inscribir
              {truncated ? ` (mostrando los primeros ${PREVIEW_CAP})` : ""}
            </p>
            {rows.length > MAX_ROWS && (
              <p className="text-sm font-semibold text-destructive">
                Máximo {MAX_ROWS} alumnos por carga. Divida el archivo.
              </p>
            )}
            <div className="rounded-2xl border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12">#</TableHead>
                    <TableHead>CURP</TableHead>
                    <TableHead>Nombre</TableHead>
                    <TableHead>Email</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.slice(0, PREVIEW_CAP).map((r, i) => (
                    <TableRow key={i}>
                      <TableCell data-numeric>{i + 1}</TableCell>
                      <TableCell className="font-mono">{r.curp}</TableCell>
                      <TableCell>{r.full_name}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {r.email || "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        <div>
          <Button
            className="font-bold"
            disabled={
              submit.isPending || rows.length === 0 || rows.length > MAX_ROWS
            }
            onClick={() => submit.mutate()}
          >
            {submit.isPending
              ? "Inscribiendo…"
              : `Inscribir ${rows.length || ""} alumnos`.trim()}
          </Button>
        </div>

        {result && (
          <div className="space-y-2">
            <p className="text-sm font-semibold text-emerald-600">
              {result.enrolled} inscritos
            </p>
            {result.errors.length > 0 && (
              <div className="rounded-2xl border bg-card">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-16">Fila</TableHead>
                      <TableHead>CURP</TableHead>
                      <TableHead>Motivo</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {result.errors.map((err) => (
                      <TableRow key={`${err.row}-${err.curp}`}>
                        <TableCell data-numeric>{err.row}</TableCell>
                        <TableCell className="font-mono">{err.curp}</TableCell>
                        <TableCell className="text-destructive">
                          {err.detail}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
