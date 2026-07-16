// Domain types for the INUE Scholar backend (source of truth: /api/v1/openapi.json)

// --- Enums -----------------------------------------------------------------

export type UserRole =
  | "admin_sistema"
  | "direccion"
  | "servicios_escolares"
  | "coordinador_academico"
  | "tesoreria"
  | "docente";

export type EducationLevel =
  | "tsu"
  | "licenciatura"
  | "especialidad"
  | "maestria"
  | "doctorado";

export type Modality = "escolarizada" | "no_escolarizada" | "mixta";

export type RvoeAuthority = "federal" | "estatal";

export type RvoeStatus =
  | "vigente"
  | "en_tramite_modificacion"
  | "cancelado"
  | "no_autorizado";

export type PeriodType = "semestral" | "cuatrimestral" | "anual";

export type EvaluationKind =
  | "parcial"
  | "ordinario"
  | "extraordinario"
  | "titulo_suficiencia";

export type StudentStatus =
  | "activo"
  | "baja_temporal"
  | "baja_definitiva"
  | "egresado";

export type AdmissionType =
  | "nuevo_ingreso"
  | "revalidacion"
  | "equivalencia"
  | "movilidad";

export type PlanEnrollmentStatus = "inscrito" | "baja" | "egresado" | "titulado";

export type GroupEnrollmentKind = "inscripcion" | "reinscripcion";

export type GroupEnrollmentStatus = "activa" | "baja";

export type SubjectEnrollmentStatus =
  | "cursando"
  | "aprobada"
  | "reprobada"
  | "baja";

export type ActaKind = "ordinaria" | "extraordinaria";

export type AttendanceStatus =
  | "presente"
  | "falta"
  | "retardo"
  | "justificado"
  | "participacion";

export type JustificationStatus = "pendiente" | "aprobado" | "rechazado";

export type ReviewStatus = "pendiente" | "aceptado" | "rechazado";

export type IssuedDocumentKind =
  | "constancia_estudios"
  | "constancia_no_adeudo"
  | "carta_pasante"
  | "kardex"
  | "certificado_parcial"
  | "certificado_total";

export type DegreeKind = "titulo" | "diploma" | "grado";

export type ChargeConceptKind =
  | "inscripcion"
  | "reinscripcion"
  | "colegiatura"
  | "titulacion"
  | "constancia"
  | "recargo"
  | "otro";

export type ChargeStatus = "pendiente" | "parcial" | "pagado" | "cancelado";

export type PaymentMethod = "efectivo" | "transferencia" | "deposito" | "tarjeta";

export type ScholarshipStatus =
  | "solicitada"
  | "activa"
  | "suspendida"
  | "vencida"
  | "cancelada";

// --- Users / audit ----------------------------------------------------------

export interface UserPublic {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  actor: string;
  action: string;
  entity?: string | null;
  entity_id?: string | null;
  detail?: string | null;
  created_at: string;
}

// --- Catalog ----------------------------------------------------------------

export interface Institution {
  id: string;
  name: string;
  short_name: string;
  rfc: string;
  fiscal_address: string;
  late_fee_pct: number;
  late_fee_grace_days: number;
  block_documents_on_debt: boolean;
}

export interface Campus {
  id: string;
  institution_id: string;
  name: string;
  address: string;
  is_active: boolean;
}

export interface Program {
  id: string;
  institution_id: string;
  code: string;
  name: string;
  level: EducationLevel;
  is_active: boolean;
  calendar_program_id?: string | null;
}

export interface Rvoe {
  id: string;
  program_id: string;
  campus_id: string;
  agreement_number: string;
  authority: RvoeAuthority;
  modality: Modality;
  issue_date: string;
  valid_until?: string | null;
  status: RvoeStatus;
  notes: string;
}

export interface PlanVersion {
  id: string;
  rvoe_id: string;
  version_label: string;
  period_type: PeriodType;
  periods_count: number;
  min_attendance_pct: number;
  is_active: boolean;
}

export interface PlanSubject {
  id: string;
  plan_version_id: string;
  code: string;
  name: string;
  period_number: number;
  credits: number;
  theory_hours: number;
  practice_hours: number;
  prerequisite_ids: string[];
}

export interface EvaluationComponent {
  id: string;
  plan_subject_id: string;
  kind: EvaluationKind;
  label: string;
  weight_pct: number;
  sequence: number;
  counts_towards_final: boolean;
}

export interface Term {
  id: string;
  institution_id: string;
  name: string;
  period_type: PeriodType;
  start_date: string;
  end_date: string;
  is_open: boolean;
  grade_capture_open: boolean;
  calendar_term_id?: string | null;
}

