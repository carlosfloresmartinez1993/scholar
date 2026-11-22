// What the user's role may open (Administración → Roles). The server checks the
// same permissions on every request; this only decides what the menu shows.
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { UserPublic } from "@/api/types";

/** Screen path → the view permission it needs (longest prefix wins). */
const PATH_PERMISSIONS: [string, string][] = [
  ["/alumnos", "alumnos"],
  ["/profesores", "profesores"],
  ["/inscripciones", "inscripciones"],
  ["/programas", "programas"],
  ["/grupos", "grupos"],
  ["/egresados", "egresados"],
  ["/calificaciones", "calificaciones"],
  ["/asistencias", "asistencias"],
  ["/tesoreria", "tesoreria"],
  ["/reportes", "reportes"],
  ["/periodos", "periodos"],
  ["/planteles", "planteles"],
  ["/configuracion", "configuracion"],
  ["/usuarios", "usuarios"],
  ["/auditoria", "auditoria"],
  ["/roles", "roles"],
];

export function can(me: UserPublic | null | undefined, permission: string): boolean {
  return !!me && (me.is_superuser || (me.permissions ?? []).includes(permission));
}

/** The permission a path needs: null = any signed-in staff (e.g. «Mi perfil»). */
export function permissionFor(pathname: string): string | null {
  if (pathname === "/" || pathname === "") return "inicio";
  const hit = PATH_PERMISSIONS.find(([p]) => pathname === p || pathname.startsWith(`${p}/`));
  return hit ? hit[1] : null;
}

/** Where to send a user who may not open the page they asked for. */
export function firstAllowedPath(me: UserPublic): string {
  if (can(me, "inicio")) return "/";
  const hit = PATH_PERMISSIONS.find(([, perm]) => can(me, perm));
  return hit ? hit[0] : "/perfil";
}

/** A role limited to its own materias (like a docente). */
export const isTeacher = (me?: UserPublic | null) => !!me && !me.is_superuser && !!me.own_subjects_only;

export function useIsTeacher(): boolean {
  const { data: me } = useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api<UserPublic>("/auth/me"),
  });
  return isTeacher(me);
}
