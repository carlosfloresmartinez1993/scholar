// Shared portrait capture: native getUserMedia preview → "Capturar" draws to a
// canvas → JPEG blob handed to the owner via onChange. File-input fallback when
// there is no camera / permission. Owners decide what to do with the blob
// (upload now — StudentPhotoDialog — or hold it in memory — the wizard).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Camera, RefreshCcw, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";

const MAX_PHOTO_BYTES = 5 * 1024 * 1024;
const MAX_SIDE = 800; // ponytail: portraits are credencial-sized, cap the capture

type CameraState = "starting" | "streaming" | "no-camera";

export function PhotoCapture({
  value,
  onChange,
}: {
  value: Blob | null;
  onChange: (blob: Blob | null) => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  // Request generation: getUserMedia may resolve after unmount (or a newer
  // request started); a stale resolution stops its tracks and bails.
  const cameraGenRef = useRef(0);
  const [cameraState, setCameraState] = useState<CameraState>("starting");

  const stopStream = useCallback(() => {
    cameraGenRef.current++; // invalidate any in-flight getUserMedia
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const startCamera = useCallback(async () => {
    const gen = ++cameraGenRef.current;
    setCameraState("starting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user" },
      });
      if (gen !== cameraGenRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
      setCameraState("streaming");
    } catch {
      if (gen !== cameraGenRef.current) return;
      // no camera / permission denied — file upload still works
      setCameraState("no-camera");
    }
  }, []);

  useEffect(() => {
    if (!value) startCamera();
    return () => {
      stopStream();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // camera lifecycle is bound to mount; "Repetir" restarts it manually

  const previewUrl = useMemo(
    () => (value ? URL.createObjectURL(value) : null),
    [value],
  );
  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );

  function capture() {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const scale = Math.min(
      1,
      MAX_SIDE / Math.max(video.videoWidth, video.videoHeight),
    );
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      (b) => {
        if (!b) return;
        stopStream();
        onChange(b);
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
    onChange(file);
  }

  return (
    <div className="space-y-3">
      <div className="flex aspect-[4/3] w-full items-center justify-center overflow-hidden rounded-md border bg-muted">
        {value && previewUrl ? (
          <img
            src={previewUrl}
            alt="Vista previa de la fotografía"
            className="h-full w-full object-contain"
          />
        ) : cameraState === "no-camera" ? (
          <p className="max-w-64 px-4 text-center text-sm text-muted-foreground">
            No hay cámara disponible o el permiso fue denegado. Puedes subir un
            archivo de imagen.
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
      <div className="flex flex-wrap items-center justify-between gap-2">
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
        {!value && cameraState === "streaming" && (
          <Button type="button" className="font-bold" onClick={capture}>
            <Camera className="size-4" /> Capturar
          </Button>
        )}
        {value && (
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              onChange(null);
              startCamera();
            }}
          >
            <RefreshCcw className="size-4" /> Repetir
          </Button>
        )}
      </div>
    </div>
  );
}
