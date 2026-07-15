// Shared term → group → subject selector for the grade-capture and attendance
// pages. Both re-implemented the identical cascade and forgot the selection on
// every visit; this hook owns the queries and persists the choice (localStorage)
// so a teacher working one subject keeps it across pages and reloads.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { Group, GroupSubject, PlanSubject, Term } from "@/api/types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const STORAGE_KEY = "academic-selector-v1";

interface Selection {
  termId: string | null;
  groupId: string | null;
  groupSubjectId: string | null;
}

const EMPTY: Selection = { termId: null, groupId: null, groupSubjectId: null };

function loadSelection(): Selection {
  try {
    return { ...EMPTY, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") };
  } catch {
    return EMPTY;
  }
}

export function useAcademicSelector() {
  const [sel, setSelRaw] = useState<Selection>(loadSelection);
  const setSel = (next: Selection) => {
    setSelRaw(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  };

  const { data: terms } = useQuery({
    queryKey: queryKeys.terms,
    queryFn: () => api<Term[]>("/catalog/terms"),
  });
  // stored term may be stale (deleted) → fall back to the open term
  const termId =
    (sel.termId && terms?.some((t) => t.id === sel.termId) ? sel.termId : null) ??
    terms?.find((t) => t.is_open)?.id ??
    null;
  const term = terms?.find((t) => t.id === termId);

  const { data: groups } = useQuery({
    queryKey: queryKeys.groups(termId ?? undefined),
    queryFn: () => api<Group[]>(`/catalog/groups?term_id=${termId}`),
    enabled: !!termId,
  });
  // ignore a stored group that isn't in this term's list
  const groupId = groups?.some((g) => g.id === sel.groupId) ? sel.groupId : null;
  const group = groups?.find((g) => g.id === groupId);

  const { data: groupSubjects } = useQuery({
    queryKey: queryKeys.groupSubjects(groupId ?? ""),
    queryFn: () => api<GroupSubject[]>(`/catalog/groups/${groupId}/subjects`),
    enabled: !!groupId,
  });
  const groupSubjectId = groupSubjects?.some((gs) => gs.id === sel.groupSubjectId)
    ? sel.groupSubjectId
    : null;

  const { data: planSubjects } = useQuery({
    queryKey: queryKeys.planSubjects(group?.plan_version_id ?? ""),
    queryFn: () =>
      api<PlanSubject[]>(
        `/catalog/plan-versions/${group!.plan_version_id}/subjects`,
      ),
    enabled: !!group,
  });
  const subjectName = (planSubjectId: string) => {
    const s = planSubjects?.find((ps) => ps.id === planSubjectId);
    return s ? `${s.code} — ${s.name}` : "Materia";
  };

  const selector = (
    <>
      <Select
        value={termId ?? ""}
        onValueChange={(v) =>
          setSel({ termId: v, groupId: null, groupSubjectId: null })
        }
      >
        <SelectTrigger className="w-56">
          <SelectValue placeholder="Ciclo" />
        </SelectTrigger>
        <SelectContent>
          {terms?.map((t) => (
            <SelectItem key={t.id} value={t.id}>
              {t.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={groupId ?? ""}
        onValueChange={(v) =>
          setSel({ termId, groupId: v, groupSubjectId: null })
        }
        disabled={!termId}
      >
        <SelectTrigger className="w-56">
          <SelectValue placeholder="Grupo" />
        </SelectTrigger>
        <SelectContent>
          {groups?.map((g) => (
            <SelectItem key={g.id} value={g.id}>
              {g.code}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={groupSubjectId ?? ""}
        onValueChange={(v) => setSel({ termId, groupId, groupSubjectId: v })}
        disabled={!groupId}
      >
        <SelectTrigger className="w-80">
          <SelectValue placeholder="Materia" />
        </SelectTrigger>
        <SelectContent>
          {groupSubjects?.map((gs) => (
            <SelectItem key={gs.id} value={gs.id}>
              {subjectName(gs.plan_subject_id)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </>
  );

  return {
    term,
    termId,
    group,
    groupId,
    groupSubjects,
    groupSubjectId,
    subjectName,
    selector,
  };
}