export interface Group {
  id: string;
  plan_version_id: string;
  term_id: string;
  campus_id: string;
  code: string;
  period_number: number;
  is_active: boolean;
  calendar_group_id?: string | null;
}

export interface GroupSubject {
  id: string;
  group_id: string;
  plan_subject_id: string;
  teacher_user_id?: string | null;
  schedule_text: string;
}

// --- Students ----------------------------------------------------------------

export interface Student {
  id: string;
  institution_id: string;
  campus_id: string;
  curp: string;
  full_name: string;
  email: string;
  phone: string;
  status: StudentStatus;
  admission_type: AdmissionType;
  enrollment_number: string;
  created_at: string;
}

export interface BulkIntakeRow {
  curp: string;
  full_name: string;
  email: string;
}

export interface BulkIntakeError {
  row: number;
  curp: string;
  detail: string;
}

export interface BulkIntakeResult {
  enrolled: number;
  errors: BulkIntakeError[];
}

export interface PlanEnrollment {
  id: string;
  student_id: string;
  plan_version_id: string;
  start_term_id: string;
  status: PlanEnrollmentStatus;
  created_at: string;
}

export interface GroupEnrollment {
  id: string;
  student_id: string;
  group_id: string;
  plan_enrollment_id: string;
  kind: GroupEnrollmentKind;
  status: GroupEnrollmentStatus;
  created_at: string;
}

export interface SubjectEnrollment {
  id: string;
  group_enrollment_id: string;
  group_subject_id: string;
  student_id: string;
  attempt_number: number;
  status: SubjectEnrollmentStatus;
  final_grade?: number | null;
}

// --- Grades -------------------------------------------------------------------

export interface GradeGridRow {
  subject_enrollment_id: string;
  student_id: string;
  student_name: string;
  enrollment_number: string;
  status: SubjectEnrollmentStatus;
  final_grade?: number | null;
  /** component_id -> value (null when not captured) */
  grades: Record<string, number | null>;
}

export interface GradeGrid {
  components: EvaluationComponent[];
  rows: GradeGridRow[];
}

export interface GradeActa {
  id: string;
  group_subject_id: string;
  kind: ActaKind;
  folio: string;
  snapshot: string;
  generated_at: string;
  signed_by_name: string;
  signed_at?: string | null;
}

export interface KardexRow {
  subject_enrollment_id: string;
  plan_subject_id: string;
  code: string;
  name: string;
  period_number: number;
  credits: number;
  group_code: string;
  attempt_number: number;
  status: SubjectEnrollmentStatus;
  final_grade?: number | null;
}

export interface CurricularProgress {
  total_subjects: number;
  passed_subjects: number;
  total_credits: number;
  earned_credits: number;
  credit_progress_pct: number;
  gpa?: number | null;
  eligible_for_degree: boolean;
}

export interface Kardex {
  student_id: string;
  plan_version_id: string;
  rows: KardexRow[];
  progress: CurricularProgress;
}

export interface DegreeRecord {
  id: string;
  student_id: string;
  kind: DegreeKind;
  program_name: string;
  issue_date: string;
  notes: string;
  folio: string;
  created_at: string;
}

// --- Attendance -----------------------------------------------------------------

export interface ClassSession {
  id: string;
  group_subject_id: string;
  session_date: string;
  sequence: number;
  notes: string;
}

export interface AttendanceRecord {
  id: string;
  session_id: string;
  student_id: string;
  status: AttendanceStatus;
}

export interface AttendanceReportRow {
  student_id: string;
  group_subject_id: string;
  student_name: string;
  enrollment_number: string;
  sessions: number;
  attended: number;
  attendance_pct: number;
  min_attendance_pct: number;
  right_to_exam: boolean;
}

export interface Justification {
  id: string;
  student_id: string;
  reason: string;
  date_from: string;
  date_to: string;
  evidence_filename: string;
  status: JustificationStatus;
  review_notes: string;
  created_at: string;
}

// --- Documents --------------------------------------------------------------------

export interface Requirement {
  id: string;
  name: string;
  level?: EducationLevel | null;
  admission_type?: AdmissionType | null;
  required: boolean;
  is_active: boolean;
}

export interface StudentDocument {
  id: string;
  student_id: string;
  requirement_id?: string | null;
  title: string;
  filename: string;
  content_type: string;
  version: number;
  status: ReviewStatus;
  reject_reason: string;
  uploaded_at: string;
}

export interface ChecklistItem {
  requirement_id: string;
  name: string;
  required: boolean;
  delivered: boolean;
}

export interface IssuedDocument {
  id: string;
  student_id: string;
  kind: IssuedDocumentKind;
  folio: string;
  payload: string;
  issued_at: string;
}

