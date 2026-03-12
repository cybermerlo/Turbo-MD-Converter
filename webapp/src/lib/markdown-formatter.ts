import type { Extraction } from "./types";

export function formatMarkdown(
  extractions: Extraction[],
  sourceFilename: string,
  totalPages: number,
  ocrText: string | null
): string {
  const lines: string[] = [];

  lines.push(`# Analisi: ${sourceFilename}`);
  lines.push("");
  lines.push(`> Pagine analizzate: ${totalPages}`);
  lines.push(`> Entita' estratte: ${extractions.length}`);
  lines.push("");

  if (extractions.length > 0) {
    lines.push("## Estrazioni");
    lines.push("");

    // Group extractions by class
    const grouped: Record<string, Extraction[]> = {};
    for (const ext of extractions) {
      const cls = ext.extractionClass;
      if (!grouped[cls]) grouped[cls] = [];
      grouped[cls].push(ext);
    }

    for (const [cls, exts] of Object.entries(grouped)) {
      lines.push(`### ${cls.toUpperCase().replace(/_/g, " ")}`);
      lines.push("");

      for (const ext of exts) {
        lines.push(`- **${ext.extractionText}**`);
        if (ext.attributes && Object.keys(ext.attributes).length > 0) {
          for (const [key, value] of Object.entries(ext.attributes)) {
            lines.push(`  - _${key}_: ${value}`);
          }
        }
      }
      lines.push("");
    }
  }

  if (ocrText) {
    lines.push("---");
    lines.push("");
    lines.push("## Testo OCR");
    lines.push("");
    lines.push(ocrText);
    lines.push("");
  }

  return lines.join("\n");
}
