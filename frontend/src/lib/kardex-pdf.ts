// Downloadable kárdex as a PDF file, same content as the printed one
// (lib/kardex-print.ts). jsPDF is loaded on demand so it stays out of the main bundle.
import {
  kardexCells,
  kardexHeaders,
  kardexSections,
  PREVIOUS_HEADERS,
  previousCells,
  showE2,
  showOrigin,
} from "@/lib/kardex";
import type { KardexPrintData } from "@/lib/kardex-print";

export async function downloadKardexPdf(d: KardexPrintData) {
  const [{ jsPDF }, { autoTable }] = await Promise.all([
    import("jspdf"),
    import("jspdf-autotable"),
  ]);
  const doc = new jsPDF({ unit: "mm", format: "letter" });
  const margin = 14;
  const institution = d.institutionName || "INUE";

  // the student's plantel logo on top (16 mm tall, at most 70 mm wide)
  let top = 0;
  if (d.logo) {
    const height = Math.min(16, (70 * d.logo.height) / d.logo.width);
    const width = (height * d.logo.width) / d.logo.height;
    doc.addImage(d.logo.dataUrl, d.logo.format, margin, 8, width, height);
    top = height + 2;
  }

  doc.setFont("helvetica", "bold");
  doc.setFontSize(14);
  doc.text(institution, margin, 18 + top);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(9);
  doc.text("Kárdex — historial académico", margin, 23 + top);
  doc.text(`Alumno: ${d.studentName}`, margin, 30 + top);
  doc.text(`Matrícula: ${d.enrollmentNumber}`, 120, 30 + top);
  doc.text(doc.splitTextToSize(`Plan vigente: ${d.planLabel}`, 188), margin, 35 + top);

  const withE2 = showE2(d.kardex);
  const withOrigin = showOrigin(d.kardex);
  const headers = kardexHeaders(withE2, withOrigin);
  const gradeCols = withE2 ? 6 : 5;
  const n = headers.length;
  const body = kardexSections(d.kardex).flatMap((s) => [
    [
      { content: s.heading, colSpan: n - 3, styles: { fontStyle: "bold" as const, fillColor: 235 } },
      {
        content: s.rvoe ?? "",
        colSpan: 3,
        styles: { halign: "right" as const, fontStyle: "bold" as const, fillColor: 235 },
      },
    ],
    ...s.rows.map((r) => kardexCells(r, withE2, withOrigin)),
  ]);

  autoTable(doc, {
    startY: 41 + top,
    margin: { left: margin, right: margin },
    head: [headers],
    body: body.length ? body : [[{ content: "Sin historial académico", colSpan: n }]],
    styles: { font: "helvetica", fontSize: 7, cellPadding: 1.2 },
    headStyles: { fillColor: 0, textColor: 255 },
    columnStyles: {
      1: { cellWidth: 52 },
      ...Object.fromEntries(
        headers.map((_, i) => [i, i === 2 || (i >= 5 && i < 5 + gradeCols) ? { halign: "right" as const } : {}]),
      ),
    },
  });

  // jspdf-autotable records where the table ended on the document
  const lastY = () => (doc as unknown as { lastAutoTable: { finalY: number } }).lastAutoTable.finalY;
  for (const p of d.kardex.previous) {
    doc.setFont("helvetica", "bold");
    doc.setFontSize(9);
    doc.text(`Estudios en RVOE anterior — ${p.rvoe} · ${p.program}`, margin, lastY() + 8);
    doc.setFont("helvetica", "normal");
    autoTable(doc, {
      startY: lastY() + 10,
      margin: { left: margin, right: margin },
      head: [PREVIOUS_HEADERS],
      body: p.rows.map(previousCells),
      styles: { font: "helvetica", fontSize: 7, cellPadding: 1.2 },
      headStyles: { fillColor: 90, textColor: 255 },
      columnStyles: { 1: { cellWidth: 60 } },
    });
  }
  const end = lastY();
  const p = d.kardex.progress;
  doc.setFontSize(8.5);
  let y = end + 7;
  if (p) {
    doc.text(
      `Créditos: ${p.earned_credits} / ${p.total_credits}    Materias aprobadas: ` +
        `${p.passed_subjects} / ${p.total_subjects}    Promedio: ${p.gpa ?? "—"}    ` +
        `Avance: ${p.credit_progress_pct}%`,
      margin,
      y,
    );
    y += 6;
  }
  doc.setFontSize(7.5);
  doc.setTextColor(90);
  doc.text(
    `Documento informativo, sin validez oficial. Generado el ${new Date().toLocaleDateString("es-MX")}.`,
    margin,
    y,
  );
  doc.save(`kardex-${d.enrollmentNumber}.pdf`);
}
