// A docente only captures grades and takes attendance of their own materias: the
// rest of the staff screens are not theirs (the backend refuses them anyway).
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { UserPublic } from "@/api/types";

/** The screens a docente may open. */
export const TEACHER_PATHS = ["/calificaciones", "/asistencias", "/perfil"] as const;

export const isTeacher = (me?: UserPublic | null) => me?.role === "docente" && !me.is_superuser;

export function useIsTeacher(): boolean {
  const { data: me } = useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api<UserPublic>("/auth/me"),
  });
  return isTeacher(me);
}