export interface Expediente {
  student: Student;
  checklist: ChecklistItem[];
  documents: StudentDocument[];
  issued_documents: IssuedDocument[];
  overdue_balance: number;
}

// --- Treasury -------------------------------------------------------------------

export interface ChargeConcept {
  id: string;
  name: string;
  kind: ChargeConceptKind;
  amount: number;
  program_id?: string | null;
  modality?: Modality | null;
  is_active: boolean;
}

export interface Charge {
  id: string;
  student_id: string;
  concept_id?: string | null;
  description: string;
  amount: number;
  scholarship_discount: number;
  due_date: string;
  status: ChargeStatus;
  is_late_fee: boolean;
  paid_amount: number;
  balance: number;
}

export interface Payment {
  id: string;
  student_id: string;
  charge_id?: string | null;
  amount: number;
  method: PaymentMethod;
  bank_reference: string;
  receipt_folio: string;
  notes: string;
  received_at: string;
  cancelled: boolean;
}

export interface AccountStatement {
  student_id: string;
  charges: Charge[];
  payments: Payment[];
  total_charged: number;
  total_paid: number;
  balance: number;
  overdue_balance: number;
  next_due_date?: string | null;
}

export interface Scholarship {
  id: string;
  student_id: string;
  name: string;
  pct?: number | null;
  fixed_amount?: number | null;
  valid_from: string;
  valid_to?: string | null;
  tolerance_days: number;
  status: ScholarshipStatus;
  approved_by?: string | null;
}

export interface FiscalProfile {
  id: string;
  student_id: string;
  rfc: string;
  razon_social: string;
  regimen_fiscal: string;
  uso_cfdi: string;
  email: string;
  cp: string;
  calle: string;
  no_ext: string;
  no_int: string;
  colonia: string;
  municipio: string;
  estado: string;
  pais: string;
}

export interface ScholarshipReport {
  active_students: number;
  students_with_scholarship: number;
  pct_with_scholarship: number;
  beca_mes: number;
  beca_cuatrimestre: number;
}

export interface TermSummaryRow {
  term_id: string;
  term_name: string;
  expected: number;
  collected: number;
  pending: number;
  collection_pct: number;
  by_concept: Record<string, { expected: number; collected: number }>;
}

/** current vs previous-term value for one dashboard metric */
export interface MetricDelta {
  current: number;
  previous: number;
}

export interface DashboardStats {
  term: { id: string; name: string } | null;
  prev_term: { id: string; name: string } | null;
  /** keyed by EducationLevel */
  students: Record<EducationLevel, MetricDelta>;
  groups: Record<EducationLevel, MetricDelta>;
  scholars: Record<EducationLevel, MetricDelta>;
  cartera_vencida: MetricDelta;
  pending: {
    justifications_pending: number;
    unsigned_actas: number;
    groups_without_teacher: number;
  };
}

export interface CollectionReport {
  date_from: string;
  date_to: string;
  payments_count: number;
  total: number;
  by_method: Record<string, number>;
}

// --- Calendar system (calendar.inue.online) ---------------------------------

export interface CalendarProgram {
  id: string;
  name: string;
  rvoe?: string | null;
  campus: "instituto_siscom" | "inue_presencial" | "inue_online";
  level: "maestria" | "licenciatura" | "bachillerato";
}

export interface CalendarTerm {
  id: string;
  code: string;
  name: string;
  year: number;
  start_date?: string | null;
  end_date?: string | null;
  is_active: boolean;
  imported: boolean;
}

export interface CalendarGroup {
  id: string;
  code: string;
  program_id?: string | null;
  term_id: string;
}

export interface ScheduleMeeting {
  /** 0 = lunes */
  weekday: number;
  start_time: string; // "HH:MM:SS"
  end_time: string; // "HH:MM:SS"
}

export interface StudentScheduleItem {
  id: string;
  group_code: string;
  subject: string;
  professor?: string | null;
  classroom?: string | null;
  classroom_is_virtual: boolean;
  start_date: string;
  end_date: string;
  group_codes: string[];
  meetings: ScheduleMeeting[];
}

export interface StudentCalendar {
  items: StudentScheduleItem[];
  linked: boolean;
}

export interface AgingRow {
  student_id: string;
  student_name: string;
  enrollment_number: string;
  description: string;
  due_date: string;
  days_overdue: number;
  bucket: "1-30" | "31-60" | "61-90" | "90+";
  balance: number;
}

export interface GroupBillingStatus {
  student_id: string;
  student_name: string;
  enrollment_number: string;
  charges_count: number;
  billed: boolean;
}
