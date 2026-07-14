// 80mm thermal receipt / comprobante rendered to HTML and sent to the browser
// print dialog (the cashier sets the RPH326B as the default printer). No PDF lib
// and no local agent: window.print() drives the installed thermal driver.
import { importeEnLetra } from "@/lib/numero-letras";

export interface ReceiptLine {
  cantidad: number;
  concepto: string;
  importe: number;
}

export interface ReceiptData {
  institutionName: string;
  rfc: string;
  fiscalAddress: string; // multiline (\n separated) address block
  folio: string;
  date: string; // ISO datetime
  programLine?: string; // e.g. "LICENCIATURA EN VITI. Y ENOL.   VYE1-L"
  modality?: string;
  studentName: string;
  enrollmentNumber: string;
  lines: ReceiptLine[];
  formaPago: string;
  observaciones?: string;
  cajero: string;
}

export interface FiscalReceptor {
  rfc: string;
  razonSocial: string;
  regimenFiscal: string;
  usoCfdi: string;
  cp: string;
  domicilio: string;
}

const money = (n: number) =>
  n.toLocaleString("es-MX", { style: "currency", currency: "MXN" });

function fmtDateTime(iso: string): string {
  const d = new Date(/[Zz]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  const fecha = d.toLocaleDateString("es-MX", { day: "2-digit", month: "2-digit", year: "numeric" });
  const hora = d.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit", hour12: true });
  return `${fecha}  ${hora}`;
}

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const STYLE = `
  @page { size: 80mm auto; margin: 0; }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body { width: 80mm; padding: 4mm 3mm; font-family: "Courier New", monospace;
         font-size: 11px; line-height: 1.35; color: #000; }
  .center { text-align: center; }
  .logo { display: block; margin: 0 auto 2px; height: 16mm; width: auto;
          filter: grayscale(1) contrast(1.4); }
  .bar { background: #000; color: #fff; padding: 1px 4px; font-weight: 700; display: inline-block; }
  .row { display: flex; justify-content: space-between; gap: 6px; }
  .muted { color: #333; }
  table { width: 100%; border-collapse: collapse; margin: 3px 0; }
  th { background: #000; color: #fff; text-align: left; padding: 2px 3px; font-size: 10px; }
  td { padding: 2px 3px; vertical-align: top; }
  .r { text-align: right; }
  hr { border: none; border-top: 1px dashed #000; margin: 4px 0; }
  .totals { margin-top: 2px; }
  .totals .row { font-weight: 700; }
  .small { font-size: 10px; }
`;

function receiptBody(d: ReceiptData, fiscal?: FiscalReceptor): string {
  const total = d.lines.reduce((s, l) => s + l.importe, 0);
  const addr = esc(d.fiscalAddress).replace(/\n/g, "<br>");
  return `
    <img class="logo" src="/logo-inue.svg" alt="${esc(d.institutionName || "INUE")}">
    <div class="row" style="margin-top:4px">
      <span class="bar">${fiscal ? "FACTURA / COMPROBANTE" : "FOLIO RECIBO"}</span>
      <span style="font-weight:700">${esc(d.folio)}</span>
    </div>
    <div class="small muted" style="margin-top:3px">${addr}</div>
    ${d.rfc ? `<div class="small muted">R.F.C. ${esc(d.rfc)}</div>` : ""}
    <hr>
    <div class="center bar" style="width:100%">Lugar y Fecha de elaboración</div>
    <div class="center small">${fmtDateTime(d.date)}</div>
    ${fiscal ? "" : `<div class="center small" style="margin:3px 0">Este comprobante no tiene validez fiscal</div>`}
    <hr>
    ${d.programLine ? `<div class="small" style="font-weight:700">${esc(d.programLine)}</div>` : ""}
    ${d.modality ? `<div class="small">${esc(d.modality)}</div>` : ""}
    <div class="row small" style="margin-top:2px"><span>Nombre Alumno</span><span>Matrícula</span></div>
    <div class="row"><span style="font-weight:700">${esc(d.studentName)}</span><span>${esc(d.enrollmentNumber)}</span></div>
    ${fiscal ? receptorBlock(fiscal) : ""}
    <table>
      <thead><tr><th>Cant.</th><th>Concepto</th><th class="r">Importe</th></tr></thead>
      <tbody>
        ${d.lines
          .map(
            (l) =>
              `<tr><td>${l.cantidad.toFixed(2)}</td><td>${esc(l.concepto)}</td><td class="r">${money(l.importe)}</td></tr>`,
          )
          .join("")}
      </tbody>
    </table>
    <div class="small"><b>Importe letra</b><br>${esc(importeEnLetra(total))}</div>
    <div class="totals">
      <div class="row"><span>${fiscal ? "Subtotal" : "Subtotal exento"}</span><span>${money(total)}</span></div>
      <div class="row"><span>TOTAL</span><span>${money(total)}</span></div>
    </div>
    <hr>
    <div class="small"><b>Forma de pago</b><br>${esc(d.formaPago)}</div>
    ${d.observaciones ? `<div class="small"><b>Observaciones</b><br>${esc(d.observaciones)}</div>` : ""}
    <div class="small" style="margin-top:6px"><b>Cajero</b> ${esc(d.cajero)}</div>
    <div style="height:8mm"></div>
  `;
}

function receptorBlock(f: FiscalReceptor): string {
  return `
    <hr>
    <div class="center bar" style="width:100%">Datos fiscales del receptor</div>
    <div class="small" style="margin-top:2px">
      <div><b>${esc(f.razonSocial)}</b></div>
      <div>RFC: ${esc(f.rfc)}</div>
      ${f.regimenFiscal ? `<div>Régimen: ${esc(f.regimenFiscal)}</div>` : ""}
      ${f.usoCfdi ? `<div>Uso CFDI: ${esc(f.usoCfdi)}</div>` : ""}
      ${f.cp ? `<div>C.P.: ${esc(f.cp)}</div>` : ""}
      ${f.domicilio ? `<div>${esc(f.domicilio)}</div>` : ""}
    </div>`;
}

function printHtml(inner: string) {
  const iframe = document.createElement("iframe");
  iframe.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;";
  document.body.appendChild(iframe);
  const win = iframe.contentWindow!;
  const doc = win.document;
  doc.open();
  doc.write(`<!doctype html><html><head><meta charset="utf-8"><style>${STYLE}</style></head><body>${inner}</body></html>`);
  doc.close();
  const cleanup = () => setTimeout(() => iframe.remove(), 500);
  win.onafterprint = cleanup;
  const fire = () => {
    win.focus();
    win.print();
    cleanup();
  };
  // Wait for the logo to decode so it never prints blank; fall back on a timer.
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

export function printReceipt(d: ReceiptData) {
  printHtml(receiptBody(d));
}

export function printComprobante(d: ReceiptData, fiscal: FiscalReceptor) {
  printHtml(receiptBody(d, fiscal));
}
