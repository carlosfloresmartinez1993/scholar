import type {
  BulkIntakeResult,
  BulkIntakeRow,
  RosterParseResult,
  CalendarGroup,
  CalendarProgram,
  CalendarTerm,
  Group,
  Program,
  PromoteCycleResult,
  StudentCalendar,
  Term,
} from "./types";

const BASE_URL = "/api/v1";

let isRefreshing = false;
let refreshPromise: Promise<boolean> | null = null;

// Active campus scope, attached as the X-Campus header on every request. Set by
// CampusProvider; a campus id restricts the request, "__all__" (or null) means
// the all-campus view. The backend enforces membership regardless.
let activeCampus: string | null = null;

export function setActiveCampus(value: string | null): void {
  activeCampus = value;
}

async function attemptRefresh(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    return res.ok;
  } catch {
    return false;
  }
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  const body = await res.json().catch(() => ({ detail: res.statusText }));
  const detail =
    typeof body.detail === "string" ? body.detail : "Error en la solicitud";
  return new ApiError(res.status, detail);
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const doFetch = () =>
    fetch(`${BASE_URL}${path}`, {
      ...options,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(activeCampus ? { "X-Campus": activeCampus } : {}),
        ...options.headers,
      },
    });

  let res = await doFetch();

  if (res.status === 401) {
    // Attempt token refresh (deduplicate concurrent refreshes)
    if (!isRefreshing) {
      isRefreshing = true;
      refreshPromise = attemptRefresh().finally(() => {
        isRefreshing = false;
        refreshPromise = null;
      });
    }

    const refreshed = await refreshPromise;
    if (refreshed) {
      res = await doFetch();
      if (res.ok) {
        return res.status === 204 ? (undefined as T) : res.json();
      }
      throw await parseError(res);
    }

    // Refresh failed — redirect to login
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new ApiError(401, "No autorizado");
  }

  if (!res.ok) throw await parseError(res);

  if (res.status === 204) return undefined as T;
  return res.json();
}

// Form-encoded POST (for OAuth2 login)
export async function apiForm<T>(
  path: string,
  body: URLSearchParams,
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });

  if (!res.ok) throw await parseError(res);
  return res.json();
}

// Multipart POST (file uploads)
export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    credentials: "include",
    headers: activeCampus ? { "X-Campus": activeCampus } : undefined,
    body: form,
  });

  if (!res.ok) throw await parseError(res);
  return res.json();
}

// --- Calendar system (calendar.inue.online) ---------------------------------

export const getCalendarPrograms = () =>
  api<CalendarProgram[]>("/catalog/calendar/programs");

export const getCalendarTerms = () =>
  api<CalendarTerm[]>("/catalog/calendar/terms");

export const importCalendarTerm = (calendarTermId: string) =>
  api<Term>("/catalog/terms/import", {
    method: "POST",
    body: JSON.stringify({ calendar_term_id: calendarTermId }),
  });

export const syncTermCalendar = (termId: string) =>
  api<Term>(`/catalog/terms/${termId}/sync-calendar`, { method: "POST" });

export const getCalendarGroups = (filters?: {
  term_id?: string;
  program_id?: string;
}) => {
  const params = new URLSearchParams();
  if (filters?.term_id) params.set("term_id", filters.term_id);
  if (filters?.program_id) params.set("program_id", filters.program_id);
  const qs = params.toString();
  return api<CalendarGroup[]>(`/catalog/calendar/groups${qs ? `?${qs}` : ""}`);
};

export const linkProgramToCalendar = (
  programId: string,
  calendarProgramId: string | null,
) =>
  api<Program>(`/catalog/programs/${programId}`, {
    method: "PATCH",
    body: JSON.stringify({ calendar_program_id: calendarProgramId }),
  });

export const linkGroupToCalendar = (
  groupId: string,
  calendarGroupId: string | null,
) =>
  api<Group>(`/catalog/groups/${groupId}`, {
    method: "PATCH",
    body: JSON.stringify({ calendar_group_id: calendarGroupId }),
  });

export const getStudentCalendar = (studentId: string) =>
  api<StudentCalendar>(`/students/${studentId}/calendar`);

// --- Cycle promotion (reinscripción) ----------------------------------------

export const promoteCycle = (dryRun: boolean) =>
  api<PromoteCycleResult>(`/students/promote-cycle?dry_run=${dryRun}`, {
    method: "POST",
  });

// --- Onboarding (Inscripciones) ---------------------------------------------

export const parseRoster = (file: File | Blob, filename: string) => {
  const form = new FormData();
  form.append("file", file, filename);
  return apiUpload<RosterParseResult>("/students/bulk-intake/parse", form);
};

export const bulkIntake = (body: {
  group_id: string;
  rows: BulkIntakeRow[];
  override_prerequisites?: boolean;
  waive_enrollment_fee?: boolean;
}) =>
  api<BulkIntakeResult>("/students/bulk-intake", {
    method: "POST",
    body: JSON.stringify(body),
  });
