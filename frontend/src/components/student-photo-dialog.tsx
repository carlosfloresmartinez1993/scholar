// Portrait dialog for an EXISTING student: shared PhotoCapture UI + immediate
// upload on "Guardar". The wizard reuses PhotoCapture directly and defers the
// upload until the student exists.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiUpload, ApiError } from "@/api/client";
import type { Student } from "@/api/types";
import { PhotoCapture } from "@/components/photo-capture";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export function uploadStudentPhoto(studentId: string, blob: Blob) {
  const form = new FormData();
  form.append(
    "file",
    blob,
    blob.type === "image/png" ? "foto.png" : "foto.jpg",
  );
  return apiUpload<Student>(`/students/${studentId}/photo`, form);
}

export function StudentPhotoDialog({
  open,
  onOpenChange,
  student,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  student: Student;
  onSaved?: () => void;
}) {
  const queryClient = useQueryClient();
  const [blob, setBlob] = useState<Blob | null>(null);

  const upload = useMutation({
    mutationFn: () => uploadStudentPhoto(student.id, blob!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["student", student.id] });
      queryClient.invalidateQueries({ queryKey: ["students"] });
      toast.success("Fotografía guardada");
      setBlob(null);
      onSaved?.();
      onOpenChange(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar la foto"),
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) setBlob(null);
        onOpenChange(v);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Fotografía del alumno</DialogTitle>
          <DialogDescription>{student.full_name}</DialogDescription>
        </DialogHeader>
        {open && <PhotoCapture value={blob} onChange={setBlob} />}
        <DialogFooter>
          <Button
            className="font-bold"
            disabled={!blob || upload.isPending}
            onClick={() => upload.mutate()}
          >
            {upload.isPending ? "Guardando…" : "Guardar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
