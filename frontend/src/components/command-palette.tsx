// Global quick-access search (⌘K / Ctrl+K, or the header search box). Built on
// the existing shadcn Dialog + Input (no cmdk dependency): a single filtered,
// keyboard-driven list that jumps to a student (deep-link), a program, a page
// or a quick action.
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { Program, Student } from "@/api/types";
import { cn } from "@/lib/utils";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

// Static pages / quick actions. `to` values are real routes from _auth.
const ACTIONS = [
  { label: "Inicio", to: "/", hint: "Página" },
  { label: "Alumnos", to: "/alumnos", hint: "Página" },
  { label: "Programas", to: "/programas", hint: "Página" },
  { label: "Grupos", to: "/grupos", hint: "Página" },
  { label: "Egresados", to: "/egresados", hint: "Página" },
  { label: "Capturar calificaciones", to: "/calificaciones", hint: "Acción" },
  { label: "Asistencias", to: "/asistencias", hint: "Página" },
  { label: "Cobrar / Caja", to: "/tesoreria", hint: "Acción" },
  { label: "Inscribir alumno", to: "/inscripciones", hint: "Acción" },
  { label: "Periodos", to: "/periodos", hint: "Página" },
  { label: "Mi perfil", to: "/perfil", hint: "Página" },
] as const;

interface Item {
  key: string;
  label: string;
  hint?: string;
  run: () => void;
}

export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [active, setActive] = useState(0);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // Keep the keyboard-highlighted result visible as it moves past the viewport.
  useEffect(() => {
    itemRefs.current[active]?.scrollIntoView({ block: "nearest" });
  }, [active]);

  // Global ⌘K / Ctrl+K toggle.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenChange(!open);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  // Reset input whenever the palette opens.
  useEffect(() => {
    if (open) {
      setQuery("");
      setDebounced("");
      setActive(0);
    }
  }, [open]);

  // Debounce the student search term.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(t);
  }, [query]);

  const { data: students } = useQuery({
    queryKey: queryKeys.students(debounced),
    queryFn: () =>
      api<Student[]>(`/students?limit=8&q=${encodeURIComponent(debounced)}`),
    enabled: open && debounced.length >= 2,
  });
  const { data: programs } = useQuery({
    queryKey: queryKeys.programs,
    queryFn: () => api<Program[]>("/catalog/programs"),
    enabled: open,
  });

  const close = () => onOpenChange(false);

  const items = useMemo<Item[]>(() => {
    const q = query.trim().toLowerCase();
    const list: Item[] = [];

    for (const a of ACTIONS) {
      if (!q || a.label.toLowerCase().includes(q)) {
        list.push({
          key: `action:${a.label}`,
          label: a.label,
          hint: a.hint,
          run: () => {
            close();
            navigate({ to: a.to });
          },
        });
      }
    }

    for (const s of students ?? []) {
      list.push({
        key: `student:${s.id}`,
        label: s.full_name,
        hint: `Alumno · ${s.enrollment_number}`,
        run: () => {
          close();
          navigate({
            to: "/alumnos/$studentId",
            params: { studentId: s.id },
          });
        },
      });
      // One keystroke from any screen to charging this student in Caja.
      list.push({
        key: `student-cobrar:${s.id}`,
        label: `Cobrar a ${s.full_name}`,
        hint: "Caja",
        run: () => {
          close();
          navigate({ to: "/tesoreria", search: { studentId: s.id } });
        },
      });
    }

    for (const p of programs ?? []) {
      if (!q || `${p.code} ${p.name}`.toLowerCase().includes(q)) {
        list.push({
          key: `program:${p.id}`,
          label: p.name,
          hint: `Programa · ${p.code}`,
          run: () => {
            close();
            navigate({ to: "/programas" });
          },
        });
      }
    }

    return list;
  }, [query, students, programs, navigate]);

  // Keep the highlighted index within bounds as the list changes.
  useEffect(() => {
    setActive((i) => Math.min(i, Math.max(0, items.length - 1)));
  }, [items.length]);

  function onInputKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      items[active]?.run();
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="top-[20%] translate-y-0 gap-0 overflow-hidden p-0 sm:max-w-xl"
        aria-label="Búsqueda rápida"
      >
        <div className="flex items-center gap-2 border-b px-3">
          <Search className="size-4 shrink-0 text-muted-foreground" />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder="Buscar alumnos, páginas y acciones…"
            aria-label="Buscar"
            className="border-0 px-0 shadow-none focus-visible:ring-0"
          />
        </div>
        <ul className="max-h-80 overflow-y-auto p-1">
          {items.map((item, i) => (
            <li key={item.key}>
              <button
                ref={(node) => {
                  itemRefs.current[i] = node;
                }}
                type="button"
                onMouseMove={() => setActive(i)}
                onClick={item.run}
                className={cn(
                  "flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-sm",
                  i === active ? "bg-muted" : "hover:bg-muted/50",
                )}
              >
                <span className="truncate font-medium">{item.label}</span>
                {item.hint && (
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {item.hint}
                  </span>
                )}
              </button>
            </li>
          ))}
          {items.length === 0 && (
            <li className="px-3 py-6 text-center text-sm text-muted-foreground">
              Sin resultados
            </li>
          )}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
