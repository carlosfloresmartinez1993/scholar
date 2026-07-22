// Inscripciones: servo-style stepper wizard (one submit at the end) + the
// existing bulk CSV intake as a secondary tab.
import { Fragment, useMemo, useRef, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, ClipboardList, Plus, Trash2, Wand2 } from "lucide-react";
import { api, ApiError, bulkIntake } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type {
  BulkIntakeResult,
  BulkIntakeRow,
  Campus,
  Group,
  PlanVersion,
  Program,
  Rvoe,
  Sex,
  Term,
  WizardIntakeResult,
} from "@/api/types";
import { CURP_RE, MX_STATES, suggestCurp as suggestCurpFrom } from "@/lib/curp";
import { formatDate, todayISO } from "@/lib/format";
import { cn } from "@/lib/utils";
import { PhotoCapture } from "@/components/photo-capture";
import { uploadStudentPhoto } from "@/components/student-photo-dialog";
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

function InscripcionesPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl">Inscripciones</h1>
      <Tabs defaultValue="wizard">
        <TabsList>
          <TabsTrigger value="wizard">Nueva inscripción</TabsTrigger>
          <TabsTrigger value="bulk">Alta masiva</TabsTrigger>
        </TabsList>
        <TabsContent value="wizard" className="mt-4">
          <EnrollmentWizard />
        </TabsContent>
        <TabsContent value="bulk" className="mt-4">
          <BulkTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// =============================== Wizard =====================================

interface RelativeRow {
  name: string;
  relationship: string;
  phone: string;
}

interface WizardData {
  // 1. datos personales
  last_name_p: string;
  last_name_m: string;
  first_names: string;
  sex: "" | Sex;
  birth_date: string;
  birth_country: string;
  birth_state: string; // RENAPO code (name is derived on submit)
  birth_place: string;
  curp: string;
  // 2. domicilio
  street: string;
  ext_no: string;
  int_no: string;
  address_reference: string;
  address_country: string;
  address_state: string;
  municipio: string;
  locality: string;
  colonia: string;
  postal_code: string;
  // 3. contacto
  email: string;
  phone: string;
  phone_home: string;
  phone_work: string;
  // 4. fotografía
  photo: Blob | null;
  // 5. familiares
  relatives: RelativeRow[];
  // 6. acceso
  enablePortal: boolean;
  // 7. registro
  termId: string;
  campusId: string;
  programId: string;
  rvoeId: string;
  planVersionId: string;
  previous_school: string;
  previous_gpa: string;
  enrollment_notes: string;
  // 8. grupo
  groupId: string;
  waiveFee: boolean;
  overridePrereqs: boolean;
}

const INITIAL: WizardData = {
  last_name_p: "", last_name_m: "", first_names: "",
  sex: "", birth_date: "", birth_country: "México", birth_state: "",
  birth_place: "", curp: "",
  street: "", ext_no: "", int_no: "", address_reference: "",
  address_country: "México", address_state: "", municipio: "", locality: "",
  colonia: "", postal_code: "",
  email: "", phone: "", phone_home: "", phone_work: "",
  photo: null,
  relatives: [],
  enablePortal: false,
  termId: "", campusId: "", programId: "", rvoeId: "", planVersionId: "",
  previous_school: "", previous_gpa: "", enrollment_notes: "",
  groupId: "", waiveFee: false, overridePrereqs: false,
};

const RELATIONSHIPS = [
  "madre", "padre", "tutor", "cónyuge", "hermano(a)", "otro",
] as const;

const EMAIL_RE = /^\S+@\S+\.\S+$/;

interface StepDef {
  label: string;
  validate: (d: WizardData) => string | null;
}

