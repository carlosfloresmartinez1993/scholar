// Kárdex as Excel (.xlsx), Word (.docx) and CSV: same content as the printed one
// and the PDF (lib/kardex-print.ts, lib/kardex-pdf.ts). The libraries load on
// demand so they stay out of the main bundle.
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

const today = () => new Date().toLocaleDateString("es-MX");
const DISCLAIMER = () => `Documento informativo, sin validez oficial. Generado el ${today()}.`;

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function progressLine(d: KardexPrintData): string | null {
  const p = d.kardex.progress;
  if (!p) return null;
  return (
    `Créditos: ${p.earned_credits} / ${p.total_credits}    Materias aprobadas: ` +
    `${p.passed_subjects} / ${p.total_subjects}    Promedio: ${p.gpa ?? "—"}    ` +
    `Avance: ${p.credit_progress_pct}%`
  );
}

/** Header lines + one table: [section heading rows and subject rows]. */
function tableModel(d: KardexPrintData) {
  const withE2 = showE2(d.kardex);
  const withOrigin = showOrigin(d.kardex);
  const headers = kardexHeaders(withE2, withOrigin);
  const sections = kardexSections(d.kardex).map((s) => ({
    heading: s.heading + (s.rvoe ? ` — RVOE ${s.rvoe}` : ""),
    rows: s.rows.map((r) => kardexCells(r, withE2, withOrigin)),
  }));
  return { headers, sections };
}

// --- Excel ----------------------------------------------------------------------

export async function downloadKardexExcel(d: KardexPrintData) {
  const { default: ExcelJS } = await import("exceljs");
  const book = new ExcelJS.Workbook();
  const sheet = book.addWorksheet("Kárdex");
  const { headers, sections } = tableModel(d);
  const n = headers.length;

  let row = 1;
  if (d.logo) {
    const id = book.addImage({ base64: d.logo.dataUrl, extension: d.logo.format === "JPEG" ? "jpeg" : "png" });
    const height = 60;
    sheet.addImage(id, { tl: { col: 0, row: 0 }, ext: { width: (height * d.logo.width) / d.logo.height, height } });
    sheet.getRow(1).height = 48;
    row = 2;
  }
  const line = (text: string, bold = false, size = 10) => {
    const r = sheet.getRow(row++);
    r.getCell(1).value = text;
    r.getCell(1).font = { bold, size };
  };
  line(d.institutionName || "INUE", true, 14);
  line("Kárdex — historial académico");
  line(`Alumno: ${d.studentName}`);
  line(`Matrícula: ${d.enrollmentNumber}`);
  line(`Plan vigente: ${d.planLabel}`);
  row++;

  const head = sheet.getRow(row++);
  headers.forEach((h, i) => {
    const cell = head.getCell(i + 1);
    cell.value = h;
    cell.font = { bold: true, color: { argb: "FFFFFFFF" } };
    cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF000000" } };
  });
  if (sections.length === 0) line("Sin historial académico");
  for (const s of sections) {
    sheet.mergeCells(row, 1, row, n);
    const h = sheet.getRow(row++).getCell(1);
    h.value = s.heading;
    h.font = { bold: true };
    h.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFEBEBEB" } };
    for (const cells of s.rows) {
      const r = sheet.getRow(row++);
      cells.forEach((c, i) => {
        // grades and credits as numbers so they can be added up in Excel
        r.getCell(i + 1).value = c !== "" && /^\d+(\.\d+)?$/.test(c) && i !== 0 ? Number(c) : c;
      });
    }
  }

  for (const p of d.kardex.previous) {
    row++;
    line(`Estudios en RVOE anterior — ${p.rvoe} · ${p.program}`, true);
    const ph = sheet.getRow(row++);
    PREVIOUS_HEADERS.forEach((h, i) => {
      ph.getCell(i + 1).value = h;
      ph.getCell(i + 1).font = { bold: true };
    });
    for (const r of p.rows) sheet.getRow(row++).values = previousCells(r);
  }
  row++;
  const progress = progressLine(d);
  if (progress) line(progress, true);
  line(DISCLAIMER());

  sheet.columns.forEach((col, i) => {
    col.width = i === 1 ? 42 : i === 0 ? 12 : headers[i] === "Estatus" ? 22 : 10;
  });
  const buffer = await book.xlsx.writeBuffer();
  saveBlob(
    new Blob([buffer], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }),
    `kardex-${d.enrollmentNumber}.xlsx`,
  );
}

// --- Word -----------------------------------------------------------------------

