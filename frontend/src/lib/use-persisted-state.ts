// Tiny localStorage-backed useState, mirroring the best-effort persistence in
// components/academic-selector.tsx. Stale-id validation stays in the caller
// (it has the loaded options), same as the selector does with terms/groups.
import { useState } from "react";

export function usePersistedState<T>(
  key: string,
  initial: T,
  // Runtime guard: a stale/malformed stored value that fails it falls back to
  // `initial` (JSON.parse's `as T` is compile-time only).
  isValid?: (value: unknown) => boolean,
): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw === null) return initial;
      const parsed = JSON.parse(raw);
      if (isValid && !isValid(parsed)) return initial;
      return parsed as T;
    } catch {
      return initial;
    }
  });

  const set = (next: T) => {
    setValue(next);
    try {
      localStorage.setItem(key, JSON.stringify(next));
    } catch {
      // persistence is best-effort (private mode / quota); ignore
    }
  };

  return [value, set];
}
