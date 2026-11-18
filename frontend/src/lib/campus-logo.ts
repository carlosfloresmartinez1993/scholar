// Logo of a plantel: goes on top of the kárdex of its students. Fetched with the
// session cookie and turned into a data URL so both the printed page and the PDF
// (jsPDF) can embed it.
export interface CampusLogo {
  dataUrl: string;
  format: "PNG" | "JPEG";
  width: number; // natural size, for the aspect ratio
  height: number;
}

export const campusLogoUrl = (campusId: string, version?: string | null) =>
  `/api/v1/catalog/campuses/${campusId}/logo${version ? `?v=${encodeURIComponent(version)}` : ""}`;

export async function fetchCampusLogo(campusId: string | null | undefined): Promise<CampusLogo | null> {
  if (!campusId) return null;
  try {
    const res = await fetch(campusLogoUrl(campusId), { credentials: "include" });
    if (!res.ok) return null; // the plantel has no logo yet
    const blob = await res.blob();
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
    const { width, height } = await new Promise<{ width: number; height: number }>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
      img.onerror = reject;
      img.src = dataUrl;
    });
    return { dataUrl, format: blob.type === "image/jpeg" ? "JPEG" : "PNG", width, height };
  } catch {
    return null;
  }
}
