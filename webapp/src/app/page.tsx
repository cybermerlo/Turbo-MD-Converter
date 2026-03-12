"use client";

import { useState, useCallback, useRef } from "react";
import { Settings, Play, Square } from "lucide-react";

import type {
  AppConfig,
  LogEntry,
  ProcessingPhase,
  CostTotals,
  Extraction,
} from "@/lib/types";
import { loadConfig, saveConfig, SCHEMA_PRESET_NAMES, AVAILABLE_OCR_MODELS } from "@/lib/defaults";
import { getSchemaPreset } from "@/lib/schemas";
import { CostTracker } from "@/lib/cost-tracker";
import { iterPages, getPageCount } from "@/lib/pdf-converter";
import { ocrPageWithRetry } from "@/lib/gemini-ocr";
import { extractStructured } from "@/lib/extraction";
import { formatMarkdown } from "@/lib/markdown-formatter";
import { deriveFilename, buildOutputFilename } from "@/lib/file-renamer";
import { PAGE_SEPARATOR } from "@/lib/defaults";

import FileUpload from "@/components/FileUpload";
import SettingsDialog from "@/components/SettingsDialog";
import ProgressPanel from "@/components/ProgressPanel";
import OutputPanel from "@/components/OutputPanel";
import LogPanel from "@/components/LogPanel";

