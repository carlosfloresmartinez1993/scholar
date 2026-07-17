// Camera capture for the student portrait: native getUserMedia preview →
// "Capturar" draws to canvas → still preview → "Guardar" uploads a JPEG blob.
// Without camera/permission the dialog falls back to a plain file input.
import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Camera, RefreshCcw, Upload } from "lucide-react";
import { apiUpload, ApiError } from "@/api/client";
import type { Student } from "@/api/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const MAX_PHOTO_BYTES = 5 * 1024 * 1024;
const MAX_SIDE = 800; // ponytail: portraits are credencial-sized, cap the capture

type Mode = "starting" | "streaming" | "captured" | "no-camera";

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
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  // Request generation: getUserMedia may resolve after the dialog closed (or a
  // newer request started); a stale resolution stops its tracks and bails.
  const cameraGenRef = useRef(0);
  const [mode, setMode] = useState<Mode>("starting");
  const [blob, setBlob] = useState<Blob | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  const stopStream = useCallback(() => {
    cameraGenRef.current++; // invalidate any in-flight getUserMedia
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const startCamera = useCallback(async () => {
    const gen = ++cameraGenRef.current;
    setMode("starting");
    setBlob(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user" },
      });
      if (gen !== cameraGenRef.current) {
        // dialog closed / newer request won while we awaited — discard
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
      setMode("streaming");
    } catch {
      if (gen !== cameraGenRef.current) return;
      // no camera / permission denied — file upload still works
      setMode("no-camera");
    }
  }, []);

  useEffect(() => {
    if (open) {
      startCamera();
    }
    return () => {
      stopStream();
    };
  }, [open, startCamera, stopStream]);

  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );

  function setCaptured(nextBlob: Blob) {
    setBlob(nextBlob);
    setPreviewUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return URL.createObjectURL(nextBlob);
    });
    setMode("captured");
  }

  function capture() {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const scale = Math.min(1, MAX_SIDE / Math.max(video.videoWidth, video.videoHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      (b) => {
        if (!b) return;
        stopStream();
        setCaptured(b);
      },
      "image/jpeg",
      0.85,
    );
  }

  function onFilePicked(file: File | undefined | null) {
    if (!file) return;
    if (!["image/jpeg", "image/png"].includes(file.type)) {
      toast.error("Solo se aceptan imágenes JPEG o PNG");
      return;
    }
    if (file.size > MAX_PHOTO_BYTES) {
      toast.error("La imagen no debe exceder 5 MB");
      return;
    }
    stopStream();
    setCaptured(file);
  }

  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append(
        "file",
        blob!,
        blob!.type === "image/png" ? "foto.png" : "foto.jpg",
      );
      return apiUpload<Student>(`/students/${student.id}/photo`, form);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["student", student.id] });
      queryClient.invalidateQueries({ queryKey: ["students"] });
      toast.success("Fotografía guardada");
      onSaved?.();
      onOpenChange(false);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar la foto"),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Fotografía del alumno</DialogTitle>
          <DialogDescription>{student.full_name}</DialogDescription>
        </DialogHeader>

        <div className="flex aspect-[4/3] w-full items-center justify-center overflow-hidden rounded-md border bg-muted">
          {mode === "captured" && previewUrl ? (
            <img
              src={previewUrl}
              alt="Vista previa de la fotografía"
              className="h-full w-full object-contain"
            />
          ) : mode === "no-camera" ? (
            <p className="max-w-64 px-4 text-center text-sm text-muted-foreground">
              No hay cámara disponible o el permiso fue denegado. Puedes subir
              un archivo de imagen.
            </p>
          ) : (
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="h-full w-full object-cover"
            />
          )}
        </div>

        <DialogFooter className="flex-wrap gap-2 sm:justify-between">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png"
            className="hidden"
            aria-hidden
            tabIndex={-1}
            onChange={(e) => {
              onFilePicked(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <Button
            type="button"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload className="size-4" /> Subir archivo
          </Button>
          <div className="flex gap-2">
            {mode === "streaming" && (
              <Button className="font-bold" onClick={capture}>
                <Camera className="size-4" /> Capturar
              </Button>
            )}
            {mode === "captured" && (
              <>
                <Button variant="outline" onClick={startCamera}>
                  <RefreshCcw className="size-4" /> Repetir
                </Button>
                <Button
                  className="font-bold"
                  disabled={!blob || upload.isPending}
                  onClick={() => upload.mutate()}
                >
                  {upload.isPending ? "Guardando…" : "Guardar"}
                </Button>
              </>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