const STEPS: StepDef[] = [
  {
    label: "Datos personales",
    validate: (d) =>
      !d.last_name_p.trim()
        ? "El apellido paterno es obligatorio"
        : !d.first_names.trim()
          ? "El nombre es obligatorio"
          : !CURP_RE.test(d.curp)
            ? "CURP inválida (18 caracteres)"
            : null,
  },
  {
    label: "Domicilio",
    validate: (d) =>
      d.postal_code.trim() && !/^\d{5}$/.test(d.postal_code.trim())
        ? "El código postal debe tener 5 dígitos"
        : null,
  },
  {
    label: "Contacto",
    validate: (d) =>
      d.email.trim() && !EMAIL_RE.test(d.email.trim())
        ? "Email inválido"
        : null,
  },
  { label: "Fotografía", validate: () => null },
  {
    label: "Familiares",
    validate: (d) =>
      d.relatives.some(
        (r) =>
          (r.name.trim() || r.phone.trim()) &&
          (!r.name.trim() || !r.relationship),
      )
        ? "Cada familiar necesita nombre y parentesco"
        : null,
  },
  {
    label: "Acceso a la plataforma",
    validate: (d) =>
      d.enablePortal && !d.email.trim()
        ? "Para habilitar el acceso se requiere un email (paso Contacto)"
        : null,
  },
  {
    label: "Registro",
    validate: (d) => {
      if (!d.termId) return "Seleccione el ciclo escolar";
      if (!d.campusId) return "Seleccione el plantel";
      if (!d.planVersionId) return "Seleccione el plan de estudios";
      if (d.previous_gpa.trim()) {
        const gpa = Number(d.previous_gpa);
        if (Number.isNaN(gpa) || gpa < 0 || gpa > 10)
          return "El promedio anterior debe estar entre 0 y 10";
      }
      return null;
    },
  },
  {
    label: "Grupo",
    validate: (d) => (!d.groupId ? "Seleccione el grupo" : null),
  },
];

