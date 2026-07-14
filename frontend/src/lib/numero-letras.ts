// Importe en letra para recibos, p. ej. 3410 -> "TRES MIL CUATROCIENTOS DIEZ
// PESOS 00/100 M.N." Soporta hasta 999,999,999.99 (suficiente para colegiaturas).

const UNIDADES = ["", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE"];
const ESPECIALES: Record<number, string> = {
  10: "DIEZ", 11: "ONCE", 12: "DOCE", 13: "TRECE", 14: "CATORCE", 15: "QUINCE",
  16: "DIECISÉIS", 17: "DIECISIETE", 18: "DIECIOCHO", 19: "DIECINUEVE",
  20: "VEINTE", 21: "VEINTIUNO", 22: "VEINTIDÓS", 23: "VEINTITRÉS",
  24: "VEINTICUATRO", 25: "VEINTICINCO", 26: "VEINTISÉIS", 27: "VEINTISIETE",
  28: "VEINTIOCHO", 29: "VEINTINUEVE",
};
const DECENAS = ["", "", "", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"];
const CENTENAS = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS",
  "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"];

function menorDeMil(n: number): string {
  if (n === 0) return "";
  if (n === 100) return "CIEN";
  const c = Math.floor(n / 100);
  const resto = n % 100;
  const parts: string[] = [];
  if (c) parts.push(CENTENAS[c]);
  if (resto < 10) {
    if (resto) parts.push(UNIDADES[resto]);
  } else if (ESPECIALES[resto]) {
    parts.push(ESPECIALES[resto]);
  } else {
    const d = Math.floor(resto / 10);
    const u = resto % 10;
    parts.push(u ? `${DECENAS[d]} Y ${UNIDADES[u]}` : DECENAS[d]);
  }
  return parts.join(" ");
}

function enteroALetras(n: number): string {
  if (n === 0) return "CERO";
  const millones = Math.floor(n / 1_000_000);
  const miles = Math.floor((n % 1_000_000) / 1000);
  const resto = n % 1000;
  const partes: string[] = [];
  if (millones) partes.push(millones === 1 ? "UN MILLÓN" : `${menorDeMil(millones)} MILLONES`);
  if (miles) partes.push(miles === 1 ? "MIL" : `${menorDeMil(miles)} MIL`);
  if (resto) partes.push(menorDeMil(resto));
  return partes.join(" ").trim();
}

export function importeEnLetra(amount: number): string {
  const entero = Math.floor(Math.abs(amount));
  const centavos = Math.round((Math.abs(amount) - entero) * 100);
  const cc = String(centavos).padStart(2, "0");
  return `${enteroALetras(entero)} PESOS ${cc}/100 M.N.`;
}
