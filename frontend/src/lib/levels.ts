// Niveles educativos: an editable catalog (Programas → Niveles educativos).
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { EducationLevelItem } from "@/api/types";

export function useEducationLevels(includeInactive = false) {
  return useQuery({
    queryKey: queryKeys.educationLevels(includeInactive),
    queryFn: () =>
      api<EducationLevelItem[]>(
        `/catalog/education-levels${includeInactive ? "?include_inactive=true" : ""}`,
      ),
  });
}

/** code → name, falling back to the code for a level that no longer exists */
export function useLevelLabel(): (code: string | null | undefined) => string {
  const { data } = useEducationLevels(true);
  return (code) => (code ? (data?.find((l) => l.code === code)?.name ?? code) : "");
}
