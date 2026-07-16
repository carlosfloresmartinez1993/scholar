import type {
  BulkIntakeResult,
  BulkIntakeRow,
  CalendarGroup,
  CalendarProgram,
  Group,
  Program,
  StudentCalendar,
} from "./types";

const BASE_URL = "/api/v1";

let isRefreshing = false;
let refreshPromise: Promise<boolean> | null = null;

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
    body: form,
  });

  if (!res.ok) throw await parseError(res);
  return res.json();
}

// --- Calendar system (calendar.inue.online) ---------------------------------

export const getCalendarPrograms = () =>
  api<CalendarProgram[]>("/catalog/calendar/programs");

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

// --- Onboarding (Inscripciones) ---------------------------------------------

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
