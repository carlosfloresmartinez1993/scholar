// Downloadable kárdex as a PDF file, same content as the printed one
// (lib/kardex-print.ts). jsPDF is loaded on demand so it stays out of the main bundle.
import { kardexCells, kardexHeaders, kardexSections, showE2 } from "@/lib/kardex";
import type { KardexPrintData } from "@/lib/kardex-print";

export async function downloadKardexPdf(d: KardexPrintData) {
  const [{ jsPDF }, { autoTable }] = await Promise.all([
    import("jspdf"),
    import("jspdf-autotable"),
  ]);
  const doc = new jsPDF({ unit: "mm", format: "letter" });
  const margin = 14;
  const institution = d.institutionName || "INUE";

  doc.setFont("helvetica", "bold");
  doc.setFontSize(14);
  doc.text(institution, margin, 18);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(9);
  doc.text("Kárdex — historial académico", margin, 23);
  doc.text(`Alumno: ${d.studentName}`, margin, 30);
  doc.text(`Matrícula: ${d.enrollmentNumber}`, 120, 30);
  doc.text(doc.splitTextToSize(`Plan vigente: ${d.planLabel}`, 188), margin, 35);

  const withE2 = showE2(d.kardex);
  const headers = kardexHeaders(withE2);
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
    ...s.rows.map((r) => kardexCells(r, withE2)),
  ]);

  autoTable(doc, {
    startY: 41,
    margin: { left: margin, right: margin },
    head: [headers],
    body: body.length ? body : [[{ content: "Sin historial académico", colSpan: n }]],
    styles: { font: "helvetica", fontSize: 7, cellPadding: 1.2 },
    headStyles: { fillColor: 0, textColor: 255 },
    columnStyles: {
      1: { cellWidth: 52 },
      ...Object.fromEntries(
        headers.map((_, i) => [i, i === 2 || (i >= 5 && i < n - 1) ? { halign: "right" as const } : {}]),
      ),
    },
  });

  // jspdf-autotable records where the table ended on the document
  const end = (doc as unknown as { lastAutoTable: { finalY: number } }).lastAutoTable.finalY;
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
