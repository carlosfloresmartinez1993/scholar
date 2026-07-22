// CURP helper: RENAPO state codes + a full 18-char suggestion computed from
// name / date of birth / sex / state. The homoclave is included: position 17 is
// RENAPO's homonymy differentiator — '0' (born <2000) / 'A' (>=2000) unless the
// person collides with a homonym, so staff verify it against the official
// document — and position 18 is the standard computable check digit.
// ponytail: skips RENAPO's "inconvenient words" substitution list — staff can
// correct the editable suggestion by hand.

/** Frontend mirror of the backend CURP format validation. */
export const CURP_RE = /^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d$/;

export const MX_STATES: { code: string; name: string }[] = [
  { code: "AS", name: "Aguascalientes" },
  { code: "BC", name: "Baja California" },
  { code: "BS", name: "Baja California Sur" },
  { code: "CC", name: "Campeche" },
  { code: "CL", name: "Coahuila" },
  { code: "CM", name: "Colima" },
  { code: "CS", name: "Chiapas" },
  { code: "CH", name: "Chihuahua" },
  { code: "DF", name: "Ciudad de México" },
  { code: "DG", name: "Durango" },
  { code: "GT", name: "Guanajuato" },
  { code: "GR", name: "Guerrero" },
  { code: "HG", name: "Hidalgo" },
  { code: "JC", name: "Jalisco" },
  { code: "MC", name: "México" },
  { code: "MN", name: "Michoacán" },
  { code: "MS", name: "Morelos" },
  { code: "NT", name: "Nayarit" },
  { code: "NL", name: "Nuevo León" },
  { code: "OC", name: "Oaxaca" },
  { code: "PL", name: "Puebla" },
  { code: "QT", name: "Querétaro" },
  { code: "QR", name: "Quintana Roo" },
  { code: "SP", name: "San Luis Potosí" },
  { code: "SL", name: "Sinaloa" },
  { code: "SR", name: "Sonora" },
  { code: "TC", name: "Tabasco" },
  { code: "TS", name: "Tamaulipas" },
  { code: "TL", name: "Tlaxcala" },
  { code: "VZ", name: "Veracruz" },
  { code: "YN", name: "Yucatán" },
  { code: "ZS", name: "Zacatecas" },
  { code: "NE", name: "Nacido en el extranjero" },
];

const VOWELS = "AEIOU";
// particles ignored when picking surname/name letters (RENAPO rule)
const PARTICLES = new Set([
  "DA", "DAS", "DE", "DEL", "DER", "DI", "DIE", "EL", "LA", "LAS", "LE",
  "LES", "LOS", "MAC", "MC", "VAN", "VON", "Y",
]);
const SKIPPED_GIVEN = new Set(["MARIA", "MA", "MA.", "JOSE", "J", "J."]);

function normalize(value: string): string {
  return value
    .normalize("NFD")
    // strip combining accents but keep U+0303 (the tilde that makes Ñ)
    .replace(/[\u0300-\u0302\u0304-\u036f]/g, "")
    .normalize("NFC")
    .toUpperCase()
    .replace(/[^A-ZÑ\s.]/g, "")
    .trim();
}

/** Main word of a surname/name, dropping particles (DE, LA, VAN…). */
function mainWord(value: string, skipCommonGiven = false): string {
  const words = normalize(value).split(/\s+/).filter(Boolean);
  let filtered = words.filter((w) => !PARTICLES.has(w));
  if (skipCommonGiven && filtered.length > 1 && SKIPPED_GIVEN.has(filtered[0])) {
    filtered = filtered.slice(1);
  }
  return filtered[0] ?? "";
}

const safeChar = (c: string | undefined): string =>
  !c ? "X" : c === "Ñ" ? "X" : c;

function firstInternalVowel(word: string): string {
  for (let i = 1; i < word.length; i++) {
    if (VOWELS.includes(word[i])) return word[i];
  }
  return "X";
}

function firstInternalConsonant(word: string): string {
  for (let i = 1; i < word.length; i++) {
    const c = word[i];
    if (/[A-ZÑ]/.test(c) && !VOWELS.includes(c)) return safeChar(c);
  }
  return "X";
}

// RENAPO check-digit alphabet: each char's value is its index here.
const CHECK_CHARS = "0123456789ABCDEFGHIJKLMNÑOPQRSTUVWXYZ";

/** Standard CURP check digit (position 18) computed from the first 17 chars. */
export function curpCheckDigit(first17: string): string {
  if (first17.length !== 17 || [...first17].some((c) => !CHECK_CHARS.includes(c))) {
    throw new Error("CURP: se requieren 17 caracteres válidos para el dígito verificador");
  }
  let sum = 0;
  for (let i = 0; i < 17; i++) {
    sum += CHECK_CHARS.indexOf(first17[i]) * (18 - i);
  }
  return String((10 - (sum % 10)) % 10);
}

export function suggestCurp(input: {
  firstNames: string;
  lastNameP: string;
  lastNameM: string;
  /** ISO yyyy-mm-dd */
  birthDate: string;
  /** student sex: F (mujer) / M (hombre) */
  sex: "F" | "M";
  /** RENAPO 2-letter state code (NE = extranjero) */
  stateCode: string;
}): string | null {
  const ap = mainWord(input.lastNameP);
  const am = mainWord(input.lastNameM);
  const name = mainWord(input.firstNames, true);
  const dateMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(input.birthDate);
  const stateCode = input.stateCode.trim().toUpperCase();
  if (!ap || !name || !dateMatch || !/^[A-Z]{2}$/.test(stateCode)) return null;
  const [, yyyy, mm, dd] = dateMatch;
  const sexChar = input.sex === "M" ? "H" : "M"; // CURP: H=hombre, M=mujer
  const prefix16 = [
    safeChar(ap[0]),
    firstInternalVowel(ap),
    safeChar(am[0]),
    safeChar(name[0]),
    yyyy.slice(2),
    mm,
    dd,
    sexChar,
    stateCode,
    firstInternalConsonant(ap),
    am ? firstInternalConsonant(am) : "X",
    firstInternalConsonant(name),
  ].join("");
  const differentiator = Number(yyyy) < 2000 ? "0" : "A";
  return prefix16 + differentiator + curpCheckDigit(prefix16 + differentiator);
}
