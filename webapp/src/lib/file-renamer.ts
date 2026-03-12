import type { Extraction } from "./types";

const ITALIAN_MONTHS: Record<string, number> = {
  gennaio: 1, febbraio: 2, marzo: 3, aprile: 4,
  maggio: 5, giugno: 6, luglio: 7, agosto: 8,
  settembre: 9, ottobre: 10, novembre: 11, dicembre: 12,
};

function parseItalianDate(text: string): string | null {
  text = text.trim();

  // Format: "15 marzo 2024"
  let m = text.match(/^(\d{1,2})\s+([a-zA-ZàèéìòùÀÈÉÌÒÙ]+)\s+(\d{4})/);
  if (m) {
    const [, day, monthName, year] = m;
    const monthNum = ITALIAN_MONTHS[monthName.toLowerCase()];
    if (monthNum) {
      return `${year}${String(monthNum).padStart(2, "0")}${day.padStart(2, "0")}`;
    }
  }

  // Format: "30.09.2024" or "30/09/2024"
  m = text.match(/^(\d{1,2})[./](\d{1,2})[./](\d{4})/);
  if (m) {
    const [, day, month, year] = m;
    return `${year}${month.padStart(2, "0")}${day.padStart(2, "0")}`;
  }

  // Format: "2024-03-15"
  m = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) {
    return `${m[1]}${m[2]}${m[3]}`;
  }

  // Search in longer string
  m = text.match(/(\d{1,2})[./](\d{1,2})[./](\d{4})/);
  if (m) {
    const [, day, month, year] = m;
    return `${year}${month.padStart(2, "0")}${day.padStart(2, "0")}`;
  }

  return null;
}

function findDate(extractions: Extraction[]): string | null {
  const priority = [
    "data_fattura", "data_deposito", "data_sentenza",
    "estratto_conto", "data_udienza", "data_scadenza", "data",
  ];

  for (const target of priority) {
    for (const ext of extractions) {
      if (ext.extractionClass.toLowerCase() !== target) continue;

      if (target === "estratto_conto" && ext.attributes) {
        const dateStr = ext.attributes["data_chiusura"] || ext.attributes["periodo_fine"] || "";
        const parsed = parseItalianDate(dateStr);
        if (parsed) return parsed;
      }

      const parsed = parseItalianDate(ext.extractionText);
      if (parsed) return parsed;

      if (ext.attributes) {
        for (const val of Object.values(ext.attributes)) {
          const p = parseItalianDate(val);
          if (p) return p;
        }
      }
    }
  }

  for (const ext of extractions) {
    if (ext.extractionClass.toLowerCase().includes("data")) {
      const parsed = parseItalianDate(ext.extractionText);
      if (parsed) return parsed;
    }
  }

  return null;
}

function shortenName(text: string, maxLen = 40): string {
  text = text.trim();
  if (text.length <= maxLen) return text;
  return text.substring(0, maxLen).replace(/\s+\S*$/, "");
}

function findDescription(extractions: Extraction[], schemaName: string): string | null {
  const byClass: Record<string, Extraction> = {};
  for (const ext of extractions) {
    const cls = ext.extractionClass.toLowerCase();
    if (!byClass[cls]) byClass[cls] = ext;
  }

  if (schemaName === "full_legal" || schemaName === "parties_dates") {
    const parts: string[] = [];
    if (byClass["dispositivo"]) parts.push("Sentenza");
    else parts.push("Documento Legale");

    if (byClass["tribunale"]) {
      const t = byClass["tribunale"].extractionText;
      parts.push(t.length < 40 ? t : t.substring(0, 35));
    }

    const attore = byClass["parte_attore"];
    const convenuto = byClass["parte_convenuto"];
    if (attore && convenuto) {
      parts.push(`${shortenName(attore.extractionText)} vs ${shortenName(convenuto.extractionText)}`);
    } else if (attore) {
      parts.push(shortenName(attore.extractionText));
    }

    return parts.length > 1 ? parts.join(" - ") : parts[0];
  }

  if (schemaName === "invoice") {
    const parts = ["Fattura"];
    if (byClass["numero_fattura"]) parts.push(byClass["numero_fattura"].extractionText.replace(/\//g, "-"));
    if (byClass["fornitore"]) parts.push(shortenName(byClass["fornitore"].extractionText));
    return parts.join(" ");
  }

  if (schemaName === "estratto_conto") {
    const parts = ["Estratto Conto"];
    if (byClass["estratto_conto"]?.attributes?.["numero"]) {
      parts.push(byClass["estratto_conto"].attributes["numero"].replace(/\//g, "-"));
    }
    if (byClass["banca"]) parts.push(shortenName(byClass["banca"].extractionText));
    return parts.join(" ");
  }

  // Generic
  const skip = ["data", "importo", "iva", "totale", "saldo", "movimento"];
  for (const [cls, ext] of Object.entries(byClass)) {
    if (!skip.some((s) => cls.includes(s)) && ext.extractionText.length > 3) {
      return shortenName(ext.extractionText, 60);
    }
  }

  return null;
}

function sanitizeFilename(name: string): string {
  name = name.replace(/[<>:"/\\|?*]/g, "");
  name = name.replace(/\s+/g, " ");
  name = name.replace(/-{2,}/g, "-");
  return name.trim().replace(/^[. -]+|[. -]+$/g, "");
}

export function deriveFilename(
  extractions: Extraction[],
  schemaName: string
): { dateStr: string; description: string } | null {
  if (extractions.length === 0) return null;

  const dateStr = findDate(extractions) || "00000000";
  const description = findDescription(extractions, schemaName) || "Documento";

  if (dateStr === "00000000" && description === "Documento") return null;

  return { dateStr, description: sanitizeFilename(description) };
}

export function buildOutputFilename(
  originalName: string,
  dateStr: string,
  description: string,
  ext: string = ".md"
): string {
  return sanitizeFilename(`${dateStr} - ${description}`) + ext;
}
