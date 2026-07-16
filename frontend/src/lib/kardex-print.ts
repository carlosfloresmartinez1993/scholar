// Printable kárdex (historial académico). Mirrors lib/receipt.ts: renders HTML
// into a hidden iframe and drives window.print() — no PDF lib, no dependencies.
// Uses a full letter page instead of the 80mm thermal layout.
import { SUBJECT_STATUS_LABELS } from "@/lib/format";
import type { Kardex } from "@/api/types";

export interface KardexPrintData {
  institutionName: string;
  studentName: string;
  enrollmentNumber: string;
  planLabel: string;
  kardex: Kardex;
}

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

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
  .r { text-align: right; }
  .totals { margin-top: 10px; font-size: 11px; }
  .totals span { display: inline-block; margin-right: 24px; }
  .foot { margin-top: 18px; font-size: 10px; color: #555; }
`;

function body(d: KardexPrintData): string {
  const p = d.kardex.progress;
  const rows = d.kardex.rows
    .map(
      (r) =>
        `<tr>
          <td class="r">${r.period_number}</td>
          <td>${esc(r.code)}</td>
          <td>${esc(r.name)}</td>
          <td class="r">${r.credits}</td>
          <td>${esc(r.group_code)}</td>
          <td class="r">${r.attempt_number}</td>
          <td class="r">${r.final_grade ?? "—"}</td>
          <td>${SUBJECT_STATUS_LABELS[r.status] ?? r.status}</td>
        </tr>`,
    )
    .join("");
  return `
    <img class="logo" src="/logo-inue.svg" alt="${esc(d.institutionName || "INUE")}">
    <h1>${esc(d.institutionName || "INUE")}</h1>
    <div class="sub">Kárdex — historial académico</div>
    <div class="meta">
      <div><b>Alumno:</b> ${esc(d.studentName)}</div>
      <div><b>Matrícula:</b> ${esc(d.enrollmentNumber)}</div>
      <div style="grid-column: 1 / -1"><b>Plan:</b> ${esc(d.planLabel)}</div>
    </div>
    <table>
      <thead>
        <tr>
          <th>Periodo</th><th>Clave</th><th>Materia</th><th>Créditos</th>
          <th>Grupo</th><th>Intento</th><th>Calif.</th><th>Estatus</th>
        </tr>
      </thead>
      <tbody>${rows || `<tr><td colspan="8">Sin historial académico en este plan</td></tr>`}</tbody>
    </table>
    <div class="totals">
      <span><b>Créditos:</b> ${p.earned_credits} / ${p.total_credits}</span>
      <span><b>Materias aprobadas:</b> ${p.passed_subjects} / ${p.total_subjects}</span>
      <span><b>Promedio:</b> ${p.gpa ?? "—"}</span>
      <span><b>Avance:</b> ${p.credit_progress_pct}%</span>
    </div>
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
