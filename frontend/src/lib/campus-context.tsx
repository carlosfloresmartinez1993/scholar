// Global campus filter: chosen in the header switcher, persisted in
// localStorage, consumed by pages that scope their data per plantel
// (students list today; other pages can adopt it later).
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

const STORAGE_KEY = "campus-filter";

/** Sentinel for "Todos los planteles" (no filter). */
export const ALL_CAMPUSES = "all";

interface CampusContextValue {
  campusId: string;
  setCampusId: (id: string) => void;
}

const CampusContext = createContext<CampusContextValue>({
  campusId: ALL_CAMPUSES,
  setCampusId: () => {},
});

export function CampusProvider({ children }: { children: ReactNode }) {
  const [campusId, setCampusId] = useState<string>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) ?? ALL_CAMPUSES;
    } catch {
      return ALL_CAMPUSES; // private mode / storage unavailable
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, campusId);
    } catch {
      // persistence is best-effort
    }
  }, [campusId]);
  return (
    <CampusContext.Provider value={{ campusId, setCampusId }}>
      {children}
    </CampusContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCampus(): CampusContextValue {
  return useContext(CampusContext);
}
