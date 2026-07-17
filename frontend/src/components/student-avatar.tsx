// Student portrait with initials fallback: native <img> against the photo
// endpoint; a 404/broken load (or has_photo=false) falls back to initials.
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

export function studentInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return (
    ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?"
  );
}

export function StudentAvatar({
  studentId,
  name,
  hasPhoto,
  version,
  className,
}: {
  studentId: string;
  name: string;
  hasPhoto?: boolean;
  /** bump after an upload to bust the browser cache */
  version?: number;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [studentId, version]);

  if (!hasPhoto || failed) {
    return (
      <span
        aria-hidden
        className={cn(
          "flex shrink-0 select-none items-center justify-center rounded-full bg-muted font-bold text-muted-foreground",
          className,
        )}
      >
        {studentInitials(name)}
      </span>
    );
  }
  return (
    <img
      src={`/api/v1/students/${studentId}/photo${version ? `?v=${version}` : ""}`}
      alt={`Fotografía de ${name}`}
      onError={() => setFailed(true)}
      className={cn("shrink-0 rounded-full object-cover", className)}
    />
  );
}
