export const queryKeys = {
  me: ["me"] as const,
  users: (role?: string) => ["users", role ?? "all"] as const,
  audit: ["audit"] as const,

  institution: ["institution"] as const,
  campuses: ["campuses"] as const,
  programs: ["programs"] as const,
  rvoes: (programId?: string) => ["rvoes", programId ?? "all"] as const,
  planVersions: (rvoeId?: string) =>
    ["plan-versions", rvoeId ?? "all"] as const,
  planSubjects: (planVersionId: string) =>
    ["plan-subjects", planVersionId] as const,
  evaluationComponents: (subjectId: string) =>
    ["evaluation-components", subjectId] as const,
  terms: ["terms"] as const,
  groups: (termId?: string) => ["groups", termId ?? "all"] as const,
  groupSubjects: (groupId: string) => ["group-subjects", groupId] as const,

  students: (q?: string) => ["students", q ?? ""] as const,
  student: (id: string) => ["student", id] as const,
  planEnrollments: (studentId: string) =>
    ["plan-enrollments", studentId] as const,
  groupEnrollments: (studentId: string) =>
    ["group-enrollments", studentId] as const,
  subjectEnrollments: (studentId: string) =>
    ["subject-enrollments", studentId] as const,

  gradeGrid: (groupSubjectId: string) => ["grade-grid", groupSubjectId] as const,
  actas: (groupSubjectId: string) => ["actas", groupSubjectId] as const,
  kardex: (studentId: string, planVersionId: string) =>
    ["kardex", studentId, planVersionId] as const,

  sessions: (groupSubjectId: string) => ["sessions", groupSubjectId] as const,
  sessionRecords: (sessionId: string) => ["session-records", sessionId] as const,
  attendanceReport: (groupSubjectId: string) =>
    ["attendance-report", groupSubjectId] as const,
  justifications: (filters: string) => ["justifications", filters] as const,

  requirements: ["requirements"] as const,
  expediente: (studentId: string) => ["expediente", studentId] as const,
  studentDocuments: (studentId: string) =>
    ["student-documents", studentId] as const,
  issuedDocuments: (studentId?: string) =>
    ["issued-documents", studentId ?? "all"] as const,

  calendarPrograms: ["calendar-programs"] as const,
  calendarGroups: (programId?: string) =>
    ["calendar-groups", programId ?? "all"] as const,
  studentCalendar: (studentId: string) =>
    ["student-calendar", studentId] as const,

  concepts: ["concepts"] as const,
  statement: (studentId: string) => ["statement", studentId] as const,
  scholarships: (studentId?: string) =>
    ["scholarships", studentId ?? "all"] as const,
  scholarshipsByStatus: (status: string) =>
    ["scholarships", "status", status] as const,
  scholarshipReport: ["scholarship-report"] as const,
  fiscalProfile: (studentId: string) => ["fiscal-profile", studentId] as const,
  collectionReport: (from: string, to: string) =>
    ["collection-report", from, to] as const,
  aging: ["aging"] as const,
  dashboardStats: ["dashboard-stats"] as const,
};