export async function downloadKardexWord(d: KardexPrintData) {
  const docx = await import("docx");
  const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ImageRun, ShadingType } = docx;
  const { headers, sections } = tableModel(d);
  const n = headers.length;
  const small = (text: string, bold = false, color?: string) =>
    new Paragraph({ children: [new TextRun({ text, bold, size: 16, color })] });
  const cell = (text: string, opts: { bold?: boolean; fill?: string; color?: string; span?: number } = {}) =>
    new TableCell({
      columnSpan: opts.span,
      shading: opts.fill ? { type: ShadingType.CLEAR, color: "auto", fill: opts.fill } : undefined,
      children: [small(text, opts.bold, opts.color)],
    });

  const children: (InstanceType<typeof Paragraph> | InstanceType<typeof Table>)[] = [];
  if (d.logo) {
    const height = 60;
    const bytes = Uint8Array.from(atob(d.logo.dataUrl.split(",")[1]), (c) => c.charCodeAt(0));
    children.push(
      new Paragraph({
        children: [
          new ImageRun({
            type: d.logo.format === "JPEG" ? "jpg" : "png",
            data: bytes,
            transformation: { width: (height * d.logo.width) / d.logo.height, height },
          }),
        ],
      }),
    );
  }
  children.push(
    new Paragraph({ children: [new TextRun({ text: d.institutionName || "INUE", bold: true, size: 28 })] }),
    new Paragraph({ children: [new TextRun({ text: "Kárdex — historial académico", size: 18 })] }),
    new Paragraph({ children: [new TextRun({ text: `Alumno: ${d.studentName}`, size: 18 })] }),
    new Paragraph({ children: [new TextRun({ text: `Matrícula: ${d.enrollmentNumber}`, size: 18 })] }),
    new Paragraph({ children: [new TextRun({ text: `Plan vigente: ${d.planLabel}`, size: 18 })], spacing: { after: 200 } }),
  );

  const rows = [
    new TableRow({
      tableHeader: true,
      children: headers.map((h) => cell(h, { bold: true, fill: "000000", color: "FFFFFF" })),
    }),
    ...(sections.length === 0
      ? [new TableRow({ children: [cell("Sin historial académico", { span: n })] })]
      : sections.flatMap((s) => [
          new TableRow({ children: [cell(s.heading, { bold: true, fill: "EBEBEB", span: n })] }),
          ...s.rows.map((cells) => new TableRow({ children: cells.map((c) => cell(c)) })),
        ])),
  ];
  children.push(new Table({ rows, width: { size: 100, type: WidthType.PERCENTAGE } }));

  for (const p of d.kardex.previous) {
    children.push(
      new Paragraph({
        spacing: { before: 240 },
        children: [new TextRun({ text: `Estudios en RVOE anterior — ${p.rvoe} · ${p.program}`, bold: true, size: 18 })],
      }),
      new Table({
        width: { size: 100, type: WidthType.PERCENTAGE },
        rows: [
          new TableRow({ tableHeader: true, children: PREVIOUS_HEADERS.map((h) => cell(h, { bold: true, fill: "5A5A5A", color: "FFFFFF" })) }),
          ...p.rows.map((r) => new TableRow({ children: previousCells(r).map((c) => cell(c)) })),
        ],
      }),
    );
  }
  const progress = progressLine(d);
  if (progress) {
    children.push(new Paragraph({ spacing: { before: 240 }, children: [new TextRun({ text: progress, bold: true, size: 18 })] }));
  }
  children.push(new Paragraph({ spacing: { before: 120 }, children: [new TextRun({ text: DISCLAIMER(), size: 15, color: "5A5A5A" })] }));

  const document = new Document({
    sections: [
      {
        properties: {
          page: {
            // letter, landscape-free; narrow margins so the columns fit
            size: { width: 12240, height: 15840 },
            margin: { top: 720, bottom: 720, left: 720, right: 720 },
          },
        },
        children,
      },
    ],
  });
  saveBlob(await Packer.toBlob(document), `kardex-${d.enrollmentNumber}.docx`);
}

// --- CSV ------------------------------------------------------------------------

export function downloadKardexCsv(d: KardexPrintData) {
  const { headers, sections } = tableModel(d);
  const q = (v: string) => (/[",\n;]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  const lines = [
    ["Alumno", d.studentName],
    ["Matrícula", d.enrollmentNumber],
    ["Plan vigente", d.planLabel],
    [],
    ["Periodo", ...headers],
    ...sections.flatMap((s) => s.rows.map((cells) => [s.heading, ...cells])),
  ];
  // BOM so Excel reads the accents right
  const text = "﻿" + lines.map((l) => l.map(q).join(",")).join("\r\n");
  saveBlob(new Blob([text], { type: "text/csv;charset=utf-8" }), `kardex-${d.enrollmentNumber}.csv`);
}
