import type {
  AdmissionType,
  AttendanceStatus,
  ChargeConceptKind,
  ChargeStatus,
  EducationLevel,
  EvaluationKind,
  IssuedDocumentKind,
  JustificationStatus,
  Modality,
  PaymentMethod,
  PeriodType,
  PlanEnrollmentStatus,
  ReviewStatus,
  RvoeStatus,
  ScholarshipStatus,
  StudentStatus,
  SubjectEnrollmentStatus,
  UserPosition,
  UserRole,
} from "@/api/types";

// --- Spanish labels for backend enums -------------------------------------

export const LEVEL_LABELS: Record<EducationLevel, string> = {
  tsu: "TSU",
  licenciatura: "Licenciatura",
  especialidad: "Especialidad",
  maestria: "Maestría",
  doctorado: "Doctorado",
};

export const MODALITY_LABELS: Record<Modality, string> = {
  escolarizada: "Escolarizada",
  no_escolarizada: "No escolarizada",
  mixta: "Mixta",
};

export const RVOE_STATUS_LABELS: Record<RvoeStatus, string> = {
  vigente: "Vigente",
  en_tramite_modificacion: "En trámite",
  cancelado: "Cancelado",
  no_autorizado: "No autorizado",
};

export const PERIOD_TYPE_LABELS: Record<PeriodType, string> = {
  semestral: "Semestral",
  cuatrimestral: "Cuatrimestral",
  anual: "Anual",
};

export const EVALUATION_KIND_LABELS: Record<EvaluationKind, string> = {
  parcial: "Parcial",
  ordinario: "Ordinario",
  extraordinario: "Extraordinario",
  titulo_suficiencia: "Título de suficiencia",
};

export const STUDENT_STATUS_LABELS: Record<StudentStatus, string> = {
  activo: "Activo",
  baja_temporal: "Baja temporal",
  baja_definitiva: "Baja definitiva",
  egresado: "Egresado",
};

export const ADMISSION_TYPE_LABELS: Record<AdmissionType, string> = {
  nuevo_ingreso: "Nuevo ingreso",
  revalidacion: "Revalidación",
  equivalencia: "Equivalencia",
  movilidad: "Movilidad",
};

export const PLAN_ENROLLMENT_STATUS_LABELS: Record<
  PlanEnrollmentStatus,
  string
> = {
  inscrito: "Inscrito",
  baja: "Baja",
  egresado: "Egresado",
  titulado: "Titulado",
};

export const SUBJECT_STATUS_LABELS: Record<SubjectEnrollmentStatus, string> = {
  cursando: "Cursando",
  aprobada: "Aprobada",
  reprobada: "Reprobada",
  baja: "Baja",
};

export const ATTENDANCE_STATUS_LABELS: Record<AttendanceStatus, string> = {
  presente: "Presente",
  falta: "Falta",
  retardo: "Retardo",
  justificado: "Justificado",
  participacion: "Participación",
};

export const JUSTIFICATION_STATUS_LABELS: Record<JustificationStatus, string> =
  {
    pendiente: "Pendiente",
    aprobado: "Aprobado",
    rechazado: "Rechazado",
  };

export const REVIEW_STATUS_LABELS: Record<ReviewStatus, string> = {
  pendiente: "Pendiente",
  aceptado: "Aceptado",
  rechazado: "Rechazado",
};

export const ISSUED_DOC_KIND_LABELS: Record<IssuedDocumentKind, string> = {
  constancia_estudios: "Constancia de estudios",
  constancia_no_adeudo: "Constancia de no adeudo",
  carta_pasante: "Carta de pasante",
  kardex: "Kárdex",
  certificado_parcial: "Certificado parcial",
  certificado_total: "Certificado total",
};

export const CONCEPT_KIND_LABELS: Record<ChargeConceptKind, string> = {
  inscripcion: "Inscripción",
  reinscripcion: "Reinscripción",
  colegiatura: "Colegiatura",
  titulacion: "Titulación",
  constancia: "Constancia",
  recargo: "Recargo",
  otro: "Otro",
};

export const CHARGE_STATUS_LABELS: Record<ChargeStatus, string> = {
  pendiente: "Pendiente",
  parcial: "Parcial",
  pagado: "Pagado",
  cancelado: "Cancelado",
};

export const PAYMENT_METHOD_LABELS: Record<PaymentMethod, string> = {
  efectivo: "Efectivo",
  transferencia: "Transferencia",
  deposito: "Depósito",
  tarjeta: "Tarjeta",
};

export const SCHOLARSHIP_STATUS_LABELS: Record<ScholarshipStatus, string> = {
  solicitada: "Solicitada",
  activa: "Activa",
  suspendida: "Suspendida",
  vencida: "Vencida",
  cancelada: "Cancelada",
};

export const POSITION_LABELS: Record<UserPosition, string> = {
  control_escolar: "Control escolar",
  directivo: "Directivo",
  cobranza: "Cobranza",
  docente: "Docente",
  coordinacion_academica: "Coordinación académica",
  direccion: "Dirección",
  sistemas: "Sistemas",
  administrativo: "Administrativo",
};

export const ROLE_LABELS: Record<UserRole, string> = {
  admin_sistema: "Administrador del sistema",
  direccion: "Dirección",
  servicios_escolares: "Servicios escolares",
  coordinador_academico: "Coordinación académica",
  tesoreria: "Tesorería",
  docente: "Docente",
  alumno: "Alumno",
};

// --- Formatting helpers ------------------------------------------------------

/** 1234.5 -> "$1,234.50" */
export function formatMoney(n?: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString("es-MX", { style: "currency", currency: "MXN" });
}

/** ISO date "2026-01-15" -> "15 ene 2026" */
export function formatDate(d?: string | null): string {
  if (!d) return "—";
  const date = new Date(`${d.slice(0, 10)}T00:00:00`);
  return date.toLocaleDateString("es-MX", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function formatDateTime(d?: string | null): string {
  if (!d) return "—";
  // Backend serializes naive UTC timestamps (no offset); mark them as UTC so
  // they are not misparsed as local time.
  const iso = /[Zz]|[+-]\d\d:?\d\d$/.test(d) ? d : `${d}Z`;
  return new Date(iso).toLocaleString("es-MX", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Today's date as YYYY-MM-DD (local time). */
export function todayISO(): string {
  return new Date().toLocaleDateString("sv-SE");
}

/** "2026-07-17T10:00:00" -> "hace 5 min" / "hace 2 h" / "hace 3 días". */
export function relativeTime(d: string): string {
  const iso = /[Zz]|[+-]\d\d:?\d\d$/.test(d) ? d : `${d}Z`;
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "hace un momento";
  if (seconds < 3600) return `hace ${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `hace ${Math.floor(seconds / 3600)} h`;
  const days = Math.floor(seconds / 86400);
  return days === 1 ? "hace 1 día" : `hace ${days} días`;
}