export default function HomePage() {
  const [config, setConfig] = useState<AppConfig>(loadConfig);
  const [files, setFiles] = useState<File[]>([]);
  const [showSettings, setShowSettings] = useState(false);

  const [phase, setPhase] = useState<ProcessingPhase>("idle");
  const [ocrProgress, setOcrProgress] = useState({ current: 0, total: 0 });
  const [extractionCount, setExtractionCount] = useState(0);
  const [costTotals, setCostTotals] = useState<CostTotals | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [markdown, setMarkdown] = useState("");
  const [suggestedFilename, setSuggestedFilename] = useState("output.md");

  // Selected schema/model overrides for quick access
  const [selectedSchema, setSelectedSchema] = useState(config.activeSchema);
  const [selectedOcrModel, setSelectedOcrModel] = useState(config.ocrModelId);

  const cancelRef = useRef(false);
  const processingRef = useRef(false);

  const addLog = useCallback((message: string, level: "INFO" | "WARNING" | "ERROR" = "INFO") => {
    setLogs((prev) => [...prev, { timestamp: Date.now(), message, level }]);
  }, []);

  const handleSaveSettings = useCallback(
    (newConfig: AppConfig) => {
      setConfig(newConfig);
      saveConfig(newConfig);
      setSelectedSchema(newConfig.activeSchema);
      setSelectedOcrModel(newConfig.ocrModelId);
    },
    []
  );

  const processFile = useCallback(
    async (file: File, costTracker: CostTracker): Promise<string | null> => {
      const isText = file.name.toLowerCase().endsWith(".txt");
      const isEml = file.name.toLowerCase().endsWith(".eml");
      let combinedText = "";
      let totalPages = 1;

      if (isText || isEml) {
        // Read text directly
        const text = await file.text();
        combinedText = text;
        addLog(`File ${isEml ? "EML" : "TXT"} letto direttamente (OCR non necessario)`);
        setOcrProgress({ current: 1, total: 1 });
      } else {
        // PDF: OCR pipeline
        setPhase("ocr");
        totalPages = await getPageCount(file);
        addLog(`Inizio OCR di '${file.name}' (${totalPages} pagine)`);
        setOcrProgress({ current: 0, total: totalPages });

        const pageTexts: string[] = [];
        let successfulPages = 0;

        for await (const { pageNum, imageData } of iterPages(
          file,
          config.pageDpi,
          config.jpegQuality / 100
        )) {
          if (cancelRef.current) {
            addLog("OCR annullato dall'utente", "WARNING");
            return null;
          }

          try {
            const result = await ocrPageWithRetry(
              config.geminiApiKey,
              selectedOcrModel,
              imageData,
              pageNum,
              config.ocrPrompt
            );

            costTracker.addCall(
              selectedOcrModel,
              result.inputTokens,
              result.outputTokens,
              "ocr"
            );

            pageTexts.push(result.text);
            successfulPages++;

            if (!result.text.trim()) {
              addLog(
                `Pagina ${pageNum + 1} saltata - Nessun testo estratto`,
                "WARNING"
              );
            }

            addLog(
              `Pagina ${pageNum + 1}/${totalPages} OK (${result.inputTokens}+${result.outputTokens} tokens)`
            );
          } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            addLog(`Errore OCR pagina ${pageNum + 1}: ${msg}`, "ERROR");
            pageTexts.push(`[Pagina ${pageNum + 1}: OCR non riuscito]`);
          }

          setOcrProgress({ current: pageNum + 1, total: totalPages });
          setCostTotals(costTracker.getTotals());
        }

        // Combine pages
        const parts: string[] = [];
        for (let i = 0; i < pageTexts.length; i++) {
          parts.push(PAGE_SEPARATOR.replace("{page_num}", String(i + 1)));
          parts.push(pageTexts[i]);
        }
        combinedText = parts.join("").trim();

        addLog(`OCR completato: ${successfulPages}/${totalPages} pagine riuscite`);
      }

      if (!combinedText.trim()) {
        addLog("Nessun testo estratto dall'OCR", "ERROR");
        return null;
      }

      // Extraction
      let extractions: Extraction[] = [];
      if (selectedSchema !== "none") {
        setPhase("extraction");
        const schema = getSchemaPreset(selectedSchema);
        if (schema) {
          // Apply custom prompt if exists
          if (config.customSchemaPrompts[selectedSchema]) {
            schema.promptDescription = config.customSchemaPrompts[selectedSchema];
          }

          addLog(
            `Inizio estrazione strutturata (${combinedText.length} caratteri, schema: ${selectedSchema})`
          );

          try {
            const result = await extractStructured(
              config.geminiApiKey,
              config.extractionModelId,
              combinedText,
              schema,
              config.maxCharBuffer,
              (msg) => addLog(msg)
            );

            extractions = result.extractions;
            costTracker.addCall(
              config.extractionModelId,
              result.inputTokens,
              result.outputTokens,
              "extraction"
            );

            setExtractionCount(extractions.length);
            addLog(`Estratte ${extractions.length} entita'`);
          } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            addLog(`Errore estrazione: ${msg}`, "ERROR");
          }
        }
      } else {
        addLog("Estrazione strutturata saltata (schema: none)");
      }

      setCostTotals(costTracker.getTotals());

      // Format markdown
      setPhase("formatting");
      const md = formatMarkdown(
        extractions,
        file.name,
        totalPages,
        config.includeOcrTextInOutput ? combinedText : null
      );

      // Derive filename
      let outputName = file.name.replace(/\.[^.]+$/, "") + ".md";
      if (extractions.length > 0) {
        const derived = deriveFilename(extractions, selectedSchema);
        if (derived) {
          outputName = buildOutputFilename(
            file.name,
            derived.dateStr,
            derived.description
          );
        }
      }

      setSuggestedFilename(outputName);
      return md;
    },
    [config, selectedOcrModel, selectedSchema, addLog]
  );

  const handleStart = useCallback(async () => {
    if (files.length === 0) return;

    if (!config.geminiApiKey) {
      const hasPdf = files.some((f) => f.name.toLowerCase().endsWith(".pdf"));
      const schemaActive = selectedSchema !== "none";
      if (hasPdf || schemaActive) {
        addLog(
          "Chiave API Gemini non configurata. Apri Impostazioni.",
          "ERROR"
        );
        return;
      }
    }

    processingRef.current = true;
    cancelRef.current = false;
    setPhase("ocr");
    setLogs([]);
    setMarkdown("");
    setExtractionCount(0);
    setCostTotals(null);

    addLog(`Avviata elaborazione di ${files.length} documenti`);

    const totalCostTracker = new CostTracker();
    let successful = 0;
    let failed = 0;
    let lastMarkdown = "";

    for (let i = 0; i < files.length; i++) {
      if (cancelRef.current) break;

      const file = files[i];
      addLog(`Documento ${i + 1}/${files.length}: ${file.name}`);

      const fileCostTracker = new CostTracker();
      const md = await processFile(file, fileCostTracker);

      // Accumulate costs
      for (const call of fileCostTracker.getAllCalls()) {
        totalCostTracker.addCall(
          call.modelId,
          call.inputTokens,
          call.outputTokens,
          call.phase
        );
      }

      if (md) {
        lastMarkdown += (lastMarkdown ? "\n\n---\n\n" : "") + md;
        successful++;
      } else {
        failed++;
      }

      setCostTotals(totalCostTracker.getTotals());
    }

    setMarkdown(lastMarkdown);

    if (cancelRef.current) {
      setPhase("cancelled");
      addLog("Elaborazione annullata", "WARNING");
    } else {
      setPhase("complete");
      addLog(
        `Completato: ${successful} riusciti, ${failed} falliti`
      );

      const totals = totalCostTracker.getTotals();
      addLog(
        `Costo totale: $${totals.total.costUsd.toFixed(4)} | ` +
        `Token: ${(totals.total.inputTokens + totals.total.outputTokens).toLocaleString()}`
      );
    }

    processingRef.current = false;
  }, [files, config, selectedSchema, addLog, processFile]);

  const handleCancel = useCallback(() => {
    cancelRef.current = true;
    addLog("Annullamento in corso...", "WARNING");
  }, [addLog]);

  const isProcessing = phase !== "idle" && phase !== "complete" && phase !== "error" && phase !== "cancelled";

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top bar */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-zinc-800">
        <h1 className="text-xl font-bold">OCR + LangExtract</h1>
        <button
          onClick={() => setShowSettings(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium
            text-zinc-300 bg-zinc-800 hover:bg-zinc-700 transition-colors"
        >
          <Settings className="w-4 h-4" />
          Impostazioni
        </button>
      </header>

      {/* Main content */}
      <div className="flex-1 flex flex-col lg:flex-row gap-4 p-4 lg:p-6 overflow-hidden">
        {/* LEFT column */}
        <div className="lg:w-[380px] flex-shrink-0 flex flex-col gap-4">
          <FileUpload
            files={files}
            onFilesChange={setFiles}
            disabled={isProcessing}
          />

          {/* Quick settings */}
          <div className="bg-zinc-800/50 rounded-xl p-4 space-y-3">
            <div>
              <label className="block text-xs font-medium text-zinc-400 mb-1">
                Modello OCR
              </label>
              <select
                value={selectedOcrModel}
                onChange={(e) => setSelectedOcrModel(e.target.value)}
                disabled={isProcessing}
                className="w-full bg-zinc-800 border border-zinc-600 rounded-lg px-3 py-1.5 text-sm text-zinc-200 disabled:opacity-50"
              >
                {AVAILABLE_OCR_MODELS.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-zinc-400 mb-1">
                Schema di estrazione
              </label>
              <select
                value={selectedSchema}
                onChange={(e) => setSelectedSchema(e.target.value)}
                disabled={isProcessing}
                className="w-full bg-zinc-800 border border-zinc-600 rounded-lg px-3 py-1.5 text-sm text-zinc-200 disabled:opacity-50"
              >
                {SCHEMA_PRESET_NAMES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Action buttons */}
          <div className="space-y-2">
            <button
              onClick={handleStart}
              disabled={files.length === 0 || isProcessing}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl
                text-sm font-bold text-white bg-blue-600 hover:bg-blue-500
                disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Play className="w-4 h-4" />
              Avvia Elaborazione
            </button>
            <button
              onClick={handleCancel}
              disabled={!isProcessing}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl
                text-sm font-medium text-white bg-red-700 hover:bg-red-600
                disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <Square className="w-4 h-4" />
              Annulla
            </button>
          </div>
        </div>

        {/* RIGHT column */}
        <div className="flex-1 flex flex-col gap-4 min-w-0 overflow-hidden">
          <ProgressPanel
            phase={phase}
            ocrProgress={ocrProgress}
            extractionCount={extractionCount}
            costTotals={costTotals}
          />
          <OutputPanel markdown={markdown} suggestedFilename={suggestedFilename} />
          <LogPanel logs={logs} />
        </div>
      </div>

      {/* Settings dialog */}
      {showSettings && (
        <SettingsDialog
          config={config}
          onSave={handleSaveSettings}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
  );
}
