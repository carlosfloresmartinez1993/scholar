// Global campus scope: chosen in the header switcher, persisted in
// localStorage, and attached as the X-Campus header on every request.
// The set of selectable campuses comes from /auth/me (the user's membership,
// or all campuses for all-campus roles) intersected with the campus catalog
// (for names). Switching campus refetches campus-tier data.
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setActiveCampus } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { Campus, UserPublic } from "@/api/types";

const STORAGE_KEY = "campus-filter";

/** Sentinel for "Todos los planteles" (no single-campus filter). */
export const ALL_CAMPUSES = "all";

/** Header value the backend reads for the all-campus view. */
const ALL_HEADER = "__all__";

interface CampusContextValue {
  /** Effective selection: ALL_CAMPUSES or a specific campus id (validated). */
  campusId: string;
  setCampusId: (id: string) => void;
  /** Campuses the user may pick (name + id), already scoped to membership. */
  availableCampuses: Campus[];
  /** Whether the "Todas" option should be offered. */
  canSelectAll: boolean;
  /** Loaded and the user has no campus membership at all (and no all-view). */
  noCampusAccess: boolean;
}

const CampusContext = createContext<CampusContextValue>({
  campusId: ALL_CAMPUSES,
  setCampusId: () => {},
  availableCampuses: [],
  canSelectAll: true,
  noCampusAccess: false,
});

export function CampusProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { data: me } = useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api<UserPublic>("/auth/me"),
  });
  const { data: allCampuses } = useQuery({
    queryKey: queryKeys.campuses,
    queryFn: () => api<Campus[]>("/catalog/campuses"),
  });

  const [campusId, setCampusIdRaw] = useState<string>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) ?? ALL_CAMPUSES;
    } catch {
      return ALL_CAMPUSES; // private mode / storage unavailable
    }
  });

  // Campuses the user is allowed to see: everything for all-campus roles,
  // otherwise only their membership ids — intersected with the catalog for names.
  const availableCampuses = useMemo<Campus[]>(() => {
    if (!allCampuses) return [];
    if (me?.all_campuses) return allCampuses;
    const allowed = new Set(me?.campuses ?? []);
    return allCampuses.filter((c) => allowed.has(c.id));
  }, [allCampuses, me]);

  const canSelectAll =
    !!me?.all_campuses || availableCampuses.length > 1;
  // Zero memberships and no all-view: the switcher surfaces this explicitly
  // instead of silently hiding (the backend serves such a user empty scopes).
  const noCampusAccess =
    !!me && !!allCampuses && !me.all_campuses && availableCampuses.length === 0;

  // Validate the persisted selection against what the user may actually pick.
  // A stale/foreign id falls back to "Todas", or to the sole campus when the
  // user has exactly one and no all-view.
  const effective = useMemo<string>(() => {
    if (!me || !allCampuses) return campusId; // still loading — don't thrash
    if (campusId === ALL_CAMPUSES) {
      return canSelectAll
        ? ALL_CAMPUSES
        : (availableCampuses[0]?.id ?? ALL_CAMPUSES);
    }
    if (availableCampuses.some((c) => c.id === campusId)) return campusId;
    return canSelectAll
      ? ALL_CAMPUSES
      : (availableCampuses[0]?.id ?? ALL_CAMPUSES);
  }, [campusId, me, allCampuses, availableCampuses, canSelectAll]);

  // Keep the request header in sync (synchronously, before child queries fire).
  setActiveCampus(effective === ALL_CAMPUSES ? ALL_HEADER : effective);

  const setCampusId = (id: string) => {
    setCampusIdRaw(id);
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      // persistence is best-effort
    }
    setActiveCampus(id === ALL_CAMPUSES ? ALL_HEADER : id);
    // campus-tier data is now stale under the new scope — refetch it. Global-tier
    // pages (users/audit) refetching too is harmless.
    queryClient.invalidateQueries();
  };

  // Persist a corrected effective value (e.g. a foreign id was dropped).
  useEffect(() => {
    if (effective !== campusId) {
      setCampusIdRaw(effective);
      try {
        localStorage.setItem(STORAGE_KEY, effective);
      } catch {
        // best-effort
      }
      // The scope just changed under us (stale/foreign persisted id) — refetch
      // anything already cached under the old header, same as setCampusId.
      queryClient.invalidateQueries();
    }
  }, [effective, campusId, queryClient]);

  return (
    <CampusContext.Provider
      value={{
        campusId: effective,
        setCampusId,
        availableCampuses,
        canSelectAll,
        noCampusAccess,
      }}
    >
      {children}
    </CampusContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCampus(): CampusContextValue {
  return useContext(CampusContext);
}
