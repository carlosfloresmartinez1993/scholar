// Printable kárdex (historial académico). Mirrors lib/receipt.ts: renders HTML
// into a hidden iframe and drives window.print() — no PDF lib, no dependencies.
// Uses a full letter page instead of the 80mm thermal layout.
import { kardexCells, kardexHeaders, kardexSections, showE2 } from "@/lib/kardex";
import type { StudentKardex } from "@/api/types";

export interface KardexPrintData {
  institutionName: string;
  studentName: string;
  enrollmentNumber: string;
  planLabel: string;
  kardex: StudentKardex;
}

const esc = (s: string) =>
  s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;") // also escape quotes — values land in attributes (alt="…")
    .replace(/'/g, "&#39;");

const STYLE = `
  @page { size: letter; margin: 14mm; }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body { font-family: Arial, Helvetica, sans-serif; font-size: 11px; color: #000; }
  .logo { display: block; height: 16mm; width: auto; margin-bottom: 6px;
          filter: grayscale(1) contrast(1.4); }
  h1 { font-size: 16px; margin: 0 0 2px; }
  .sub { color: #333; font-size: 11px; }
  .meta { margin: 10px 0; display: grid; grid-template-columns: 1fr 1fr; gap: 2px 16px; }
  .meta b { display: inline-block; min-width: 90px; }
  table { width: 100%; border-collapse: collapse; margin-top: 6px; }
  th { background: #000; color: #fff; text-align: left; padding: 4px 6px; font-size: 10px; }
  td { padding: 3px 6px; border-bottom: 1px solid #ccc; }
  td.period { background: #eee; font-weight: bold; border-bottom: 1px solid #999; }
  td.period span { float: right; font-size: 10px; }
  .r { text-align: right; }
  .totals { margin-top: 10px; font-size: 11px; }
  .totals span { display: inline-block; margin-right: 24px; }
  .foot { margin-top: 18px; font-size: 10px; color: #555; }
`;

// columns after Asignatura are numeric except the last (Estatus)
const isNumeric = (i: number, total: number) => i === 2 || (i >= 5 && i < total - 1);

function body(d: KardexPrintData): string {
  const p = d.kardex.progress;
  const withE2 = showE2(d.kardex);
  const headers = kardexHeaders(withE2);
  const rows = kardexSections(d.kardex)
    .map(
      (s) =>
        `<tr><td class="period" colspan="${headers.length}">${esc(s.heading)}` +
        (s.rvoe ? `<span>${esc(s.rvoe)}</span>` : "") +
        `</td></tr>` +
        s.rows
          .map(
            (r) =>
              `<tr>${kardexCells(r, withE2)
                .map((cell, i) => `<td${isNumeric(i, headers.length) ? ' class="r"' : ""}>${esc(cell)}</td>`)
                .join("")}</tr>`,
          )
          .join(""),
    )
    .join("");
  return `
    <img class="logo" src="/logo-inue.svg" alt="${esc(d.institutionName || "INUE")}">
    <h1>${esc(d.institutionName || "INUE")}</h1>
    <div class="sub">Kárdex — historial académico</div>
    <div class="meta">
      <div><b>Alumno:</b> ${esc(d.studentName)}</div>
      <div><b>Matrícula:</b> ${esc(d.enrollmentNumber)}</div>
      <div style="grid-column: 1 / -1"><b>Plan vigente:</b> ${esc(d.planLabel)}</div>
    </div>
    <table>
      <thead>
        <tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>
      </thead>
      <tbody>${rows || `<tr><td colspan="${headers.length}">Sin historial académico</td></tr>`}</tbody>
    </table>
    ${
      p
        ? `<div class="totals">
      <span><b>Créditos:</b> ${p.earned_credits} / ${p.total_credits}</span>
      <span><b>Materias aprobadas:</b> ${p.passed_subjects} / ${p.total_subjects}</span>
      <span><b>Promedio:</b> ${p.gpa ?? "—"}</span>
      <span><b>Avance:</b> ${p.credit_progress_pct}%</span>
    </div>`
        : ""
    }
    <div class="foot">Documento informativo, sin validez oficial. Impreso el ${new Date().toLocaleDateString("es-MX")}.</div>
  `;
}

export function printKardex(d: KardexPrintData) {
  const iframe = document.createElement("iframe");
  iframe.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;";
  document.body.appendChild(iframe);
  const win = iframe.contentWindow!;
  const doc = win.document;
  doc.open();
  doc.write(
    `<!doctype html><html><head><meta charset="utf-8"><style>${STYLE}</style></head><body>${body(d)}</body></html>`,
  );
  doc.close();
  const cleanup = () => setTimeout(() => iframe.remove(), 500);
  win.onafterprint = cleanup;
  const fire = () => {
    win.focus();
    win.print();
    cleanup();
  };
  const img = doc.querySelector("img");
  if (img && !img.complete) {
    let done = false;
    const go = () => {
      if (done) return;
      done = true;
      fire();
    };
    img.addEventListener("load", go);
    img.addEventListener("error", go);
    setTimeout(go, 1500);
  } else {
    setTimeout(fire, 200);
  }
}