function EnrollmentWizard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [data, setData] = useState<WizardData>(INITIAL);
  const [step, setStep] = useState(0);
  const [maxVisited, setMaxVisited] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const set = (patch: Partial<WizardData>) =>
    setData((d) => ({ ...d, ...patch }));

  // --- catalog data (shared by Registro / Grupo steps) ---
  const { data: terms } = useQuery({
    queryKey: queryKeys.terms,
    queryFn: () => api<Term[]>("/catalog/terms"),
  });
  const { data: campuses } = useQuery({
    queryKey: queryKeys.campuses,
    queryFn: () => api<Campus[]>("/catalog/campuses"),
  });
  const { data: programs } = useQuery({
    queryKey: queryKeys.programs,
    queryFn: () => api<Program[]>("/catalog/programs"),
  });
  const { data: rvoes } = useQuery({
    queryKey: queryKeys.rvoes(),
    queryFn: () => api<Rvoe[]>("/catalog/rvoes"),
  });
  const { data: planVersions } = useQuery({
    queryKey: queryKeys.planVersions(data.rvoeId),
    queryFn: () =>
      api<PlanVersion[]>(`/catalog/plan-versions?rvoe_id=${data.rvoeId}`),
    enabled: !!data.rvoeId,
  });
  const { data: groups } = useQuery({
    queryKey: ["groups", data.termId, data.planVersionId],
    queryFn: () =>
      api<Group[]>(
        `/catalog/groups?term_id=${data.termId}&plan_version_id=${data.planVersionId}`,
      ),
    enabled: !!data.termId && !!data.planVersionId,
  });

  const campusRvoes = rvoes?.filter(
    (r) => r.program_id === data.programId && r.campus_id === data.campusId,
  );
  // A step reads as "done" only once visited AND valid — permissive validators
  // (most fields optional) would otherwise check-mark steps never opened.
  const doneFlags = STEPS.map(
    (s, i) => i <= maxVisited && s.validate(data) === null,
  );

  function goNext() {
    const problem = STEPS[step].validate(data);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    const next = Math.min(step + 1, STEPS.length - 1);
    setStep(next);
    setMaxVisited((m) => Math.max(m, next));
  }

  function goBack() {
    setError(null);
    setStep((s) => Math.max(0, s - 1));
  }

  function jumpTo(i: number) {
    if (i > maxVisited) return; // forward jumps only via "Siguiente"
    setError(null);
    setStep(i);
  }

  const submit = useMutation({
    mutationFn: async () => {
      const stateName =
        MX_STATES.find((s) => s.code === data.birth_state)?.name ?? null;
      const clean = (v: string) => v.trim() || null;
      const payload = {
        group_id: data.groupId,
        waive_enrollment_fee: data.waiveFee,
        override_prerequisites: data.overridePrereqs,
        enable_portal_access: data.enablePortal,
        student: {
          curp: data.curp.trim().toUpperCase(),
          first_names: data.first_names.trim(),
          last_name_p: data.last_name_p.trim(),
          last_name_m: clean(data.last_name_m),
          sex: data.sex || null,
          birth_date: data.birth_date || null,
          birth_country: clean(data.birth_country),
          birth_state: stateName,
          birth_place: clean(data.birth_place),
          street: clean(data.street),
          ext_no: clean(data.ext_no),
          int_no: clean(data.int_no),
          address_reference: clean(data.address_reference),
          address_country: clean(data.address_country),
          address_state: clean(data.address_state),
          municipio: clean(data.municipio),
          locality: clean(data.locality),
          colonia: clean(data.colonia),
          postal_code: clean(data.postal_code),
          email: data.email.trim(),
          phone: data.phone.trim(),
          phone_home: clean(data.phone_home),
          phone_work: clean(data.phone_work),
          previous_school: clean(data.previous_school),
          previous_gpa: data.previous_gpa.trim()
            ? Number(data.previous_gpa)
            : null,
          enrollment_notes: clean(data.enrollment_notes),
          campus_id: data.campusId,
          relatives: data.relatives
            .filter((r) => r.name.trim())
            .map((r) => ({
              name: r.name.trim(),
              relationship: r.relationship,
              phone: clean(r.phone),
            })),
        },
      };
      const result = await api<WizardIntakeResult>("/students/intake", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (data.photo) {
        try {
          await uploadStudentPhoto(result.student.id, data.photo);
        } catch {
          toast.warning(
            "El alumno quedó inscrito, pero la fotografía no se pudo subir; captúrala desde su perfil",
          );
        }
      }
      return result;
    },
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ["students"] });
      toast.success(
        `Alumno inscrito · matrícula ${r.student.enrollment_number}`,
      );
      navigate({
        to: "/alumnos/$studentId",
        params: { studentId: r.student.id },
      });
    },
    onError: (e) =>
      setError(
        e instanceof ApiError ? e.message : "Error al guardar la inscripción",
      ),
  });

  function suggestCurp() {
    if (!data.sex || !data.birth_date || !data.birth_state) {
      setError(
        "Para sugerir la CURP captura sexo, fecha de nacimiento y estado",
      );
      return;
    }
    const curp = suggestCurpFrom({
      firstNames: data.first_names,
      lastNameP: data.last_name_p,
      lastNameM: data.last_name_m,
      birthDate: data.birth_date,
      sex: data.sex,
      stateCode: data.birth_state,
    });
    if (!curp) {
      setError("Completa nombre y apellidos para sugerir la CURP");
      return;
    }
    setError(null);
    set({ curp });
  }

  const termName = terms?.find((t) => t.id === data.termId)?.name ?? "—";
  const campusName = campuses?.find((c) => c.id === data.campusId)?.name ?? "—";
  const programName =
    programs?.find((p) => p.id === data.programId)?.name ?? "—";
  const planLabel =
    planVersions?.find((p) => p.id === data.planVersionId)?.version_label ??
    "—";
  const groupCode = groups?.find((g) => g.id === data.groupId)?.code ?? "—";
  const fullName = [data.first_names, data.last_name_p, data.last_name_m]
    .map((p) => p.trim())
    .filter(Boolean)
    .join(" ");

  return (
    <div className="space-y-6">
      {/* top progress bar: step nodes joined by connectors */}
      <div className="flex items-center px-1">
        {STEPS.map((s, i) => (
          <Fragment key={s.label}>
            {i > 0 && (
              <div
                aria-hidden
                className={cn(
                  "h-0.5 min-w-3 flex-1",
                  i <= maxVisited ? "bg-primary" : "bg-border",
                )}
              />
            )}
            <button
              type="button"
              title={s.label}
              aria-label={`Paso ${i + 1}: ${s.label}`}
              aria-current={i === step ? "step" : undefined}
              disabled={i > maxVisited}
              onClick={() => jumpTo(i)}
              className={cn(
                "flex size-8 shrink-0 items-center justify-center rounded-full border-2 text-xs font-bold transition-colors",
                i === step
                  ? "border-primary bg-primary text-primary-foreground"
                  : doneFlags[i]
                    ? "border-primary bg-primary/15 text-foreground"
                    : i <= maxVisited
                      ? "border-border text-muted-foreground hover:border-primary"
                      : "border-border text-muted-foreground opacity-50",
              )}
            >
              {doneFlags[i] && i !== step ? <Check className="size-4" /> : i + 1}
            </button>
          </Fragment>
        ))}
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[220px_1fr]">
        {/* left step list — same look as the tesorería sidebar */}
        <nav aria-label="Pasos de la inscripción" className="flex flex-col gap-1">
          {STEPS.map((s, i) => (
            <button
              key={s.label}
              type="button"
              onClick={() => jumpTo(i)}
              disabled={i > maxVisited}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-semibold transition-colors",
                i === step
                  ? "bg-primary/15 text-foreground"
                  : i <= maxVisited
                    ? "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                    : "text-muted-foreground opacity-50",
              )}
            >
              {doneFlags[i] && i !== step ? (
                <Check
                  className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400"
                  aria-hidden
                />
              ) : (
                <span className="w-4 shrink-0 text-center text-xs" data-numeric aria-hidden>
                  {i + 1}
                </span>
              )}
              <span className="truncate">{s.label}</span>
            </button>
          ))}
        </nav>

        {/* content, borderless, with the nav buttons pinned at the bottom */}
        <div className="flex min-h-[480px] flex-col">
          <div className="flex-1">
            <h2 className="text-lg font-bold">{STEPS[step].label}</h2>
            <div className="mt-4">
            {step === 0 && (
              <div className="grid max-w-2xl gap-4 sm:grid-cols-2">
                <Field label="Apellido paterno *" id="w-app">
                  <Input id="w-app" required value={data.last_name_p}
                    onChange={(e) => set({ last_name_p: e.target.value })} />
                </Field>
                <Field label="Apellido materno" id="w-apm">
                  <Input id="w-apm" value={data.last_name_m}
                    onChange={(e) => set({ last_name_m: e.target.value })} />
                </Field>
                <Field label="Nombre(s) *" id="w-nom">
                  <Input id="w-nom" required value={data.first_names}
                    onChange={(e) => set({ first_names: e.target.value })} />
                </Field>
                <Field label="Sexo" id="w-sex">
                  <Select value={data.sex}
                    onValueChange={(v) => set({ sex: v as Sex })}>
                    <SelectTrigger id="w-sex" className="w-full">
                      <SelectValue placeholder="Seleccione" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="F">Femenino</SelectItem>
                      <SelectItem value="M">Masculino</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Fecha de nacimiento" id="w-dob">
                  <Input id="w-dob" type="date" value={data.birth_date}
                    max={todayISO()}
                    onChange={(e) => set({ birth_date: e.target.value })} />
                </Field>
                <Field label="País de origen" id="w-pais">
                  <Input id="w-pais" value={data.birth_country}
                    onChange={(e) => set({ birth_country: e.target.value })} />
                </Field>
                <Field label="Estado" id="w-edo">
                  <Select value={data.birth_state}
                    onValueChange={(v) => set({ birth_state: v })}>
                    <SelectTrigger id="w-edo" className="w-full">
                      <SelectValue placeholder="Seleccione" />
                    </SelectTrigger>
                    <SelectContent>
                      {MX_STATES.map((s) => (
                        <SelectItem key={s.code} value={s.code}>
                          {s.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Lugar de nacimiento" id="w-lugar">
                  <Input id="w-lugar" value={data.birth_place}
                    onChange={(e) => set({ birth_place: e.target.value })} />
                </Field>
                <div className="grid gap-2 sm:col-span-2">
                  <Label htmlFor="w-curp">CURP *</Label>
                  <div className="flex gap-2">
                    <Input id="w-curp" required maxLength={18}
                      value={data.curp}
                      onChange={(e) =>
                        set({ curp: e.target.value.toUpperCase() })
                      }
                      placeholder="GOMC010203HBCNRL09"
                      className="font-mono uppercase"
                      aria-invalid={
                        data.curp.length > 0 && !CURP_RE.test(data.curp)
                      }
                    />
                    <Button type="button" variant="outline" onClick={suggestCurp}>
                      <Wand2 className="size-4" /> Sugerir
                    </Button>
                  </div>
                  <p className={cn(
                    "text-xs",
                    data.curp.length === 0
                      ? "text-muted-foreground"
                      : CURP_RE.test(data.curp)
                        ? "font-semibold text-emerald-600"
                        : "font-semibold text-destructive",
                  )}>
                    {/* ponytail: pos 17 defaults to 0/A by birth year — only RENAPO
                        knows real homonym collisions, staff verifies */}
                    {data.curp.length === 0
                      ? "«Sugerir» calcula la CURP completa con homoclave; verifícala contra el documento oficial."
                      : CURP_RE.test(data.curp)
                        ? "Formato de CURP válido"
                        : `Formato de CURP inválido (${data.curp.length}/18 caracteres)`}
                  </p>
                </div>
              </div>
            )}

            {step === 1 && (
              <div className="grid max-w-2xl gap-4 sm:grid-cols-2">
                <Field label="Calle" id="w-calle">
                  <Input id="w-calle" value={data.street}
                    onChange={(e) => set({ street: e.target.value })} />
                </Field>
                <div className="grid grid-cols-2 gap-4">
                  <Field label="No. exterior" id="w-ext">
                    <Input id="w-ext" value={data.ext_no}
                      onChange={(e) => set({ ext_no: e.target.value })} />
                  </Field>
                  <Field label="No. interior" id="w-int">
                    <Input id="w-int" value={data.int_no}
                      onChange={(e) => set({ int_no: e.target.value })} />
                  </Field>
                </div>
                <div className="sm:col-span-2">
                  <Field label="Referencia (entre calles)" id="w-ref">
                    <Input id="w-ref" value={data.address_reference}
                      onChange={(e) =>
                        set({ address_reference: e.target.value })
                      } />
                  </Field>
                </div>
                <Field label="País" id="w-dpais">
                  <Input id="w-dpais" value={data.address_country}
                    onChange={(e) => set({ address_country: e.target.value })} />
                </Field>
                <Field label="Estado" id="w-dedo">
                  <Input id="w-dedo" value={data.address_state}
                    onChange={(e) => set({ address_state: e.target.value })} />
                </Field>
                <Field label="Municipio" id="w-mun">
                  <Input id="w-mun" value={data.municipio}
                    onChange={(e) => set({ municipio: e.target.value })} />
                </Field>
                <Field label="Localidad" id="w-loc">
                  <Input id="w-loc" value={data.locality}
                    onChange={(e) => set({ locality: e.target.value })} />
                </Field>
                <Field label="Colonia" id="w-col">
                  <Input id="w-col" value={data.colonia}
                    onChange={(e) => set({ colonia: e.target.value })} />
                </Field>
                <Field label="Código postal" id="w-cp">
                  <Input id="w-cp" inputMode="numeric" maxLength={5}
                    value={data.postal_code}
                    onChange={(e) =>
                      set({ postal_code: e.target.value.replace(/\D/g, "") })
                    } />
                </Field>
              </div>
            )}

            {step === 2 && (
              <div className="grid max-w-2xl gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <Field label="Email" id="w-email">
                    <Input id="w-email" type="email" value={data.email}
                      placeholder="alumno@correo.com"
                      onChange={(e) => set({ email: e.target.value })} />
                  </Field>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Necesario si se habilitará el acceso del alumno a la
                    plataforma.
                  </p>
                </div>
                <Field label="Teléfono móvil" id="w-tmov">
                  <Input id="w-tmov" value={data.phone}
                    onChange={(e) => set({ phone: e.target.value })} />
                </Field>
                <Field label="Teléfono casa" id="w-tcasa">
                  <Input id="w-tcasa" value={data.phone_home}
                    onChange={(e) => set({ phone_home: e.target.value })} />
                </Field>
                <Field label="Teléfono trabajo" id="w-ttrab">
                  <Input id="w-ttrab" value={data.phone_work}
                    onChange={(e) => set({ phone_work: e.target.value })} />
                </Field>
              </div>
            )}

            {step === 3 && (
              <div className="max-w-md space-y-2">
                <p className="text-sm text-muted-foreground">
                  Opcional — la fotografía se sube al guardar la inscripción.
                </p>
                <PhotoCapture
                  value={data.photo}
                  onChange={(b) => set({ photo: b })}
                />
              </div>
            )}

            {step === 4 && (
              <div className="max-w-3xl space-y-3">
                <p className="text-sm text-muted-foreground">
                  Opcional — contactos familiares del alumno.
                </p>
                <div className="space-y-2">
                  {data.relatives.map((r, i) => (
                    <div
                      key={i}
                      className="grid items-end gap-2 sm:grid-cols-[1fr_190px_170px_auto]"
                    >
                      <Field label={i === 0 ? "Nombre" : ""} id={`w-fam-n-${i}`}>
                        <Input id={`w-fam-n-${i}`} value={r.name}
                          onChange={(e) => {
                            const relatives = [...data.relatives];
                            relatives[i] = { ...r, name: e.target.value };
                            set({ relatives });
                          }} />
                      </Field>
                      <Field label={i === 0 ? "Parentesco" : ""} id={`w-fam-p-${i}`}>
                        <Select value={r.relationship}
                          onValueChange={(v) => {
                            const relatives = [...data.relatives];
                            relatives[i] = { ...r, relationship: v };
                            set({ relatives });
                          }}>
                          <SelectTrigger id={`w-fam-p-${i}`} className="w-full">
                            <SelectValue placeholder="Seleccione" />
                          </SelectTrigger>
                          <SelectContent>
                            {RELATIONSHIPS.map((rel) => (
                              <SelectItem key={rel} value={rel}>
                                {rel.charAt(0).toUpperCase() + rel.slice(1)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </Field>
                      <Field label={i === 0 ? "Teléfono" : ""} id={`w-fam-t-${i}`}>
                        <Input id={`w-fam-t-${i}`} value={r.phone}
                          onChange={(e) => {
                            const relatives = [...data.relatives];
                            relatives[i] = { ...r, phone: e.target.value };
                            set({ relatives });
                          }} />
                      </Field>
                      <Button type="button" variant="ghost" size="icon-sm"
                        aria-label="Quitar familiar"
                        onClick={() =>
                          set({
                            relatives: data.relatives.filter(
                              (_, j) => j !== i,
                            ),
                          })
                        }>
                        <Trash2 className="size-4 text-destructive" />
                      </Button>
                    </div>
                  ))}
                </div>
                <Button type="button" variant="outline"
                  onClick={() =>
                    set({
                      relatives: [
                        ...data.relatives,
                        { name: "", relationship: "", phone: "" },
                      ],
                    })
                  }>
                  <Plus className="size-4" /> Agregar familiar
                </Button>
              </div>
            )}

            {step === 5 && (
              <div className="max-w-xl space-y-4">
                <label className="flex items-start gap-3 text-sm font-medium">
                  <Checkbox
                    checked={data.enablePortal}
                    disabled={!data.email.trim() && !data.enablePortal}
                    onCheckedChange={(v) => set({ enablePortal: v === true })}
                    className="mt-0.5"
                  />
                  <span>
                    Habilitar acceso del alumno a la plataforma
                    <span className="block font-normal text-muted-foreground">
                      Al guardar se creará su cuenta y recibirá por correo una
                      contraseña generada.
                    </span>
                  </span>
                </label>
                <p className={cn(
                  "text-sm",
                  data.email.trim()
                    ? "text-muted-foreground"
                    : "font-semibold text-destructive",
                )}>
                  {data.email.trim()
                    ? `La cuenta se creará con el correo ${data.email.trim()}.`
                    : "Se requiere capturar un email en el paso «Contacto»."}
                </p>
              </div>
            )}

            {step === 6 && (
              <div className="grid max-w-2xl gap-4 sm:grid-cols-2">
                <Field label="Ciclo escolar *" id="w-term">
                  <Select value={data.termId}
                    onValueChange={(v) => set({ termId: v, groupId: "" })}>
                    <SelectTrigger id="w-term" className="w-full">
                      <SelectValue placeholder="Seleccione un ciclo" />
                    </SelectTrigger>
                    <SelectContent>
                      {terms?.map((t) => (
                        <SelectItem key={t.id} value={t.id}>
                          {t.name}{t.is_open ? " · abierto" : ""}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Plantel *" id="w-campus">
                  <Select value={data.campusId}
                    onValueChange={(v) =>
                      set({ campusId: v, rvoeId: "", planVersionId: "", groupId: "" })
                    }>
                    <SelectTrigger id="w-campus" className="w-full">
                      <SelectValue placeholder="Seleccione un plantel" />
                    </SelectTrigger>
                    <SelectContent>
                      {campuses?.map((c) => (
                        <SelectItem key={c.id} value={c.id}>
                          {c.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Programa *" id="w-prog">
                  <Select value={data.programId}
                    onValueChange={(v) =>
                      set({ programId: v, rvoeId: "", planVersionId: "", groupId: "" })
                    }>
                    <SelectTrigger id="w-prog" className="w-full">
                      <SelectValue placeholder="Seleccione un programa" />
                    </SelectTrigger>
                    <SelectContent>
                      {programs?.map((p) => (
                        <SelectItem key={p.id} value={p.id}>
                          {p.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="RVOE *" id="w-rvoe">
                  <Select value={data.rvoeId}
                    disabled={!data.programId || !data.campusId}
                    onValueChange={(v) =>
                      set({ rvoeId: v, planVersionId: "", groupId: "" })
                    }>
                    <SelectTrigger id="w-rvoe" className="w-full">
                      <SelectValue placeholder="Seleccione un RVOE" />
                    </SelectTrigger>
                    <SelectContent>
                      {campusRvoes?.map((r) => (
                        <SelectItem key={r.id} value={r.id}>
                          {r.agreement_number}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Plan de estudios *" id="w-plan">
                  <Select value={data.planVersionId}
                    disabled={!data.rvoeId}
                    onValueChange={(v) =>
                      set({ planVersionId: v, groupId: "" })
                    }>
                    <SelectTrigger id="w-plan" className="w-full">
                      <SelectValue placeholder="Seleccione un plan" />
                    </SelectTrigger>
                    <SelectContent>
                      {planVersions?.map((p) => (
                        <SelectItem key={p.id} value={p.id}>
                          Plan {p.version_label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Matrícula" id="w-mat">
                  <Input id="w-mat" disabled value="Se asigna automáticamente" />
                </Field>
                <Field label="Escuela de procedencia" id="w-esc">
                  <Input id="w-esc" value={data.previous_school}
                    onChange={(e) => set({ previous_school: e.target.value })} />
                </Field>
                <Field label="Promedio anterior" id="w-gpa">
                  <Input id="w-gpa" type="number" min={0} max={10} step="0.1"
                    value={data.previous_gpa}
                    onChange={(e) => set({ previous_gpa: e.target.value })} />
                </Field>
                <div className="sm:col-span-2">
                  <Field label="Observaciones" id="w-obs">
                    <Textarea id="w-obs" rows={3} value={data.enrollment_notes}
                      maxLength={1000}
                      onChange={(e) =>
                        set({ enrollment_notes: e.target.value })
                      } />
                  </Field>
                </div>
              </div>
            )}

            {step === 7 && (
              <div className="max-w-2xl space-y-5">
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Grupo *" id="w-grupo">
                    <Select value={data.groupId}
                      onValueChange={(v) => set({ groupId: v })}>
                      <SelectTrigger id="w-grupo" className="w-full">
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
                    {groups && groups.length === 0 && (
                      <p className="text-xs font-semibold text-destructive">
                        No hay grupos del plan seleccionado en ese ciclo.
                      </p>
                    )}
                  </Field>
                  <Field label="Fecha de inscripción" id="w-fecha">
                    <Input id="w-fecha" disabled
                      value={`${formatDate(todayISO())} (se registra al guardar)`} />
                  </Field>
                </div>
                <p className="text-sm text-muted-foreground">
                  Tipo de ingreso:{" "}
                  <span className="font-semibold text-foreground">
                    se determina automáticamente
                  </span>{" "}
                  (inscripción o reinscripción según el historial del alumno).
                </p>
                <div className="flex flex-wrap gap-6">
                  <label className="flex items-center gap-2 text-sm font-medium">
                    <Checkbox checked={data.waiveFee}
                      onCheckedChange={(v) => set({ waiveFee: v === true })} />
                    Condonar inscripción (no cobrar)
                  </label>
                  <label className="flex items-center gap-2 text-sm font-medium">
                    <Checkbox checked={data.overridePrereqs}
                      onCheckedChange={(v) =>
                        set({ overridePrereqs: v === true })
                      } />
                    Omitir seriación (autorización especial)
                  </label>
                </div>

                <div className="rounded-md border bg-muted/30 p-4">
                  <h3 className="text-xs font-bold uppercase tracking-wide text-muted-foreground">
                    Resumen
                  </h3>
                  <dl className="mt-3 grid gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
                    <SummaryRow label="Alumno" value={fullName || "—"} />
                    <SummaryRow label="CURP" value={data.curp || "—"} mono />
                    <SummaryRow label="Ciclo" value={termName} />
                    <SummaryRow label="Plantel" value={campusName} />
                    <SummaryRow label="Programa" value={programName} />
                    <SummaryRow label="Plan" value={`Plan ${planLabel}`} />
                    <SummaryRow label="Grupo" value={groupCode} />
                    <SummaryRow label="Email" value={data.email.trim() || "—"} />
                    <SummaryRow
                      label="Familiares"
                      value={String(
                        data.relatives.filter((r) => r.name.trim()).length,
                      )}
                    />
                    <SummaryRow
                      label="Fotografía"
                      value={data.photo ? "Capturada" : "Sin foto"}
                    />
                    <SummaryRow
                      label="Acceso a plataforma"
                      value={data.enablePortal ? "Se habilitará" : "No"}
                    />
                    <SummaryRow
                      label="Inscripción"
                      value={data.waiveFee ? "Condonada" : "Se cobra"}
                    />
                  </dl>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="sticky bottom-0 flex items-center justify-between gap-4 bg-background py-4">
          <Button type="button" variant="outline" onClick={goBack}
            disabled={step === 0 || submit.isPending}>
            Anterior
          </Button>
          <p aria-live="polite"
            className="min-h-5 flex-1 text-center text-sm font-semibold text-destructive">
            {error}
          </p>
          {step < STEPS.length - 1 ? (
            <Button type="button" className="font-bold" onClick={goNext}>
              Siguiente
            </Button>
          ) : (
            <Button type="button" className="font-bold"
              disabled={submit.isPending}
              onClick={() => {
                // a visited step may have been edited into an invalid state —
                // re-validate ALL steps and jump to the first broken one
                const invalid = STEPS.findIndex((s) => s.validate(data) !== null);
                if (invalid !== -1) {
                  setStep(invalid);
                  setError(STEPS[invalid].validate(data));
                  return;
                }
                setError(null);
                submit.mutate();
              }}>
              {submit.isPending ? "Guardando…" : "Guardar e inscribir"}
            </Button>
          )}
        </div>
      </div>
      </div>
    </div>
  );
}

function Field({
  label,
  id,
  children,
}: {
  label: string;
  id: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid content-start gap-2">
      {label ? <Label htmlFor={id}>{label}</Label> : null}
      {children}
    </div>
  );
}

function SummaryRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="shrink-0 font-semibold text-muted-foreground">{label}</dt>
      <dd className={cn("truncate text-right", mono && "font-mono")}>{value}</dd>
    </div>
  );
}

// ============================ Alta masiva (CSV) ==============================

const PREVIEW_CAP = 50;
const MAX_ROWS = 1000; // mirrors the backend cap on bulk-intake rows

// ponytail: names containing a comma break comma-separated parsing
// (curp,nombre,email). Paste from Excel (tab-separated) to avoid it.
function parseRows(text: string): BulkIntakeRow[] {
  const lines = text
    .replace(/^﻿/, "") // strip a UTF-8 BOM (Excel .csv) before parsing
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

function BulkTab() {
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
  const [waiveEnrollmentFee, setWaiveEnrollmentFee] = useState(false);
  const [override, setOverride] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
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
        <Select value={groupId ?? ""} onValueChange={setGroupId} disabled={!termId}>
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
        <label className="ml-2 flex items-center gap-2 text-sm font-medium">
          <Checkbox
            checked={waiveEnrollmentFee}
            onCheckedChange={(v) => setWaiveEnrollmentFee(v === true)}
          />
          Condonar inscripción
        </label>
        <label className="flex items-center gap-2 text-sm font-medium">
          <Checkbox
            checked={override}
            onCheckedChange={(v) => setOverride(v === true)}
          />
          Omitir seriación
        </label>
      </div>

      {!group ? (
        <EmptyState
          icon={ClipboardList}
          title="Seleccione un grupo"
          description="Elija el ciclo y el grupo al que inscribirá a los alumnos. El campus se toma del grupo."
        />
      ) : (
        <BulkIntake
          group={group}
          options={{
            waive_enrollment_fee: waiveEnrollmentFee,
            override_prerequisites: override,
          }}
        />
      )}
    </div>
  );
}

type SharedOptions = {
  waive_enrollment_fee: boolean;
  override_prerequisites: boolean;
};

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
            <div className="rounded-md border bg-card">
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
              <div className="rounded-md border bg-card">
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
